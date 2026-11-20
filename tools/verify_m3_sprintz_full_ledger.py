#!/usr/bin/env python3
"""Replay only the retained Sprintz FIRE ABI and SFB1 samples of one M3 seal."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_sprintz_timing as query
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.m3_sprintz import verify_frame
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, parse_json, require
from tsbench.planner.m3_sprintz import BATCH, DRIVER, QUERY
from tsbench.planner.sprintz_execution import ABI_METHOD
from tsbench.recovery import plan_recovery, stage_recovery
from tsbench.supervisor.isolated_worker import invoke_isolated_worker, launcher_lock
from tsbench.supervisor.timing_resource import reserve

SCHEMA = 'bmk.m3-sprintz-full-ledger-audit/1'
FLAGS = dict.fromkeys(('timing_admitted', 'qualification_granted', 'stage_accepted'), False)
NATIVE_BATCH = {'operation': 'decode', 'threads': 1, 'lanes': 4, 'algorithm': 'fire', 'path': 'generic_rle'}


def project(run, item, row):
    batch = (item['selection'], item['route']) == BATCH
    evidence, extent = row['evidence'], item['input']
    require(evidence['driver'] == (DRIVER if batch else 'sprintz-corpus-query/1') and
            extent['slice_extent']['max_per_unit'] == query.ROWS and evidence['units'] and
            len(evidence['units']) == extent['size_estimate']['input_units'], 'Sprintz replay driver or extent differs')
    region, = extent['row_ranges']
    unit = evidence['units'][0]
    sample = evidence['retained_sample']
    nrows = min(region['end'], query.ROWS)
    expected_suffix = 'batch-sample.bmk' if batch else 'query-sample.sfb1'
    require(region['start'] == 0 and nrows > 0 and extent['value_column_range'][0] == 0 and
            (unit['column'], unit['row_start'], unit['row_end'], unit['raw_bytes']) == (0, 0, nrows, 8 * nrows) and
            sample['observation'] == unit and sample['sha256'] == unit['frame_sha256'] and
            sample['bytes'] == unit['artifact_bytes' if batch else 'frame_bytes'] and
            sample['path'] == f"retained/{item['work_item_id']}/{expected_suffix}", 'Sprintz first retained frame identity differs')
    path = query.check(run, sample)
    require(path == run / sample['path'], 'Sprintz retained sample path is linked')
    return ({'dataset_id': row['dataset_id'], 'work_item_id': item['work_item_id'], 'route': item['route'],
             'rows': nrows, 'columns': 1, 'workspace_bytes': evidence.get('codec_workspace_bytes'),
             'units': [unit], 'artifact': {k: sample[k] for k in ('path', 'bytes', 'sha256')}}, path)


def same_first_unit(batch, q):
    a, b = batch['units'][0], q['units'][0]
    require(all(a[k] == b[k] for k in ('column', 'row_start', 'row_end', 'raw_bytes', 'restored_sha256')) and
            (a['sfb1_bytes'], a['sfb1_sha256']) == (b['frame_bytes'], b['frame_sha256']),
            'Sprintz ABI embedded frame and compressed-domain retained sample differ')


def _file_only(case, name, process, sessions):
    expected = {k: case['artifact'][k] for k in ('bytes', 'sha256')}
    sid = process.get('session_id')
    require(process['status'] == 'completed' and process['returncode'] == 0 and sid and sid not in sessions and
            process['input_mounts'] == {name: expected}, 'Sprintz replay was not a fresh frame-only process')
    sessions.add(sid)


def replay_batch(bundle, binding, case, path, work, sessions):
    work.mkdir()
    out, process = invoke_isolated_worker(bundle, binding['decoder'], ABI_METHOD, binding['limits'], work, work,
                                           'decode-columns', {'frame': path},
                                           ['/inputs/frame', '/out/schema', '/out/raw'], lambda: False, observe=True)
    _file_only(case, 'frame', process, sessions)
    require({p.name for p in out.iterdir()} == {'schema', 'raw'} and not (work / 'decode-columns.stderr').stat().st_size,
            'Sprintz batch replay emitted unexpected output')
    raw, schema = ((out / name).read_bytes() for name in ('raw', 'schema'))
    inner = verify_frame(path.read_bytes(), raw, schema)
    obs = [parse_json(line) for line in (work / 'decode-columns.stdout').read_bytes().splitlines()]
    unit = case['units'][0]
    require(query.ref(out / 'raw') == {'bytes': unit['raw_bytes'], 'sha256': unit['restored_sha256']} and
            query.ref(out / 'schema')['sha256'] == unit['schema_sha256'] and
            sha256(inner).hexdigest() == unit['sfb1_sha256'] and len(inner) == unit['sfb1_bytes'] and
            obs == [{'columns': [{'dtype': 4, 'count': len(raw) // 2}]}, NATIVE_BATCH], 'Sprintz batch replay differs')
    return {'artifact': case['artifact'], 'decode_session': process['session_id'], 'restored_sha256': unit['restored_sha256']}


def replay_query(bundle, runtime, case, path, work, sessions):
    work.mkdir()
    runtime_plan = {'runtime': runtime}
    inputs = {'archive.sfb1': path}
    out, decoded, doc = query._invoke(bundle, runtime_plan, case, work / 'restore', 'decode', inputs)
    _file_only(case, 'archive.sfb1', decoded, sessions)
    query._native(case, 'decode', doc)
    columns = query._verify_columns(case, out, oracle=True)
    query_out, queried, doc = query._invoke(bundle, runtime_plan, case, work / 'query', 'query', inputs)
    _file_only(case, 'archive.sfb1', queried, sessions)
    require(not any(query_out.iterdir()), 'Sprintz compressed-domain query emitted undeclared files')
    query._native(case, 'query', doc)
    return {'artifact': case['artifact'], 'decode_session': decoded['session_id'], 'query_session': queried['session_id'],
            'restored_sha256': columns['column-0000.bin']['sha256']}


def audit(root, plan, run):
    ledger, seal = full_run_source(plan, run)
    with reserve():
        projected, absent, pairs = [], [], {}
        for row, item in full_run_rows(plan, ledger):
            if item is None or (item['selection'], item['route']) not in {BATCH, QUERY}:
                continue
            if row['status'] != 'verified':
                absent.append({k: row[k] for k in ('work_item_id', 'dataset_id', 'route', 'status', 'reason')})
                continue
            case, path = project(run, item, row)
            projected.append((case, path))
            pairs.setdefault(case['dataset_id'], {})[case['route']] = case
        expected = [i for i in plan['work_items'] if (i['selection'], i['route']) in {BATCH, QUERY}]
        require(len(projected) + len(absent) == len(expected) == 46, 'Sprintz audit needs the full 23-file two-route scope')
        for pair in pairs.values():
            if pair.keys() == {BATCH[1], QUERY[1]}:
                same_first_unit(pair[BATCH[1]], pair[QUERY[1]])
        batch = plan['specialized']['sprintz']
        require(launcher_lock() == batch['launchers'], 'Sprintz replay launchers differ from the frozen runtime')
        spec = plan['build']['sprintz_query']
        for ref in spec.values():
            query.check(root, ref)
        program = {k: spec['executable'][k] for k in ('path', 'sha256')}
        decoder = plan_recovery(root, {}, (), tools={query.TOOL: program}, libraries=[spec['dependency']])
        with TemporaryDirectory(prefix='m3-sprintz-files-only-') as tmp:
            work = Path(tmp)
            batch_bundle, query_bundle = work / 'batch-runtime', work / 'query-runtime'
            stage_recovery(root, work, batch['decoder'], directory=batch_bundle.name)
            stage_recovery(root, work, decoder, directory=query_bundle.name)
            replayed, sessions = [], set()
            for n, (case, path) in enumerate(projected):
                scratch = work / f'replay-{n:04d}'
                if case['route'] == BATCH[1]:
                    result = replay_batch(batch_bundle, batch, case, path, scratch, sessions)
                else:
                    result = replay_query(query_bundle, decoder, case, path, scratch, sessions)
                replayed.append({**{k: case[k] for k in ('work_item_id', 'dataset_id', 'route', 'rows')}, **result})
    body = {'schema': SCHEMA, 'run_id': run.name, 'run_seal_id': seal, 'plan_id': plan['plan_content_id'],
            'scope': 'retained_first_unit_only_frame_only_isolated_replay_no_native_timing',
            'native_runtime_ids': {'fire-batch': batch['decoder']['recovery_id'], 'query': decoder['recovery_id']},
            'replayed_samples': replayed, 'nonverified_corpus_decisions': absent, 'isolated_processes': len(sessions), **FLAGS}
    return {**body, 'audit_id': content_id(body)}


def main():
    p = ArgumentParser(description=__doc__)
    for name in ('plan', 'run', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    try:
        doc = audit(ROOT, load_json(a.plan), a.run.resolve(strict=True))
        write_new(a.out, doc)
        print(doc['audit_id'], len(doc['replayed_samples']))
    except (ValueError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
