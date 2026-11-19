"""Single CPU worker invocation with a sealed ELF closure and inherited Linux limits."""
from pathlib import Path
from signal import SIGXFSZ

from ..assets import canonical_bytes, digest, require, verify_asset
from .process import invoke

LAUNCHERS = ('/usr/bin/prlimit', '/usr/bin/bwrap')
MOUNT = '/runtime'


def launcher_lock():
    return {name: digest(Path(name)) for name in LAUNCHERS}


def validate_limits(limits, *, file_ceiling=1 << 20):
    require(type(file_ceiling) is int and 1 << 20 <= file_ceiling <= 8 << 20,
            "invalid isolated worker file ceiling")
    minimums = {'address_space_bytes': (64 << 20, 1 << 30),
                'file_bytes': (4096, file_ceiling), 'wall_seconds': (1, 60)}
    require(isinstance(limits, dict) and limits.keys() == minimums.keys() and
            all(type(limits[key]) is int and lo <= limits[key] <= hi
                for key, (lo, hi) in minimums.items()), 'invalid isolated worker limits')


def program_files(spec, roots):
    pending = [spec['loader'], *roots]
    reached = set()
    while pending:
        name = pending.pop()
        if name not in reached:
            reached.add(name)
            pending.extend('lib/' + lib for lib in spec['files'][name]['needed'])
    return sorted(reached)


def invoke_isolated_worker(bundle, spec, method, limits, work, logs, operation, inputs, arguments, cancelled,
                           *, label=None, observe=False, file_ceiling=1 << 20, options_text=None):
    plugin = method['plugin']
    library = spec['plugins'][plugin]
    require(options_text is None or (type(options_text) is str and len(options_text) <= 1024 and options_text.isascii() and '\0' not in options_text),
            'invalid literal isolated worker options word')
    options = canonical_bytes(method['options']).decode('utf-8') if options_text is None else options_text
    args = [operation, f'{MOUNT}/{library}', plugin, options, *arguments]
    return _invoke(bundle, spec, limits, work, logs, label or operation, inputs, spec['worker'], [library], args, cancelled,
                   observe=observe, file_ceiling=file_ceiling)


def invoke_isolated_tool(bundle, spec, tool, limits, work, logs, label, inputs, arguments, cancelled, *, observe=False, file_ceiling=1 << 20, process_env=None, private_tmp=False, bind_inputs=False):
    return _invoke(bundle, spec, limits, work, logs, label, inputs, spec['tools'][tool], [], arguments, cancelled,
                   observe=observe, file_ceiling=file_ceiling, process_env=process_env, private_tmp=private_tmp, bind_inputs=bind_inputs)


def _invoke(bundle, spec, limits, work, logs, operation, inputs, executable, additional_roots, arguments, cancelled,
            *, observe=False, file_ceiling=1 << 20, process_env=None, private_tmp=False, bind_inputs=False):
    """Mount exactly the ELF dependencies, inputs and one writable output directory.

    RLIMIT_AS and RLIMIT_FSIZE bound address space per process and writes per file.
    """
    validate_limits(limits,file_ceiling=file_ceiling)
    output = work / 'out'
    output.mkdir()
    as_limit, file_limit = limits['address_space_bytes'], limits['file_bytes']
    argv = [LAUNCHERS[0], f'--as={as_limit}:{as_limit}', f'--fsize={file_limit}:{file_limit}', '--core=0:0',
            '--', LAUNCHERS[1], '--unshare-net', '--unshare-pid', '--unshare-ipc', '--die-with-parent',
            '--clearenv', '--cap-drop', 'ALL']
    require(not process_env or process_env == {'OMP_DYNAMIC':'FALSE','OMP_THREAD_LIMIT':'2'},
            'unsupported isolated process environment')
    for key,value in sorted((process_env or {}).items()):
        argv.extend(('--setenv', key, value))
    if private_tmp:
        argv.extend(('--tmpfs','/tmp'))
    for relative in program_files(spec, [executable, *additional_roots]):
        row = spec['files'][relative]
        path = verify_asset(bundle, {'path': relative, 'sha256': row['sha256']})
        require(path.stat().st_size == row['bytes'], 'isolated runtime asset size differs')
        argv.extend(('--ro-bind', str(path), f'{MOUNT}/{relative}'))
    mounts = {}
    for name, path in sorted(inputs.items()):
        require(Path(name).name == name and name not in {'', '.', '..'} and path.is_file() and not path.is_symlink(),
                'invalid isolated input binding')
        argv.extend(('--ro-bind', str(path), f'/inputs/{name}'))
        if observe or bind_inputs:
            mounts[name] = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    argv.extend(('--bind', str(output), '/out', '--chdir', '/out', '--', f"{MOUNT}/{spec['loader']}",
                 '--inhibit-cache', '--library-path', f'{MOUNT}/lib', f'{MOUNT}/{executable}', *arguments))
    result = invoke(argv, work, logs, operation, limits['wall_seconds'], cancelled, environment={},
                    observe_process=observe, capture_usage=observe)
    if (observe or bind_inputs) and result['pid'] is not None:
        result['input_mounts'] = mounts
    # Bubblewrap can forward a worker signal as a shell-style exit code.
    if result['returncode'] in {-SIGXFSZ, 128 + SIGXFSZ} and result['status'] in {'crash', 'failed'}:
        result.update(status='file_limit_signal', reason='worker received SIGXFSZ')
    elif result['status'] == 'failed':
        with (logs / (operation + '.stderr')).open('rb') as stream:
            if stream.read(7) == b'bwrap: ':
                result.update(status='sandbox_failed', reason='Bubblewrap setup failed; see retained stderr')
    return output, result
