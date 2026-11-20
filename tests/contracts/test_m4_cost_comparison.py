"""Cross-stage joins reject identities that happen to have identical byte counts."""
from copy import deepcopy

import pytest

from tsbench.application import m4_cost_comparison as cost
from tsbench.application.m4_cost_comparison import _batch_summary, match_batch, match_zstd
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError


def test_zstd_match_checks_fixed_frame_and_workers_and_library():
    raw = {'bytes':64,'sha256':'raw'}
    frame = {'bytes':10,'sha256':'frame'}
    config = {'encode':{'workers':2},'decode':{'workers':0},'jobs':{'worker_threads':2,'jobs':17},
              'span_bytes':{'encode':[262139,65521],'decode':[1<<20,131071]}}
    common = dict(dataset_id='weather', route='zstd-workers', work_item_id='unique', operation_config_id='config')
    case = {**common,'canonical_object_id':'V','geometry':{'byte_range':[0,64]},'original':{'raw':raw},
            'expected_m3_frame':frame,'native_config':config}
    timed = {**common,'codec':'zstd','scope':[{'object_id':'V','start':0,'partition':'full'}], 'source':raw,
             'variants':{'2':{'frame':frame,'decode_anchor':'2','expected':{
                'encode':{'effective_parameters':config['encode'],'jobs':config['jobs']},
                'decode':{'effective_parameters':config['decode'],'jobs':{'worker_threads':0}}}}}}
    name='liblzbench_native.so'
    pristine = {name:{'bytes':20,'sha256':'binary'}}
    plan = {'runtime':{'files':{'lib/'+name:pristine[name]}}}
    match_zstd(case,timed,pristine,plan)
    bad = deepcopy(timed)
    bad['variants']['2']['decode_anchor']='0'
    with pytest.raises(ContractError,match='fixed frame'):
        match_zstd(case,bad,pristine,plan)
    bad = deepcopy(timed)
    bad['variants']['2']['expected']['encode']['jobs']['jobs']=18
    with pytest.raises(ContractError,match='span profile'):
        match_zstd(case,bad,pristine,plan)
    with pytest.raises(ContractError,match='binary differs'):
        match_zstd(case,timed,{name:{'bytes':20,'sha256':'other'}},plan)


def test_opaque_match_preserves_geometry_schema_and_configuration():
    common = dict(dataset_id='ettm1', route='xz-baseline', work_item_id='unique', operation_config_id='config',
                  canonical_object_id='source', geometry={'byte_range':[0,64]}, original={'raw':'raw','schema':'schema'},
                  plugin='xz-baseline', view='v_bytes_interleaved')
    cfg = {'encode':{'preset':6},'decode':{'threads':1}}
    case = {**common,'native_config':cfg,'expected_m3_frame':{'bytes':16,'sha256':'frame'}}
    timed = {**common,'expected_native':cfg,'frame':{**case['expected_m3_frame'],'path':'path'}}
    name='liblzbench_native.so'
    pristine = {name:{'bytes':20,'sha256':'binary'}}
    plan = {'physical_build':{'xz-baseline':{'project_runtime_assets':{'lib/'+name:pristine[name]}}}}
    match_batch('xz-opaque',case,timed,pristine,plan)
    changed = {**timed,'geometry':{'byte_range':[64,128]}}
    with pytest.raises(ContractError,match='range/schema'):
        match_batch('xz-opaque',case,changed,pristine,plan)


def test_per_loop_costs_preserve_signed_pair_deltas_and_independent_population():
    rounds = [{'round':1,'loops':8,'directions':{'encode':{'linked_entry':48,'dlopen':32},'decode':{'linked_entry':20,'dlopen':28}}}]
    cold = {'group_id':'g1','lifecycle':'cold','matched_rounds':rounds,'lanes':{}}
    steady = {**cold,'group_id':'g2','lifecycle':'steady'}
    result = _batch_summary([cold,steady],1)
    expect = {'independent_rounds':1,'min_ns':-2,'median_ns':-2,'max_ns':-2}
    assert result['cold']['directions']['encode']['dlopen_minus_linked_per_operation'] == expect
    with pytest.raises(ContractError,match='missing pair'):
        _batch_summary([cold,steady],2)


@pytest.mark.parametrize('declared', [None, {'path':'functional', 'ledger_bytes':42, 'sealed':False}])
def test_overlap_only_describes_sealed_observations(declared):
    raw = {'before':{'overlap':declared}, 'after':{'overlap':declared}}
    policy = cost._overlap_policy(raw)
    assert policy['declared_functional_overlap'] == (declared is not None)
    assert policy['sealed_snapshots'] == {'before':declared, 'after':declared}
    assert policy['host_exclusivity_established'] is False


def test_multiscale_link_checks_exact_profile_and_replays_seals(tmp_path, monkeypatch):
    def seal(name):
        run = tmp_path / name
        run.mkdir()
        write_new(run / 'completion.json', {'name':name})
        return cost.reference(tmp_path, run / 'completion.json')

    seals = {tag:seal(tag) for tag in ('native', 'multiscale_abi', 'profile')}
    write_new(tmp_path / 'multiscale_abi' / 'report.json', {'data':'published'})
    expected = {'schema':cost.MULTISCALE_SCHEMA, 'seals':seals, 'scale_regimes':['small'], 'audit_id':'matched'}
    profile_run = tmp_path / 'profile'

    def replay(root, native_run, abi_run, profile_path):
        assert (root, native_run, abi_run, profile_path) == (tmp_path, tmp_path / 'native', tmp_path / 'multiscale_abi', profile_run)
        return expected, {'trials':14, 'pairs':{'case':{}}, 'policy':{'scope':'test'}}

    monkeypatch.setattr(cost, '_replay_multiscale', replay)
    link = tmp_path / 'link.json'
    write_new(link, expected)
    result = cost._bind_multiscale(tmp_path, link, profile_run, seals['profile'])
    assert result['abi_verified_direction_trials'] == 14
    assert result['paired_groups'] == 1
    assert result['abi_report']['path'] == 'multiscale_abi/report.json'

    with pytest.raises(ContractError, match='different profile seal'):
        cost._bind_multiscale(tmp_path, link, profile_run, seal('other'))
    changed = tmp_path / 'changed.json'
    write_new(changed, {**expected, 'scale_regimes':['unverified']})
    with pytest.raises(ContractError, match='differs from recomputation'):
        cost._bind_multiscale(tmp_path, changed, profile_run, seals['profile'])
