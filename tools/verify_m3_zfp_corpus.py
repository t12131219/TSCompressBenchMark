#!/usr/bin/env python3
"""Verify a sealed ZFP preflight, its detached corpus samples and any isolated specialists."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_sprintz_query import _stage
from tsbench.application.m3_zfp import PROFILES, _reopen, array_evidence, array_windows
from tsbench.application.m3_zfp_specialized import audit_specialized
from tsbench.assets import canonical_bytes, content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.planner.m3_zfp import DRIVER, ROUTES
from tsbench.planner.zfp_execution import THREAD_ENV
from tsbench.recovery import DIRECTORY, plan_recovery, stage_recovery
from tsbench.supervisor.isolated_worker import invoke_isolated_tool, launcher_lock

TOOL = 'zfp-corpus-reopen'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 30}


def ref(data):
    return {'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def align(sample, name, expected, run):
    part = sample['parts'][name]
    data = verify_asset(run, part).read_bytes()
    require(part['bytes'] == len(data) and ref(data) == expected, 'ZFP retained part identity differs')
    return data


class IsolatedReplay:
    """Stage the sealed build's decoder once; each call exposes only one frame."""

    def __init__(self, root, plan, scratch):
        binding = plan['build']['zfp_corpus']
        self.launchers = launcher_lock()
        require(self.launchers == plan['specialized']['zfp']['launchers'], 'ZFP replay launchers differ from the frozen plan')
        for artifact in (binding['executable'], binding['dependency']):
            require(verify_asset(root, artifact).stat().st_size == artifact['bytes'], 'ZFP decoder extent differs')
        program = {k: binding['executable'][k] for k in ('path', 'sha256')}
        self.runtime = plan_recovery(root, {}, (), tools={TOOL: program}, libraries=[binding['dependency']])
        stage_recovery(root, scratch, self.runtime)
        self.bundle = scratch / DIRECTORY
        self.sessions = set()

    def reopen(self, work, part, operation, wire, rows):
        require(operation in ('array-reopen', 'field-restore'), 'ZFP replay permits only restore operations')
        with TemporaryDirectory(prefix='zfp-frame-only-', dir=work) as tmp:
            folder = Path(tmp)
            frame = folder / 'wire'
            frame.write_bytes(wire)
            out, process = invoke_isolated_tool(self.bundle, self.runtime, TOOL, LIMITS, folder, folder, operation,
                {'frame': frame}, [operation, str(rows), '/inputs/frame'], lambda: False,
                process_env=THREAD_ENV, bind_inputs=True)
            stdout, stderr = ((folder / f'{operation}.{ext}').read_bytes() for ext in ('stdout', 'stderr'))
            require(process['status'] == 'completed' and process['returncode'] == 0 and not stderr,
                    f'ZFP isolated {operation} failed: {stderr.decode(errors="replace").strip() or process["reason"]}')
            session = process['session_id']
            require(session and session not in self.sessions and process['input_mounts'] == {'frame': ref(wire)},
                    'ZFP reopen was not a fresh frame-only process')
            require({p.name for p in out.iterdir()} == {'values'}, 'ZFP isolated reopen output closure differs')
            values = local_file(out, 'values').read_bytes()
            require(len(values) == rows * 8, 'ZFP isolated restored extent differs')
            observed = parse_json(stdout, 'ZFP isolated corpus control')
            self.sessions.add(session)
            return values, observed, {'part': part, 'operation': operation, 'session_id': session,
                'input_mounts': process['input_mounts'], 'logs': {'stdout': ref(stdout), 'stderr': ref(stderr)},
                'observed': observed, 'restored': ref(values)}


def replay(control, run, work, record, sample, raw, array, *, isolated=None):
    n = len(raw) // 8
    processes = []

    def reopen(part, operation, wire):
        if isolated is None:
            return _reopen(control, work, operation, wire, n)
        values, observed, process = isolated.reopen(work, part, operation, wire, n)
        processes.append(process)
        return values, observed

    if array:
        require(sample['parts'].keys() == {'before', 'after', 'metadata.json'}, 'ZFP array retained parts differ')
        before = align(sample, 'before', record['before_frame'], run)
        after = align(sample, 'after', record['after_frame'], run)
        metadata = align(sample, 'metadata.json', record['metadata'], run)
        require(metadata == canonical_bytes({'format': 'zfp-array-rank1-v1', 'type': 'f64', 'shape': [n],
                                             'requested_rate': 18, 'effective_rate': 32}), 'ZFP array binding differs')
        left, left_doc = reopen('before', 'array-reopen', before)
        right, right_doc = reopen('after', 'array-reopen', after)
        check = array_evidence(raw, before, after, left, right)
        require(left_doc == right_doc == record['config'] and ref(right) == record['restored'] and
                check == {k: record[k] for k in check}, 'ZFP array reopen or quality result differs')
    else:
        fields = record['profiles']
        require(sample['parts'].keys() == {f'{mode}.{name}' for mode in fields for name in ('frame', 'metadata.json')},
                'ZFP field retained parts differ')
        for mode, field in fields.items():
            frame = align(sample, mode+'.frame', field['frame'], run)
            metadata = align(sample, mode+'.metadata.json', field['metadata'], run)
            require(metadata == canonical_bytes({'format': 'zfp-raw-reversible-v1', 'type': 'f64', 'shape': [n]}),
                    'ZFP field binding differs')
            restored, observed = reopen(mode+'.frame', 'field-restore', frame)
            require(restored == raw and observed == field['restore'], 'ZFP field sample did not independently restore')
    return processes


def replay_corpus(root, plan, run, datasets, *, isolated=None):
    """Audit complete ZFP input geometry and independently reopen retained payloads."""
    definition = load_json(verify_asset(root, plan['definition']['plan']))
    manifest = load_full_manifest(root, definition['bindings']['manifest'], parse=False)
    binding = plan['build']['zfp_corpus']
    control = verify_asset(root, binding['executable'])
    verify_asset(root, binding['dependency'])
    counts, replayed = Counter(), []
    for entry in manifest['datasets']:
        if not datasets[entry['id']]:
            continue
        with TemporaryDirectory(prefix='m3-zfp-audit-') as tmp:
            workdir = Path(tmp)
            columns = _stage(root, entry, workdir / 'columns')
            for work, result in datasets[entry['id']]:
                route = work['route']
                array = route == 'fixed-rate-array'
                info = result['evidence']
                rows, cols = entry['rows'], entry['value_count']
                shape = array_windows(work['input']['array_contract'], cols, rows) if array else ((i,0,rows) for i in range(cols))
                expected_extent = work['input']['size_estimate']
                sample = info['retained_sample']
                require(info['driver'] == DRIVER and not info['timing_admitted'] and info['columns'] == cols and
                        (len(info['units']),info['input_bytes_one_pass']) == (expected_extent['input_units'],
                         expected_extent['native_input_bytes_one_pass']), 'ZFP execution scope differs')
                bytes_by_profile, counts_rejected, sample_matches, input_bytes = Counter(), 0, 0, 0
                for (col,a,b), record in zip(shape, info['units'], strict=True):
                    n = b-a
                    with columns[col].open('rb') as stream:
                        stream.seek(a*8)
                        original = stream.read(8*n)
                    require((record['column'],record['row_range'],record['logical_input_bytes']) == (col,[a,b],len(original)) and
                            len(original) == 8*n, 'ZFP processed an unexpected piece of source')
                    input_bytes += len(original)
                    if array:
                        cfg = {'rows': n, 'frame_bytes': 16*((n+3)//4), 'requested_rate': 18, 'effective_rate': 32}
                        require(record['config'] == cfg and record['input'] == ref(original) and
                                record['before_frame']['bytes'] == record['after_frame']['bytes'] == cfg['frame_bytes'] and
                                record['artifact_bytes'] == cfg['frame_bytes'] + record['metadata']['bytes'] and
                                record['quality_passed'] == (record['before']['accepted'] and record['after']['accepted']),
                                'ZFP array source, configuration, billing or quality marker differs')
                        counts_rejected += not record['quality_passed']
                        bytes_by_profile['array'] += record['artifact_bytes']
                    else:
                        profiles = record['profiles']
                        require(profiles.keys() == (PROFILES.keys() if route=='openmp-encode' else {'serial'}) and
                                record['same_field'] == ref(original) and record['identical_payloads'] ==
                                (len({p['frame']['sha256'] for p in profiles.values()}) == 1), 'ZFP same-field report differs')
                        for mode, observation in profiles.items():
                            size = observation['frame']['bytes']
                            policy,threads,chunk = PROFILES[mode]
                            expected_cfg = dict(rows=n,frame_bytes=size,decode_execution=0)
                            require(size > 0 and size % 8 == 0 and observation['restored'] == record['same_field'] and
                                    observation['encode'] == dict(expected_cfg,execution=policy,configured_threads=threads,chunk_blocks=chunk) and
                                    observation['restore'] == dict(expected_cfg,execution=0,configured_threads=1,chunk_blocks=0) and
                                    observation['artifact_bytes'] == size + observation['metadata']['bytes'],
                                    'ZFP field policy, restoration or billing differs')
                            bytes_by_profile[mode] += observation['artifact_bytes']
                    if (sample['column'],sample['row_range']) == (col,[a,b]):
                        require(sample['quality_passed'] == record.get('quality_passed', True), 'ZFP sample quality marker differs')
                        processes = replay(control, run, workdir, record, sample, original, array, isolated=isolated)
                        sample_matches += 1
                require(sample_matches == 1 and input_bytes == info['input_bytes_one_pass'] and
                        info['artifact_bytes'] == (bytes_by_profile['array'] if array else dict(bytes_by_profile)) and
                        counts_rejected == info['quality_rejected_units'] and sample['quality_passed'] == (counts_rejected == 0) and
                        result['status'] == ('quality_rejected' if counts_rejected else 'verified'), 'ZFP file result accounting differs')
                replayed.append({'dataset_id': entry['id'], 'route': route, 'sample': sample,
                                 **({'processes': processes} if isolated is not None else {})})
                counts[route] += len(info['units'])
                counts['array_quality_rejected_units'] += counts_rejected
    return counts, replayed


def verify(root, plan_path, run, *, replay_specialized=False):
    plan = load_json(plan_path)
    check_m3_real_corpus_plan(root, plan)
    paths = {p: local_file(run, p) for p in ('report.json', 'ledger.jsonl', 'completion.json')}
    report, seal = (load_json(paths[p]) for p in ('report.json', 'completion.json'))
    load_contract(root, 'm3-real-corpus-plan').validate(plan, 'ZFP plan')
    load_contract(root, 'm3-real-corpus-run').validate(report, 'ZFP report')
    require(seal['run_id'] == report['run_id'] == run.name and report['plan_content_id'] == plan['plan_content_id'] == seal['plan_content_id']
            and seal['ledger_sha256'] == digest(paths['ledger.jsonl']) and seal['report_sha256'] == digest(paths['report.json']) and
            seal['seal_id'] == content_id({k: v for k,v in seal.items() if k != 'seal_id'}), 'ZFP run seal differs')
    require(report['partial_preflight'] and report['route_filter'] == sorted(r for _, r in ROUTES),
            'expected a ZFP route-filtered preflight')
    binding = plan.get('specialized', {}).get('zfp')
    specialized = report['specialized'].get('zfp')
    require(set(report['specialized']) <= {'zfp'} and (binding is None) == (specialized is None) and
            (not replay_specialized or specialized is not None), 'ZFP specialist closure differs from plan')
    products = ([] if specialized is None else
                [{'entry_kind': 'specialized_product', 'selection': 31, **item} for item in specialized['fixtures'].values()])
    expected = [r for r in plan['work_items'] if (r['selection'], r['route']) in ROUTES]
    require(report['selected_work_items'] == report['selected_corpus_decisions'] == len(expected) == 92 and
            len(report['obligations']) == 20 and report['obligation_statuses'] == ({'not_run': 20} if binding is None else {'verified': 20}), 'ZFP preflight denominator differs')
    with paths['ledger.jsonl'].open(encoding='utf-8') as ledger:
        for line, row in zip(ledger, [*report['rows'], *products, *report['obligations']], strict=True):
            require(json.loads(line) == row, 'ZFP report differs from its single main ledger')
    wanted = [r for r in plan['obligations'] if (r['selection'], r['route']) in ROUTES]
    for ob, row in zip(wanted, report['obligations'], strict=True):
        require(all(ob[k] == row[k] for k in ('obligation_id', 'selection', 'route', 'kind', 'check')) and
                (binding is not None or row['status'] == 'not_run' and row['evidence'] is None), 'ZFP obligation identity differs')
    require(dict(Counter(r['status'] for r in report['rows'])) == report['statuses'], 'ZFP status accounting differs')
    routes = defaultdict(Counter)
    datasets = defaultdict(list)
    failures = []
    for work, row in zip(expected, report['rows'], strict=True):
        require(all(work[k] == row[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route', 'operation', 'applicability')) and
                row['applicability'] == 'input_domain_matches', 'ZFP work item differs from the frozen decision')
        routes[row['route']][row['status']] += 1
        if row['status'] not in {'verified', 'quality_rejected'}:
            require(row['evidence'] is None and row['reason'], 'unexplained ZFP nonpass')
            failures.append({k: row[k] for k in ('route', 'dataset_id', 'status', 'reason')})
            continue
        datasets[row['dataset_id']].append((work, row))
    counts, replayed = replay_corpus(root, plan, run, datasets)
    specialists = (audit_specialized(root, run, binding, report['obligations'], specialized, replay=replay_specialized)
                   if binding is not None else None)
    return {'schema': 'bmk.m3-zfp-corpus-audit/1', 'run_id': report['run_id'], 'run_seal_id': seal['seal_id'],
            'plan_content_id': report['plan_content_id'], 'route_statuses': routes, 'units': counts, 'failure_details': failures,
            'replayed_samples': replayed, 'specialized_executed': specialists is not None, 'specialized': specialists, 'stage_accepted': False,
            'qualification_granted': False, 'timing_admitted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--replay-specialized', action='store_true', help='replay the isolated specialist products as well')
    args = parser.parse_args()
    print(json.dumps(verify(ROOT, args.plan, args.run.resolve(strict=True), replay_specialized=args.replay_specialized), indent=2))
