"""Small real NumPy recovery check against preserved old and fixed helpers.

No native codec, benchmark, source oracle, or giant old case is executed.
"""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib.util
import json
import math
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
OLD=OUT/'before/source_snapshot/src/tscompbench/adapters/byte_container.py'
NEW=ROOT/'src/tscompbench/adapters/byte_container.py'
rows=256
empty_count=125
raw_bits=np.resize(np.array([0x8000000000000000,0,0x7ff8000000000001,0x3ff0000000000000],dtype='<u8'),(rows,2))
values=raw_bits.view('<f8')
tags=np.arange(rows,dtype='|u1').reshape(rows,1)
validity=(np.arange(rows)%2==0).reshape(rows,1)
arrays=[np.empty((rows,0,3),dtype='<f8') for _ in range(empty_count)]+[values,tags,validity]
names=[f'empty-{index}' for index in range(empty_count)]+['values','tags','validity']
descriptors=[{'name':name,'dtype':array.dtype.str,'shape':list(array.shape),'payload_bytes':array.nbytes,'logical_bits':array.size if name=='validity' else array.nbytes*8} for name,array in zip(names,arrays)]
header={'buffers':descriptors,'payload_layout':'BLOCK_MAJOR_BUFFER_ORDER','stream_block_size':1}
payload=b''.join(array[row:row+1].tobytes() for row in range(rows) for array in arrays[-3:])
counts={}
outputs={}
for label,path in [('before',OLD),('fixed',NEW)]:
    spec=importlib.util.spec_from_file_location('isolated_byte_helper_'+label,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    counts[label]=0
    def prod(value,*,_label=label):
        counts[_label]+=1
        return math.prod(value)
    module.math=SimpleNamespace(prod=prod)
    decoded=module.decode_byte_payload(header,memoryview(payload))
    outputs[label]=[{'name':buffer.name,'dtype':buffer.array.dtype.str,'shape':list(buffer.array.shape),'logical_bits':buffer.logical_bits,'readonly':not buffer.array.flags.writeable,'owned':buffer.array.flags.owndata or buffer.array.base is not None,'bytes_sha256':hashlib.sha256(buffer.array.tobytes()).hexdigest()} for buffer in decoded.buffers]
    assert len(decoded.buffers)==len(arrays)
    for expected,actual in zip(arrays,decoded.buffers):
        assert expected.dtype==actual.array.dtype and expected.shape==actual.array.shape
        assert expected.tobytes()==actual.array.tobytes()
        assert not actual.array.flags.writeable
assert outputs['before']==outputs['fixed']
assert counts['before']==2*len(arrays)+rows*len(arrays)
assert counts['fixed']==3*len(arrays)
result={'status':'PASS_FIXED_MIXED_ZERO_REAL_HELPER_RECOVERY_AND_BOUNDED_WORK','scope':'SMALL_REAL_NUMPY_HELPER_NO_CODEC_NATIVE_OR_SOURCE_EXECUTION','rows':rows,'buffer_count':len(arrays),'empty_buffer_count':empty_count,'payload_bytes':len(payload),'math_prod_calls':counts,'outputs_exactly_equal':outputs['before']==outputs['fixed'],'ieee_raw_bits_validity_and_empty_shapes_preserved':True,'all_outputs_readonly':True,'before_source_sha256':hashlib.sha256(OLD.read_bytes()).hexdigest(),'fixed_source_sha256':hashlib.sha256(NEW.read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
fixed=OUT/'fixed'
fixed.mkdir(exist_ok=True)
(fixed/'mixed_zero_helper_review.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
