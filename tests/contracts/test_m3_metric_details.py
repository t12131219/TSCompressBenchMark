import copy
import io
from pathlib import Path

import pytest

from tsbench.application.m3_metric_details import BATCH_PROCESS, FIXED, extract, metric_row
from tsbench.assets import ContractError, canonical_bytes, content_id, digest, parse_json


def case():
    item = {'work_item_id': 'id', 'dataset_id': 'd1', 'route': 'decode-backends', 'selection': 9,
            'operation': 'decode_common_frame', 'view': 'f64_columns', 'operation_config_id': 'cfg',
            'route_contract_id': 'contract', 'canonical_object_id': 'object', 'applicability': 'input_domain_matches',
            'input': {'size_estimate': {'unique_logical_axis_bytes': 0, 'unique_logical_value_bytes': 64}}}

    def op(direction, name, wall):
        return {'process': {'status': 'completed', 'returncode': 0, 'process_wall_ns': wall,
                            'child_usage': {'user_cpu_ns': 3, 'system_cpu_ns': 5, 'maxrss_bytes': 21}},
                'native': {'operation': direction, 'backend': name, 'threads': 1, 'fallback': False}}
    u = {'input_bytes': 32, 'original': {'schema': {'bytes': 4}}, 'artifact': {'bytes': 46},
         'encode': op('encode', 'auto', 11), 'decodes': {'scalar': op('decode', 'scalar', 13),
                                                       'simd': op('decode', 'simd', 17)}}
    e = {'driver': FIXED, 'units': [u, copy.deepcopy(u)]}
    return item, {**item, 'status': 'verified', 'reason': '', 'evidence': e}


def test_common_frame_charged_once_and_process_wall_is_not_native():
    item, row = case()
    data = metric_row(item, row, 1)
    assert data['accounting']['complete_artifact_bytes'] == 92
    assert data['accounting']['components'] == {'native_payload_bytes': 20, 'embedded_schema_bytes': 8,
                                                 'linear_frame_header_bytes': 64}
    observed = {(s['operation'], s['backend']): s for s in data['operations']}
    assert set(observed) == {('encode', 'auto'), ('decode', 'scalar'), ('decode', 'simd')}
    assert all(s['clock_scope'] == BATCH_PROCESS and s['clock_kind'] == 'process' and s['wall_ns']['count'] == 2 and
               s['logical_bytes_measured'] == 64 and s['cpu_ns']['sum'] == 16 and s['max_process_rss_bytes'] == 21 and
               s['repeated_measurement_distribution'] is None for s in observed.values())
    assert data['missing_metrics']['native_timing'] == 'clock_not_recorded_by_functional_driver'
    assert data['timing_admitted'] is False


def test_outside_domain_and_quality_failure_are_retained_without_fake_zeroes():
    item, row = case()
    bad = metric_row(item, {**row, 'status': 'quality_rejected', 'reason': 'non-exact'}, 4)
    assert bad['accounting'] is None and bad['operations'] == [] and bad['reason'] == 'non-exact'
    assert bad['missing_metrics']['byte_accounting'] == 'non_verified_outcome_raw_evidence_retained'
    item.update(applicability='outside_declared_domain', input=None)
    excluded = metric_row(item, {**row, 'applicability': item['applicability'], 'status': item['applicability'], 'evidence': None}, 2)
    assert excluded['accounting'] is None and excluded['status'] == item['applicability']


def sealed(tmp_path, items, rows):
    run = tmp_path / 'r'
    run.mkdir()
    body = {'work_items': items}
    plan = {**body, 'plan_content_id': content_id(body)}
    ledger = run / 'ledger.jsonl'
    ledger.write_bytes(b''.join(canonical_bytes(r) + b'\n' for r in rows))
    report = run / 'report.json'
    report.write_bytes(b'{}')
    seal = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(report), 'ledger_sha256': digest(ledger)}
    (run / 'completion.json').write_bytes(canonical_bytes({**seal, 'seal_id': content_id(seal)}))
    return plan, run


def test_sealed_partial_detail_keeps_missing_decision_visible_in_summary(tmp_path: Path):
    item, row = case()
    plan, run = sealed(tmp_path, [item, {**item, 'work_item_id': 'not_executed'}], [row])
    out = io.BytesIO()
    report = extract(plan, run, out)
    assert report['decision_rows'] == 1 and report['work_items_in_plan'] == 2 and not report['includes_all_plan_decisions']
    assert parse_json(out.getvalue().decode())['ledger_line'] == 1
    with (run / 'ledger.jsonl').open('ab') as f:
        f.write(b' ')
    with pytest.raises(ContractError, match='source seal differs'):
        extract(plan, run, io.BytesIO())


def test_resealed_unknown_source_or_unbalanced_charge_is_rejected(tmp_path):
    item, row = case()
    broken = copy.deepcopy(row)
    broken['evidence']['units'][0]['artifact']['bytes'] = 30
    with pytest.raises(ContractError, match='missing encoded payload'):
        metric_row(item, broken, 1)
    plan, run = sealed(tmp_path, [item], [row, row])
    with pytest.raises(ContractError, match='duplicate or unknown corpus ID'):
        extract(plan, run, io.BytesIO())


def test_dictionary_bills_holdout_and_shared_model_once_not_training():
    item, row = case()
    item['input']['training'] = {'consumed_byte_range': [0, 24]}
    e = {'driver': 'zstd-dictionary-corpus/1', 'train_bytes': 24, 'holdout': {'bytes': 40},
         'phase': 'heldout_validation', 'failed_units': 0, 'test_attempted': True,
         'dictionary': {'bytes': 10}, 'training_native_ns': 13, 'verified_frame_bytes': 12,
         'verified_frame_bytes_plus_shared_dictionary_once': 22,
         'frames': [{'bytes': 9, 'logical_bytes': 20, 'status': 'verified'},
                    {'bytes': 3, 'logical_bytes': 20, 'status': 'verified'}]}
    detail = metric_row(item, {**row, 'evidence': e}, 9)
    bill = detail['variant_accounting']['dictionary_once']
    assert bill['logical_bytes'] == 40 and bill['complete_artifact_bytes'] == 22
    assert detail['specialized_metrics']['train_bytes'] == 24
    assert [(x['operation'], x['clock_kind'], x['logical_bytes_measured']) for x in detail['operations']] == [('train', 'native', 24)]
    e['train_bytes'] = 25
    with pytest.raises(ContractError, match='denominator differs'):
        metric_row(item, {**row, 'evidence': e}, 9)
    e['train_bytes'] = 24
    e['failed_units'] = 1
    e['frames'][1] = {'logical_bytes': 20, 'status': 'failed'}
    e['verified_frame_bytes'], e['verified_frame_bytes_plus_shared_dictionary_once'] = 9, 19
    rejected = metric_row(item, {**row, 'evidence': e, 'status': 'failed'}, 9)
    assert rejected['variant_accounting'] == {} and rejected['rejected_evidence_not_timing_admitted']


def test_progressive_prefixes_are_not_added_and_failed_window_has_no_ratio():
    item, row = case()

    def layer(n, payload, extra, exact_error):
        return {'layer': n, 'bytes': 4 + payload, 'header_bytes': 4, 'payload_bytes': payload,
                'layer_payload_bytes': extra, 'exact_max_abs_error': exact_error, 'quality_passed': True}

    a = {'logical_input_bytes': 32, 'layers': [layer(1, 3, 3, '1/3'), layer(2, 8, 5, '1/9')]}
    b = {'logical_input_bytes': 32, 'layers': [layer(1, 2, 2, '1/2'), layer(2, 7, 5, '1/13')]}
    e = {'driver': 'pbepla-corpus-control/1', 'units': [a, b], 'failed_units': 0, 'quality_rejected_units': 0}
    detail = metric_row(item, {**row, 'evidence': e}, 8)
    assert detail['alternate_costs_are_not_summed']
    assert detail['variant_accounting']['prefix:1']['complete_artifact_bytes'] == 13
    assert detail['variant_accounting']['prefix:2']['complete_artifact_bytes'] == 23
    assert detail['specialized_metrics']['prefixes']['1']['max_exact_abs_error'] == '1/2'
    assert detail['specialized_metrics']['prefixes']['2']['incremental_payload_bytes'] == 10
    e['failed_units'] = 1
    e['units'][1] = {'logical_input_bytes': 32}
    failed = metric_row(item, {**row, 'evidence': e, 'status': 'failed'}, 8)
    assert not failed['variant_accounting'] and failed['specialized_metrics']['prefixes']['1']['restored_windows'] == 1
