"""File-isolated launcher for the frozen Zstd dictionary grouped controller."""
from signal import SIGXFSZ

from ..assets import digest, require, verify_asset
from ..planner.m3_zstd_dictionary import LIMIT
from ..qualification.zstd_dictionary_grouped_wire import FRAME, HEAD, MAX_WIRE
from .isolated_worker import LAUNCHERS, MOUNT, program_files
from .process import invoke

NAME = 'zstd-dictionary-grouped'
TOOL = 'bin/tsbench_zstd_dictionary_grouped'
LIBRARY = 'lib/liblzbench_native.so'
FILE_CEILING = 32 << 20
ADDRESS_SPACE = 1 << 30
WALL_SECONDS = 60


def _input(path):
    require(path.is_absolute() and path.is_file() and not path.is_symlink(), 'dictionary worker input must be a regular file')
    size = path.stat().st_size
    require(0 < size <= FILE_CEILING, 'dictionary worker input size is outside the locked ceiling')
    return {'bytes': size, 'sha256': digest(path)}


def _contract(op, source, *, dictionary=None, logical=None, training=None):
    require(op in {'train', 'encode', 'decode'}, 'unsupported dictionary worker operation')
    names = {'train': 'prefix', 'encode': 'holdout', 'decode': 'archive'}
    role = names[op]
    facts = _input(source)
    files = {role: (source, facts)}
    if op == 'train':
        require(dictionary is None and logical is None and isinstance(training, tuple) and len(training) == 3 and
                all(type(x) is int for x in training), 'train needs the prefix and geometry only')
        cap, each, count = training
        require(8 <= count <= 128 and facts['bytes'] == each * count and
                ((cap == 256 and each == 32) or (cap == 2048 and 0 < each <= 2048 and each % 8 == 0 and each*count >= 8192)),
                'dictionary train tier or sample geometry differs')
        args = [f'/inputs/{role}', '/out/object', *map(str, training)]
        return files, args, cap
    require(training is None and dictionary is not None and type(logical) is int and 0 < logical <= FILE_CEILING,
            'held-out work needs logical size and one fixed dictionary, not training samples')
    shared = _input(dictionary)
    require(8 <= shared['bytes'] <= 2048 and not source.samefile(dictionary), 'invalid fixed dictionary dependency')
    files['dictionary'] = (dictionary, shared)
    count = (logical + LIMIT-1) // LIMIT
    wrapper = HEAD.size + FRAME.size*count
    archive_max = wrapper + count*MAX_WIRE
    if op == 'encode':
        require(facts['bytes'] == logical and archive_max <= FILE_CEILING, 'held-out encode extent differs')
        cap = archive_max
    else:
        require(wrapper + count <= facts['bytes'] <= archive_max <= FILE_CEILING, 'fixed archive extent differs')
        cap = logical
    return files, [f'/inputs/{role}', '/out/object', '/inputs/dictionary', str(logical)], cap


def run(bundle, spec, scratch, source, op, **geometry):
    require(scratch.is_absolute() and spec['tools'] == {NAME: TOOL}, 'isolated dictionary tool differs')
    files, args, cap = _contract(op, source, **geometry)
    closure = program_files(spec, [TOOL])
    require(LIBRARY in closure, 'frozen Zstd dictionary library missing')
    out = scratch / 'out'
    out.mkdir()
    # RLIMIT_FSIZE also applies to stdout/stderr; small valid views still need a bounded diagnostics allowance.
    file_cap = max(cap, 4096)
    argv = [LAUNCHERS[0], f'--as={ADDRESS_SPACE}:{ADDRESS_SPACE}', f'--fsize={file_cap}:{file_cap}', '--core=0:0',
            '--', LAUNCHERS[1], '--unshare-net', '--unshare-pid', '--unshare-ipc', '--die-with-parent',
            '--clearenv', '--cap-drop', 'ALL']
    for name in closure:
        ref = spec['files'][name]
        path = verify_asset(bundle, {'path': name, 'sha256': ref['sha256']})
        require(path.stat().st_size == ref['bytes'], 'isolated dictionary runtime size differs')
        argv.extend(('--ro-bind', str(path), f'{MOUNT}/{name}'))
    for role, (path, _) in files.items():
        argv.extend(('--ro-bind', str(path), f'/inputs/{role}'))
    argv.extend(('--bind', str(out), '/out', '--chdir', '/out', '--', f"{MOUNT}/{spec['loader']}",
                 '--inhibit-cache', '--library-path', f'{MOUNT}/lib', f'{MOUNT}/{TOOL}', op, *args))
    result = invoke(argv, scratch, scratch, 'native', WALL_SECONDS, lambda: False, environment={},
                    observe_process=True, capture_usage=True)
    if result['pid'] is not None:
        result['input_mounts'] = {k: facts for k, (_, facts) in files.items()}
    if result['returncode'] in {-SIGXFSZ, 128 + SIGXFSZ} and result['status'] in {'crash', 'failed'}:
        result.update(status='file_limit_signal', reason='grouped dictionary tool exceeded its operation file limit')
    elif result['status'] == 'failed':
        with (scratch / 'native.stderr').open('rb') as stream:
            if stream.read(7) == b'bwrap: ':
                result.update(status='sandbox_failed', reason='Bubblewrap setup failed; see retained stderr')
    return out / 'object', result
