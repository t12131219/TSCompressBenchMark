from copy import deepcopy

import pytest

from tsbench.application import m3_in_run_failure as failure, m3_in_run_gorilla_retained as gorilla
from tsbench.application import m3_in_run_pcodec_pages as pages
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v4 import GORILLA
from tsbench.planner.m3_in_run_measurement_v5 import PCODEC_PAGES, population


def test_only_native_page_routes_added_and_randomized():
    items = [{'work_item_id': key, 'selection': 11, 'route': route, 'applicability': app,
              'operation_config_id': 'config'} for key, route, app in (
                  ('a', 'source-pages', 'input_domain_matches'), ('b', 'native-pages', 'input_domain_matches'),
                  ('c', 'source-auto', 'input_domain_matches'), ('d', 'native-pages', 'outside_declared_domain'))]
    base = {key: {'status': 'measurement_adapter_not_integrated'} for key in 'abc'}
    base['d'] = {'status': 'outside_declared_domain'}
    result = population(items, base, {(11, 'source-pages'), (11, 'native-pages')})
    assert all(result[k]['adapter'] == PCODEC_PAGES for k in 'ab') and result['c'] == base['c'] and result['d'] == base['d']
    for key, lane in [('a', 'source'), ('b', 'native')]:
        slots = list(pages.schedule(result[key]['case_id'], lane))
        assert slots == list(pages.schedule(result[key]['case_id'], lane)) and len(slots) == 8
        for i in range(4):
            assert {s['direction'] for s in slots if s['repeat'] == i} == {'encode', 'decode'}
    with pytest.raises(ContractError, match='overlapping'):
        population(items, result, {(11, 'source-pages')})


def mock_failed_operation(scratch):
    scratch.mkdir(parents=True)
    (scratch/'native.stdout').write_text('')
    err = scratch/'native.stderr'
    err.write_text('bwrap: example failure\n')
    raise ContractError(f'sandbox_failed; see {err}')


@pytest.mark.parametrize('codec', ('gorilla', 'pcodec'))
def test_anchor_failure_keeps_stderr_and_leaves_lanes_unrun(tmp_path, monkeypatch, codec):
    run, work = tmp_path/'run', tmp_path/'work'
    run.mkdir(); work.mkdir()
    route, adapter = ('append-resume', GORILLA) if codec == 'gorilla' else ('native-pages', PCODEC_PAGES)
    item = {'work_item_id': 'work', 'route': route}
    case = 'a'*64
    plan = {'measurement': {'population': {'work': {'adapter': adapter, 'case_id': case}}, 'environment': {'cpu': 0},
                            'gorilla': {'bindings': {'repair': {'runtime': {}}}}, 'pcodec_pages': {'runtime': {}}}}
    row = {'status': 'verified'}
    if codec == 'gorilla':
        monkeypatch.setattr(gorilla.original, '_case', lambda *a: {})
        monkeypatch.setattr(gorilla.original, '_stage', lambda *a: {})
        monkeypatch.setattr(gorilla.original, '_outputs', lambda *a: {})
        monkeypatch.setattr(gorilla, 'stage_recovery', lambda *a, **kw: None)
        monkeypatch.setattr(gorilla.original.clock, '_invoke', lambda *a: mock_failed_operation(a[-2]))
        doc = gorilla.measure(None, plan, item, {}, work, run, row)
        audit = gorilla.recompute
    else:
        monkeypatch.setattr(pages, '_case', lambda *a: ({}, 'native'))
        monkeypatch.setattr(pages, 'stage_recovery', lambda *a, **kw: None)
        monkeypatch.setattr(pages, '_anchors', lambda *a: mock_failed_operation(a[3]/'encode'))
        doc = pages.measure(None, plan, item, {}, run, work, row)
        audit = pages.recompute
    assert doc['status'] == 'measurement_failed' and doc['anchors'] is None and doc['summary'] is None
    assert len(doc['trials']) == (12 if codec == 'gorilla' else 8)
    assert {t['status'] for t in doc['trials']} == {'not_run_after_measurement_failure'}
    assert [x['path'].split('/')[-1] for x in doc['failure_logs']] == list(failure.NAMES)
    assert (run/doc['failure_logs'][1]['path']).read_text() == 'bwrap: example failure\n'
    assert str(work) not in doc['reason'] and doc['reason'].endswith(doc['failure_logs'][1]['path'])
    assert audit(None, plan, item, row, {}, run, doc, set()) is None
    changed = deepcopy(doc)
    changed['failure_logs'] = changed['failure_logs'][:1]
    with pytest.raises(ContractError, match='not retained'):
        audit(None, plan, item, row, {}, run, changed, set())
    (run/doc['failure_logs'][1]['path']).write_text('edited log\n')
    with pytest.raises(ContractError):
        audit(None, plan, item, row, {}, run, doc, set())


def test_failed_trial_log_is_bound_to_the_failed_direction(tmp_path):
    run, scratch = tmp_path/'run', tmp_path/'scratch'
    run.mkdir(); scratch.mkdir()
    for op in ('encode', 'decode'):
        stage = scratch/op
        stage.mkdir()
        (stage/'native.stdout').write_text(op)
        (stage/'native.stderr').write_text('operation failed')
    base = f'{pages.FAILED}/case'
    doc = {'status': 'measurement_failed', 'reason': 'operation failed',
           'failure_logs': failure.retain(run, base, 'trial', scratch, ('decode',)),
           'trials': [{'status': 'measured_as_declared', 'direction': 'encode'},
                      {'status': 'measurement_failed', 'direction': 'decode'}]}
    failure.check(run, base, doc, ('encode', 'decode'))
    doc['trials'][1]['direction'] = 'encode'
    with pytest.raises(ContractError, match='unexpected M3 failure log paths'):
        failure.check(run, base, doc, ('encode', 'decode'))
