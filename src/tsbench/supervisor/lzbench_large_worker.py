"""Files-only observation for whole real Zstd worker objects above the small replay limit."""
from signal import SIGXFSZ

from ..assets import digest, require, verify_asset
from .isolated_worker import LAUNCHERS, MOUNT, program_files
from .process import invoke

FILE_CEILING = 128 << 20
LIMITS = {'address_space_bytes': 1 << 30, 'file_bytes': FILE_CEILING, 'wall_seconds': 60}


def run_zstd_worker(bundle, spec, limits, scratch, source, op, lane, cap, cancelled):
    """The larger budget is opt-in for this exact tool, not for ordinary decoders."""
    require(limits == LIMITS and type(cap) is int and 0 < cap <= FILE_CEILING and
            not source.is_symlink() and source.is_absolute() and source.is_file() and 0 < source.stat().st_size <= FILE_CEILING and
            ((op == 'encode' and lane in ('0', '2')) or (op == 'decode' and lane == '0')),
            'invalid isolated Zstd worker launch extent')
    executable = spec['tools']['lzbench_workers']
    require(executable == 'bin/tsbench_lzbench_corpus_worker_control' and scratch.is_absolute(),
            'unbound isolated Zstd worker tool')
    output = scratch / 'out'
    output.mkdir()
    argv = [LAUNCHERS[0], f"--as={limits['address_space_bytes']}:{limits['address_space_bytes']}",
            f'--fsize={cap}:{cap}', '--core=0:0', '--', LAUNCHERS[1], '--unshare-net', '--unshare-pid', '--unshare-ipc',
            '--die-with-parent', '--clearenv', '--cap-drop', 'ALL']
    for name in program_files(spec, [executable]):
        ref = spec['files'][name]
        path = verify_asset(bundle, {'path': name, 'sha256': ref['sha256']})
        require(path.stat().st_size == ref['bytes'], 'isolated Zstd worker runtime size differs')
        argv.extend(('--ro-bind', str(path), f'{MOUNT}/{name}'))
    mounts = {'object': {'bytes': source.stat().st_size, 'sha256': digest(source)}}
    argv.extend(('--ro-bind', str(source), '/inputs/object', '--bind', str(output), '/out', '--chdir', '/out', '--',
                 f"{MOUNT}/{spec['loader']}", '--inhibit-cache', '--library-path', f'{MOUNT}/lib', f'{MOUNT}/{executable}',
                 'zstd', op, lane, '/inputs/object', '/out/object', str(cap)))
    result = invoke(argv, scratch, scratch, 'native', limits['wall_seconds'], cancelled, environment={},
                    observe_process=True, capture_usage=True)
    if result['pid'] is not None:
        result['input_mounts'] = mounts
    if result['returncode'] in {-SIGXFSZ, 128 + SIGXFSZ} and result['status'] in {'crash', 'failed'}:
        result.update(status='file_limit_signal', reason='Zstd worker received SIGXFSZ')
    elif result['status'] == 'failed':
        with (scratch / 'native.stderr').open('rb') as stream:
            if stream.read(7) == b'bwrap: ':
                result.update(status='sandbox_failed', reason='Bubblewrap setup failed; see retained stderr')
    return output, result
