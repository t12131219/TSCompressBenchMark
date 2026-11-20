#!/usr/bin/env python3
"""Diagnostic only: check an opt-in Gorilla repair build against the frozen batch oracle."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from tsbench.application.m3_gorilla import invoke, run_gorilla
from tsbench.assets import ContractError, digest, load_json, local_file, require, verify_asset
from tsbench.corpus_ingress import load_full_manifest

PATCH = 'third_party/patches/gorilla-c11-resume-initial-window.candidate.patch'


def run(root, plan, reference, build, out):
    out.mkdir(parents=True, exist_ok=False)
    control = build / 'tsbench_gorilla_corpus_control'
    dependency = build / 'libgorilla_c.so'
    original = plan['build']['gorilla_corpus']
    require(digest(control) == original['executable']['sha256'] and digest(dependency) != original['dependency']['sha256'],
            'candidate must change exactly the explicitly nominated dependency, not the harness')
    frozen = load_json(verify_asset(root, plan['definition']['plan']))
    reference_path = local_file(reference, 'report.json')
    seal = load_json(local_file(reference, 'completion.json'))
    report = load_json(reference_path)
    require(seal['report_sha256'] == digest(reference_path) and seal['plan_content_id'] == report['plan_content_id'] ==
            plan['plan_content_id'] and report['stage_accepted'] is False, 'reference batch run is not the frozen r17 evidence')
    reference_batches = {r['dataset_id']: r['evidence'] for r in report['rows'] if r['route']=='tv-batch' and r['status']=='verified'}
    selected = [r for r in plan['work_items'] if r['route']=='append-resume' and r['applicability']=='input_domain_matches']
    entries = {e['id']:e for e in load_full_manifest(root, frozen['bindings']['manifest'])['datasets']}
    require(len(selected) == len(reference_batches) == 16, 'candidate scope must cover all 16 admitted inputs')
    # Pin the four-row reproducer independently from the real corpus failures.
    with tempfile.TemporaryDirectory(prefix='m3-gorilla-minimal-') as td:
        work = Path(td)
        (work / 'input').mkdir()
        (work / 'input/axis.ms').write_bytes(struct.pack('<4q', 0, 1000, 2000, 3000))
        (work / 'input/column-0000.bin').write_bytes(struct.pack('<4Q', 0, 0, 1, 1))
        frozen_exe = verify_asset(root, original['executable'])
        why = None
        try:
            invoke(frozen_exe, work, 'encode', 'append-resume', 'input', 1, 4, 'frozen.gtv1', 'frozen-snap.gtv1')
        except ContractError as exc:
            why = str(exc)
        require(why and 'resumed result differs from batch bytes' in why, 'frozen reproducer did not exercise initial-window failure')
        invoke(control, work, 'encode', 'append-resume', 'input', 1, 4, 'repair.gtv1', 'repair-snap.gtv1')
        (work / 'restore').mkdir()
        invoke(control, work, 'decode', 'append-resume', 'repair.gtv1', 'restore')
        bits = (work / 'restore/column-0000.tv').read_bytes()
        require(bits == b''.join(struct.pack('<qQ', t, v) for t, v in zip((0,1000,2000,3000), (0,0,1,1))),
                'candidate four-row restoration differs')
        minimal = {'rows': 4, 'frozen_result': why, 'candidate_restored_tv_sha256': sha256(bits).hexdigest()}
    opts = {'build':{'gorilla_corpus':{'executable':{'path':control.relative_to(root).as_posix()}}}}
    rows = []
    for item in selected:
        dataset = item['dataset_id']
        with tempfile.TemporaryDirectory(prefix='m3-gorilla-candidate-') as td:
            evidence = run_gorilla(root, opts, item, entries[dataset], Path(td), out)
        actual, oracle = evidence['units'], reference_batches[dataset]['units']
        require(len(actual)==len(oracle) and all((a['frame_sha256'],a['restored_tv_sha256']) ==
                (b['frame_sha256'],b['restored_tv_sha256']) for a,b in zip(actual,oracle,strict=True)),
                f'candidate disagrees with frozen batch on {dataset}')
        record = {'dataset_id':dataset,'status':'verified_diagnostic','chunks':len(actual),
                  'candidate_final_frame_bytes':evidence['native_frame_bytes'],'candidate_snapshot_native_bytes':evidence['snapshot_native_bytes'],
                  'retained_samples':evidence['retained_samples']}
        rows.append(record)
        with (out / 'ledger.jsonl').open('a',encoding='utf-8') as ledger:
            ledger.write(json.dumps(record)+'\n')
    evidence = {'schema':'bmk.m3-gorilla-repair-candidate/1','reference_run_id':report['run_id'],
                'base_plan_content_id':plan['plan_content_id'],'published_m3_driver_unchanged':True,
                'patch_sha256':digest(local_file(root,PATCH)), 'candidate_gorilla_c_sha256':digest(dependency),
                'original_gorilla_c_sha256':original['dependency']['sha256'],'minimal_reproducer':minimal,'rows':rows,
                'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}
    (out / 'report.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(len(rows), sum(r['chunks'] for r in rows), 'candidate-only matches against frozen batch')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan','reference','build','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    a = parser.parse_args()
    run(ROOT, load_json(a.plan), a.reference.resolve(strict=True), a.build.resolve(strict=True), a.out.resolve())
