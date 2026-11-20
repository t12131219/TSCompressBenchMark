#!/usr/bin/env python3
"""Replay r40 SElf* retained first columns and specialist terminals from the full sealed ledger."""
import argparse
from collections import Counter
from hashlib import sha256
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.batch_execution import _files
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.m3_selfstar import audit_specialized, validate_profiles, wire_facts
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.corpus_ingress import read_batches
from tsbench.planner.m3_selfstar import CORPUS_TOOL, DRIVERS
from tsbench.planner.selfstar import BLOCK
from tsbench.planner.selfstar_execution import LIVE, PLUGIN
from tsbench.recovery import DIRECTORY
from tsbench.supervisor.isolated_worker import invoke_isolated_tool, invoke_isolated_worker, launcher_lock

LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 8 << 20, 'wall_seconds': 30}


def original_first_column(root, entry):
    col, n = sha256(), 0
    for batch in read_batches(root, entry):
        col.update(np.frombuffer(batch.values, dtype='V8').reshape(batch.rows, entry['value_count'])[:, 0].tobytes())
        n += batch.rows
    require(n == entry['rows'], 'SElf* audited original did not consume the full declared column extent')
    return {'bytes': n*8, 'sha256': col.hexdigest()}


def replay(run, binding, row, expected, work):
    first, evidence = row['evidence']['units'][0], row['evidence']
    sample = evidence['retained_sample']
    frame = verify_asset(run, sample)
    refs = {'bytes': sample['bytes'], 'sha256': sample['sha256']}
    require(sample['path'] == f"retained/{row['work_item_id']}/full-column-zero.bmk" and
            refs == {'bytes': first['artifact_bytes'], 'sha256': first['frame_sha256']} and
            first['column'] == 0 and first['row_range'] == [0, evidence['rows']] and
            expected == {'bytes': first['input_bytes'], 'sha256': first['restored_sha256']},
            'SElf* full-ledger first-column identity differs')
    spec = binding['decoder']
    bundle = run / 'selfstar-specialized' / DIRECTORY
    live = row['route'] == LIVE
    if live:
        name = 'read-finalized'
        out, proc = invoke_isolated_tool(bundle, spec, CORPUS_TOOL, LIMITS, work, work, name,
                                         {'frame': frame}, [name, '/inputs/frame', '/out/raw', '/out/schema'], lambda: False,
                                         bind_inputs=True, file_ceiling=LIMITS['file_bytes'])
    else:
        name = 'decode-columns'
        out, proc = invoke_isolated_worker(bundle, spec, {'plugin': PLUGIN, 'options': {}}, LIMITS, work, work, name,
                                           {'frame': frame}, ['/inputs/frame', '/out/schema', '/out/raw'], lambda: False,
                                           observe=True, file_ceiling=LIMITS['file_bytes'])
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and proc['input_mounts'] == {'frame': refs} and
            {p.name for p in out.iterdir()} == {'raw', 'schema'} and not (work/(name+'.stderr')).stat().st_size,
            'SElf* files-only replay failed: ' + (work/(name+'.stderr')).read_text()[:300])
    raw, schema = local_file(out, 'raw'), local_file(out, 'schema').read_bytes()
    facts = wire_facts(frame.read_bytes(), evidence['rows'], schema)
    require({'bytes': raw.stat().st_size, 'sha256': digest(raw)} == expected and
            sha256(schema).hexdigest() == first['schema_sha256'] and facts == {k: first[k] for k in facts},
            'SElf* replay differs from locked values/schema/complete frame')
    dec = [parse_json(line, 'SElf* replay profile') for line in (work/(name+'.stdout')).read_text().splitlines() if line]
    # The ledger retains the reduced encoding facts and lifecycle, not stdout.
    counts = {k: facts[k] for k in ('blocks', 'native_bits', 'native_payload_bytes')}
    if live:
        enc = [{'mode': 'live', 'rows': evidence['rows'], **counts, **first['lifecycle']}]
    else:
        require(first['lifecycle'] is None, 'SElf* batch retained unexpected stream state')
        enc = [{'backend': 'selfstar-c-scalar', 'mode': 'batch', 'threads': 1, 'fallback': False,
                'block_values': BLOCK, 'block_header_bytes': facts['block_header_bytes'], 'operation': 'encode', **counts}]
    validate_profiles(enc, dec, live, evidence['rows'], facts)
    return {'dataset_id': row['dataset_id'], 'work_item_id': row['work_item_id'], 'route': row['route'],
            'artifact': {'path': sample['path'], **refs}, 'restored': expected, 'schema_sha256': first['schema_sha256'],
            'wire': facts, 'decode_observation': dec, 'session_id': proc['session_id']}


def audit(root, planfile, run):
    plan = load_json(planfile)
    ledger, seal = full_run_source(plan, run)
    binding = plan['specialized']['selfstar']
    require(binding['launchers'] == launcher_lock(), 'SElf* isolation launcher lock changed')
    definition = load_json(verify_asset(root, plan['definition']['plan']))
    entries = _entry_map(root, definition)
    parts, obligations, rows = {}, [], []
    for row, scope in full_run_rows(plan, ledger):
        if row.get('selection') != 4:
            continue
        kind = row.get('entry_kind')
        if kind == 'specialized_product':
            slot = row['product_slot']
            require(slot not in parts, 'duplicate SElf* specialized terminal')
            parts[slot] = {k: v for k, v in row.items() if k not in ('entry_kind', 'selection')}
        elif kind == 'specialized_obligation':
            obligations.append({k: v for k, v in row.items() if k != 'entry_kind'})
        elif kind is None and (4, row['route']) in DRIVERS:
            require(scope['input']['full_extent_of_file_rows_and_value_columns'] and row['status'] == 'verified',
                    'SElf* full-corpus route not verified')
            rows.append(row)
    require(len(rows) == 2*len(entries), 'SElf* missing a file-route row in the full ledger')
    candidates, sessions, replayed = {}, set(), []
    for row in rows:
        ds = row['dataset_id']
        if ds not in candidates:
            candidates[ds] = original_first_column(root, entries[ds])
        with TemporaryDirectory(prefix='m3-selfstar-r40-replay-') as d:
            r = replay(run, binding, row, candidates[ds], Path(d))
        require(r['session_id'] and r['session_id'] not in sessions, 'SElf* isolated decode process was reused')
        sessions.add(r['session_id'])
        replayed.append(r)
    folder = run/'selfstar-specialized'
    specialized = audit_specialized(root, run, binding, obligations, {
        'driver': binding['driver'], 'recovery_id': binding['decoder']['recovery_id'], 'fixtures': parts,
        'statuses': dict(Counter(row['status'] for row in parts.values())), 'files': _files(folder)}, replay=True)
    out = {'schema': 'bmk.m3-selfstar-full-ledger-audit/1', 'run_id': run.name, 'run_seal_id': seal,
           'plan_id': plan['plan_content_id'], 'replayed_samples': replayed, 'specialized': specialized,
           'replay_scope': 'historical_full_first_value_column_per_route_and_separate_specialist_products',
           'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}
    return {**out, 'audit_id': content_id(out)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for opt in ('plan', 'run', 'out'):
        ap.add_argument('--'+opt, type=Path, required=True)
    args = ap.parse_args()
    try:
        result = audit(ROOT, args.plan.resolve(strict=True), args.run.resolve(strict=True))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_new(args.out, result)
        print(result['audit_id'], len(result['replayed_samples']))
    except (ContractError, OSError) as exc:
        ap.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
