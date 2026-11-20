"""Files-only wrapper for the standalone pcodec grouped measurement controller."""
from signal import SIGXFSZ

from ..assets import digest, require, verify_asset
from .isolated_worker import LAUNCHERS, MOUNT, program_files
from .process import invoke

NAME = 'pcodec-pages-grouped'
TOOL = 'bin/tsbench_pcodec_pages_grouped'
LIBRARY = 'lib/libpcodec_c.so'
FILE_CEILING = 128 << 20
AS_LIMIT = 1 << 30
WALL_SECONDS = 60


def run(bundle, spec, scratch, source, lane, op, cols, rows, cap):
    require(lane in ('source', 'native') and op in ('encode', 'decode') and
            type(cols) is int and 0 < cols <= 4096 and type(rows) is int and 0 < rows <= 10000000 and
            type(cap) is int and 4096 <= cap <= FILE_CEILING and scratch.is_absolute() and
            source.is_absolute() and source.is_file() and not source.is_symlink() and
            16 < source.stat().st_size <= FILE_CEILING, 'invalid isolated pcodec groups or file extent')
    require(spec['tools'] == {NAME: TOOL}, 'isolated pcodec grouped tool differs')
    closure = program_files(spec, [TOOL])
    require(LIBRARY in closure, 'isolated pcodec grouped library missing')
    out = scratch / 'out'
    out.mkdir()
    argv = [LAUNCHERS[0], f'--as={AS_LIMIT}:{AS_LIMIT}', f'--fsize={cap}:{cap}', '--core=0:0',
            '--', LAUNCHERS[1], '--unshare-net', '--unshare-pid', '--unshare-ipc', '--die-with-parent',
            '--clearenv', '--cap-drop', 'ALL']
    for name in closure:
        ref = spec['files'][name]
        path = verify_asset(bundle, {'path': name, 'sha256': ref['sha256']})
        require(path.stat().st_size == ref['bytes'], 'isolated pcodec runtime size differs')
        argv.extend(('--ro-bind', str(path), f'{MOUNT}/{name}'))
    mounted = {'object': {'bytes': source.stat().st_size, 'sha256': digest(source)}}
    argv.extend(('--ro-bind', str(source), '/inputs/object', '--bind', str(out), '/out', '--chdir', '/out', '--',
                 f"{MOUNT}/{spec['loader']}", '--inhibit-cache', '--library-path', f'{MOUNT}/lib', f'{MOUNT}/{TOOL}',
                 op, lane, str(cols), str(rows), '/inputs/object', '/out/object'))
    result = invoke(argv, scratch, scratch, 'native', WALL_SECONDS, lambda: False, environment={},
                    observe_process=True, capture_usage=True)
    if result['pid'] is not None:
        result['input_mounts'] = mounted
    if result['returncode'] in {-SIGXFSZ, 128 + SIGXFSZ} and result['status'] in {'crash', 'failed'}:
        result.update(status='file_limit_signal', reason='grouped pcodec tool exceeded file limit')
    elif result['status'] == 'failed':
        with (scratch / 'native.stderr').open('rb') as stream:
            if stream.read(7) == b'bwrap: ':
                result.update(status='sandbox_failed', reason='Bubblewrap setup failed; see retained stderr')
    return out / 'object', result
