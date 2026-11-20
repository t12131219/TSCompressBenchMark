"""Freeze bounded real-corpus, same-ABI paired measurement diagnostics."""
from hashlib import sha256
from pathlib import Path
from random import Random
from struct import unpack_from

from ..assets import content_id, digest, load_json, local_file, require, verify_asset
from ..supervisor import timing_resource as resource
from .frame_batches import EXTENTS, LANES
from .m3_fixed_batch import ROUTES

SCHEMA = 'bmk.m3-fixed-batch-timing-plan/1'
PROFILE_EXACT = 'released_unit_reconstructed_for_exact_m4_case'
CONFIG = {'warmups': 2, 'matched_rounds': 3, 'target_batch_ns': 3_000_000,
          'max_loops': 256, 'retention_budget_bytes': 128 << 20}
POLICY = {'address_space_bytes': 1 << 30, 'file_bytes': 1 << 20, 'timeout_seconds': 30,
          'parallel_batches': 1, 'cache': 'natural_repeated_input',
          'clock': 'native_steady_clock_to_result_ready', 'attempts': 1,
          'steady': 'reset_and_codec', 'cold': 'context_create_codec_destroy_not_process_startup',
          'verification': 'artifact_each_outside_clock_reference_and_original_bits',
          'decode_input': 'each_timed_frame_is_byte_identical_to_frozen_reference',
          'diagnostic': 'no_core_exclusivity_no_ranking'}
MAGIC = {'alp-auto': b'BMKALP\x01\x00', 'pcodec-c-native-auto': b'BMKPCN\x01\x00',
         'pcodec-source-auto': b'BMKPCS\x01\x00', 'zstd': b'BMKZST\x01\x00', 'xz-baseline': b'BMKXZ\x00\x01\x00'}


def reference(root, path):
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def checked_file(root, ref):
    path = verify_asset(root, ref)
    require(path.stat().st_size == ref['bytes'], 'M3 timing asset byte length changed')
    return path


def _frame_cost(wire, plugin, original):
    require(len(wire) >= 32, 'short M3 timing reference frame')
    dtype, count, schema, payload = unpack_from('<IQIQ', wire, 8)
    require(wire[:8] == MAGIC[plugin] and (dtype, count, schema) ==
            (original['dtype'], original['count'], original['schema']['bytes']) and
            payload > 0 and len(wire) == 32 + schema + payload,
            'M3 timing reference frame geometry differs from functional run')
    require(sha256(wire[32:32 + schema]).hexdigest() == original['schema']['sha256'],
            'M3 timing reference schema digest differs from functional run')
    return {'logical_value_bytes': original['raw']['bytes'], 'schema_bytes': schema, 'header_bytes': 32,
            'native_payload_bytes': payload, 'complete_frame_bytes': len(wire)}


def protocol(root):
    files = ('src/tsbench/planner/m3_batch_timing.py', 'src/tsbench/application/m3_batch_timing.py',
             'src/tsbench/planner/frame_batches.py', 'src/tsbench/supervisor/timing_resource.py',
             'src/tsbench/supervisor/process.py', 'src/tsbench/application/timing.py',
             'src/tsbench/application/m3_fixed_batch.py', 'src/tsbench/application/m3_real_corpus_execution.py',
             'src/tsbench/application/m3_fixed_batch_audit.py', 'src/tsbench/application/m3_sealed_ledger.py',
             'tools/probe_m3_fixed_batch_timing_lanes.py', 'tools/m3_profile_alp_comparison.py',
             'native/measurement/frame_batches.cpp', 'native/measurement/paired_batch/CMakeLists.txt')
    return {'code': {p: digest(local_file(root, p)) for p in files},
            'launchers': {p: digest(Path(p)) for p in (resource.TASKSET, resource.PRLIMIT)}}


def schedule(group):
    yield from (('calibration', 0, lane) for lane in group['calibration_order'])
    for round_, lanes in enumerate(group['round_orders'], 1):
        yield from (('measured', round_, lane) for lane in lanes)


def _groups(cases, seed):
    rng = Random(seed)
    groups = []
    for case in cases:
        for lifecycle in EXTENTS:
            row = {'case_id': case['case_id'], 'lifecycle': lifecycle, 'calibration_order': rng.sample(LANES, len(LANES)),
                   'round_orders': [rng.sample(LANES, len(LANES)) for _ in range(CONFIG['matched_rounds'])]}
            groups.append({**row, 'group_id': content_id(row)})
    return groups


def plan_timing(root, func_plan_path, func_run, audit_path, probe_path, *, cpu, seed=20261120, full_ledger=False):
    from ..application.m3_fixed_batch_audit import audit_fixed_batch, sealed_batch_scope

    func_plan = load_json(func_plan_path)
    custody = audit_fixed_batch(root, func_plan, func_run, full_ledger=full_ledger)
    audited, probe = load_json(audit_path), load_json(probe_path)
    require(audited.get('schema') == 'bmk.m3-fixed-batch-retention-audit/1' and audited['replay_performed'] is True and
            all(audited[k] == custody[k] for k in custody if k not in ('replay_performed', 'replayed')),
            'M3 timing requires a matching completed detached replay audit')
    require(probe.get('schema') == 'bmk.m3-fixed-batch-timing-lane-probe/1' and
            probe['probe_id'] == content_id({k: v for k, v in probe.items() if k != 'probe_id'}) and
            probe.get('source_projection') == custody.get('source_projection') and
            (probe['plan_content_id'], probe['functional_seal_id'], probe['run_id']) ==
            (custody['plan_content_id'], custody['seal_id'], custody['run_id']), 'M3 paired lane probe is stale')
    seal_id, _, source_rows = sealed_batch_scope(root, func_plan, func_run, full_ledger=full_ledger)
    require(seal_id == custody['seal_id'], 'M3 timing planner read a different sealed functional run')
    replay = {(r['work_item_id'], r['unit_index'], r['decode_backend']): r for r in audited['replayed']}
    probe_rows = {(r['work_item_id'], r['unit_index'], r['backend'], r['lifecycle'], r['lane']): r for r in probe['results']}
    require(len(replay) == len(audited['replayed']) and len(probe_rows) == len(probe['results']),
            'M3 replay or lane probe has duplicated timing cases')
    cases = []
    for row, item in source_rows:
        if row['status'] != 'verified' or (row['selection'], row['route']) not in ROUTES:
            continue
        plugin, _, backends = ROUTES[row['selection'], row['route']]
        for sample in row['evidence']['retained_samples']:
            index = sample['unit_index']
            unit = row['evidence']['units'][index]
            frame = reference(root, checked_file(func_run, sample))
            original = unit['original']
            sizes = _frame_cost(checked_file(root, frame).read_bytes(), plugin, original)
            for backend in backends:
                key = (row['work_item_id'], index, backend)
                restoration = replay.pop(key, None)
                require(restoration and restoration['artifact'] == sample and restoration['restored'] == original and
                        restoration['process']['input_mounts'] == {'frame': unit['artifact']} and
                        restoration['process']['status'] == 'completed', 'M3 timing case lacks matching frame-only replay')
                native = {'encode': unit['encode']['native'], 'decode': unit['decodes'][backend]['native']}
                for lifecycle in EXTENTS:
                    for lane in LANES:
                        check = probe_rows.pop((*key, lifecycle, lane), None)
                        require(check and check['frame_sha256'] == sample['sha256'] and
                                [check['encode_native'], check['decode_native']] == list(native.values()),
                                'M3 timing case lacks matching same-ABI lane probe')
                scope = {k: item[k] for k in ('work_item_id', 'dataset_id', 'view', 'route', 'selection',
                                               'canonical_object_id', 'operation_config_id')}
                case = {**scope, 'plugin': plugin, 'module': func_plan['build']['fixed_batch']['decoder']['plugins'][plugin],
                        'decode_backend': backend,
                        'options': {'decode_backend': backend} if plugin == 'alp-auto' else {},
                        'unit_index': index, 'geometry': {k: unit[k] for k in ('column', 'row_range', 'byte_range') if k in unit},
                        'original': original, 'frame': frame, 'bytes': sizes, 'expected_native': native}
                cases.append({**case, 'case_id': content_id(case)})
    require(cases and not replay and not probe_rows, 'M3 timing replay/lane scope differs from frozen cases')
    methods = probe['timing_build']
    require(methods.keys() == {c['plugin'] for c in cases}, 'M3 timing build does not span the case methods')
    for roles in methods.values():
        require(set(roles['lanes']) == set(LANES), 'M3 timing build must provide both lanes')
        for ref in (*roles['lanes'].values(), *roles['project_runtime_assets'].values()):
            checked_file(root, ref)
    groups = _groups(cases, seed)
    body = {'schema': SCHEMA, 'diagnostic_only': True, 'performance_admitted': False, 'seed': seed,
            'functional': {'plan': reference(root, func_plan_path), 'report': reference(root, func_run / 'report.json'),
                           'seal_id': custody['seal_id'], 'audit': reference(root, audit_path), 'probe': reference(root, probe_path)},
            'definition': func_plan['definition']['plan'], 'physical_build': methods,
            'environment': resource.environment(cpu), 'protocol': protocol(root), 'config': CONFIG,
            'policy': POLICY, 'cases': cases, 'groups': groups, 'expected_batches': sum(len(list(schedule(g))) for g in groups)}
    if full_ledger:
        body['functional'].update(ledger=reference(root, func_run / 'ledger.jsonl'), source_projection=custody['source_projection'])
    return {**body, 'plan_content_id': content_id(body)}


def check_plan(plan):
    require(plan['schema'] == SCHEMA and plan['diagnostic_only'] is True and plan['performance_admitted'] is False and
            plan['config'] == CONFIG and plan['policy'] == POLICY and
            plan['plan_content_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}),
            'invalid M3 paired timing plan')
    cases = plan['cases']
    require(cases and len(cases) == len({c['case_id'] for c in cases}) and
            all(c['case_id'] == content_id({k: v for k, v in c.items() if k != 'case_id'}) for c in cases) and
            plan['groups'] == _groups(cases, plan['seed']) and
            plan['expected_batches'] == sum(len(list(schedule(g))) for g in plan['groups']),
            'M3 paired timing case IDs or randomized scope differ')
    source = plan.get('functional', {})
    if source.get('source_projection') == PROFILE_EXACT:
        require({'logically_matched_profile_seal', 'profile_plan', 'profile_reference_seal', 'ledger', 'runtime_reference_seal',
                 'anchor', 'plan', 'report', 'seal_id'} <= source.keys() and len(cases) == 2 and
                {c['decode_backend'] for c in cases} == {'scalar-unfused', 'falp-auto'} and
                all(c['plugin'] == 'alp-auto' and c['route'] == 'decode-backends' for c in cases) and
                all(cases[0][k] == cases[1][k] for k in ('work_item_id', 'unit_index', 'geometry', 'original', 'frame')),
                'M3 exact profile timing must use both ALP decoders on one frame')
