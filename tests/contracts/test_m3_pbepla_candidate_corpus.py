"""Packed candidate products must belong to the operation and exact input."""
from io import BytesIO
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from m3_pbepla_candidate_corpus import Operations, identity
from tsbench.assets import ContractError


def replay(pack=b'one', offset=0, input_bytes=b'pbep'):
    record = {'lane':'candidate','mode':'restore-batch','layer':1,
              'process':{'status':'completed','returncode':0,'operation':'restore-batch','pid':123,'session_id':'a',
                         'input_mounts':{'0-1':identity(input_bytes)}},
              'native':[{'status':'restored','index':0,'layer':1}],
              'products':{'0-1':{'offset':offset,**identity(b'one')}}}
    return Operations(None,None,BytesIO(pack),None,[record],set())


def test_pack_reads_bound_products_in_order():
    replayed = replay()
    out, obs = replayed.invoke('candidate','restore-batch',{'0-1':b'pbep'},1)
    assert out=={'0-1':b'one'} and obs['0-1']['status']=='restored' and replayed.pack.tell()==3


@pytest.mark.parametrize(('kwargs','reason'), (({'offset':1},'gapped'),({'pack':b'two'},'digest'),({'input_bytes':b'alt'},'input or terminal')))
def test_pack_mismatches_do_not_become_success(kwargs,reason):
    with pytest.raises(ContractError,match=reason):
        replay(**kwargs).invoke('candidate','restore-batch',{'0-1':b'pbep'},1)
