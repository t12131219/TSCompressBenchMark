"""Read-only, actual restoration of trusted internal candidate evidence."""
from pathlib import Path
import subprocess
import tempfile

from ..assets import ContractError, canonical_bytes, digest, require, verify_asset
from ..recovery import DIRECTORY
from .smoke import _read_report, _worker_json

BWRAP = '/usr/bin/bwrap'
MOUNT = '/recovery'


def _restore(bundle, spec, method, artifact, source, timeout):
    # The child sees no /usr, loader cache, host libraries, build, or input data.
    # Mount individual sealed files, not even the entire recovery directory.
    argv = [BWRAP, '--unshare-net', '--unshare-pid', '--unshare-ipc', '--die-with-parent',
            '--clearenv', '--cap-drop', 'ALL']
    for rel, ref in sorted(spec['files'].items()):
        file = verify_asset(bundle, {'path':rel, 'sha256':ref['sha256']})
        argv.extend(('--ro-bind', str(file), f'{MOUNT}/{rel}'))
    with tempfile.TemporaryDirectory(prefix='tsbench-restore-') as tmp:
        tmp = Path(tmp)
        out = tmp/'outputs'
        out.mkdir()
        stdout, stderr = tmp/'stdout', tmp/'stderr'
        plugin = method['plugin']
        argv.extend(('--ro-bind', str(artifact), '/input.bmk', '--bind', str(out), '/out', '--chdir', '/out',
                     '--', f"{MOUNT}/{spec['loader']}", '--inhibit-cache', '--library-path', f'{MOUNT}/lib',
                     f"{MOUNT}/{spec['worker']}", 'decode', f"{MOUNT}/{spec['plugins'][plugin]}", plugin,
                     canonical_bytes(method['options']).decode('utf-8'), '/input.bmk', '/out/values', '/out/schema'))
        try:
            with stdout.open('xb') as log, stderr.open('xb') as err:
                proc = subprocess.run(argv, env={}, stdin=subprocess.DEVNULL, stdout=log, stderr=err,
                                      timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ContractError('isolated restore exceeded its frozen per-operation deadline') from exc
        require(proc.returncode==0, f'isolated restore exited {proc.returncode}: '
                + _diagnostic(stderr))
        shape, _ = _worker_json(stdout, 2)
        require(shape=={'dtype':source['dtype'], 'count':source['count']}, 'isolated restore dtype or shape differs')
        require(sorted(p.name for p in out.iterdir())==['schema','values'] and
                all(p.is_file() and not p.is_symlink() for p in out.iterdir()), 'missing or undeclared restore outputs')
        values, schema = out/'values', out/'schema'
        restored = {'values_sha256':digest(values), 'schema_sha256':digest(schema)}
        require(values.stat().st_size==source['bytes'] and restored=={
            'values_sha256':source['raw_sha256'], 'schema_sha256':source['schema_sha256']},
            'isolated restore values or schema differ from the sealed validation')
        return {**shape, **restored}


def _diagnostic(path):
    with path.open('rb') as stream:
        return stream.read(4096).decode('utf-8',errors='replace').strip()


def audit_smoke_restore(root: Path, run_id: str) -> dict:
    """Restore every verified slot or reject the audit; never write into the run."""
    report, run, plan, seal = _read_report(root, run_id)
    recovery = report.get('recovery', {})
    require(recovery.get('status')=='ready' and recovery['sample_slots'],
            'run has no complete sealed decoder closure with verified samples')
    spec = plan['contract_bindings']['recovery']
    timeout = plan['suite']['timeout_seconds_per_operation']
    results = []
    for case in report['cases']:
        if case['status']!='verified':
            continue
        try:
            artifact = verify_asset(run, case['artifact'])
            restored = _restore(run/DIRECTORY, spec, plan['methods'][case['method_id']], artifact,
                                plan['inputs'][case['input_id']], timeout)
        except (ContractError, OSError) as exc:
            raise ContractError(f"restore {case['slot_id']}: {exc}") from exc
        results.append({'slot_id':case['slot_id'], 'artifact':case['artifact'], **restored})
    return {'schema':'bmk.dev-smoke-restore-audit/1', 'run_id':run_id,
            'seal_id':seal['seal_id'], 'recovery_id':recovery['recovery_id'],
            'isolation':'bubblewrap_network_pid_ipc_sealed_files_only',
            'planned_slots':report['planned_slots'], 'restored_verified_slots':len(results),
            'slots':results, 'qualification_granted':False}
