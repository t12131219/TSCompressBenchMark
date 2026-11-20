"""Index independently recomputed M3 diagnostics against the one functional denominator.

Completeness of a frozen diagnostic extent is not timing admission or stage passage.
No link means not inventoried (not that no other evidence exists).
"""
from collections import Counter, defaultdict

from ..assets import content_id, load_json, local_file, parse_json, require
from ..planner.m3_fixed_batch import ROUTES as BATCH_ROUTES, units as fixed_geometry
from ..planner.m3_pbepla import PROGRESSIVE, REPLAY, ROUTES as PBEPLA_ROUTES, windows as pbepla_windows
from ..recovery import plan_recovery
from . import (m3_abi_corpus_timing as abi, m3_batch_timing as batch, m3_column_batch_timing as columns,
               m3_etb1_pipeline_timing as etb, m3_fixed_batch_corpus as fixed,
               m3_gorilla_corpus_clock as gorilla, m3_lzbench_corpus_clock as lz, m3_lzbench_durable as durable,
               m3_pbepla_grouped_timing as pbep, m3_pcodec_grouped_timing as pgroup, m3_pcodec_page_timing as pages,
               m3_selfstar_timing as selfstar, m3_sprintz_durable as sprintz,
               m3_titchy_grouped_timing as tgroup, m3_titchy_stream_timing as titchy, m3_zfp_array_timing as array, m3_zfp_field_timing as zfp,
               m3_whole_durable as whole, m3_zstd_dictionary_timing as dictionary)
from .m3_lzbench_timing import _file, _folder, _ref
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source

MODES = {
    'abi': (abi.verify, ('fire-batch', 'huff0-reference'), ('native_repeat',)),
    'column-batch': (columns.verify, tuple(r for _, r in columns.batch.ROUTES), ('native_repeat', 'verified_durable_repeat')),
    'fixed-batch-corpus': (fixed.verify, tuple(r for _, r in fixed.ROUTES), ('native_repeat', 'verified_durable_repeat')),
    'etb1': (etb.verify, ('huff0-shared-table',), ('native_repeat', 'verified_durable_repeat')),
    'gorilla': (gorilla.verify, gorilla.ROUTES, ('native_repeat', 'verified_durable_repeat')),
    'lzbench-native': (lz.verify, lz.ROUTES, ('native_repeat',)),
    'lzbench-durable': (durable.verify, lz.ROUTES, ('native_repeat', 'verified_durable_repeat')),
    'pbepla-grouped': (pbep.verify, (PROGRESSIVE, REPLAY), ('native_repeat', 'verified_durable_repeat')),
    'pcodec-grouped': (pgroup.verify, tuple(pgroup.LANES.values()), ('native_repeat', 'verified_durable_repeat')),
    'pcodec-pages': (pages.verify_report, ('native-pages', 'source-pages'), ('native_repeat',)),
    'retained-batch': (batch.report_timing, tuple(sorted({r for _, r in BATCH_ROUTES})), ('native_repeat',)),
    'selfstar': (selfstar.verify, ('selfstar-batch', 'selfstar-incremental'), ('native_repeat',)),
    'sprintz-sfb1': (sprintz.verify, ('query',), ('native_repeat', 'verified_durable_repeat')),
    'titchy-stream': (titchy.verify, ('packet-stream',), ('native_repeat',)),
    'titchy-grouped': (tgroup.verify, tgroup.titchy.ROUTES, ('native_repeat', 'verified_durable_repeat')),
    'whole-durable': (whole.verify, whole.ROUTES, ('native_repeat', 'verified_durable_repeat')),
    'zfp-array': (array.verify, (array.ROUTE,), ('native_repeat', 'verified_durable_repeat')),
    'zfp-field': (zfp.verify, zfp.ROUTES, ('native_repeat', 'verified_durable_repeat')),
    'zstd-dictionary': (dictionary.verify, ('zstd-dictionary',), ('native_repeat', 'verified_durable_repeat')),
}


def _basis(p, mode, root):
    if mode == 'retained-batch':
        return p['functional']['plan'], p['functional']['seal_id']
    if mode == 'pcodec-pages':
        return p['functional']['source_plan'], p['functional']['source_seal']
    if mode == 'lzbench-durable':
        native = load_json(local_file(_folder(root, p['native_run']), 'plan.json'))
        return native['source_plan'], native['source_seal']
    return p.get('source_plan', p.get('source')), p['source_seal']


def _case_parts(mode, case):
    """Work/route identity and exact measured slice (if narrower than the frozen input)."""
    if mode == 'pcodec-pages':
        for variant in case['variants'].values():
            yield variant, {'column': case['column'], 'rows': case['rows']}
    elif mode == 'pcodec-grouped':
        for variant in case['variants'].values():
            yield {**variant, **{k: case[k] for k in ('columns', 'rows', 'group_count', 'logical_bytes')}}, None
    elif mode == 'zfp-field':
        for variant in case['variants'].values():
            yield {**variant, 'columns': case['columns'], 'rows': case['rows']}, None
    elif mode == 'titchy-stream':
        yield case, {'column': case['value_column'], 'rows': case['range']}
    elif mode == 'retained-batch':
        yield case, {'geometry': case['geometry'], 'decode_backend': case['decode_backend']}
    else:
        yield case, None


def _exact_extent(mode, c, item):
    extent = item['input']
    if mode in ('abi', 'etb1', 'selfstar', 'sprintz-sfb1', 'whole-durable'):
        return c['configuration'] == extent
    if mode == 'fixed-batch-corpus':
        return (c['configuration'] == extent and c['view'] == item['view'] and
                len(c['units']) == extent['size_estimate']['input_units'] and
                len(c['units']) == len(expected := list(fixed_geometry(item))) and
                all(all(u[k] == v for k, v in pos.items()) and u['original']['bytes'] == pos['input_bytes']
                    for u, pos in zip(c['units'], expected, strict=True)) and
                sum(u['original']['bytes'] for u in c['units']) == extent['size_estimate']['native_input_bytes_one_pass'])
    if mode in ('column-batch', 'titchy-grouped'):
        if c['configuration'] != extent or len(extent['row_ranges']) != 1:
            return False
        lo, hi = extent['value_column_range']
        a, b = (extent['row_ranges'][0][k] for k in ('start', 'end'))
        cap = extent['slice_extent']['max_per_unit']
        if mode == 'titchy-grouped' and c['route'] == 'packet-stream':
            if cap is not None:
                return False
            cap = b - a
        if type(cap) is not int or cap <= 0:
            return False
        expect = [(col, [start, min(start+cap, b)]) for col in range(lo, hi) for start in range(a,b,cap)]
        return ([(u['column'], u['row_range']) for u in c['units']] == expect and
                len(expect) == extent['size_estimate']['input_units'] and
                all(u['original']['bytes'] == (end-start)*8 for u, (_, (start,end)) in zip(c['units'], expect, strict=True)) and
                sum(u['original']['bytes'] for u in c['units']) == extent['size_estimate']['native_input_bytes_one_pass'])
    if mode in ('lzbench-native', 'lzbench-durable'):
        return c['scope'] == extent['row_ranges'] and c['source']['bytes'] == extent['size_estimate']['native_input_bytes_one_pass']
    if mode == 'pcodec-grouped':
        return (extent['value_column_range'] == [0, c['columns']] and len(extent['row_ranges']) == 1 and
                [extent['row_ranges'][0][k] for k in ('start', 'end')] == [0, c['rows']] and
                c['group_count'] == extent['size_estimate']['input_units'] and
                c['logical_bytes'] == extent['size_estimate']['native_input_bytes_one_pass'])
    if mode == 'zfp-array':
        return (c['configuration'] == extent and len(c['units']) == extent['size_estimate']['input_units'] and
                c['logical_bytes'] == extent['size_estimate']['native_input_bytes_one_pass'])
    if mode == 'zfp-field':
        return (c['configuration'] == extent and extent['value_column_range'] == [0, c['columns']] and
                len(extent['row_ranges']) == 1 and [extent['row_ranges'][0][k] for k in ('start', 'end')] == [0, c['rows']] and
                extent['size_estimate']['input_units'] == c['columns'] and
                extent['size_estimate']['native_input_bytes_one_pass'] == c['columns'] * c['rows'] * 8)
    if mode == 'zstd-dictionary':
        return (c['item'] == item and c['training'] == [extent['training']['dictionary_capacity_bytes'],
                extent['training']['sample_geometry']['bytes_each'], extent['training']['sample_geometry']['count']] and
                c['training'][1] * c['training'][2] == extent['training']['consumed_byte_range'][1] and
                len(c['anchor']['frames']) + 1 == extent['size_estimate']['input_units'] and
                c['anchor']['holdout']['bytes'] + extent['training']['consumed_byte_range'][1] ==
                extent['size_estimate']['native_input_bytes_one_pass'])
    if mode == 'gorilla':
        return (extent['value_column_range'] == [0, c['columns']] and len(extent['row_ranges']) == 1 and
                [extent['row_ranges'][0][k] for k in ('start', 'end')] == [0, c['rows']] and
                c['units'] == extent['size_estimate']['input_units'] and
                c['input_bytes'] == extent['size_estimate']['native_input_bytes_one_pass'])
    return False


def _merge(spans):
    out = []
    for lo, hi in sorted(spans):
        require(type(lo) is int and type(hi) is int and 0 <= lo < hi, 'invalid measurement coverage interval')
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def _slice_scope(parts, extent):
    axis_ranges = _merge((r['start'], r['end']) for r in extent['row_ranges'])
    lo, hi = extent['value_column_range']
    actual = defaultdict(list)
    for part in parts:
        col, (a, b) = part['column'], part['rows']
        require(type(col) is int and lo <= col < hi and any(s <= a < b <= e for s, e in axis_ranges),
                'measured slice lies outside the frozen M3 extent')
        actual[col].append((a, b))
    return ('frozen_extent' if len(actual) == hi - lo and all(_merge(spans) == axis_ranges for spans in actual.values())
            else 'projected_extent')


def _titchy_column(row):
    """Normalize the exact measured V column, excluding only prior timing and file paths."""
    require(row['route'] == 'packet-stream' and row['status'] == 'verified', 'Titchy bridge requires verified packet stream')
    proof = row['evidence']
    require(proof['driver'] == 'titchy-stream-control/1', 'Titchy bridge uses a different stream driver')
    sample, unit = proof['retained_sample'], proof['units'][0]
    parts = sample['parts']
    require(sample['column'] == unit['column'] == 0 and sample['row_range'] == unit['row_range'] and
            sample['restored_sha256'] == unit['restored_sha256'] and set(parts) == set(titchy.PARTS) and
            parts['tstr']['sha256'] == unit['archive_sha256'] and parts['tsc1']['sha256'] == unit['config_sha256'],
            'Titchy bridge column or retained sample differs')
    return {'range': unit['row_range'], 'value_column': 0,
            'original': {'bytes': unit['logical_input_bytes'], 'sha256': unit['restored_sha256']},
            'parts': parts, 'expected_native': {op: titchy._facts(unit[op]) for op in titchy.DIRECTIONS},
            'billing': {k: unit[k] for k in titchy.COST}}


def _titchy_facts(data):
    return {**data, 'parts': {k: {n: v[n] for n in ('bytes', 'sha256')} for k, v in data['parts'].items()}}


def _titchy_bridge(root, plan, expected, source_context, by_id):
    """Prove that the old elapsed samples used the same first column and bitstream."""
    main, target_run, columns = source_context
    require(plan['main_plan'] == expected[0] and plan['definition'] == main['definition']['plan'],
            'Titchy measurements target a different M3 plan or definition')
    old_ref = plan['source_plan']
    old, old_run = load_json(_file(root, old_ref)), _folder(root, plan['source_run'])
    old_ledger, old_seal = full_run_source(old, old_run)
    require(old_seal == plan['source_seal'] and main['definition'] == old['definition'] and
            main['build']['titchy_stream'] == old['build']['titchy_stream'], 'Titchy historical source seal, definition or build differs')
    binding = main['build']['titchy_stream']
    for ref in binding.values():
        _file(root, ref)
    wanted_runtime = plan_recovery(root, {}, (), tools={titchy.TOOL: {k: binding['executable'][k] for k in ('path', 'sha256')}},
                                   libraries=[binding['dependency']])
    require(plan['runtime'] == wanted_runtime, 'Titchy bridge runtime closure differs')
    wanted_ids = {c['work_item_id'] for c in plan['cases']}
    require(len(wanted_ids) == len(plan['cases']) and wanted_ids <= columns.keys(), 'Titchy measured work identity absent from r40')
    old_items = {w['work_item_id']: w for w in old['work_items'] if w['work_item_id'] in wanted_ids}
    matches = {}
    with old_ledger.open(encoding='utf-8') as f:
        for line in f:
            row = parse_json(line, 'Titchy historical trial anchor')
            wid = row.get('work_item_id')
            if wid in wanted_ids:
                require(wid not in matches and row['dataset_id'] == old_items[wid]['dataset_id'], 'Titchy duplicate or foreign historical anchor')
                matches[wid] = _titchy_column(row)
    require(matches.keys() == wanted_ids, 'Titchy historical anchor population is incomplete')
    proofs = []
    for case in plan['cases']:
        wid = case['work_item_id']
        previous, current = matches[wid], columns[wid]
        measured = {k: case[k] for k in current}
        require(old_items[wid] == by_id[wid][1] and previous == measured and _titchy_facts(current) == _titchy_facts(measured),
                'Titchy historical and r40 measured slice, native work or output differ')
        for key in titchy.PARTS:
            _file(old_run, previous['parts'][key])
            _file(target_run, current['parts'][key])
        proofs.append({'case_id': case['case_id'], 'work_item_id': wid, 'slice_facts_id': content_id(_titchy_facts(current))})
    return {'scope': 'projection_equivalence_not_same_functional_run', 'source_plan': old_ref, 'source_seal_id': old_seal,
            'source_completion': _ref(root, local_file(old_run, 'completion.json')), 'target_seal_id': expected[1], 'cases': proofs}


def _linked(root, run, mode, expected, by_id, source_context):
    check, routes, clocks = MODES[mode]
    plan = load_json(local_file(run, 'plan.json'))
    bridge = None
    if _basis(plan, mode, root) != expected:
        require(mode == 'titchy-stream', f'{mode} diagnostic does not derive from the same M3 seal and input plan')
        bridge = _titchy_bridge(root, plan, expected, source_context, by_id)
    report = check(root, run) if mode in ('lzbench-durable', 'fixed-batch-corpus', 'whole-durable') else check(run)
    require(report == load_json(local_file(run, 'report.json')) and report['run_id'] == run.name and
            not any(report.get(k) for k in ('stage_accepted', 'qualification_granted', 'timing_admitted', 'performance_admitted')),
            'diagnostic report failed independent recomputation or scope check')
    links, rejected, failures = defaultdict(list), [], []
    pbepla_units = {}
    if mode in ('column-batch', 'titchy-grouped', 'pbepla-grouped'):
        require(plan['dataset_projection'] is None, f'{mode} preflight is not an admissible whole-corpus link')
        cases = load_json(local_file(run, 'population.json'))['cases']
        identities = {'column-batch': set(columns.batch.ROUTES), 'titchy-grouped': {(85, r) for r in tgroup.titchy.ROUTES},
                      'pbepla-grouped': PBEPLA_ROUTES}[mode]
        statuses = {'verified', 'failed', 'quality_rejected'} if mode == 'pbepla-grouped' else {'verified'}
        required = {key for key, (decision, item) in by_id.items()
                    if decision['status'] in statuses and (item['selection'], item['route']) in identities}
        require(len(cases) == len(required) and {c['work_item_id'] for c in cases} == required,
                f'{mode} measurement population omits or repeats frozen work')
        if mode == 'pbepla-grouped':
            source = source_context[0]
            entries = _entry_map(root, load_json(_file(root, source['definition']['plan'])))
            pairs = defaultdict(dict)
            for key in required:
                item = by_id[key][1]
                pairs[item['dataset_id']][item['route']] = item
            pbepla_units = {ds: [(w.column, w.ordinal, [w.start, w.end], w.rows*8)
                                 for w in pbepla_windows(entries[ds], pair[PROGRESSIVE], pair[REPLAY])]
                            for ds, pair in pairs.items()}
    else:
        cases = plan['cases']
        if mode in ('fixed-batch-corpus', 'whole-durable'):
            require(plan['dataset_projection'] is None, f'{mode} preflight cannot link as full corpus')
            required = {key for key, (decision, item) in by_id.items()
                        if decision['status'] == 'verified' and item['route'] in routes}
            require(len(cases) == len(required) and {c['work_item_id'] for c in cases} == required,
                    f'{mode} diagnostic omits or repeats verified corpus work')
    for c in cases:
        for case, part in _case_parts(mode, c):
            key = case['work_item_id']
            require(key in by_id, 'timing case outside the frozen M3 denominator')
            decision, item = by_id[key]
            require(item['route'] in routes and c['dataset_id'] == item['dataset_id'] and
                    all(case.get(k, item[k]) == item[k] for k in ('operation_config_id', 'route', 'canonical_object_id')),
                    'timing case with foreign source or configuration')
            if mode == 'pbepla-grouped':
                require(part is None and case['configuration'] == item['input'] and case['status'] == decision['status'] and
                        case['reason'] == decision['reason'] and
                        [(u['column'],u['window_ordinal'],u['row_range'],u['logical_input_bytes']) for u in case['units']] ==
                        pbepla_units[item['dataset_id']], 'PBEPLA diagnostic changed frozen windows or termination')
                if case['status'] != 'verified':
                    failed = [{'column':u['column'],'row_range':u['row_range'],'input_sha256':u['input_sha256'],
                               'status':u['status'],'reason':u.get('reason')} for u in case['units'] if u['status'] != 'verified']
                    require(failed, 'PBEPLA nonpassing case must disclose its measured window failures')
                    failures.append({'work_item_id':key,'case_id':case['case_id'],'status':case['status'],
                                     'reason':case['reason'],'windows':failed})
                    continue
            elif part is None:
                require(_exact_extent(mode, case, item), 'diagnostic extent differs from the frozen M3 input')
            if mode == 'zfp-array':
                require(case['status'] == decision['status'] and case['reason'] == decision['reason'],
                        'ZFP array diagnostic cannot change the original quality verdict')
                if case['status'] == 'quality_rejected':
                    require(part is None and case['rejected_windows'] > 0, 'ZFP array rejected case lacks full scope or rejected windows')
                    rejected.append({'work_item_id': key, 'case_id': case['case_id'], 'status': case['status'],
                                     'reason': case['reason'], 'rejected_windows': case['rejected_windows']})
                    continue
            require(decision['status'] == 'verified', 'diagnostic cannot link a non-verified functional outcome')
            links[key].append({'case_id': c['case_id'], 'extent': part})
    require(links, 'verified diagnostic has no matching M3 work')
    result = {}
    for key, refs in links.items():
        parts = [r['extent'] for r in refs]
        scope = ('retained_units_only' if mode == 'retained-batch' else 'frozen_extent' if all(x is None for x in parts) else
                 _slice_scope(parts, by_id[key][1]['input']))
        result[key] = {'run_id': run.name, 'mode': mode, 'clock_types': list(clocks), 'scope': scope, 'cases': refs}
    proof = {'run_id': run.name, 'mode': mode,
             'seal': _ref(root, local_file(run, 'completion.json')), 'report': _ref(root, local_file(run, 'report.json')),
             'links': len(result), 'coverage': dict(Counter(d['scope'] for d in result.values()))}
    if mode == 'zfp-array':
        proof['measured_but_excluded_by_quality'] = rejected
    if mode == 'pbepla-grouped':
        proof['measured_but_excluded_by_frozen_status'] = failures
    if bridge is not None:
        proof['functional_source_bridge'] = bridge
    return result, proof


def audit(root, plan_file, source_run, evidence):
    plan = load_json(plan_file)
    ledger, seal = full_run_source(plan, source_run)
    decisions, by_id, obligations, columns = [], {}, [], {}
    bridge_stream = any(mode == 'titchy-stream' for mode, _ in evidence)
    for row, item in full_run_rows(plan, ledger):
        if row.get('entry_kind') == 'specialized_obligation':
            obligations.append({k: row[k] for k in ('obligation_id', 'selection', 'route', 'kind', 'check', 'status', 'reason')})
        if row.get('entry_kind') is not None:
            continue
        rec = {k: row[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route', 'operation', 'applicability', 'status', 'reason')}
        if bridge_stream and row['route'] == 'packet-stream' and row['status'] == 'verified':
            columns[rec['work_item_id']] = _titchy_column(row)
        rec['operation_config_id'] = item['operation_config_id']
        extent = item['input'] or {}
        rec['frozen_extent'] = {k: extent[k] for k in ('row_ranges', 'value_column_range') if k in extent}
        rec['links'] = []
        require(rec['work_item_id'] not in by_id, 'M3 work identity repeated')
        by_id[rec['work_item_id']] = rec, item
        decisions.append(rec)
    require(len(evidence) == len({mode for mode, _ in evidence}), 'use one sealed diagnostic per inventory mode')
    source = _ref(root, plan_file)
    proofs = []
    for mode, path in sorted(evidence):
        links, proof = _linked(root, path, mode, (source, seal), by_id, (plan, source_run, columns))
        for key, link in links.items():
            by_id[key][0]['links'].append(link)
        proofs.append(proof)
    routes = defaultdict(Counter)
    for r in decisions:
        full = {k for link in r['links'] if link['scope'] == 'frozen_extent' for k in link['clock_types']}
        partial = {k for link in r['links'] for k in link['clock_types']} - full
        r['clock_coverage'] = {k: ('frozen_extent' if k in full else 'projected_or_retained' if k in partial else 'not_inventoried')
                               for k in ('native_repeat', 'verified_durable_repeat')}
        route = routes[r['route']]
        route['status:' + r['status']] += 1
        if r['status'] == 'verified':
            for k, v in r['clock_coverage'].items():
                route[k + ':' + v] += 1
    body = {'schema': 'bmk.m3-diagnostic-measurement-inventory/1', 'source_plan': source, 'source_seal': seal, 'source_run': source_run.name,
            'diagnostics': proofs, 'decisions': decisions, 'unverified_obligations': [o for o in obligations if o['status'] != 'verified'],
            'obligation_outcomes': dict(Counter(o['kind'] + ':' + o['status'] for o in obligations)),
            'routes': {k: dict(v) for k, v in sorted(routes.items())}, 'qualification_granted': False, 'stage_accepted': False,
            'timing_admitted': False, 'not_inventoried_means': 'no matching link from the evidence provided, not an assertion of absence'}
    return {**body, 'inventory_id': content_id(body)}
