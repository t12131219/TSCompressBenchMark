from copy import deepcopy
from hashlib import sha256
from struct import pack

import pytest

from tsbench.application.m3_batch_timing import _check_sample, _samples
from tsbench.assets import ContractError, content_id
from tsbench.planner.m3_batch_timing import CONFIG, MAGIC, POLICY, SCHEMA, _frame_cost, _groups, check_plan, schedule


def test_frame_cost_uses_original_value_bytes_and_full_transport():
    schema, payload = b'{"dtype":"u8"}', b'a' * 5
    original = {'dtype': 2, 'count': 30, 'raw': {'bytes': 30},
                'schema': {'bytes': len(schema), 'sha256': sha256(schema).hexdigest()}}
    wire = MAGIC['zstd'] + pack('<IQIQ', 2, 30, len(schema), len(payload)) + schema + payload
    assert _frame_cost(wire, 'zstd', original) == {'logical_value_bytes': 30, 'schema_bytes': len(schema),
                                                  'header_bytes': 32, 'native_payload_bytes': 5,
                                                  'complete_frame_bytes': len(wire)}
    with pytest.raises(ContractError, match='schema digest'):
        _frame_cost(wire[:32] + bytes(len(schema)) + payload, 'zstd', original)


def test_frozen_schedule_verifies_two_lanes_and_three_matched_rounds_per_lifecycle():
    case = {'dataset_id': 'test'}
    case['case_id'] = content_id(case)
    groups = _groups([case], 3)
    body = {'schema': SCHEMA, 'cases': [case], 'groups': groups, 'seed': 3, 'expected_batches': 16,
            'diagnostic_only': True, 'performance_admitted': False, 'config': CONFIG, 'policy': POLICY}
    check_plan({**body, 'plan_content_id': content_id(body)})
    for group in groups:
        batches = list(schedule(group))
        assert len(batches) == 8
        for round_ in range(4):
            assert {lane for _, index, lane in batches if index == round_} == {'dlopen', 'linked_entry'}
    tampered = deepcopy(body)
    tampered['groups'][0]['round_orders'][0].reverse()
    with pytest.raises(ContractError, match='randomized scope'):
        check_plan({**tampered, 'plan_content_id': content_id(tampered)})


@pytest.fixture
def measured():
    case = {'case_id': 'case', 'dataset_id': 'source', 'route': 'source-auto', 'unit_index': 0,
            'decode_backend': 'default', 'bytes': {'logical_value_bytes': 200, 'schema_bytes': 20},
            'frame': {'sha256': '123', 'bytes': 80}, 'expected_native': {'encode': {'backend': 'codec'},
                                                                         'decode': {'backend': 'codec'}}}
    group = {'lifecycle': 'cold', 'group_id': 'group'}
    sample = {'lane': 'dlopen', 'lifecycle': 'cold', 'pid': 42, 'loops': 2, 'warmups': CONFIG['warmups'],
              'encoded_verified': 2, 'decoded_verified': 2, 'encode_batch_ns': 1300, 'decode_batch_ns': 1500,
              'release_ns': 100, 'frame_bytes_each': 80, 'frame_capacity_total': 180,
              'decoded_logical_and_schema_total': 440, 'budget_bytes': CONFIG['retention_budget_bytes'],
              'encode_cpu_endpoints': [4, 4], 'decode_cpu_endpoints': [4, 4], 'reference_sha256': '123',
              'warmup_encode_info': {'backend': 'codec'}, 'warmup_decode_info': {'backend': 'codec'}}
    proc = {'pid': 42, 'process_wall_ns': 4000, 'child_usage': {'user_cpu_ns': 500, 'maxrss_bytes': 5000}}
    return case, group, sample, proc


def test_sample_checks_ref_backend_affinity_and_elapsed(measured):
    case, group, sample, proc = measured
    _check_sample(sample, case, group, proc, CONFIG, 4, 'dlopen', 2)
    for key, value in (('frame_bytes_each', 81), ('decode_cpu_endpoints', [4, 5]), ('encoded_verified', 1),
                       ('encode_batch_ns', 5000), ('warmup_decode_info', {'backend': 'fallback'})):
        with pytest.raises(ContractError):
            _check_sample({**sample, key: value}, case, group, proc, CONFIG, 4, 'dlopen', 2)


def test_missing_pair_is_not_promoted_and_inner_loops_are_not_samples(measured):
    case, group, sample, proc = measured
    base = {'phase': 'measured', 'round': 1, 'loops': 2, 'process': proc}
    rows = [{**base, 'lane': 'dlopen', 'status': 'verified', 'sample': sample},
            {**base, 'lane': 'linked_entry', 'status': 'failed', 'sample': None}]
    report = _samples(group, case, rows)
    assert report['matched_rounds'] == []
    lane = report['lanes']['dlopen']
    assert lane['verified_batches'] == 1 and lane['inner_loops_not_independent'] == 2
    assert lane['median_native_ns_per_operation'] == {'encode': 650, 'decode': 750}
    assert report['lanes']['linked_entry']['median_native_ns_per_operation'] == {'encode': None, 'decode': None}
