"""Bounded files-only M4 ABI measurement, including the >LLC raw-store control."""
from signal import SIGXFSZ

from ..assets import digest, require, verify_asset
from .isolated_worker import LAUNCHERS, MOUNT, _invoke, program_files
from .process import invoke

TOOLS = {'timing_only': 'tsbench_m4_abi_cost', 'counted': 'tsbench_m4_abi_cost_counted'}
MODULES = {p: 'lib/libbmk_' + p.replace('-', '_') + '.so' for p in ('raw-store', 'zstd', 'alp-auto', 'xz-baseline')}
LIMITS = {'address_space_bytes': 1 << 29, 'file_bytes': 1 << 20, 'wall_seconds': 15}
RAW_FILE_CEILING = 32 << 20


def run(bundle, spec, scratch, plugin, mode, arm, lifecycle, direction, inputs, count, dtype, ceiling):
    executable = spec['tools'][mode]
    library = spec['plugins'][plugin]
    require(executable == 'bin/' + TOOLS[mode] and library == MODULES[plugin] and
            arm in ('direct', 'framework') and lifecycle in ('cold', 'steady_reset') and direction in ('encode', 'decode') and
            type(count) is int and count > 0 and dtype in (2, 10) and set(inputs) == {'object', 'schema'}, 'unbound M4 ABI launch')
    options = '{"decode_backend":"falp-auto"}' if plugin == 'alp-auto' else '{}'
    args = [arm, lifecycle, direction, plugin, f'{MOUNT}/{library}', options,
            '/inputs/object', '/inputs/schema', str(count), str(dtype), '/out/result']
    if ceiling == LIMITS['file_bytes']:
        return _invoke(bundle, spec, LIMITS, scratch, scratch, 'cost', inputs, executable, [library], args, lambda: False, observe=True)
    # The generic isolation limit is unchanged. Only the exact raw-store
    # control/host executables may see a byte view large enough to cross LLC.
    require(plugin == 'raw-store' and dtype == 2 and type(ceiling) is int and 8 << 20 < ceiling <= RAW_FILE_CEILING and
            count < ceiling and scratch.is_absolute(), 'invalid large M4 raw-store extent')
    output = scratch / 'out'
    output.mkdir()
    as_limit = LIMITS['address_space_bytes']
    argv = [LAUNCHERS[0], f'--as={as_limit}:{as_limit}', f'--fsize={ceiling}:{ceiling}', '--core=0:0',
            '--', LAUNCHERS[1], '--unshare-net', '--unshare-pid', '--unshare-ipc', '--die-with-parent', '--clearenv', '--cap-drop', 'ALL']
    for name in program_files(spec, [executable, library]):
        ref = spec['files'][name]
        path = verify_asset(bundle, {'path': name, 'sha256': ref['sha256']})
        require(path.stat().st_size == ref['bytes'], 'large M4 ABI runtime extent differs')
        argv.extend(('--ro-bind', str(path), f'{MOUNT}/{name}'))
    mounts = {}
    for name, path in sorted(inputs.items()):
        require(path.is_absolute() and path.is_file() and not path.is_symlink() and
                0 < path.stat().st_size <= (65536 if name == 'schema' else ceiling), 'unsafe large M4 raw-store input')
        mounts[name] = {'bytes': path.stat().st_size, 'sha256': digest(path)}
        argv.extend(('--ro-bind', str(path), f'/inputs/{name}'))
    argv.extend(('--bind', str(output), '/out', '--chdir', '/out', '--', f"{MOUNT}/{spec['loader']}", '--inhibit-cache',
                 '--library-path', f'{MOUNT}/lib', f'{MOUNT}/{executable}', *args))
    proc = invoke(argv, scratch, scratch, 'cost', LIMITS['wall_seconds'], lambda: False, environment={},
                  observe_process=True, capture_usage=True)
    if proc['pid'] is not None:
        proc['input_mounts'] = mounts
    if proc['returncode'] in {-SIGXFSZ, 128 + SIGXFSZ} and proc['status'] in {'crash', 'failed'}:
        proc.update(status='file_limit_signal', reason='large M4 raw-store received SIGXFSZ')
    elif proc['status'] == 'failed' and (scratch / 'cost.stderr').read_bytes()[:7] == b'bwrap: ':
        proc.update(status='sandbox_failed', reason='Bubblewrap setup failed; see stderr')
    return output, proc
