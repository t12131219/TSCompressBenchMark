"""Isolate only the two standalone lzbench clock drivers on whole-file inputs."""
from signal import SIGXFSZ

from ..assets import digest, require, verify_asset
from .isolated_worker import LAUNCHERS, MOUNT, program_files
from .process import invoke

TOOLS = {family: f'tsbench_lzbench_{family}_clock' for family in ('session', 'workers')}
FILE_CEILING = 128 << 20
ADDRESS_SPACE = 1 << 30
WALL_SECONDS = 60


def run(bundle, spec, scratch, source, codec, family, direction, lane, cap):
    require(codec in ('xz', 'zstd') and direction in ('encode', 'decode') and
            family in TOOLS and type(cap) is int and 0 < cap <= FILE_CEILING and
            source.is_absolute() and source.is_file() and not source.is_symlink() and
            0 < source.stat().st_size <= FILE_CEILING and scratch.is_absolute(), 'invalid lzbench clock launch extent')
    if family == 'session':
        require(lane == 'session', 'unsupported lzbench session lane')
        args = []
    else:
        lanes = ('synchronous', '1', '2') if codec == 'xz' else ('0', '2') if direction == 'encode' else ('0',)
        require(lane in lanes, 'unsupported lzbench worker lane')
        args = [lane]
    executable = spec['tools'][family]
    require(executable == 'bin/' + TOOLS[family], 'unbound lzbench clock tool')
    output = scratch / 'out'
    output.mkdir()
    argv = [LAUNCHERS[0], f'--as={ADDRESS_SPACE}:{ADDRESS_SPACE}', f'--fsize={cap}:{cap}', '--core=0:0',
            '--', LAUNCHERS[1], '--unshare-net', '--unshare-pid', '--unshare-ipc', '--die-with-parent',
            '--clearenv', '--cap-drop', 'ALL']
    for name in program_files(spec, [executable]):
        ref = spec['files'][name]
        path = verify_asset(bundle, {'path': name, 'sha256': ref['sha256']})
        require(path.stat().st_size == ref['bytes'], 'lzbench clock runtime extent differs')
        argv.extend(('--ro-bind', str(path), f'{MOUNT}/{name}'))
    mounts = {'object': {'bytes': source.stat().st_size, 'sha256': digest(source)}}
    argv.extend(('--ro-bind', str(source), '/inputs/object', '--bind', str(output), '/out', '--chdir', '/out', '--',
                 f"{MOUNT}/{spec['loader']}", '--inhibit-cache', '--library-path', f'{MOUNT}/lib', f'{MOUNT}/{executable}',
                 codec, direction, *args, '/inputs/object', '/out/object', str(cap)))
    result = invoke(argv, scratch, scratch, 'native', WALL_SECONDS, lambda: False, environment={},
                    observe_process=True, capture_usage=True)
    if result['pid'] is not None:
        result['input_mounts'] = mounts
    if result['returncode'] in {-SIGXFSZ, 128 + SIGXFSZ} and result['status'] in {'crash', 'failed'}:
        result.update(status='file_limit_signal', reason='lzbench clock received SIGXFSZ')
    elif result['status'] == 'failed':
        with (scratch / 'native.stderr').open('rb') as stream:
            if stream.read(7) == b'bwrap: ':
                result.update(status='sandbox_failed', reason='Bubblewrap setup failed; see retained stderr')
    return output, result
