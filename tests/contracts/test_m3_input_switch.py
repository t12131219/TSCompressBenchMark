"""The supplemental scope cannot disguise the original full denominator or recycle data."""
from copy import deepcopy
from pathlib import Path

import pytest

from tsbench.assets import ContractError, load_json
from tsbench.contracts import load_contract
from tsbench.planner.m3_input_switch import MODE, _novelty

ROOT = Path(__file__).resolve().parents[2]


def entry(tag):
    return {'id':tag,'source_cluster':tag,'file':{'sha256':tag},
            'canonical':{'object_id':tag,'values_sha256':tag},
            'partitions':[{'canonical':{'object_id':tag+'-partition','values_sha256':tag+'-partition'}}]}


def test_input_switch_novelty_checks_values_independently_of_schema_and_axis():
    old, new = entry('original'), entry('replacement')
    _novelty([new],[old])
    for key in ('id','source_cluster','file','canonical','partitions'):
        changed = deepcopy(new)
        changed[key] = old[key]
        with pytest.raises(ContractError,match='reuses a known input'):
            _novelty([changed],[old])
    new['partitions'][0]['canonical']['values_sha256'] = old['canonical']['values_sha256']
    with pytest.raises(ContractError,match='reuses a known input'):
        _novelty([new],[old])


def test_run_contract_distinguishes_original_denominator_and_supplement():
    run = {'schema':'bmk.m3-real-corpus-run/1','run_id':'0'*32,'plan_content_id':'1'*64,'stage_accepted':False,
           'qualification_granted':False,'timing_admitted':False,'partial_preflight':False,'planned_work_items':36,
           'selected_work_items':33,'statuses':{'verified':33},'rows':[{}],
           'artifact_retention':'verified_then_released_after_hash_and_size','execution_policy':{'input_scope':MODE},'obligations':[]}
    contract = load_contract(ROOT,'m3-real-corpus-run')
    contract.validate(run,'supplement')
    for invalid in ({**run,'execution_policy':{}}, {**run,'obligations':[{}]}):
        with pytest.raises(ContractError):
            contract.validate(invalid,'invalid supplement')
    contract.validate({**run,'planned_work_items':828,'execution_policy':{}},'previous full run')
