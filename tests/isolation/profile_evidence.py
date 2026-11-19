"""Exercise sealed replay with actual profile data and adversarial resealing."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.api import plan_profile
from tsbench.application.profiling import read_profile
from tsbench.assets import ContractError, canonical_bytes, content_id, digest, load_json


def reject(run, path, rev, text):
    old = path.read_bytes()
    seal_path = run / 'completion.json'
    original = seal_path.read_bytes()
    try:
        path.write_bytes(canonical_bytes(rev) + b'\n')
        seal = json.loads(original)
        del seal['seal_id']
        next(r for r in seal['files'] if r['path'] == path.relative_to(run).as_posix()).update(
            sha256=digest(path), bytes=path.stat().st_size)
        seal_path.write_bytes(canonical_bytes({**seal, 'seal_id': content_id(seal)}) + b'\n')
        try:
            read_profile(run.parents[1], run.name)
        except ContractError as exc:
            assert text in str(exc), exc
            return str(exc)
        raise AssertionError('sealed verification unexpectedly accepted source mutation')
    finally:
        seal_path.write_bytes(original)
        path.write_bytes(old)


def main(run_id):
    source, report = read_profile(ROOT, run_id)
    plan = load_json(source / 'plan.json')
    plain, profiled = plan['builds']['plain'], plan['builds']['profile']
    assert plan_profile(ROOT, plain, profiled) == plan
    cli = subprocess.check_output([sys.executable, '-B', ROOT / 'bmk', 'profile-plan', '--plain-build', plain,
                                   '--profile-build', profiled])
    assert json.loads(cli) == plan
    assert report['statuses'] == {'verified': 28}
    assert {d['case'] for d in report['perturbation'] if len(d['complete_matched_rounds']) == 3} == set(plan['inputs'])
    jobs = [s for trial in report['trials'] if trial['case'] == 'zstd-mt' and trial['mode'] == 'profiled'
            for s in trial['observations'][0]['trace']['stages'] if s['stage'] == 6]
    assert len(jobs) == 3 and all(j['events'] == 11 for j in jobs)
    assert any(j['max_observed_concurrency'] == 2 and j['observed_overlap_ns'] > 0 for j in jobs)
    assert all(j['observed_union_ns'] <= j['sum_thread_interval_ns_not_wall'] for j in jobs)
    elf_needed = {}
    for mode, records in plan['artifacts'].items():
        elf_needed[mode] = {}
        for name, ref in records.items():
            if name.startswith('trace-overlay/') or name == 'libtsbench_trace.so':
                continue
            p = ROOT / ref['path']
            assert digest(p) == ref['sha256']
            output = subprocess.check_output(['/usr/bin/readelf', '-d', p], text=True, env={'LC_ALL':'C'})
            needed = re.findall(r'Shared library: \[([^\]]+)\]', output)
            assert ('libtsbench_trace.so' in needed) == (mode == 'profile'), (p, needed)
            elf_needed[mode][Path(name).name] = needed
    with tempfile.TemporaryDirectory(prefix='profile-control-') as t:
        run = Path(t) / 'results' / run_id
        shutil.copytree(source, run)
        _, replay = read_profile(Path(t), run_id)
        assert canonical_bytes(replay) + b'\n' == (run/'derived/report.json').read_bytes()
        pressure = run / 'logs/p28-decode.stdout'
        lost = load_json(pressure)
        assert lost['trace']['dropped'] == 10
        lost['trace']['dropped'] = 0
        lost_rejected = reject(run, pressure, lost, 'trace event coverage differs')
        zstd = next(t for t in report['trials'] if t['case'] == 'zstd-mt' and t['mode'] == 'profiled')
        path = run / 'logs' / (zstd['slot'] + '-encode.stdout')
        native = deepcopy(load_json(path))
        root = next(r for r in native['trace']['spans'] if r['stage'] == 1)
        worker = next(r for r in native['trace']['spans'] if r['stage'] == 6)
        worker['end_ns'] = root['end_ns'] + 1
        interval_rejected = reject(run, path, native, 'outside L0')
    return {'run_id':run_id, 'plan_content_id':plan['plan_content_id'], 'cli_api_same_plan':True,
            'profiles_overlap_observed':True, 'clean_and_profile_elf_needed':elf_needed,
            'replay_byte_identical':True, 'lost_event_relabel_rejected':lost_rejected,
            'worker_interval_outside_l0_rejected':interval_rejected}


if __name__ == '__main__':
    print(json.dumps(main(sys.argv[1]), ensure_ascii=False, indent=2))
