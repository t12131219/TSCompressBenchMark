from collections import Counter
from copy import deepcopy

import pytest

from tsbench.application import m3_in_run_zstd_dictionary as adapter, m3_primary_measurement_v9 as observer
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v9 import DICTIONARY, population


def test_dictionary_population_preserves_unmatched_routes_and_conditions():
    items = [{'work_item_id': f'w{n}', 'selection': 40, 'route': route,
              'operation_config_id': f'operation{n}', 'applicability': status}
             for n, (route, status) in enumerate((('zstd-dictionary','input_domain_matches'),
                                                    ('zstd-session','input_domain_matches'),
                                                    ('zstd-dictionary','condition_not_triggered')))]
    unavailable = 'measurement_adapter_not_integrated'
    base = {'w0': {'status': unavailable}, 'w1': {'status': unavailable},
            'w2': {'status': 'condition_not_triggered'}}
    pop = population(items, base)
    assert pop['w0'] == {'status':'scheduled','adapter':DICTIONARY,'case_id':pop['w0']['case_id']}
    assert pop['w1'] == base['w1'] and pop['w2'] == base['w2'] and base['w0']['status'] == unavailable
    assert population(items[::-1],base) == pop
    with pytest.raises(ContractError,match='overlapping'):
        population(items,pop)
    row = {'status':'quality_rejected'}
    out = observer.observe(None,{'measurement':{'population':pop}},items[0],None,None,None,row)
    assert out == {**pop['w0'],'status':'functional_dependency_not_verified','reason':'quality_rejected',
                   'trials':[],'timing_admitted':False}


def test_dictionary_trial_schedule_has_one_warmup_and_three_measurements_per_op():
    slots = list(adapter._schedule('case'))
    ops = ('train','encode','decode')
    assert Counter((t['phase'],t['op']) for t in slots) == {(p,op):n for p,n in [('warmup',1),('measured',3)] for op in ops}
    assert all({t['op'] for t in slots[i:i+3]} == set(ops) for i in range(0,12,3))
    assert len({t['path'] for t in slots}) == 12 and slots == list(adapter._schedule('case'))


def test_dictionary_train_failure_preserves_actual_logs_and_never_counts_unrun_work(tmp_path, monkeypatch):
    item = {'work_item_id':'candidate'}; cid = 'case'; row = {'status':'verified'}
    frozen = {'status':'scheduled','adapter':DICTIONARY,'case_id':cid}
    plan = {'measurement':{'population':{'candidate':frozen}}}
    monkeypatch.setattr(adapter,'_case',lambda *args:{'anchor':{}})
    scratch = tmp_path/'scratch'; scratch.mkdir()
    (scratch/'native.stdout').write_bytes(b'')
    (scratch/'native.stderr').write_text('trainer terminated\n')
    trials = [{**slot,'status':'not_run_after_measurement_failure','reason':'setup failed'} for slot in adapter._schedule(cid)]
    anchors_failed = {**frozen,'status':'measurement_failed','anchors':None,'reason':'setup failed',
                      'timing_admitted':False,'trials':trials,'failure_logs':[]}
    assert adapter.recompute(None,plan,item,None,tmp_path,row,anchors_failed,set()) is None
    bad = deepcopy(anchors_failed); bad['trials'].pop()
    with pytest.raises(ContractError,match='denominator'):
        adapter.recompute(None,plan,item,None,tmp_path,row,bad,set())
    bad = deepcopy(anchors_failed); bad['trials'][0]['status'] = 'measurement_failed'
    with pytest.raises(ContractError,match='trial terminal'):
        adapter.recompute(None,plan,item,None,tmp_path,row,bad,set())
    refs = adapter._retain(tmp_path,cid,'trial',[('train',scratch)])
    doc = {'status':'measurement_failed','reason':f"trainer failed; see {tmp_path/refs[1]['path']}",
           'trials':[{'direction':'train','status':'measurement_failed'}],'failure_logs':refs}
    adapter.failure.check(tmp_path,f'{adapter.FAILED}/{cid}',doc,('train','encode','decode'))
    (tmp_path/refs[1]['path']).write_text('not the original stderr\n')
    with pytest.raises(ContractError,match='SHA-256 mismatch'):
        adapter.failure.check(tmp_path,f'{adapter.FAILED}/{cid}',doc,('train','encode','decode'))


def test_dictionary_anchor_initializes_scratch_before_preparing_dictionary(tmp_path, monkeypatch):
    run = tmp_path/'run'; run.mkdir()
    work = tmp_path/'work'; work.mkdir()
    dictionary = run/'functional-dict'; dictionary.write_bytes(b'verified dictionary')
    monkeypatch.setattr(adapter.timing,'_file',lambda root, ref: dictionary)
    def check(_ref, path):
        assert path == work/'anchor'/'fixed'/'shared.zdict'
        assert path.read_bytes() == dictionary.read_bytes()
        raise ContractError('stop before launching a native operation')
    monkeypatch.setattr(adapter.timing,'_dict_facts',check)
    case = {'anchor':{'dictionary':{},'holdout':{'bytes':8}}}
    with pytest.raises(ContractError,match='stop before launching'):
        adapter._fixed(None,run,work,None,case,None)
    assert list(run.iterdir()) == [dictionary]
