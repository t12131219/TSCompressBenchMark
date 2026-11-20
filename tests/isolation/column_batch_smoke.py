"""Validate fixed complete ALP/Titchy frames and detached bits in Bubblewrap."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_column_batch as batch
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, digest, load_json, local_file, require
from tsbench.recovery import stage_recovery
from tsbench.supervisor import timing_resource as resource

CASES = {('ettm2', 'auto-batch'), ('ettm2', 'decode-backends'), ('etth1', 'batch')}


@contextmanager
def pinned(cpu):
    allowed = os.sched_getaffinity(0)
    require(cpu in allowed, 'column batch smoke CPU not allowed')
    os.sched_setaffinity(0, {cpu})
    try:
        yield
    finally:
        os.sched_setaffinity(0, allowed)


def smoke(path, cpu):
    pop = load_json(path)
    require(pop['schema'] == batch.SCHEMA and pop['population_id'] == content_id({k: v for k, v in pop.items() if k != 'population_id'})
            and pop['launchers'] == batch.launcher_lock() and pop['limits'] == batch.LIMITS and
            all(digest(local_file(ROOT, p)) == h for p, h in pop['code'].items()), 'column batch control population differs')
    source = load_json(batch.check(ROOT, pop['source_plan']))
    entries = batch._entry_map(ROOT, load_json(batch.check(ROOT, source['definition']['plan'])))
    cases = [c for c in pop['cases'] if (c['dataset_id'], c['route']) in CASES]
    require(len(cases) == len(CASES) and {(c['dataset_id'], c['route']) for c in cases} == CASES,
            'column batch smoke is missing frozen full-file cases')
    results, sessions = [], set()
    with resource.reserve(), pinned(cpu), TemporaryDirectory(prefix='tsbench-column-batch-smoke-') as tmp:
        run = Path(tmp)
        bundle = run / 'runtime'
        stage_recovery(ROOT, run, pop['runtime'], directory='runtime')
        for case in cases:
            work = run / case['case_id']
            work.mkdir()
            original = batch.prepare_values(ROOT, entries[case['dataset_id']], case, work)
            raw = batch.identities(original)
            wire, encoded, enc_proc = batch.invoke(pop, bundle, case, 'encode', original, work / 'encode')
            fixed = batch.verify_frames(wire, case['units'])
            details = {}
            for slot in case['decode_backends']:
                restored, decoded, proc = batch.invoke(pop, bundle, case, slot, wire, work / slot)
                require(batch.identities(restored) == raw and proc['input_mounts'] == fixed and
                        proc['session_id'] not in sessions and proc['session_id'] != enc_proc['session_id'],
                        'column batch smoke detached original or process differs')
                sessions.add(proc['session_id'])
                details[slot] = decoded['execution_census']
            require(enc_proc['session_id'] not in sessions, 'duplicate column batch encode session')
            sessions.add(enc_proc['session_id'])
            results.append({'dataset': case['dataset_id'], 'route': case['route'], 'case_id': case['case_id'],
                            'frames': len(case['units']), 'groups': len(raw), 'archive': fixed, 'restored_original': raw,
                            'encode_census': encoded['execution_census'], 'decode_censuses': details})
    body = {'schema': 'bmk.m3-column-batch-isolation-smoke/1', 'population_id': pop['population_id'],
            'verified_direction_operations': len(sessions), 'cpu': cpu, 'cases': results,
            'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}
    return {**body, 'smoke_id': content_id(body)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--population', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--cpu', type=int, required=True)
    args = ap.parse_args()
    try:
        report = smoke(args.population, args.cpu)
        write_new(args.out, report)
        print(report['verified_direction_operations'], report['smoke_id'])
    except (ContractError, OSError) as exc:
        ap.exit(1, f'{exc}\n')
