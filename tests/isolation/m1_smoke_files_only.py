"""Exercise the v3 submission with real error/signal/deadline/cancel and a lost DSO."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.api import SmokePlanRequest, plan_smoke, report_smoke, run_smoke
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, digest, load_json
from tsbench.planner.smoke_isolation import SUITE
from tsbench.runtime import create_build_lock


def resealed_rejection(source):
    run_id = source.name
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        run = root / 'results' / run_id
        shutil.copytree(source, run)
        observations = run / 'observations.jsonl'
        rows = [json.loads(line) for line in observations.read_text().splitlines()]
        row = next(r for r in rows if r['status'] == 'verified')
        row['operations'][1]['input_mounts'].update(row['operations'][0]['input_mounts'])
        # Keep the schema shape valid (frame + one extra input); the semantic
        # binding, not just the reseal or JSON schema, must reject the record.
        del row['operations'][1]['input_mounts']['original.json']
        observations.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        path = run / 'completion.json'
        seal = load_json(path)
        del seal['seal_id']
        item = next(r for r in seal['files'] if r['path'] == observations.name)
        item.update(bytes=observations.stat().st_size, sha256=digest(observations))
        path.write_text(json.dumps({**seal, 'seal_id': content_id(seal)}))
        try:
            report_smoke(root, run_id)
        except ContractError as exc:
            assert str(exc) == 'isolated inputs do not match the slot boundary', exc
            return str(exc)
        raise AssertionError('accepted an extra binding of original input during decode')


def exercise(build):
    cwd = build.resolve()
    libraries = {'raw-store': 'libbmk_raw_store.so', 'zstd': 'libbmk_zstd.so', 'alp-auto': 'libbmk_alp_auto.so'}
    worker = cwd / 'tsbench_m1_isolation_control'
    with tempfile.TemporaryDirectory(prefix='m1-control-', dir=cwd) as work:
        work = Path(work)
        relative = lambda p: p.relative_to(ROOT).as_posix()
        for name, library in libraries.items():
            tree = cwd / 'plugins' / 'codecs' / name
            for path in [tree / library, *tree.glob('liblzbench_native.so'), *tree.glob('libalp_native.so')]:
                shutil.copy2(path, work / path.name)
        request = SmokePlanRequest(relative(work / 'build.json'), SUITE)
        write_new(work / 'build.json', create_build_lock(ROOT, relative(worker),
                                                        {k: relative(work / v) for k, v in libraries.items()}))
        plan = plan_smoke(ROOT, request)
        results = ROOT / 'results'
        earlier = set(results.iterdir())
        last = plan['slots'][-1]['slot_id']

        def cancelled():
            for run in set(results.iterdir()) - earlier:
                log = run / 'logs' / last / 'encode.stderr'
                if log.is_file() and b'control: cancellation wait' in log.read_bytes():
                    return True
            return False

        report = run_smoke(ROOT, plan, cancelled=cancelled)
        run = results / report['run_id']
        assert report['statuses'] == {'cancelled': 1, 'crash': 1, 'failed': 1, 'timeout': 1, 'verified': 14}, report['statuses']
        rows = [json.loads(line) for line in (run / 'observations.jsonl').read_text().splitlines()]
        facts = {}
        for row in rows:
            slot = row['slot_id']
            log = run / 'logs' / slot
            enc = (log / 'encode.stderr').read_text()
            assert 'original-only read-only encode' in enc, enc
            if row['status'] == 'verified':
                assert 'frame-only read-only decode' in (log / 'decode.stderr').read_text()
            else:
                op, = row['operations']
                assert op['pid'] and op['returncode'] != 0 and len(row['workspace']) == 2
                facts[row['status']] = {'slot': slot, 'operation': op, 'control_stderr': enc}
        assert 'actual SIGSEGV' in facts['crash']['control_stderr']
        assert 'cancellation wait' in facts['cancelled']['control_stderr']
        assert report_smoke(ROOT, run.name) == report
        rejection = resealed_rejection(run)
        # Move a real locked dependency only in the disposable build copy, then
        # submit the same plan. This must preserve all 18 dependency terminals.
        (work / 'liblzbench_native.so').rename(work / 'withheld.so')
        missing = run_smoke(ROOT, plan)
        assert missing['statuses'] == {'dependency_failed': 18} and missing['recovery']['status'] == 'setup_failed'
        assert report_smoke(ROOT, missing['run_id']) == missing
        return {'plan_content_id': plan['plan_content_id'], 'fault_run_id': run.name,
                'fault_statuses': report['statuses'], 'faults': facts,
                'sealed_replay_rejection': rejection, 'missing_dependency_run_id': missing['run_id'],
                'missing_dependency_statuses': missing['statuses']}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: m1_smoke_files_only.py PROJECT_LOCAL_BUILD_DIR')
    print(json.dumps(exercise(Path(sys.argv[1])), ensure_ascii=False, indent=2))
