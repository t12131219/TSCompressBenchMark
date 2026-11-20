import os
from pathlib import Path
import random

import pytest

from tsbench.application.m3_lzbench_session import invoke
from tsbench.assets import ContractError
from tsbench.planner.m3_lzbench_session import INPUT_SPAN, OUTPUT_SPAN, input_size


@pytest.fixture
def control():
    exe = os.environ.get('TSBENCH_LZBENCH_CORPUS_SESSION_CONTROL')
    if not exe:
        pytest.skip('requires the built lzbench whole-object session control')
    return Path(exe).resolve(strict=True)


@pytest.mark.parametrize('codec', ['zstd','xz'])
def test_native_backpressure_finish_and_independent_restore(control,tmp_path,codec):
    data = random.Random(141).randbytes(136013)
    raw, wire, decoded = (tmp_path/p for p in ('input','frame','output'))
    raw.write_bytes(data)
    enc = invoke(control,codec,'encode',raw,wire,len(data)+65536)
    assert enc['full_output_calls'] and enc['zero_input_finish_calls'] and enc['first_output_bytes'] <= OUTPUT_SPAN
    raw.unlink()
    dec = invoke(control,codec,'decode',wire,decoded,len(data))
    assert decoded.read_bytes()==data
    assert enc['calls'] >= (len(data)+INPUT_SPAN-1)//INPUT_SPAN and dec['finish_calls']
    encoded = wire.read_bytes()
    for altered, cap in [(encoded[:-1],len(data)), (encoded+b'extra',len(data)), (encoded,len(data)-1)]:
        wire.write_bytes(altered)
        with pytest.raises(ContractError, match='lzbench .* decode:'):
            invoke(control,codec,'decode',wire,decoded,cap)


def test_full_interleaved_extent_not_a_session_per_block_or_column():
    entry = {'id':'new','rows':3103,'value_count':7,'canonical':{'object_id':'unique-v'}}
    size = 3103 * 7 * 8
    item = {'dataset_id':'new','canonical_object_id':'unique-v','applicability':'input_domain_matches',
            'input':{'representation':'v_bytes_interleaved','full_extent_of_file_rows_and_value_columns':True,
                     'skipped_row_ranges':[],'value_column_range':[0,7],
                     'row_ranges':[{'partition':'full','start':0,'end':3103}],
                     'size_estimate':{'input_units':1,'native_input_bytes_one_pass':size}}}
    assert input_size(item,entry)==size
    item['input']['size_estimate']['input_units']=2
    with pytest.raises(ContractError,match='one complete'):
        input_size(item,entry)


@pytest.fixture
def frozen():
    from tsbench.assets import load_json

    root = Path(__file__).resolve().parents[2]
    path = root/'results/m3-real-r27-20261119/plan.json'
    if not path.is_file():
        pytest.skip('requires a local r27 whole-object session development plan')
    plan = load_json(path)
    build = load_json(root/plan['build']['lock']['path'])
    return root,plan,build


def test_named_session_checks_reject_a_mismatched_case(frozen):
    from copy import deepcopy
    from tsbench.planner.m3_lzbench_specialized import bind

    root,plan,build = frozen
    binding = bind(root,build,plan['obligations'],plan['build']['lzbench_session'])
    assert len(binding['slots'])==2 and len(binding['obligation_slots'])==10
    bad = deepcopy(plan['obligations'])
    row = next(r for r in bad if r['route']=='zstd-session')
    row['planned_case_inputs'][0]['case_name'] += '-wrong'
    with pytest.raises(ContractError,match='named case'):
        bind(root,build,bad,plan['build']['lzbench_session'])


@pytest.mark.skipif(os.environ.get('TSBENCH_M3_LZBENCH_ISOLATION')!='1',reason='requires Bubblewrap namespaces')
def test_specialized_session_lifecycle_and_independent_replay(frozen,tmp_path):
    from tsbench.application.m3_lzbench_specialized import audit_specialized, run_specialized
    from tsbench.planner.m3_lzbench_specialized import bind

    root,plan,build = frozen
    binding = bind(root,build,plan['obligations'],plan['build']['lzbench_session'])
    rows = [{k:r[k] for k in ('selection','route','check','obligation_id','kind')} for r in plan['obligations']
            if r['obligation_id'] in binding['obligation_slots']]
    ledger = []
    evidence = run_specialized(root,tmp_path,binding,rows,ledger.append)
    assert [(r['route'],r['check'],r['reason']) for r in rows if r['status']!='verified']==[]
    assert evidence['statuses']=={'verified':2} and len(ledger)==2 and {r['selection'] for r in ledger}=={39,40}
    audited = audit_specialized(tmp_path,binding,rows,evidence,replay=True)
    assert audited['verified_obligations']==10 and len(audited['replayed'])==2
    assert not list(tmp_path.rglob('completion.json'))
