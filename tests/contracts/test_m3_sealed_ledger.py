"""A full-ledger replay projection must not silently borrow or omit evidence."""
import pytest

from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.assets import ContractError, canonical_bytes, content_id, digest


def fixture(tmp_path):
    def item(i):
        return {'work_item_id': f'w{i}', 'dataset_id': f'd{i}', 'selection': 9, 'route': 'auto-batch',
                'operation': 'roundtrip', 'applicability': 'input_domain_matches'}

    ob = {'obligation_id': 'o1', 'selection': 9, 'route': 'auto-batch', 'kind': 'required', 'check': 'recovery'}
    p = {'work_items': [item(1), item(2)], 'obligations': [ob]}
    plan = {**p, 'plan_content_id': content_id(p)}
    return plan, [*p['work_items'], {'entry_kind': 'specialized_product', 'product_slot': 'f1'},
                  {'entry_kind': 'specialized_obligation', **ob}], tmp_path / 'ledger.jsonl'


def _seal(plan, run, rows, ledger):
    ledger.write_bytes(b''.join(canonical_bytes(row) + b'\n' for row in rows))
    report = run / 'report.json'
    report.write_bytes(b'{"projection_scope_test":true}\n')
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name,
            'plan_content_id': plan['plan_content_id'], 'report_sha256': digest(report), 'ledger_sha256': digest(ledger)}
    seal_id = content_id(body)
    (run / 'completion.json').write_bytes(canonical_bytes({**body, 'seal_id': seal_id}))
    return seal_id


def test_project_complete_sealed_run(tmp_path):
    plan, rows, ledger = fixture(tmp_path)
    seal = _seal(plan, tmp_path, rows, ledger)
    assert full_run_source(plan, tmp_path) == (ledger, seal)
    assert list(full_run_rows(plan, ledger)) == list(zip(rows, [*plan['work_items'], None, *plan['obligations']]))


@pytest.mark.parametrize('change,match', [
    ('changed_report', 'source seal'), ('changed_ledger', 'source seal'), ('changed_plan', 'plan identity'),
    ('partial', 'omits frozen corpus'), ('missing_obligation', 'omits frozen corpus decisions or obligations'),
    ('duplicate', 'extra, out of order or foreign'), ('foreign', 'extra, out of order or foreign'),
    ('misordered', 'unexpected typed row'),
])
def test_reject_incomplete_or_mixed_evidence(tmp_path, change, match):
    plan, rows, ledger = fixture(tmp_path)
    if change == 'partial':
        del rows[1]
    elif change == 'missing_obligation':
        rows.pop()
    elif change == 'duplicate':
        rows.insert(1, rows[0])
    elif change == 'foreign':
        rows[-1] = {**rows[-1], 'route': 'some-other-route'}
    elif change == 'misordered':
        rows[-2:] = reversed(rows[-2:])
    _seal(plan, tmp_path, rows, ledger)
    if change == 'changed_report':
        (tmp_path / 'report.json').write_text('{}\n')
    elif change == 'changed_ledger':
        ledger.write_text('{}\n')
    elif change == 'changed_plan':
        plan['obligations'] = []
    with pytest.raises(ContractError, match=match):
        path, _ = full_run_source(plan, tmp_path)
        list(full_run_rows(plan, path))


def test_fixed_batch_audits_shared_frame_with_both_frozen_decoders(tmp_path, monkeypatch):
    from tsbench.application import m3_fixed_batch_audit as batch
    from tsbench.planner.m3_fixed_batch import AUTO, DIRECTORY, DRIVER, RETENTION, SCALAR

    item = {'work_item_id': 'w1', 'dataset_id': 'd1', 'selection': 9, 'route': 'decode-backends',
            'operation': 'decode_common_frame', 'applicability': 'input_domain_matches', 'view': 'f64_columns',
            'input': {'full_extent_of_file_rows_and_value_columns': True, 'row_ranges': [{'start': 0, 'end': 1}],
                      'value_column_range': [0, 1], 'skipped_row_ranges': [],
                      'slice_extent': {'max_per_unit': 65536, 'unit': 'row_span'},
                      'column_grouping': 'one_work_unit_series_per_value_column'}}
    runtime = tmp_path / DIRECTORY
    runtime.mkdir()
    (runtime / 'worker').write_bytes(b'worker')
    samples = tmp_path / RETENTION['directory']
    samples.mkdir()
    frame = samples / 'frame'
    frame.write_bytes(b'frame')
    artifact = {'bytes': 5, 'sha256': digest(frame)}
    frame = frame.rename(samples / f"{artifact['sha256']}.bmk")
    path = frame.relative_to(tmp_path).as_posix()
    original = {'raw': 'original-identity'}
    ref = {'unit_index': 0, 'path': path, **artifact}
    binding = {'driver': DRIVER, 'retention': RETENTION, 'launchers': {},
               'decoder': {'recovery_id': 'recovery', 'files': {'worker': {'bytes': 6, 'sha256': digest(runtime / 'worker')}}}}
    p = {'work_items': [item], 'obligations': [], 'build': {'fixed_batch': binding}}
    plan = {**p, 'plan_content_id': content_id(p)}
    unit = {'artifact': artifact, 'original': original, 'encode': {'process': {'session_id': 'old-encode'}},
            'decodes': {tag: {'process': {'session_id': f'old-{tag}'}} for tag in (SCALAR, AUTO)}}
    row = {**item, 'status': 'verified', 'evidence': {'driver': DRIVER, 'recovery_id': 'recovery', 'units': [unit],
                                                      'retained_samples': [ref], 'released_frames': {'count': 0, 'bytes': 0}}}
    seal = _seal(plan, tmp_path, [row], tmp_path / 'ledger.jsonl')

    def restore(bundle, runtime_binding, decision, tag, work, compressed, frame_identity, original_identity):
        assert (bundle, runtime_binding, decision, compressed, frame_identity, original_identity) == (
            runtime, binding, item, frame, artifact, original)
        return {'process': {'session_id': f'new-{tag}', 'input_mounts': {'frame': frame_identity}}}

    monkeypatch.setattr(batch, 'restore_frame', restore)
    monkeypatch.setattr(batch, 'launcher_lock', dict)
    audit = batch.audit_fixed_batch(tmp_path, plan, tmp_path, replay=True, full_ledger=True)
    assert audit['seal_id'] == seal
    assert audit['sample_references'] == audit['unique_retained_frames'] == audit['verified_case_count'] == 1
    assert [r['decode_backend'] for r in audit['replayed']] == [SCALAR, AUTO]
    assert not audit['stage_accepted'] and not audit['timing_admitted']
