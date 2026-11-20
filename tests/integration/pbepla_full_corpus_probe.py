"""Run a development PBEPLA pair from a rederived full-corpus definition.

Not a submission entry point or a receipt; uses historical executable assets,
never historical codec outputs. Run as a module with PYTHONPATH=src in tsbench.
"""
import argparse
from pathlib import Path
import shutil
import tempfile

from tsbench.application.pbepla_execution import check_same_run, inspect_evidence, run_slot
from tsbench.assets import canonical_bytes, content_id, digest, load_json, require, verify_asset
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.batch_execution import BatchInput
from tsbench.planner.native_corpus import verify_native_corpus_plan
from tsbench.planner.pbepla_corpus import bind_native_pair
from tsbench.planner.pbepla_execution import DEFAULT_METHOD, DIRECT, CALLBACK, PROGRESSIVE, REPLAY
from tsbench.supervisor.isolated_worker import invoke_isolated_worker, program_files

ROOT = Path(__file__).resolve().parents[2]


def seal(name, data):
    with name.open('xb') as stream:
        stream.write(canonical_bytes(data) + b'\n')


def run(args):
    definition = load_json(args.definition)
    require(verify_native_corpus_plan(ROOT, definition)['definition_verified'], 'cannot bind unverified definition')
    corpus = load_full_manifest(ROOT, definition['bindings']['manifest'])
    entries = {e['id']: e for e in corpus['datasets']}
    decisions = {(d['dataset_id'], d['route']): d for d in definition['decisions']}
    pairs = [bind_native_pair(ROOT, entries[name], decisions[name, PROGRESSIVE], decisions[name, REPLAY],
                              column=int(col), window=int(window))
             for name, col, window in (request.split(':') for request in args.input)]
    previous = load_json(args.previous_run/'plan.json')
    runtime = previous['decoder']
    roots = [runtime['worker'], runtime['plugins'][DEFAULT_METHOD['plugin']],
             runtime['tools'][DIRECT], runtime['tools'][CALLBACK]]
    files = program_files(runtime, roots)
    slots = [slot for pair, _ in pairs for slot in pair]
    require(len(slots) == len({slot['product_slot'] for slot in slots}), 'duplicate probe input')
    plan = {'purpose': 'pbepla_real_corpus_probe_not_acceptance', 'corpus_plan_content_id': definition['plan_content_id'],
            'build_id': previous['build']['build_id'], 'decoder': runtime, 'limits': previous['limits'],
            'slots': slots, 'qualification_granted': False, 'timing_admitted': False,
            'code': {p: digest(ROOT/p) for p in ('src/tsbench/planner/pbepla_corpus.py',
                     'src/tsbench/application/pbepla_execution.py', 'tests/integration/pbepla_full_corpus_probe.py')}}
    plan['plan_content_id'] = content_id(plan)
    out = args.out.resolve()
    out.mkdir(parents=True)
    for part in ('logs', 'products', 'restore'):
        (out/part).mkdir()
    for key in files:
        src = verify_asset(args.previous_run/'recovery', {'path': key, 'sha256': runtime['files'][key]['sha256']})
        dest = out/'recovery'/key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    seal(out/'plan.json', plan)
    rows = []
    with (out/'ledger.jsonl').open('xb') as ledger:
        for pair, raw in pairs:
            for slot in pair:
                row = run_slot(out, plan, slot, BatchInput(b'', (raw,)), lambda: False)
                ledger.write(canonical_bytes(row) + b'\n')
                ledger.flush()
                rows.append(row)
    sealed = {str(p.relative_to(out)): {'path': str(p.relative_to(out)), 'bytes': p.stat().st_size, 'sha256': digest(p)}
              for folder in ('products', 'logs') for p in (out/folder).rglob('*') if p.is_file()}
    verified = {slot['product_slot'] for slot, row in zip(slots, rows, strict=True)
                if inspect_evidence(out, plan, slot, row, sealed, set())}
    check_same_run(plan, rows, verified)
    restore = []
    for slot, row in zip(slots, rows, strict=True):
        sid = slot['product_slot']
        if sid not in verified:
            continue
        with tempfile.TemporaryDirectory(prefix='pbepla-corpus-only-frames-') as tmp:
            work = Path(tmp)
            for name, layer in zip(slot['spec']['frame_paths'], row['pbepla']['layers'], strict=True):
                label = f'{sid}-{layer["layer"]}'
                frame = verify_asset(out, row['parts'][name])
                step = work/label
                step.mkdir()
                output, operation = invoke_isolated_worker(out/'recovery', runtime, DEFAULT_METHOD, plan['limits'],
                    step, out/'restore', 'decode', {'frame': frame}, ['/inputs/frame', 'values', 'schema'], lambda: False,
                    label=label, observe=True, options_text='{}')
                require(operation['status'] == 'completed' and operation['returncode'] == 0 and
                        set(operation['input_mounts']) == {'frame'} and
                        digest(output/'values') == layer['restored_sha256'] and
                        digest(output/'schema') == slot['spec']['schema_sha256'], 'PBEPLA detached recovery differs')
                restore.append({'slot': sid, 'layer': layer['layer'], 'operation': operation})
    report = {'plan_content_id': plan['plan_content_id'], 'verified_products': len(verified),
              'product_denominator': len(slots), 'isolated_prefix_restores': len(restore),
              'restore': restore, 'products': rows, 'stage_accepted': False, 'timing_admitted': False}
    seal(out/'report.json', report)
    require(len(verified) == len(slots), 'one or more real PBEPLA probe products did not verify')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition', type=Path, required=True)
    parser.add_argument('--previous-run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--input', metavar='DATASET:COL:WINDOW', action='append', required=True)
    run(parser.parse_args())
