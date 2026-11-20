"""File-only ZFP field timing and separate same-work native thread observation."""
from signal import SIGXFSZ

from ..assets import digest, require, verify_asset
from ..planner.zfp_execution import THREAD_ENV
from .isolated_worker import LAUNCHERS, MOUNT, program_files
from .process import invoke

TOOLS = {'timing': 'bin/tsbench_zfp_field_grouped', 'observer': 'bin/tsbench_zfp_field_observer'}
LIBRARY = 'lib/libzfp_native_c.so'
FILE_CEILING = 128 << 20
AS_LIMIT = 1 << 30
WALL_SECONDS = 60
HEAD_BYTES, LENGTH_BYTES = 12, 4


def run(bundle, spec, scratch, source, op, profile, columns, rows, product_bytes, arm):
    require(arm in TOOLS and spec['tools'] == TOOLS and op in ('encode', 'decode') and
            profile in ('serial', 'omp1', 'omp2') and (op == 'encode' or profile == 'serial') and
            type(columns) is int and 0 < columns <= 4096 and type(rows) is int and 0 < rows <= 131072 and
            type(product_bytes) is int and 0 < product_bytes <= FILE_CEILING and
            scratch.is_absolute() and source.is_absolute() and source.is_file() and not source.is_symlink(),
            'invalid isolated ZFP whole-column field launch')
    raw_bytes, source_bytes = columns * rows * 8, source.stat().st_size
    wrapper_minimum = HEAD_BYTES + LENGTH_BYTES * columns + 8 * columns
    require(raw_bytes <= FILE_CEILING and source_bytes <= FILE_CEILING and
            ((source_bytes == raw_bytes and product_bytes >= wrapper_minimum) if op == 'encode' else
             (source_bytes >= wrapper_minimum and product_bytes == raw_bytes)), 'isolated ZFP input or product geometry differs')
    executable = TOOLS[arm]
    closure = program_files(spec, [executable])
    require(LIBRARY in closure and TOOLS['observer' if arm == 'timing' else 'timing'] not in closure,
            'ZFP timed and instrumented executables must be distinct closures')
    output = scratch / 'out'
    output.mkdir()
    # Stdout includes one small structured record per column.
    cap = max(product_bytes, 1024 * columns, 4096)
    argv = [LAUNCHERS[0], f'--as={AS_LIMIT}:{AS_LIMIT}', f'--fsize={cap}:{cap}', '--core=0:0',
            '--', LAUNCHERS[1], '--unshare-net', '--unshare-pid', '--unshare-ipc', '--die-with-parent',
            '--clearenv', '--cap-drop', 'ALL']
    for k, v in sorted(THREAD_ENV.items()):
        argv.extend(('--setenv', k, v))
    for name in closure:
        ref = spec['files'][name]
        path = verify_asset(bundle, {'path': name, 'sha256': ref['sha256']})
        require(path.stat().st_size == ref['bytes'], 'isolated ZFP ELF extent differs')
        argv.extend(('--ro-bind', str(path), f'{MOUNT}/{name}'))
    facts = {'bytes': source_bytes, 'sha256': digest(source)}
    role = 'columns' if op == 'encode' else 'archive'
    argv.extend(('--ro-bind', str(source), f'/inputs/{role}', '--bind', str(output), '/out', '--chdir', '/out', '--',
                 f"{MOUNT}/{spec['loader']}", '--inhibit-cache', '--library-path', f'{MOUNT}/lib', f'{MOUNT}/{executable}',
                 op, profile, str(columns), str(rows), f'/inputs/{role}', '/out/object'))
    result = invoke(argv, scratch, scratch, 'native', WALL_SECONDS, lambda: False, environment={},
                    observe_process=arm == 'timing', capture_usage=arm == 'timing')
    if result['pid'] is not None:
        result['input_mounts'] = {role: facts}
    if result['returncode'] in {-SIGXFSZ, 128 + SIGXFSZ} and result['status'] in {'crash', 'failed'}:
        result.update(status='file_limit_signal', reason='grouped ZFP field tool exceeded file cap')
    elif result['status'] == 'failed':
        with (scratch / 'native.stderr').open('rb') as f:
            if f.read(7) == b'bwrap: ':
                result.update(status='sandbox_failed', reason='Bubblewrap setup failed; see retained stderr')
    return output / 'object', result
