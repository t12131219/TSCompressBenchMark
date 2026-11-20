"""Files-only supervisor for grouped initial/update/reopen ZFP array operations."""
from signal import SIGXFSZ

from ..assets import digest, require, verify_asset
from ..planner.zfp_execution import THREAD_ENV
from .isolated_worker import LAUNCHERS, MOUNT, program_files
from .process import invoke

NAME = 'zfp-array-grouped'
TOOL = 'bin/tsbench_zfp_array_grouped'
LIBRARY = 'lib/libzfp_native_c.so'
FILE_CEILING = 128 << 20
AS_LIMIT = 1 << 30
WALL_SECONDS = 60
OPERATIONS = ('update', 'reopen_initial', 'reopen_updated')


def _binding(op, staged):
    require(op in OPERATIONS, 'invalid grouped ZFP array operation')
    role = {'update': 'windows', 'reopen_initial': 'initial', 'reopen_updated': 'updated'}[op]
    suffix = ['update', f'/inputs/{role}', '/out/initial', '/out/updated'] if op == 'update' else [
        'reopen', f'/inputs/{role}', '/out/values']
    return role, staged, suffix


def run(bundle, spec, scratch, staged, op, *, input_bytes, output_bytes, windows):
    role, source, arguments = _binding(op, staged)
    require(spec['tools'] == {NAME: TOOL} and scratch.is_absolute() and source.is_absolute() and source.is_file() and
            not source.is_symlink() and type(input_bytes) is int and type(output_bytes) is int and
            source.stat().st_size == input_bytes and 0 < input_bytes <= FILE_CEILING and 0 < output_bytes <= FILE_CEILING and
            type(windows) is int and 0 < windows <= 25000, 'invalid isolated ZFP array geometry or runtime')
    closure = program_files(spec, [TOOL])
    require(LIBRARY in closure, 'isolated ZFP array runtime missing frozen dependency')
    out = scratch / 'out'
    out.mkdir()
    # stdout owns the per-window native observations; it obeys RLIMIT_FSIZE too.
    cap = max(output_bytes, 4096, 1024*windows)
    argv = [LAUNCHERS[0], f'--as={AS_LIMIT}:{AS_LIMIT}', f'--fsize={cap}:{cap}', '--core=0:0', '--', LAUNCHERS[1],
            '--unshare-net', '--unshare-pid', '--unshare-ipc', '--die-with-parent', '--clearenv', '--cap-drop', 'ALL']
    for k, v in sorted(THREAD_ENV.items()):
        argv.extend(('--setenv', k, v))
    for name in closure:
        ref = spec['files'][name]
        path = verify_asset(bundle, {'path': name, 'sha256': ref['sha256']})
        require(path.stat().st_size == ref['bytes'], 'isolated ZFP array ELF size differs')
        argv.extend(('--ro-bind', str(path), f'{MOUNT}/{name}'))
    proof = {'bytes': input_bytes, 'sha256': digest(source)}
    argv.extend(('--ro-bind', str(source), f'/inputs/{role}', '--bind', str(out), '/out', '--chdir', '/out', '--',
                 f"{MOUNT}/{spec['loader']}", '--inhibit-cache', '--library-path', f'{MOUNT}/lib', f'{MOUNT}/{TOOL}', *arguments))
    result = invoke(argv, scratch, scratch, 'native', WALL_SECONDS, lambda: False, environment={},
                    observe_process=True, capture_usage=True)
    if result['pid'] is not None:
        result['input_mounts'] = {role: proof}
    if result['returncode'] in {-SIGXFSZ, 128 + SIGXFSZ} and result['status'] in {'crash', 'failed'}:
        result.update(status='file_limit_signal', reason='grouped ZFP array exceeded file quota')
    elif result['status'] == 'failed':
        with (scratch / 'native.stderr').open('rb') as f:
            if f.read(7) == b'bwrap: ':
                result.update(status='sandbox_failed', reason='Bubblewrap setup failed; see captured stderr')
    return out, result
