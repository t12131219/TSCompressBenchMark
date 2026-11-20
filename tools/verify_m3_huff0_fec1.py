#!/usr/bin/env python3
"""Audit sealed FEC1 corpus extent/charges and replay only the retained frames."""
import argparse
from binascii import crc32
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_huff0_fec1 import asset, call, frames
from tsbench.application.m3_huff0_specialized import ledger_products
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import load_full_manifest, read_batches
from tsbench.planner.huff0 import BLOCK, ENVELOPE, FEC, RECORD
from tsbench.planner.m3_huff0_fec1 import BATCH, DRIVER, KEY, UNIT
from tsbench.planner.m3_huff0_table import KEY as TABLE_KEY
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan


def check_file(root, entry, item, proof, run, binding, sessions):
    n = entry['rows']*entry['value_count']*8
    expected = {'bytes': n, 'sha256': entry['canonical']['values_sha256']}
    schema = json.dumps({'role': 'bytes', 'dtype': 'u8', 'rows': entry['rows']}, separators=(',', ':')).encode()
    require(proof['input'] == proof['recovered'] == expected and proof['schema'] == asset(schema) and
            proof['driver'] == DRIVER and proof['timing_admitted'] is False and
            (proof['native_block_bytes'], proof['abi_unit_bytes']) == (BLOCK, UNIT), 'FEC1 corpus identity differs')
    in_hash, counts, charges, samples = sha256(), Counter(), Counter(), []
    native_frames = 0
    with TemporaryDirectory(prefix='tsbench-fec1-audit-') as tmp:
        # Rebuild the canonical original outside all decode mounts. The staging file
        # lets the audit read the original using the frozen byte slices, not CSV batches.
        temp = Path(tmp)
        original = temp / 'values.u8'
        with original.open('xb') as output:
            for b in read_batches(root, entry):
                output.write(b.values)
        with original.open('rb') as source:
            for offset, group in zip(range(0, n, BATCH), proof['groups'], strict=True):
                raw = source.read(BATCH)
                gsize = 0
                in_hash.update(raw)
                require(group['offset'] == offset and group['decoded'] == asset(raw), 'FEC1 process group differs')
                obs = group['detached_process']
                sid = obs['session_id']
                require(obs['input_mounts'] == {'frames.bmk': group['wire']} and isinstance(sid, str) and sid and
                        sid not in sessions and type(obs['pid']) is int and obs['pid'] > 0,
                        'FEC1 process mount or identity differs')
                sessions.add(sid)
                for start, row in zip(range(0, len(raw), UNIT), group['frames'], strict=True):
                    unit = raw[start:start+UNIT]
                    require(row['decoded'] == asset(unit), 'FEC1 original frame digest differs')
                    unit_cost = Counter({'abi_header': ENVELOPE.size, 'schema': len(schema), 'fec_header': FEC.size,
                                         'record_headers': RECORD.size*len(row['records'])})
                    for off, r in zip(range(0, len(unit), BLOCK), row['records'], strict=True):
                        block = unit[off:off+BLOCK]
                        mode, d, c = (r[k] for k in ('mode', 'decoded_bytes', 'body_bytes'))
                        require(d == len(block) and r['crc32'] == crc32(block) and
                                (mode == 'raw' and c == d or mode == 'rle' and c == 1 < d or
                                 mode == 'huffman' and 0 < c < d), 'FEC1 block census differs')
                        counts[mode] += 1
                        unit_cost[mode+'_body'] += c
                    charges.update(unit_cost)
                    unit_size = sum(unit_cost.values())
                    require(row['frame']['bytes'] == unit_size, 'FEC1 complete frame cost differs')
                    gsize += unit_size
                    native_frames += 1
                    name = ('first.bmk' if offset+start == 0 else 'last.bmk' if offset+start+len(unit) == n else None)
                    retained = row.get('retained')
                    if name:
                        require(retained == {'path': f"retained/{item['work_item_id']}/{name}", **row['frame']},
                                'FEC1 retained extent differs')
                        wire = verify_asset(run, retained)
                        require(list(frames(wire.read_bytes(), unit, schema)) ==
                                [((0, unit_size), {k: v for k, v in row.items() if k != 'retained'})], 'retained FEC1 layout differs')
                        out, meta, obs = call(run, binding, temp / name, 'decode', {'frames.bmk': wire})
                        require(out.read_bytes() == unit and obs['input_mounts'] == {'frames.bmk': row['frame']} and
                                meta == {'frames': 1, 'input_bytes': len(unit), 'frame_bytes': unit_size},
                                'retained FEC1 isolated replay differs')
                        samples.append(retained)
                    else:
                        require(retained is None, 'unexpected retained FEC1 frame')
                require(gsize == group['wire']['bytes'], 'FEC1 group accounting differs')
            require(not source.read(1), 'FEC1 original has unaccounted bytes')
    require(in_hash.hexdigest() == expected['sha256'] and proof['modes'] == counts and proof['byte_cost'] == charges and
            proof['complete_bytes'] == sum(charges.values()) and native_frames == item['input']['size_estimate']['input_units'],
            'FEC1 corpus total differs')
    return native_frames, counts, charges, samples


def verify(root, plan, run):
    check_m3_real_corpus_plan(root, plan)
    f = {n: local_file(run, n) for n in ('report.json', 'ledger.jsonl', 'completion.json')}
    report, seal = load_json(f['report.json']), load_json(f['completion.json'])
    load_contract(root, 'm3-real-corpus-run').validate(report, 'Huff0 FEC1 run')
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(f['report.json']), 'ledger_sha256': digest(f['ledger.jsonl'])}
    require(seal == {**body, 'seal_id': content_id(body)} and report['run_id'] == run.name and
            report['plan_content_id'] == plan['plan_content_id'] and report['partial_preflight'] and
            report['route_filter'] in ([KEY[1]], sorted([KEY[1], TABLE_KEY[1]])), 'FEC1 run scope or seal differs')
    special = report['specialized']
    require(special.keys() <= {'huff0'}, 'unexpected FEC1 audit specialist scope')
    products = ledger_products(plan['specialized']['huff0'], special['huff0']) if 'huff0' in special else []
    with f['ledger.jsonl'].open(encoding='utf-8') as ledger:
        for line, record in zip(ledger, [*report['rows'], *products, *report['obligations']], strict=True):
            require(json.loads(line) == record, 'FEC1 report differs from main ledger')
    wanted = [i for i in plan['work_items'] if (i['selection'], i['route']) == KEY]
    rows = [r for r in report['rows'] if (r['selection'], r['route']) == KEY]
    require(len(wanted) == len(rows) == 23 and dict(Counter(r['status'] for r in report['rows'])) == report['statuses'],
            'FEC1 run census differs')
    definition = load_json(verify_asset(root, plan['definition']['plan']))
    entries = {e['id']: e for e in load_full_manifest(root, definition['bindings']['manifest'], parse=False)['datasets']}
    binding = plan['build']['huff0_fec1']
    sessions, modes, charges, replays, failures = set(), Counter(), Counter(), [], []
    frame_count = 0
    for item, row in zip(wanted, rows, strict=True):
        require(all(row[k] == item[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route', 'operation', 'applicability'))
                and row['applicability'] == 'input_domain_matches', 'FEC1 file-route identity differs')
        if row['status'] == 'failed':
            require(row['reason'] and row['evidence'] is None, 'FEC1 error lacks a terminal cause')
            failures.append({k: row[k] for k in ('dataset_id', 'reason')})
            continue
        require(row['status'] == 'verified' and not row['reason'], 'unexpected FEC1 result status')
        n, m, c, samples = check_file(root, entries[item['dataset_id']], item, row['evidence'], run, binding, sessions)
        frame_count += n
        modes.update(m)
        charges.update(c)
        replays.extend(samples)
    return {'schema': 'bmk.m3-huff0-fec1-audit/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'run_seal_id': seal['seal_id'], 'files_verified': len(wanted)-len(failures), 'abi_frames': frame_count,
            'decode_processes': len(sessions), 'native_modes': dict(modes), 'byte_cost': dict(charges),
            'complete_bytes': sum(charges.values()), 'replayed_samples': replays, 'failures': failures,
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(verify(ROOT, load_json(a.plan), a.run.resolve(strict=True)), indent=2))
