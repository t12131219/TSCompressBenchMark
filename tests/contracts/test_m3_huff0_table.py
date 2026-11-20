from copy import deepcopy
from pathlib import Path

import pytest

from tsbench.application.m3_huff0_table import run_table
from tsbench.assets import ContractError, load_json, verify_asset
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.m3_huff0_table import KEY, bind, inputs

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def fixture():
    p=ROOT/'results/m3-real-r30-20261119/plan.json'
    if not p.is_file():
        pytest.skip('requires a local frozen real-corpus plan')
    doc=load_json(p)
    control=bind(ROOT,load_json(ROOT/doc['build']['lock']['path']))
    if control is None:
        pytest.skip('build tsbench_huff0_corpus_table_control first')
    assets=load_json(ROOT/doc['definition']['plan']['path'])['bindings']['manifest']
    ids={e['id']:e for e in load_full_manifest(ROOT,assets,parse=False)['datasets']}
    return {'build':{'huff0_table':control}},ids,{i['dataset_id']:i for i in doc['work_items'] if (i['selection'],i['route'])==KEY}


@pytest.mark.parametrize('name,blocks',[('etth1',6),('economics-17',1)])
def test_real_reused_table_and_independent_restore(fixture,tmp_path,name,blocks):
    p,assets,items=fixture
    result=run_table(ROOT,p,items[name],assets[name],tmp_path,tmp_path)
    assert result['errors']==[] and set(result['profiles'])=={'1','4'}
    for k,v in result['profiles'].items():
        assert v['encode']==v['decode'] and v['encode']['context_count']==1 and v['encode']['streams']==int(k)
        assert len(v['blocks'])==blocks and v['recovered']==result['holdout']
        assert v['complete_bytes']==sum(v[part]['bytes'] for part in ('model','frame','binding'))
        assert not v['different_valid_model_binding_rejection']['native_decode_started']
        assert all(verify_asset(tmp_path,r).is_file() for r in v['retained'].values())


def test_wrong_partition_stops_before_native_training(fixture):
    _,assets,items=fixture
    bad=deepcopy(items['etth1']); bad['input']['training']['evaluation']['absolute_rows'][0]-=1
    with pytest.raises(ContractError,match='holdout identities'):
        inputs(bad,assets['etth1'])
