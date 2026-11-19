"""Bind a runnable lossless batch execution to the existing admission definition (pilot #7)."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..assets import content_id, digest, load_json, local_file, require
from ..recovery import check_recovery, plan_recovery
from ..runtime import resolve_worker
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from .gorilla import HEADER, LIMIT, PLUGIN, columns, max_payload, plan_gorilla, sha
from .method_boundaries import plan_boundary_cases
from .native_admission import plan_native_admission

SCHEMA = 'bmk.lossless-batch-execution/1'
CROSS_SCHEMA = 'bmk.lossless-batch-execution/2'
CROSS_CHECK = 'native_payload_cross_decode'
DIRECT_TOOL = 'gorilla-c-direct'
DIRECT_TARGET = 'tsbench_gorilla_batch_control'
DIRECT_SOURCE = 'plugins/codecs/gorilla-tv/direct_control.c'
POLICY = 'configs/suites/m3_first_batch_native_v2/gorilla-batch-execution.json'
METHOD = {'plugin': PLUGIN, 'options': {}}
CHECKS = {'chunk_boundary_triplet', 'timestamp_and_delta_edges', 'f64_bits_empty_and_single',
          'native_payload_cross_decode'}
CONTRACT_CODE = tuple('src/tsbench/' + name for name in (
    'application/batch_execution.py', 'planner/batch_execution.py', 'qualification/gorilla.py',
    'supervisor/isolated_worker.py', 'supervisor/process.py', 'recovery.py', 'assets.py',
    'application/restore.py', 'application/smoke.py', 'planner/gorilla.py', 'planner/method_boundaries.py',
    'planner/native_admission.py'))


@dataclass(frozen=True, slots=True)
class BatchInput:
    schema: bytes
    columns: tuple[bytes, ...]


def _inputs(root):
    gorilla, pairs = plan_gorilla(root)
    boundary, cases = plan_boundary_cases(root)
    sources = {}
    by_case = {}

    def add(name, sample, rows, lineage, status):
        expected = {'columns': [{'dtype': t, 'count': rows} for t in (7, 10)],
                    'column_bytes': [len(x) for x in sample.columns],
                    'column_sha256': [sha(x) for x in sample.columns],
                    'schema_sha256': sha(sample.schema), 'schema_bytes': len(sample.schema)}
        require(expected['column_bytes'] == [8 * rows] * 2, 'Gorilla input word layout differs')
        body = {'name': name, 'lineage': lineage, 'original': expected, 'expected_status': status,
                'max_frame_bytes': HEADER.size + len(sample.schema) + max_payload(rows) if status == 0 else 0}
        identity = content_id(body)
        sources[name] = ({**body, 'product_slot': identity}, sample)

    for row in gorilla['fixtures']:
        name = row['name']
        sample = BatchInput(row['schema'].encode('ascii'), columns(pairs[name]))
        require([sha(x) for x in sample.columns] == [row['milliseconds_sha256'], row['value_sha256']],
                'Gorilla fixture does not match its original-domain definition')
        add(name, sample, row['rows'], row['lineage'], 0)
    for row in gorilla['cases']:
        if row['route'] == 'tv-batch':
            by_case[row['case_id']] = (gorilla['bundle_id'], [x['name'] for x in row['criteria']['fixtures']])
    for case in cases:
        d = case.definition
        if (d['selection'], d['route']) == (7, 'tv-batch'):
            row = d['row']
            name = row['case']
            status = {'resource_limit_7': 7, 'verified': 0}[row['expected']]
            add(name, BatchInput(case.schema, case.columns), row['rows'], row, status)
            by_case[d['case_id']] = (boundary['bundle_id'], [name])
    return sources, by_case


def gorilla_inputs(root):
    """Reuse the original inputs, with explicit route/method identity for a shared ledger."""
    sources, cases = _inputs(root)
    products, ids = {}, {}
    for name,(row,sample) in sources.items():
        body = {**{k:v for k,v in row.items() if k!='product_slot'},
                'method':PLUGIN,'reject_decodes':[],'upstream_zstd':False}
        sid = content_id(body)
        products[sid] = {**body,'product_slot':sid},sample
        ids[name] = sid
    return products,{cid:(bundle,[ids[n] for n in names]) for cid,(bundle,names) in cases.items()}


def cross_binding_key(plan):
    return f'7/tv-batch/{CROSS_CHECK}' if 'methods' in plan else CROSS_CHECK


def requires_cross(plan, slot):
    return (DIRECT_TOOL in (plan.get('direct_control') or {}).get('tool_refs',{}) and
            slot['product_slot'] in plan['obligation_bindings'][cross_binding_key(plan)]['product_slots'])


def is_gorilla_slot(slot):
    return slot.get('method',PLUGIN)==PLUGIN


def compile_batch_execution(root: Path, build: dict, direct_control: str | None = None):
    policy = load_json(local_file(root, POLICY))
    require(policy.keys() == {'schema','selection','route','limits','max_shared_decoder_bytes','verification','retention'} and
            (policy['schema'], policy['selection'], policy['route'], policy['verification'], policy['retention']) ==
            ('bmk.lossless-batch-execution-policy/1', 7, 'tv-batch', 'artifact_each',
             'unique_serialized_product_and_bounded_logs_or_rejection_per_slot'), 'invalid batch execution policy')
    validate_limits(policy['limits'])
    require(type(policy['max_shared_decoder_bytes']) is int and 0 < policy['max_shared_decoder_bytes'] <= 16 << 20,
            'invalid shared decoder byte budget')
    admission = plan_native_admission(root)
    sources, by_case = _inputs(root)
    groups = [r for r in admission['routes'] if (r['selection'], r['route']) == (7, 'tv-batch')]
    require(len(groups) == 1, 'missing Gorilla batch admission group')
    group = groups[0]
    checks = {}
    for obligation in admission['obligations']:
        if obligation['route_contract_id'] != group['route_contract_id']:
            continue
        bound = []
        for row in obligation['planned_case_inputs']:
            source_id, names = by_case[row['case_id']]
            require(source_id == row['bundle_id'], 'batch execution case source differs from admission definition')
            bound.extend(sources[name][0]['product_slot'] for name in names)
        require(bound and len(bound) == len(set(bound)), 'empty or duplicated obligation binding')
        checks[obligation['check']] = {'obligation_id': obligation['obligation_id'], 'product_slots': bound}
    require(set(checks) == CHECKS and set.union(*(set(c['product_slots']) for c in checks.values())) ==
            {row['product_slot'] for row, _ in sources.values()}, 'Gorilla execution coverage differs')
    require(set(build['plugins']) == {PLUGIN}, 'batch execution build lock must bind exactly gorilla-tv')
    resolved = resolve_worker(root, build, PLUGIN, {})
    tools = None
    if direct_control is not None:
        library = PurePosixPath(build['plugins'][PLUGIN]['library']['path'])
        require(PurePosixPath(direct_control) == library.with_name(DIRECT_TARGET),
                'direct control must be built alongside the selected Gorilla plugin')
        tools = {DIRECT_TOOL: {'path': direct_control, 'sha256': digest(local_file(root, direct_control))}}
    recovery = plan_recovery(root, build, {PLUGIN: METHOD}, tools=tools)
    if tools:
        _check_native_link(recovery)
    shared = sum(row['bytes'] for row in recovery['files'].values())
    require(shared <= policy['max_shared_decoder_bytes'], 'shared decoder closure exceeds policy budget')
    slots = [row for row, _ in sources.values()]
    frame_budget = sum(row['max_frame_bytes'] for row in slots)
    require(all(max([row['max_frame_bytes'], row['original']['schema_bytes'], *row['original']['column_bytes']]) <=
                policy['limits']['file_bytes'] and
                row['original']['columns'][0]['count'] <= LIMIT + (row['expected_status'] == 7) for row in slots),
            'logical product or output bound exceeds the execution policy')
    logs = sum(2 if row['expected_status'] else 4 for row in slots) * policy['limits']['file_bytes']
    body = {'schema': CROSS_SCHEMA if tools else SCHEMA, 'purpose': 'native_admission_execution_candidate', 'runnable': True,
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False,
            'verification': policy['verification'], 'policy_id': content_id(policy), 'limits': policy['limits'],
            'admission_plan_id': admission['plan_content_id'], 'admission_coverage': admission['coverage'],
            'route_contract': group, 'obligation_bindings': checks, 'slots': slots, 'method': METHOD,
            'code': {path: digest(local_file(root, path)) for path in CONTRACT_CODE}, 'launchers': launcher_lock(),
            'configuration_id': resolved['configuration_id'], 'build': build, 'decoder': recovery,
            'retention_bounds': {'serialized_products_bytes': frame_budget, 'operation_logs_bytes': logs,
                                 'shared_decoder_bytes': shared,
                                 'excludes': 'plan_ledger_seal_and_filesystem_overhead'}}
    if tools:
        cross_slots = checks[CROSS_CHECK]['product_slots']
        need = [row for row in slots if row['product_slot'] in cross_slots]
        require(all(row['expected_status'] == 0 for row in need), 'direct cross-control includes rejection product')
        body['direct_control'] = {'tool_refs': tools, 'protocol': 'raw_xorchunk_c11_bidirectional_v1'}
        body['code'][DIRECT_SOURCE] = digest(local_file(root, DIRECT_SOURCE))
        body['retention_bounds'].update(
            control_payload_bytes=sum(max_payload(row['original']['columns'][0]['count']) for row in need),
            operation_logs_bytes=logs + len(need) * 6 * policy['limits']['file_bytes'])
    return {**body, 'plan_content_id': content_id(body)}, {row['product_slot']: sample for row, sample in sources.values()}


def compile_batch_suite(root, build, direct_control, suite, fenv_control=None, titchy_control=None, xz_control=None,
                        pcodec_control=None, wrapped_driver=None, gorilla_control=None, selfstar_control=None, huff0_control=None, sprintz_control=None, titchy_access_control=None, titchy_stream_control=None,
                        huff0_portable_build=None):
    from .linear_batch import TYPED_SUITES, compile_linear_batch

    if suite in {'linear-v1', *TYPED_SUITES}:
        return compile_linear_batch(root, build, direct_control, fenv_control, suite=suite, titchy_control=titchy_control,
                                    xz_control=xz_control, pcodec_control=pcodec_control, wrapped_driver=wrapped_driver,
                                    gorilla_control=gorilla_control,selfstar_control=selfstar_control,huff0_control=huff0_control,
                                    sprintz_control=sprintz_control,titchy_access_control=titchy_access_control,
                                    titchy_stream_control=titchy_stream_control,huff0_portable_build=huff0_portable_build)
    require(suite == 'gorilla' and all(x is None for x in (fenv_control,titchy_control,xz_control,pcodec_control,wrapped_driver,gorilla_control,selfstar_control,huff0_control,sprintz_control,titchy_access_control,titchy_stream_control,huff0_portable_build)),
            'unknown batch execution suite or incompatible control')
    return compile_batch_execution(root, build, direct_control)


def plan_batch_execution(root: Path, build: dict, *, direct_control: str | None = None,
                         suite: str = 'gorilla', fenv_control: str | None = None, titchy_control: str | None = None,
                         xz_control: str | None = None, pcodec_control: str | None = None,
                         wrapped_driver: str | None = None, gorilla_control: str | None = None,
                         selfstar_control: str | None = None, huff0_control: str | None = None,
                         sprintz_control: str | None = None, titchy_access_control: str | None = None,
                         titchy_stream_control: str | None = None, huff0_portable_build: str | None = None) -> dict:
    return compile_batch_suite(root, build, direct_control, suite, fenv_control, titchy_control, xz_control,
                               pcodec_control, wrapped_driver,gorilla_control,selfstar_control,huff0_control,sprintz_control,titchy_access_control,titchy_stream_control,huff0_portable_build)[0]


def _check_native_link(spec):
    worker = spec['files'][spec['plugins'][PLUGIN]]
    direct = spec['files'][spec['tools'][DIRECT_TOOL]]
    require('libgorilla_c.so' in worker['needed'] and 'libgorilla_c.so' in direct['needed'] and
            all(name in {'libgorilla_c.so', 'libc.so.6'} for name in direct['needed']),
            'direct control and plugin must link the same sealed C library, without a plugin in the control')


def direct_path(plan):
    return plan['direct_control']['tool_refs'][DIRECT_TOOL]['path'] if plan['schema'] == CROSS_SCHEMA else None


def check_batch_execution(plan):
    from .linear_batch import LINEAR_SCHEMAS, check_linear_batch

    require(isinstance(plan, dict) and plan.get('schema') in {SCHEMA, CROSS_SCHEMA, *LINEAR_SCHEMAS} and
            plan.get('plan_content_id') == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}) and
            plan.get('qualification_granted') is False and plan.get('stage_accepted') is False and
            plan.get('timing_admitted') is False and plan.get('runnable') is True and
            plan.get('verification') == 'artifact_each', 'invalid frozen batch execution plan')
    validate_limits(plan['limits'])
    if plan['schema'] in LINEAR_SCHEMAS:
        check_linear_batch(plan)
        return
    require(plan.get('method') == METHOD, 'invalid Gorilla batch method')
    control = plan.get('direct_control')
    tools = None
    if plan['schema'] == CROSS_SCHEMA:
        require(isinstance(control, dict) and set(control) == {'tool_refs', 'protocol'} and
                control['protocol'] == 'raw_xorchunk_c11_bidirectional_v1' and set(control['tool_refs']) == {DIRECT_TOOL},
                'invalid direct control definition')
        tools = control['tool_refs']
        require(PurePosixPath(direct_path(plan)) ==
                PurePosixPath(plan['build']['plugins'][PLUGIN]['library']['path']).with_name(DIRECT_TARGET),
                'direct control build path differs')
    else:
        require(control is None, 'legacy batch execution cannot carry a direct control')
    check_recovery(plan['decoder'], plan['build'], {PLUGIN: METHOD}, tools=tools)
    if tools:
        _check_native_link(plan['decoder'])
