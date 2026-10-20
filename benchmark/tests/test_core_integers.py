"""Direct integer paths: whole output, exact source bytes and fresh decoder.

Short correctness checks, not performance samples. Use explicit installed builds.
"""
from pathlib import Path
import numpy as np
import pytest
from tsbench import native
from tsbench.build import artifact_path
from tsbench.config import DEFAULT_TASK, DEFAULT_EXECUTION, DEFAULT_PROFILE
from tsbench.data import TimeSeriesObject
from tsbench.registry import Registry
ROOT=Path(__file__).resolve().parents[2]
KEYS=('sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman',
      'simdcomp-u32','neats-lossless-i64','leats-lossless-i64')

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('mode',['prepared','fresh_request'])
def test_direct_integer_whole_output_and_independent_decoder(key,mode,tmp_path):
    path=artifact_path(ROOT,key)
    if not path.is_file():pytest.skip('build codec first: '+key)
    dtype='<u4' if key=='simdcomp-u32' else '<i8' if key.startswith(('neats','leats')) else '|u1'
    a=(np.arange(257)%73).astype(dtype)
    obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}})
    method={'codec':key,'id':key,'params':Registry(ROOT).resolve_params(key)}
    task={**DEFAULT_TASK,'boundary':'native_core','lifecycle':mode}
    execution={**DEFAULT_EXECUTION,'native_loops':2,'native_warmup_loops':1,'timeout_s':60}
    support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench')
    assert support['supported'],support
    handle=native.NativeMeasurement(method,task,execution,support,ROOT,ROOT/'build/tsbench')
    handle.prepare(obj)
    row,_=handle.measure(obj,independent=True,artifact_dir=tmp_path)
    assert row['status']=='ok' and row['independent_recovery']['passed']
    assert row['verification']['validated_operations']==3
    assert row['codec_input_bytes']==row['raw_bytes']==a.nbytes
    assert row['native_input']['content_sha256']==__import__('hashlib').sha256(a.tobytes()).hexdigest()
    assert row['codec_complete_bytes']==len(Path(row['artifact_path']).read_bytes())
    assert row['native_batch']['abi']=='core' and not row['native_batch']['native_api_internal_work_included']
    assert all(x['verification']['passed'] for x in row['native_products'])
    payload=Path(row['artifact_path']).read_bytes()
    assert payload[:4] not in (b'TSI1',b'TSF1',b'SBP1',b'NTI1')

@pytest.mark.parametrize('key',['sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman'])
@pytest.mark.parametrize('dtype',['<i2','<u2'])
def test_sprintz_exact_odd_byte_tail_typed_multichannel(key,dtype,tmp_path):
    if not artifact_path(ROOT,key).is_file():pytest.skip('build codec first')
    a=(np.arange(259*3).reshape(259,3)*7%257).astype(dtype)
    obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}})
    method={'codec':key,'id':key,'params':Registry(ROOT).resolve_params(key)}
    task=dict(DEFAULT_TASK);execution={**DEFAULT_EXECUTION,'native_loops':1,'native_warmup_loops':0}
    support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench')
    assert support['supported'],support
    h=native.NativeMeasurement(method,task,execution,support,ROOT,ROOT/'build/tsbench');h.prepare(obj)
    row,_=h.measure(obj,independent=True,artifact_dir=tmp_path)
    assert row['status']=='ok' and row['codec_input_bytes']==a.nbytes
