"""Full audit composition cannot mix runs, shrink denominators, or turn a failure green."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from audit_m3_full_run import _summary
from tsbench.assets import ContractError


def views():
    plan = {'plan_content_id': 'p', 'obligations': [1, 2], 'work_items': [
        {'applicability': 'input_domain_matches'}, {'applicability': 'outside_declared_domain'}]}
    identity = {'run_id': 'r', 'plan_content_id': 'p'}
    outcomes = {'quality_rejected': 1, 'outside_declared_domain': 1}
    census = {**identity, 'seal_id': 's', 'all_frozen_decisions_and_obligations_accounted': True, 'decisions': [1, 2],
              'corpus_statuses': outcomes, 'obligation_statuses': {'required': {'verified': 1},
                                                                'conditional': {'pending_supported_runtime': 1}},
              'specialist_product_statuses': {'expected_rejection': 1}, 'batch_unit_mismatches': [],
              'no_unbound_obligations': True}
    metric = {**identity, 'seal_id': 's', 'includes_all_plan_decisions': True, 'decision_rows': 2, 'decision_statuses': outcomes}
    custody = {**identity, 'source_seal_id': 's', 'corpus_decision_count': 2, 'all_corpus_decisions_present': True,
               'physical_retained_files': 1, 'physical_retained_bytes': 10, 'isolated_page_replays': []}
    return plan, census, metric, custody


def test_full_audit_preserves_failures_and_pending_conditions():
    result = _summary(*views())
    assert result['applicable_corpus_nonverified'] == {'quality_rejected': 1}
    assert result['obligations_nonverified']['conditional'] == {'pending_supported_runtime': 1}
    assert result['frozen_applicability'] == {'input_domain_matches': 1, 'outside_declared_domain': 1}
    assert not result['stage_accepted'] and not result['timing_admitted']


@pytest.mark.parametrize('change,match', [('short', 'denominator'), ('foreign', 'different runs'), ('partial', 'not a preflight')])
def test_audit_rejects_mixed_evidence(change, match):
    plan, census, metric, custody = views()
    if change == 'short':
        metric['decision_rows'] = 1
    elif change == 'foreign':
        custody['source_seal_id'] = 'different'
    else:
        census['all_frozen_decisions_and_obligations_accounted'] = False
    with pytest.raises(ContractError, match=match):
        _summary(plan, census, metric, custody)
