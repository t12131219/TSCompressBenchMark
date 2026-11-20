"""Files-only launcher for the frozen C11 Gorilla corpus controller."""
from pathlib import Path
from signal import SIGXFSZ

from ..assets import digest, require, verify_asset
from .isolated_worker import LAUNCHERS, MOUNT, program_files
from .process import invoke

TOOL = 'bin/tsbench_gorilla_corpus_control'
LIBRARY = 'lib/libgorilla_c.so'
FILE_CEILING = 128 << 20
ADDRESS_SPACE = 1 << 30
WALL_SECONDS = 60
ROUTES = ('tv-batch', 'append-resume', 'iterator')


def value_files(cols):
    return tuple(f'column-{c:04d}.bin' for c in range(cols))


def run(bundle, spec, scratch, inputs, route, direction, cols, rows, cap):
    """Bind exact input files, never the directory containing the original input."""
    require(route in ROUTES and direction in ('encode', 'decode', 'snapshot_decode') and
            (direction != 'snapshot_decode' or route == 'append-resume') and
            type(cols) is int and 0 < cols <= 4096 and type(rows) is int and 0 < rows <= 1000000 and
            type(cap) is int and 4096 <= cap <= FILE_CEILING and scratch.is_absolute(),
            'invalid isolated Gorilla corpus operation or extent')
    encode = direction == 'encode'
    names = ('axis.ms', *value_files(cols)) if encode else ('frame.gtv1',)
    require(set(inputs) == set(names) and spec['tools'] == {'gorilla': TOOL} and
            LIBRARY in program_files(spec, [TOOL]), 'invalid isolated Gorilla corpus inputs or tool')
    out = scratch / 'out'
    out.mkdir()
    argv = [LAUNCHERS[0], f'--as={ADDRESS_SPACE}:{ADDRESS_SPACE}', f'--fsize={cap}:{cap}', '--core=0:0',
            '--', LAUNCHERS[1], '--unshare-net', '--unshare-pid', '--unshare-ipc', '--die-with-parent',
            '--clearenv', '--cap-drop', 'ALL']
    for name in program_files(spec, [TOOL]):
        ref = spec['files'][name]
        path = verify_asset(bundle, {'path': name, 'sha256': ref['sha256']})
        require(path.stat().st_size == ref['bytes'], 'isolated Gorilla runtime extent differs')
        argv.extend(('--ro-bind', str(path), f'{MOUNT}/{name}'))
    mounts = {}
    for name in names:
        path = inputs[name]
        require(isinstance(path, Path) and path.is_absolute() and not path.is_symlink() and path.is_file(),
                'unsafe isolated Gorilla input')
        n = path.stat().st_size
        require(n == rows * 8 if encode else 20 < n <= FILE_CEILING, 'invalid isolated Gorilla input size')
        mounts[name] = {'bytes': n, 'sha256': digest(path)}
        argv.extend(('--ro-bind', str(path), f'/inputs/{name}'))
    args = ('encode', route, '/inputs', str(cols), str(rows), '/out/frame.gtv1',
            '/out/snapshot.gtv1' if route == 'append-resume' else '-') if encode else (
            'decode', 'snapshots' if direction == 'snapshot_decode' else route, '/inputs/frame.gtv1', '/out')
    argv.extend(('--bind', str(out), '/out', '--chdir', '/out', '--', f"{MOUNT}/{spec['loader']}",
                 '--inhibit-cache', '--library-path', f'{MOUNT}/lib', f'{MOUNT}/{TOOL}', *args))
    result = invoke(argv, scratch, scratch, 'native', WALL_SECONDS, lambda: False, environment={},
                    observe_process=True, capture_usage=True)
    if result['pid'] is not None:
        result['input_mounts'] = mounts
    if result['returncode'] in {-SIGXFSZ, 128 + SIGXFSZ} and result['status'] in {'crash', 'failed'}:
        result.update(status='file_limit_signal', reason='Gorilla corpus controller received SIGXFSZ')
    elif result['status'] == 'failed':
        with (scratch / 'native.stderr').open('rb') as stderr:
            if stderr.read(7) == b'bwrap: ':
                result.update(status='sandbox_failed', reason='Bubblewrap setup failed; see retained stderr')
    return out, result
