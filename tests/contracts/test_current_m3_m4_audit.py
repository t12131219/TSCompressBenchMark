"""Current audit keeps failure and diagnostic scope distinct from acceptance."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import audit_current_m3_m4 as audit
from tsbench.assets import ContractError


def test_diagnostic_clocks_cannot_upgrade_frozen_verdicts():
    corpus = [
        {'work_item_id': 'a', 'dataset_id': 'data', 'route': 'route', 'status': 'verified'},
        {'work_item_id': 'b', 'dataset_id': 'data', 'route': 'route2', 'status': 'quality_rejected'},
    ]
    clock_coverage = {'native_repeat': 'frozen_extent', 'verified_durable_repeat': 'projected_or_retained'}
    inv = {'decisions': [{**row, 'clock_coverage': clock_coverage} for row in corpus]}
    counts, gaps = audit._clock_gaps(corpus, inv)
    assert counts == {'native_repeat': {'frozen_extent': 1}, 'verified_durable_repeat': {'projected_or_retained': 1}}
    assert gaps == {'route': {'verified_durable_repeat': [
        {'work_item_id': 'a', 'dataset_id': 'data', 'scope': 'projected_or_retained'}]}}
    inv['decisions'][1]['status'] = 'verified'
    with pytest.raises(ContractError, match='changes a main-ledger verdict'):
        audit._clock_gaps(corpus, inv)


def test_switch_manifest_is_a_local_path_and_quality_failure_is_not_a_pass(tmp_path, monkeypatch):
    manifest, plan, run = tmp_path/'manifest.json', tmp_path/'plan.json', tmp_path/'run'
    manifest.write_text(json.dumps({'scope': 'same_entry_independent_real_projection_v1'}))
    plan.write_text('{}')
    run.mkdir()
    (run/'completion.json').write_text('{}')
    switch = {'schema': 'bmk.m3-input-switch-audit/1', 'manifest': manifest.name, 'baseline_plan_id': 'base',
              'audit_id': 'diag', 'statuses': {'verified': 1, 'quality_rejected': 1},
              'selections': [{'selection': 4, 'native_execution_and_validator_evidence': ['a'],
                              'verified_input_switch_work_items': ['a']},
                             {'selection': 7, 'native_execution_and_validator_evidence': ['b'],
                              'verified_input_switch_work_items': []}],
              **{flag: False for flag in audit.FLAGS}}
    monkeypatch.setattr(audit, 'audit_switch', lambda *args: switch)
    proof = audit._switch_proof(tmp_path, 'base', {4, 7}, plan, run)
    assert proof['type'] == 'independent_real'
    assert proof['manifest'] == audit.ref(tmp_path, manifest)
    assert proof['executed_selections'] == [4, 7]
    assert proof['verified_selections'] == [4]
    with pytest.raises(ContractError, match='different M3 baseline'):
        audit._switch_proof(tmp_path, 'different', {4, 7}, plan, run)
    with pytest.raises(ContractError, match='undeclared or unexecuted'):
        audit._switch_proof(tmp_path, 'base', {4}, plan, run)
    switch['stage_accepted'] = True
    with pytest.raises(ContractError, match='non-admitting'):
        audit._switch_proof(tmp_path, 'base', {4, 7}, plan, run)
