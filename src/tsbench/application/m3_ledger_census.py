"""Recompute the M3 corpus/obligation census from a sealed main ledger.

This is not an artifact replay, a measurement admission, or a stage receipt.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import re

from ..assets import canonical_bytes, local_file, parse_json, require
from ..contracts import load_contract
from ..planner.m3_binding_coverage import binding_coverage
from ..planner.m3_fixed_batch import DRIVER as BATCH_DRIVER, RETENTION, ROUTES as BATCH_ROUTES, sample_indices, units as batch_units
from ..planner.m3_real_corpus import check_m3_real_corpus_plan
from .m3_fixed_batch import _verify_execution_info
from .m3_report_stream import stream_report
from .m3_sealed_ledger import full_run_source

CORPUS_STATES = {'verified', 'quality_rejected', 'failed', 'hardware_pending', 'dependency_failed', 'pending_driver', 'not_run'}
OBLIGATION_STATES = {'verified', 'quality_rejected', 'failed', 'hardware_pending', 'pending_supported_runtime',
                     'pending_supported_build', 'dependency_failed', 'not_run'}
FIXED_UNIT_ROUTES = {'auto-batch', 'decode-backends', 'source-auto', 'c-native-auto', 'source-pages', 'native-pages',
                     'zstd-baseline', 'xz-baseline'}


def _detached_groups(planned, evidence, binding):
    require(binding and evidence['recovery_id'] == binding['decoder']['recovery_id'] and
            evidence['process_timing_scope'] == 'isolated_process_diagnostic_not_m2_measurement' and
            evidence['timing_admitted'] is False, 'M3 batch evidence differs from frozen runtime')
    plugin, _, backends = BATCH_ROUTES[planned['selection'], planned['route']]
    dtype, width = (2, 1) if planned['view'] == 'v_bytes_interleaved' else (10, 8)
    groups = {tag: [] for tag in backends}
    sessions = set()

    def identity(ref):
        return (set(ref) == {'bytes', 'sha256'} and type(ref['bytes']) is int and ref['bytes'] > 0 and
                re.fullmatch(r'[a-f0-9]{64}', ref['sha256']))

    def operation(record, label, backend, mounts):
        op = record['process']
        require(op['operation'] == label and op['status'] == 'completed' and op['returncode'] == 0 and
                type(op['pid']) is int and op['pid'] > 0 and re.fullmatch(r'[a-f0-9]{32}', op['session_id'] or '') and
                not op['reason'] and op['session_id'] not in sessions and op['input_mounts'] == mounts and
                op['options'] == ({'decode_backend': backend} if plugin == 'alp-auto' else {}),
                'M3 detached operation did not prove a fresh session with the declared mounts and options')
        _verify_execution_info(planned, 'encode' if label == 'encode' else backend, record['native'])
        sessions.add(op['session_id'])

    geometry = list(batch_units(planned))
    require(len(geometry) == len(evidence['units']), 'M3 detached batch unit count differs from frozen scope')
    for expected, unit in zip(geometry, evidence['units'], strict=True):
        source, frame = unit['original'], unit['artifact']
        count = expected['input_bytes'] // width
        schema = canonical_bytes({'role': 'bytes', 'dtype': 'u8', 'bytes': count} if dtype == 2 else
                                 {'role': 'value', 'dtype': 'f64', 'rows': count})
        require(all(unit.get(k) == v for k, v in expected.items()) and identity(source['raw']) and
                source['schema'] == {'bytes': len(schema), 'sha256': sha256(schema).hexdigest()} and
                identity(frame) and frame['bytes'] <= binding['limits']['file_bytes'] and
                source['raw']['bytes'] == unit['input_bytes'] and source['dtype'] == dtype and
                source['count'] == count and set(unit['decodes']) == set(backends),
                'M3 detached unit coordinates, source identity, artifact size or decoder scope differs')
        operation(unit['encode'], 'encode', backends[0], {k: source[k] for k in ('raw', 'schema')})
        for tag in backends:
            decoded = unit['decodes'][tag]
            operation(decoded, f'decode-{tag}', tag, {'frame': frame})
            require(decoded['restored'] == source, 'M3 detached decode does not bind the original schema and bits')
            groups[tag].append(unit['input_bytes'])
    return groups


def _unit_census(planned, row, batch_binding=None):
    if row['status'] != 'verified' or row['route'] not in FIXED_UNIT_ROUTES:
        return None
    estimate, evidence = planned['input']['size_estimate'], row['evidence']
    detached = evidence.get('driver') == BATCH_DRIVER
    if batch_binding and (row['selection'], row['route']) in BATCH_ROUTES:
        require(detached, 'M3 fixed batch route cannot use historical same-process evidence')
    if detached:
        groups = _detached_groups(planned, evidence, batch_binding)
        if 'retention' in batch_binding:
            check_retention(planned, evidence)
        decode_scope = 'isolated_process_frame_only'
    elif 'units' in evidence:
        groups = {'primary': [u['input_bytes'] for u in evidence['units']]}
        decode_scope = 'corpus_page_driver_separate_process'
    elif planned['view'] == 'v_bytes_interleaved':
        groups = {'primary': [o['observed']['input_bytes'] for o in evidence['observed']]}
        decode_scope = 'same_process_roundtrip'
    else:
        groups = {obs['backend']: [c['input_bytes'] for c in obs['observed']['columns']] for obs in evidence['observed']}
        decode_scope = 'same_process_roundtrip'
    want = {'units': estimate['input_units'], 'input_bytes': estimate['native_input_bytes_one_pass'],
            'largest_unit_bytes_limit': estimate['largest_input_unit_bytes']}
    observed = {b: {'units': len(sizes), 'input_bytes': sum(sizes), 'largest_unit_bytes': max(sizes, default=0)}
                for b, sizes in groups.items()}
    matches = bool(observed) and all(a['units'] == want['units'] and a['input_bytes'] == want['input_bytes'] and
                                    a['largest_unit_bytes'] <= want['largest_unit_bytes_limit'] for a in observed.values())
    return {'expected': want, 'observed': observed, 'matches_frozen_units': matches, 'decode_scope': decode_scope,
            'shared_artifact_reuse_proved': detached if planned['operation'] == 'decode_common_frame' else None}


def check_retention(planned, evidence):
    chosen = set(sample_indices(planned))
    refs = []
    released = {'count': 0, 'bytes': 0}
    for i, unit in enumerate(evidence['units']):
        artifact = unit['artifact']
        if i in chosen:
            refs.append({'unit_index': i, 'path': f"{RETENTION['directory']}/{artifact['sha256']}.bmk", **artifact})
        else:
            released['count'] += 1
            released['bytes'] += artifact['bytes']
    require(evidence.get('retained_samples') == refs and evidence.get('released_frames') == released,
            'M3 batch retention or released byte accounting differs from frozen policy')
    return refs


def _specialists(report):
    products, regressions = {}, []
    for driver, group in report['specialized'].items():
        if driver == 'gorilla':
            lanes = group['lanes'].values()
            if 'regression' in group:
                regressions.append(group['regression'])
        else:
            lanes = [group]
        for lane in lanes:
            require(lane['statuses'] == dict(Counter(r['status'] for r in lane['fixtures'].values())),
                    f'M3 {driver} reported product census differs')
            for sid, row in lane['fixtures'].items():
                require(sid == row['product_slot'] and sid not in products, 'M3 specialist product slot reused')
                products[sid] = row
    return products, regressions


def _match_products(entries, report):
    products, regressions = _specialists(report)
    seen, actual_regressions = set(), []
    scope = defaultdict(set)
    for row in report['obligations']:
        ev = row['evidence'] or {}
        ids = ev.get('fixture_slots', ())
        if 'fixture_slot' in ev:
            ids = [*ids, ev['fixture_slot']]
        for sid in ids:
            scope[sid].add(row['selection'])
    for row in entries:
        if row.get('entry_kind') == 'implementation_regression':
            actual_regressions.append(row)
            continue
        sid = row.get('product_slot')
        require(row.get('entry_kind') == 'specialized_product' and sid in products and sid not in seen and
                scope[sid] == {row.get('selection')} and
                {k: v for k, v in row.items() if k not in ('entry_kind', 'selection', 'route', 'lane')} == products[sid],
                'M3 unexpected, duplicated or mismatched specialist product ledger row')
        seen.add(sid)
    require(seen == products.keys() and actual_regressions == regressions, 'M3 main ledger omits specialist or regression evidence')
    return Counter(products[p]['status'] for p in seen), len(regressions)


def _scope(plan, report, nc):
    route_filter = report['route_filter']
    dataset_filter, limit = report.get('dataset_filter'), report.get('max_work_items')
    require(report['partial_preflight'] or (route_filter is None and 'dataset_filter' not in report and
            'max_work_items' not in report), 'M3 full census contains a preflight filter')
    if route_filter is not None:
        require(report['partial_preflight'] and route_filter == sorted(set(route_filter)) and
                set(route_filter) <= {r['route'] for r in plan['routes']}, 'M3 run route filter differs')
    if dataset_filter is not None:
        require(report['partial_preflight'] and dataset_filter == sorted(set(dataset_filter)) and dataset_filter and
                set(dataset_filter) <= {r['dataset_id'] for r in plan['work_items']}, 'M3 run dataset filter differs')
    expected = [r for r in plan['work_items'] if (route_filter is None or r['route'] in route_filter) and
                (dataset_filter is None or r['dataset_id'] in dataset_filter)]
    required = [o for o in plan['obligations'] if route_filter is None or o['route'] in route_filter]
    no = len(report['obligations'])
    if limit is not None:
        require(report['partial_preflight'] and type(limit) is int and limit > 0, 'M3 run preflight limit differs')
        expected = [r for r in expected if r['applicability'] == 'input_domain_matches'][:limit]
        required = []
    elif dataset_filter is not None:
        required = []
    elif report['partial_preflight'] and not no:
        expected = [r for r in expected if r['applicability'] == 'input_domain_matches'][:nc]
        required = []
    require(nc == len(expected) == report['selected_corpus_decisions'] and no == len(required) and
            report['selected_work_items'] == sum(r['applicability'] == 'input_domain_matches' for r in expected) and
            report['planned_work_items'] == len(plan['work_items']),
            'M3 run denominator or policy differs from the plan')
    return expected,required


def _project(plan, report, entries):
    nc, no = len(report['rows']), len(report['obligations'])
    expected, required = _scope(plan,report,nc)
    require(len(entries) >= nc + no and entries[:nc] == report['rows'] and
            (not no or entries[-no:] == report['obligations']), 'M3 ledger corpus or obligation rows differ from report')
    return _project_rows(plan,report,entries[:nc],expected,entries[nc:len(entries)-no],required)


def _project_rows(plan,report,corpus_rows,expected,tail_products,required):
    corpus, obligations, routes, by_kind = Counter(), Counter(), defaultdict(Counter), defaultdict(Counter)
    details = []
    for row, planned in zip(corpus_rows, expected, strict=True):
        require(all(row[k] == planned[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route', 'operation', 'applicability')),
                'M3 corpus ledger identity differs from the plan')
        state = row['status']
        if planned['applicability'] == 'input_domain_matches':
            require(state in CORPUS_STATES and (bool(row['reason']) if state != 'verified' else row['evidence'] is not None),
                    'M3 corpus ledger terminal differs from applicability')
        else:
            require(state == planned['applicability'] and row['evidence'] is None and row['reason'] == '; '.join(planned['reasons']),
                    'M3 non-applicable decision was not preserved')
        corpus[state] += 1
        routes[planned['selection'], planned['route']][state] += 1
        unit_census = _unit_census(planned, row, plan['build'].get('fixed_batch'))
        details.append({**{k: row[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route', 'operation', 'applicability', 'status', 'reason')},
                        'operation_config_id': planned['operation_config_id'], 'view': planned['view'],
                        **({'batch_unit_observation': unit_census} if unit_census else {})})
    products, n_regressions = _match_products(tail_products, report)
    require(report['execution_policy'] == plan['execution_policy'],'M3 run execution policy differs from the plan')
    binding = binding_coverage(plan)
    for row, planned in zip(report['obligations'], required, strict=True):
        key = planned['obligation_id']
        state = row['status']
        require(row['entry_kind'] == 'specialized_obligation' and
                all(row[k] == planned[k] for k in ('obligation_id', 'selection', 'route', 'kind', 'check')) and state in OBLIGATION_STATES and
                (row['evidence'] is not None and key in binding['obligation_drivers'] and not row['reason']
                 if state == 'verified' else bool(row['reason'])), 'M3 obligation ledger differs from frozen scope or terminal')
        obligations[state] += 1
        by_kind[planned['kind']][state] += 1
    require(dict(corpus) == report['statuses'] and dict(obligations) == report['obligation_statuses'], 'M3 reported census differs from ledger')
    unit_mismatches = [d['work_item_id'] for d in details if 'batch_unit_observation' in d and
                       not d['batch_unit_observation']['matches_frozen_units']]
    return {'corpus_statuses': dict(corpus), 'obligation_statuses': {k: dict(v) for k, v in by_kind.items()},
            'specialist_product_statuses': dict(products), 'implementation_regressions': n_regressions,
            'routes': [{'selection': n, 'route': r, 'statuses': dict(stats)} for (n, r), stats in sorted(routes.items())],
            'decisions': details, 'batch_unit_mismatches': unit_mismatches,
            'all_frozen_decisions_and_obligations_accounted': not report['partial_preflight'],
            'no_unbound_obligations': not any(binding['unbound'].values())}


def _stream_projection(root,plan,run,ledger_path):
    with stream_report(local_file(run,'report.json')) as (report, rows), ledger_path.open('rb') as stream:
        require(report['run_id']==run.name and report['plan_content_id']==plan['plan_content_id'],
                'M3 main report identity differs')
        expected, required = _scope(plan,report,report['selected_corpus_decisions'])
        def matched_corpus():
            for prior in rows:
                line = stream.readline()
                require(bool(line),'M3 ledger omits a report decision')
                row = parse_json(line,'M3 primary corpus row')
                require(row==prior,'M3 ledger corpus or obligation rows differ from report')
                yield row
        def tail():
            for line in stream:
                row = parse_json(line,'M3 typed ledger row')
                if row.get('entry_kind')=='specialized_obligation':
                    break
                yield row
            else:
                require(not required,'M3 ledger omits all obligation rows')
                return
            for prior in report['obligations']:
                require(row==prior,'M3 ledger corpus or obligation rows differ from report')
                line = stream.readline()
                row = parse_json(line,'M3 obligation row') if line else None
            require(row is None,'M3 ledger has extra rows after obligations')
        result = _project_rows(plan,report,matched_corpus(),expected,tail(),required)
        # The current schema constrains this field only to a nonempty array.
        # Every actual row was parsed and checked against the ledger and plan.
        load_contract(root,'m3-real-corpus-run').validate({**report,'rows':[{}]},'M3 ledger census')
    return result


def census(root, plan, run):
    check_m3_real_corpus_plan(root, plan)
    ledger_path,seal_id = full_run_source(plan,run)
    result = _stream_projection(root,plan,run,ledger_path)
    return {'schema': 'bmk.m3-ledger-census/1', 'scope': 'sealed_plan_and_ledger_not_artifact_replay_or_admission',
            'run_id': run.name, 'seal_id': seal_id, 'plan_content_id': plan['plan_content_id'], **result,
            'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}
