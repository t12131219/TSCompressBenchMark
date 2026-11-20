"""The real route uses both frozen tiers, the actual selected trainer and sealed frames."""
from copy import deepcopy
from pathlib import Path

import pytest

from tsbench.application.m3_zstd_dictionary import run_dictionary
from tsbench.assets import ContractError, load_json, verify_asset
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.m3_zstd_dictionary import KEY, LIMIT, bind, extents

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def inputs():
    path = ROOT/'results/m3-real-r27-20261119/plan.json'
    if not path.is_file():
        pytest.skip('requires the local M3 development plan and native controls')
    plan = load_json(path); build = load_json(ROOT/plan['build']['lock']['path'])
    control = bind(ROOT,build)
    if not control:
        pytest.skip('build tsbench_lzbench_feature_control first')
    manifest = load_json(ROOT/plan['definition']['plan']['path'])['bindings']['manifest']
    entries = {e['id']:e for e in load_full_manifest(ROOT,manifest,parse=False)['datasets']}
    items = {item['dataset_id']:item for item in plan['work_items'] if (item['selection'],item['route'])==KEY}
    return {'build':{'zstd_dictionary':control}},entries,items


@pytest.mark.parametrize('data_id,tier', [('etth1','standard'),('economics-17','short')])
def test_real_tier_independent_frames_and_dictionary_rejections(inputs,tmp_path,data_id,tier):
    plan,entries,items = inputs
    work,run = tmp_path/'work',tmp_path/'run'; work.mkdir(); run.mkdir()
    proof = run_dictionary(ROOT,plan,items[data_id],entries[data_id],work,run)
    assert proof['tier']==tier and not proof['failed_units'] and not proof['fallback_used']
    assert proof['holdout']=={'bytes':sum(f['logical_bytes'] for f in proof['frames']),
                              'sha256':entries[data_id]['partitions'][2]['canonical']['values_sha256']}
    assert all(0 < f['logical_bytes'] <= LIMIT and f['input_sha256']==f['restored_sha256'] for f in proof['frames'])
    assert proof['verified_frame_bytes_plus_shared_dictionary_once']==proof['verified_frame_bytes']+proof['dictionary']['bytes']
    assert {r['status'] for r in proof['negative_controls'].values()}=={'expected_rejection'}
    assert all(verify_asset(run,proof[k]).is_file() for k in ('retained_frame','dictionary'))
    if tier=='standard':
        assert len(proof['frames'])>1


def test_changed_holdout_or_tier_rejected_before_training(inputs):
    _,entries,items = inputs
    item = deepcopy(items['etth1'])
    item['input']['training']['evaluation']['absolute_rows'][0]-=1
    with pytest.raises(ContractError, match='frozen input'):
        extents(item,entries['etth1'])
