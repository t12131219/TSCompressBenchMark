from copy import deepcopy
import os
from pathlib import Path

import pytest

from tsbench.application.m3_lzbench_workers import LANES, artifact, outcome, run_workers
from tsbench.assets import ContractError, load_json
from tsbench.planner.lzbench import worker_input
from tsbench.planner.m3_lzbench_workers import MINIMUM

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('codec',['zstd','xz'])
def test_matched_native_lanes_restore_all_and_only_xz_has_shared_worker_decode(codec,tmp_path):
    control=os.environ.get('TSBENCH_LZBENCH_CORPUS_WORKER_CONTROL')
    if not control:
        pytest.skip('requires the built worker corpus control')
    size=(MINIMUM[codec]+7)//8*8; rows=size//8
    source=tmp_path/'raw'; source.write_bytes(worker_input(codec,size)); identity=artifact(source)
    plan={'build':{'lzbench_workers':{'executable':{'path':control}}}}
    item={'route':codec+'-workers','dataset_id':'x','canonical_object_id':'x','work_item_id':'x','applicability':'input_domain_matches',
          'input':{'representation':'v_bytes_interleaved','full_extent_of_file_rows_and_value_columns':True,
                   'skipped_row_ranges':[],'value_column_range':[0,1], 'row_ranges':[{'partition':'full','start':0,'end':rows}],
                   'size_estimate':{'input_units':1,'native_input_bytes_one_pass':size}}}
    entry={'id':'x','rows':rows,'value_count':1,'canonical':{'object_id':'x','values_sha256':identity['sha256']}}
    got=run_workers(ROOT,plan,item,entry,{'paths':[source]},tmp_path,tmp_path)
    assert not got['unmet_worker_observations'] and set(got['retained'])==set(LANES[codec])
    assert got['source']==identity and not got['timing_admitted']
    assert [x['observed']['jobs']['worker_threads'] for x in got['encode'].values()]==([0,2] if codec=='zstd' else [0,1,2])
    if codec=='xz':
        assert [x['observed']['jobs']['worker_threads'] for x in got['decode_shared'].values()]==[0,1,2]
        altered=deepcopy(got); altered['decode_shared']['1']['source_frame']={'sha256':'0'*64,'bytes':1}
        with pytest.raises(ContractError,match='same frame'):
            outcome(altered)
    else:
        assert not got['decode_shared'] and all(x['observed']['jobs']['worker_threads']==0 for x in got['decode_own'].values())
    wrong=deepcopy(got); wrong['encode']['2']['observed']['jobs']['worker_threads']=1
    assert outcome(wrong)==['encode:2']


def _binding():
    from tsbench.planner.m3_lzbench_profiles import bind
    from tsbench.planner.m3_lzbench_workers import bind as worker_bind
    path=ROOT/'results/m3-real-r29-20261119/plan.json'
    if not path.is_file():
        pytest.skip('requires a local real-corpus plan and its native controls')
    p=load_json(path); build=load_json(ROOT/p['build']['lock']['path']); worker=worker_bind(ROOT,build)
    binding=bind(ROOT,build,p['obligations'],p['build']['zstd_dictionary'],worker)
    if binding is None:
        pytest.skip('requires the lzbench worker and feature controls')
    return p,build,worker,binding


def test_lzbench_profile_binding_checks_actual_work_condition():
    from tsbench.planner.m3_lzbench_profiles import bind
    p,build,worker,b=_binding()
    assert len(b['obligation_slots'])==13 and len(b['slots'])==3
    changed=deepcopy(p['obligations'])
    ob=next(r for r in changed if r['kind']=='conditional' and r['route']=='xz-workers')
    ob['condition_case']['criteria']['native_decoding_workers']=[0,0,0]
    with pytest.raises(ContractError,match='condition criteria'):
        bind(ROOT,build,changed,p['build']['zstd_dictionary'],worker)


@pytest.mark.skipif(os.environ.get('TSBENCH_M3_LZBENCH_ISOLATION')!='1',reason='requires Bubblewrap namespaces')
def test_profiles_isolated_main_ledger_and_replay(tmp_path):
    from tsbench.application.m3_lzbench_profiles import audit_specialized,run_specialized
    p,_,_,b=_binding()
    rows=[{k:r[k] for k in ('selection','route','kind','check','obligation_id')} for r in p['obligations'] if r['obligation_id'] in b['obligation_slots']]
    ledger=[]
    got=run_specialized(ROOT,tmp_path,b,rows,ledger.append)
    assert [(r['route'],r['reason']) for r in rows if r['status']!='verified']==[]
    assert len(ledger)==3 and {r['selection'] for r in ledger}=={39,40}
    checked=audit_specialized(tmp_path,b,rows,got,replay=True)
    assert checked['verified_obligations']==13 and len(checked['replayed'])==3
    assert not list(tmp_path.rglob('completion.json'))
