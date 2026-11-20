#!/usr/bin/env python3
"""Restore retained Huff0 FEC1 and ETB1 objects without re-encoding or training."""
from argparse import ArgumentParser
from pathlib import Path
from tempfile import TemporaryDirectory

from m3_huff0_corpus_repeats import (ROOT, ETB1_KEY, ETB1_TOOL, FEC1_KEY, STREAMS, check,
                                    expected, frames, info, invoke, layout)
from tsbench.application.m3_huff0_fec1 import asset
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, require
from tsbench.planner.huff0 import ENVELOPE
from tsbench.planner.m3_huff0_fec1 import DRIVER as FEC1_DRIVER, UNIT
from tsbench.planner.m3_huff0_table import DRIVER as ETB1_DRIVER, RETAIN_MAX
from tsbench.qualification.huff0 import _model
from tsbench.recovery import plan_recovery, stage_recovery
from tsbench.supervisor.isolated_worker import launcher_lock
from tsbench.supervisor.timing_resource import reserve

SCHEMA = 'bmk.m3-huff0-full-ledger-audit/1'
FLAGS = dict.fromkeys(('stage_accepted', 'qualification_granted', 'timing_admitted'), False)
ETB1_PARTS = {'model.etb1': 'model', 'test.blocks': 'frame', 'binding.json': 'binding'}


def _sealed_part(run, sample, path, identity):
    require(sample == {'path': path, **identity}, 'Huff0 retained part identity or namespace differs')
    bound = check(run, sample)
    require(bound == run / path, 'Huff0 retained part is linked')
    return bound


def fec1_cases(run, item, ev):
    size = item['input']['size_estimate']; total = size['native_input_bytes_one_pass']
    require(ev['driver'] == FEC1_DRIVER and ev['input'] == ev['recovered'] and ev['input']['bytes'] == total,
            'Huff0 FEC1 whole input evidence differs')
    base = f"retained/{item['work_item_id']}"
    offset = count = 0
    for group in ev['groups']:
        require(group['offset'] == offset and group['frames'], 'Huff0 FEC1 group order differs')
        start = offset
        for frame in group['frames']:
            n = frame['decoded']['bytes']
            require(n == min(UNIT, total-offset) > 0, 'Huff0 FEC1 decoded extent differs')
            suffix = 'first.bmk' if not offset else 'last.bmk' if offset+n == total else None
            sample = frame.get('retained')
            require(bool(sample) == bool(suffix), 'Huff0 FEC1 retention does not match first/last policy')
            if suffix:
                path = _sealed_part(run, sample, f'{base}/{suffix}', frame['frame'])
                yield {'format': 'FEC1', 'byte_range': [offset, offset+n], 'artifact': frame['frame'], 'original': frame['decoded'],
                       'schema': ev['schema'], 'records': frame['records'], 'references': [sample]}, {'frame': path}
            offset += n
            count += 1
        require(offset-start == group['decoded']['bytes'], 'Huff0 FEC1 group length differs')
    require((offset, count) == (total, size['input_units']), 'Huff0 FEC1 complete extent differs')


def etb1_cases(run, item, ev):
    require(ev['driver'] == ETB1_DRIVER and ev['profiles'].keys() == {str(n) for n in STREAMS},
            'Huff0 ETB1 profiles differ')
    for streams in STREAMS:
        lane = ev['profiles'][str(streams)]
        require(lane['status'] == 'verified' and lane['recovered'] == ev['holdout'], 'Huff0 ETB1 held-out identity differs')
        parts = lane['retained']
        require(bool(parts) == (lane['frame']['bytes'] <= RETAIN_MAX), 'Huff0 ETB1 retention threshold differs')
        if not parts:
            yield {'streams': streams, 'reason': 'block_sequence_exceeded_retention_limit'}, None
            continue
        require(parts.keys() == ETB1_PARTS.keys(), 'Huff0 ETB1 retained set differs')
        base = f"retained/{item['work_item_id']}/{streams}x"
        identities = {name: lane[key] for name, key in ETB1_PARTS.items()}
        paths = {n: _sealed_part(run, parts[n], f'{base}/{n}', ref) for n, ref in identities.items()}
        yield {'format': 'ETB1', 'streams': streams, 'artifact': identities, 'original': ev['holdout'],
               'training': ev['training'], 'blocks': lane['blocks'], 'native': {'decode': lane['decode']},
               'references': [parts[n] for n in ETB1_PARTS]}, {
                   'model': paths['model.etb1'], 'blocks': paths['test.blocks'], 'binding': paths['binding.json']}


def fec1_check(wire, restored, case):
    require(len(wire) >= ENVELOPE.size, 'Huff0 FEC1 truncated ABI envelope')
    schema_n = ENVELOPE.unpack_from(wire)[3]
    require(schema_n == case['schema']['bytes'] and schema_n <= len(wire) - ENVELOPE.size,
            'Huff0 FEC1 embedded schema length differs')
    schema = wire[ENVELOPE.size:ENVELOPE.size+schema_n]
    require(asset(schema) == case['schema'], 'Huff0 FEC1 embedded schema identity differs')
    (_, parsed), = frames(wire, restored, schema)
    require(parsed == {'frame': case['artifact'], 'decoded': case['original'], 'records': case['records']},
            'Huff0 FEC1 independently parsed frame differs')


def replay(work, environment, case, paths, folder, sessions):
    mounts, output, native = expected(case, 'decode')
    if case['format'] == 'ETB1':
        require(_model(paths['model'].read_bytes(), case['streams']) == native['effective_table_log'] and
                layout(paths['blocks'], case['streams'], output['bytes']) == case['blocks'], 'Huff0 ETB1 parsed layout differs')
    # invoke verifies the ETB1 binding sidecar before launch, and mounts only model
    # + blocks for ETB1 (only the sealed frame for FEC1), never raw values/schema.
    restored, proc, meta = invoke(work, environment, case, folder, 'decode', paths)
    session = proc.get('session_id')
    require(session and session not in sessions and proc.get('input_mounts') == mounts and
            info(restored) == output and meta == native, 'Huff0 detached replay, native counters or restored identity differ')
    sessions.add(session)
    if case['format'] == 'FEC1':
        fec1_check(paths['frame'].read_bytes(), restored.read_bytes(), case)
    return {'references': case['references'], 'decode_session': session, 'restored': output}


def audit(root, plan, run):
    with reserve():
        ledger, seal = full_run_source(plan, run)
        jobs, absent, decisions = [], [], 0
        for row, item in full_run_rows(plan, ledger):
            if item is None or (item['selection'], item['route']) not in (FEC1_KEY, ETB1_KEY):
                continue
            decisions += 1
            coordinates = {k: item[k] for k in ('dataset_id', 'work_item_id', 'route')}
            if row['status'] != 'verified':
                absent.append({**coordinates, 'status': row['status'], 'reason': row['reason']})
                continue
            factory = fec1_cases if (item['selection'], item['route']) == FEC1_KEY else etb1_cases
            for case, paths in factory(run, item, row['evidence']):
                if paths is None:
                    absent.append({**coordinates, **case, 'status': 'sample_not_retained'})
                else:
                    jobs.append(({**coordinates, **case}, paths))
        require(decisions == 46, 'Huff0 audit requires 23 files over the two corpus routes')
        specs = plan['build']; fec, etb = specs['huff0_fec1'], specs['huff0_table']
        require(launcher_lock() == fec['launchers'], 'Huff0 replay launchers differ from the frozen runtime')
        for key in ('executable', 'dependency'):
            check(root, etb[key])
        spec = {k: etb['executable'][k] for k in ('path', 'sha256')}
        runtime = {'FEC1': fec['decoder'], 'ETB1': plan_recovery(root, {}, (), tools={ETB1_TOOL: spec}, libraries=[etb['dependency']])}
        with TemporaryDirectory(prefix='m3-huff0-files-only-') as tmp:
            work = Path(tmp)
            for name, closure in runtime.items():
                stage_recovery(root, work, closure, directory=name)
            sessions, replayed = set(), []
            for i, (case, inputs) in enumerate(jobs):
                result = replay(work, {'runtime': runtime}, case, inputs, work/f'replay-{i:04d}', sessions)
                keys = ('dataset_id', 'work_item_id', 'route', 'format', 'byte_range', 'streams')
                replayed.append({**{k: case[k] for k in keys if k in case}, **result})
    body = {'schema': SCHEMA, 'run_id': run.name, 'plan_id': plan['plan_content_id'], 'run_seal_id': seal,
            'scope': 'retained_corpus_objects_only_no_training_or_reencoding_no_native_timing',
            'runtime_ids': {k: v['recovery_id'] for k, v in runtime.items()}, 'isolated_processes': len(sessions),
            'replayed_samples': replayed, 'absent_samples_or_nonverified_decisions': absent, **FLAGS}
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
