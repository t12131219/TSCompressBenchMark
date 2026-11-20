"""Retention audits reject missing, altered, unbound and linked objects."""
from pathlib import Path

import pytest

from tsbench.application.m3_full_custody import _collect, audit
from tsbench.assets import ContractError, canonical_bytes, content_id, digest


@pytest.fixture
def case(tmp_path):
    run = tmp_path / 'audit-run'
    work = {'work_item_id': 'item', 'dataset_id': 'd', 'route': 'route', 'selection': 1,
            'operation': 'roundtrip', 'applicability': 'input_domain_matches'}
    plan = {'work_items': [work]}
    plan['plan_content_id'] = content_id(plan)
    ref = 'retained/item/sample'
    obj = run / ref
    obj.parent.mkdir(parents=True)
    obj.write_bytes(b'frame')
    evidence = {'retained': {'path': ref, 'bytes': obj.stat().st_size, 'sha256': digest(obj)}}
    row = {**work, 'status': 'verified', 'evidence': evidence}
    ledger = run / 'ledger.jsonl'
    ledger.write_bytes(canonical_bytes(row) + b'\n')
    report = run / 'report.json'
    report.write_bytes(canonical_bytes({'rows': [row]}))
    seal = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(report), 'ledger_sha256': digest(ledger)}
    (run / 'completion.json').write_bytes(canonical_bytes({**seal, 'seal_id': content_id(seal)}))
    return run, plan, obj, ledger, row


def test_sealed_custody_does_not_award_stage_or_replay(case):
    run, plan, *_ = case
    report = audit(run.parent, plan, run)
    assert report['physical_retained_files'] == 1 and report['physical_retained_bytes'] == 5
    assert report['all_corpus_decisions_present'] and not report['stage_accepted']
    assert not report['isolated_page_replays']


@pytest.mark.parametrize('change,message', [('extra', 'inventory differs'), ('linked', 'linked or non-regular'),
                                            ('data', 'SHA-256 mismatch'), ('ledger', 'source seal differs')])
def test_custody_rejects_retention_and_seal_tamper(case, change, message):
    run, plan, obj, ledger, _ = case
    if change == 'extra':
        obj.with_name('orphan').write_bytes(b'?')
    elif change == 'linked':
        other = obj.with_name('other')
        obj.rename(other)
        obj.symlink_to(other)
    elif change == 'data':
        obj.write_bytes(b'FRAME')
    else:
        ledger.write_bytes(ledger.read_bytes() + b'\n')
    with pytest.raises(ContractError, match=message):
        audit(run.parent, plan, run)


def test_corpus_rows_cannot_appear_after_specialist_tail(case):
    run, plan, _, ledger, row = case
    ledger.write_bytes(b'{"entry_kind":"specialized_product"}\n' + canonical_bytes(row) + b'\n')
    with pytest.raises(ContractError, match='out-of-order'):
        _collect(plan, run, ledger, full=True)
