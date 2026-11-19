#!/usr/bin/env python3
"""ZFP field baseline, measured worker participation, and compressed-array lifecycle."""
from contextlib import contextmanager
import ctypes as c
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest, load_json
from tsbench.planner.zfp import (ARRAY_REJECTIONS, BATCH_WIRE_REJECTIONS, FIELD_REJECTIONS, HEADER, MAGIC, PLUGIN, WEATHER,
                                 array_input, array_metadata, batch_inputs, field_input, field_layout, field_metadata,
                                 plan_zfp, ref, retained_paths, values as typed_values)
from tsbench.runtime import create_build_lock, resolve_worker

TYPES = {'i32': (5,1,c.c_int32), 'i64': (7,2,c.c_int64), 'f32': (9,3,c.c_float), 'f64': (10,4,c.c_double)}
MODES = {'reversible': 0,'rate': 1,'precision': 2,'accuracy': 3}
PTR, SIZE, INT = c.c_void_p, c.c_size_t, c.c_int
PP, PS = c.POINTER(PTR), c.POINTER(SIZE)


class Config(c.Structure):
    _fields_ = [('type', INT), ('dims', c.c_uint), ('size', SIZE*4), ('mode', INT), ('parameter', c.c_double)]


class Options(c.Structure):
    _fields_ = [('execution', INT), ('threads', c.c_uint), ('chunk_size', c.c_uint), ('stride', c.c_ssize_t*4)]


class Info(c.Structure):
    _fields_ = [('config', Config), ('options', Options), ('effective_parameter', c.c_double), ('logical_bytes', SIZE),
                ('min_offset', c.c_ssize_t), ('max_offset', c.c_ssize_t), ('openmp_built', INT), ('omp_dynamic', INT),
                ('omp_thread_limit', INT), ('decode_execution', INT)]


def config(dtype, shape, mode='reversible', param=0):
    return Config(TYPES[dtype][1],len(shape),(SIZE*4)(*shape,*([1]*(4-len(shape)))),MODES[mode],param)


def sha(data):
    return ref('',data)['sha256']


class Native:
    def __init__(self, library):
        lib = c.CDLL(str(library))
        self.statuses = {}
        def bind(name, sig, result=INT):
            f = getattr(lib,'zn_'+name)
            f.argtypes, f.restype = sig,result
            setattr(self,name,f)
        pc, po, pi = (c.POINTER(x) for x in (Config,Options,Info))
        bind('config_1d',[INT,SIZE],Config)
        bind('create',[pc,PP]); bind('create_ex',[pc,po,PP]); bind('destroy',[PTR],None)
        bind('get_info',[PTR,pi]); bind('data',[PTR],PTR); bind('capacity',[PTR],SIZE)
        bind('encode',[PTR,PTR,SIZE,PS]); bind('decode',[PTR,PTR,SIZE,PTR,SIZE])
        bind('encode_field',[PTR,PTR,SIZE,SIZE,PS]); bind('decode_field',[PTR,PTR,SIZE,PTR,SIZE,SIZE])
        bind('array_create',[pc,PTR,SIZE,PP]); bind('array_import',[pc,PTR,SIZE,PP]); bind('array_destroy',[PTR],None)
        bind('array_count',[PTR],SIZE); bind('array_compressed_size',[PTR],SIZE); bind('array_rate',[PTR],c.c_double)
        bind('array_set',[PTR,SIZE,PTR]); bind('array_get',[PTR,SIZE,PTR]); bind('array_set_range',[PTR,SIZE,SIZE,PTR,SIZE])
        bind('array_get_range',[PTR,SIZE,SIZE,PTR,SIZE]); bind('array_export',[PTR,PTR,SIZE,PS]); bind('array_flush',[PTR])
        bind('array_cache_size',[PTR],SIZE); bind('array_flush_cache',[PTR]); bind('array_set_cache_size',[PTR,SIZE])
        bind('backend_info',[],c.c_char_p); bind('cuda_built',[]); bind('cuda_available',[]); bind('cuda_runtime_available',[])

    def expect(self, name, actual, expected):
        assert actual == expected, (name, actual, expected)
        if name:
            self.statuses[name] = actual
        return actual

    @contextmanager
    def handle(self, create, free, *args, status=0, name=None):
        p = PTR()
        try:
            actual = create(*args,c.byref(p))
            self.expect(name,actual,status)
            assert bool(p) == (status == 0), (create.__name__, actual, status)
            yield p
        finally:
            free(p)

    def legacy(self,dtype,kind,raw):
        t = TYPES[dtype][2]
        n = len(raw)//c.sizeof(t)
        cfg = self.config_1d(kind,n)
        vals, out = (t*n).from_buffer_copy(raw),(t*n)()
        with self.handle(self.create,self.destroy,c.byref(cfg)) as p:
            used = SIZE()
            assert self.encode(p,vals,len(raw),c.byref(used)) == 0
            assert 0 < used.value <= self.capacity(p) and used.value % 8 == 0
            wire = c.string_at(self.data(p),used.value)
        with self.handle(self.create,self.destroy,c.byref(cfg)) as p:
            assert self.decode(p,wire,len(wire),out,len(raw)) == 0 and bytes(out) == raw
        return wire

    def original_field(self,root,lib,req,real):
        dtype, shape, mode = req['type'], req['shape'], req['mode']
        cfg = config(dtype,shape,mode,req['requested'])
        t = TYPES[dtype][2]
        layout = field_layout(req)
        stride,origin,at = (layout[k] for k in ('strides','origin','offsets'))
        span = t*layout['span_count']
        input = span(*([-8191]*span._length_))
        raw = field_input(req,real)
        for i,v in zip(at,typed_values(dtype,raw),strict=True):
            input[i] = v
        source = [input[i] for i in at]
        opts = Options(0,1,0,(c.c_ssize_t*4)(*req['strides']))
        with self.handle(self.create_ex,self.destroy,c.byref(cfg),c.byref(opts)) as p:
            info, used = Info(),SIZE()
            assert self.get_info(p,c.byref(info)) == 0
            assert list(info.options.stride)[:len(shape)] == stride
            assert [info.min_offset,info.max_offset] == layout['offset_bounds'] and info.logical_bytes == len(raw)
            invalid_origin = 0 if info.min_offset < 0 else span._length_
            rejected = self.expect(None,self.encode_field(p,input,c.sizeof(input),invalid_origin,c.byref(used)),1)
            assert self.encode_field(p,input,c.sizeof(input),origin,c.byref(used)) == 0
            wire = c.string_at(self.data(p),used.value)
        paths = {k:root/v for k,v in req['artifacts'].items()}
        meta = canonical_bytes(field_metadata(req))
        paths['metadata'].write_bytes(meta)
        paths['payload'].write_bytes(wire)
        run_worker(root,[sys.executable,'-I','-B',__file__,'--field',lib,paths['metadata'],paths['payload'],paths['restored_span']])
        recovered = paths['restored_span'].read_bytes()
        output = span.from_buffer_copy(recovered)
        restored = [output[i] for i in at]
        touched = set(at)
        assert all(output[i] == 8191 for i in range(span._length_) if i not in touched)
        assert all(math.isfinite(x) for x in restored)
        errors = [abs(a-b) for a,b in zip(source,restored,strict=True)]
        assert max(errors) <= req['max_observed_error'] and info.effective_parameter == req['effective']
        return {'case':req['id'],'dtype':dtype,'mode':mode,'shape':shape,'strides_elements':list(info.options.stride)[:len(shape)],
                'offset_bounds':[info.min_offset,info.max_offset],'origin_elements':origin,'input':req['input'],
                'logical_bytes':info.logical_bytes,'requested_parameter':req['requested'],'effective_parameter':info.effective_parameter,
                'observed_max_abs_error':max(errors),'observed_rmse':math.sqrt(sum(e*e for e in errors)/len(at)),
                'predeclared_case_error_limit':req['max_observed_error'],'bad_origin_status':rejected,
                'payload':ref(paths['payload'].name,wire),'metadata':ref(paths['metadata'].name,meta),
                'restored_span':ref(paths['restored_span'].name,recovered)}


def detached_field(api,metadata,payload,output):
    req = load_json(metadata)
    dtype = req['type']
    cfg = config(dtype,req['shape'],req['mode'],req['requested'])
    opts = Options(0,1,0,(c.c_ssize_t*4)(*req['strides']))
    layout = field_layout(req)
    out = (TYPES[dtype][2]*layout['span_count'])(*([8191]*layout['span_count']))
    wire = payload.read_bytes()
    with api.handle(api.create_ex,api.destroy,c.byref(cfg),c.byref(opts)) as p:
        assert api.decode_field(p,wire,len(wire),out,c.sizeof(out),layout['origin']) == 0
    output.write_bytes(bytes(out))


def rejects(root,invoke,op,args,expected,outputs,options='{}'):
    r = invoke(op,*args,check=False,options=options)
    assert r.returncode == 3 and f'plugin status {expected}:'.encode() in r.stderr, r
    assert not any((root / name).exists() for name in outputs)
    return expected


def batch_case(root,invoke,api,label,dtype,raw,lineage=None):
    dtype_id, kind, scalar = TYPES[dtype]
    n = len(raw)//c.sizeof(scalar)
    schema = canonical_bytes({'column':'value','dtype':dtype})
    (root/'input').write_bytes(raw); (root/'schema').write_bytes(schema)
    data = api.legacy(dtype,kind,raw)
    def frame(data=data,count=n,dt=dtype_id):
        return HEADER.pack(MAGIC,dt,count,len(schema),len(data)) + schema + data
    result = invoke('encode',dtype_id,'input','schema','frame')
    assert json.loads(result.stdout) == {'backend':'zfp-c11-serial','entry':'zn_encode','mode':'batch',
                                        'quality':'reversible','threads':1,'operation':'encode'}
    full = (root/'frame').read_bytes()
    assert full == frame()
    (root/'input').unlink(); (root/'schema').unlink()
    desc,info = map(json.loads,invoke('decode','frame','restored','schema.out').stdout.splitlines())
    assert desc == {'dtype':dtype_id,'count':n} and info['entry'] == 'zn_decode' and info['threads'] == 1
    restored, schema_out = (root/'restored').read_bytes(), (root/'schema.out').read_bytes()
    assert restored == raw and schema_out == schema
    (root/'restored').unlink(); (root/'schema.out').unlink()
    # Only negative envelope/metadata cases, rejected before upstream raw decoding.
    invalid = [(full[:-1],5),(full+b'\0',5),(frame(count=0),5),(frame(dt=8),5),(frame(data[:-1]),5),(frame(count=1<<28),7)]
    rejected = {}
    for name,(bad,status) in zip(BATCH_WIRE_REJECTIONS,invalid,strict=True):
        (root/'frame').write_bytes(bad)
        rejected[name] = rejects(root,invoke,'decode',['frame','restored','schema.out'],status,['restored','schema.out'])
    (root/'frame').unlink()
    artifact = root/f'zfp-{label}.bmk'
    artifact.write_bytes(full)
    return {'case':label,'dtype':dtype,'count':n,'input':ref('frozen:'+label,raw),'artifact':ref(artifact.name,full),
            'native_bytes':len(data),'native_sha256':sha(data),'restored_sha256':sha(restored),'schema_sha256':sha(schema_out),
            'descriptor':desc,'rejected_envelopes':rejected,**(lineage or {})}


def openmp_case(root,exe,lib,real,req):
    src = root/'omp.in'
    src.write_bytes(real)
    variants, payloads = [],[]
    for spec in req['profiles']:
        path = root/spec['payload']
        r = subprocess.run([exe,src,str(req['count']),spec['policy'],str(req['chunk_blocks']),path],cwd=root,
                           env={'LC_ALL':'C','HOME':str(root),'LD_LIBRARY_PATH':str(root),**req['env']},
                           capture_output=True,check=True,timeout=12)
        payloads.append(path.read_bytes())
        variants.append({**json.loads(r.stdout),'payload':ref(path.name,payloads[-1])})
    src.unlink()
    assert len(set(payloads)) == 1  # same field and tested policies, not a general guarantee
    for row in variants:
        restored = root/'omp.out'
        run_worker(root,[sys.executable,'-I','-B',__file__,'--omp-restore',lib,root/row['payload']['path'],str(req['count']),restored])
        recovered = restored.read_bytes()
        assert recovered == real
        row['detached_restored_sha256'] = sha(recovered)
        restored.unlink()
    return {'observation':'ELF_interposed_native_full_block_functions_not_timing','omp_env':req['env'],
            'profiles':variants,'diagnostic_executable_sha256':digest(exe),'diagnostic_source_sha256':digest(ROOT/'tests/native/zfp_omp_control.cpp')}


def detached_omp(api,payload,count,restored):
    size = int(str(count))
    out = (c.c_double*size)()
    cfg = api.config_1d(TYPES['f64'][1],size)
    wire = payload.read_bytes()
    with api.handle(api.create,api.destroy,c.byref(cfg)) as ctx:
        assert api.decode(ctx,wire,len(wire),out,c.sizeof(out)) == 0
    restored.write_bytes(bytes(out))


def array_values(api,p,n,t=c.c_double):
    data = (t*n)()
    assert api.array_get_range(p,0,n,data,c.sizeof(data)) == 0
    return data


def detached_array(api,metadata,payload,output):
    metadata = load_json(metadata)
    assert metadata['format'] == 'zfp-fixed-rate-array/1' and metadata['mode'] == 'rate'
    dtype, shape = metadata['dtype'], metadata['shape']
    cfg = config(dtype,shape,'rate',metadata['requested_rate'])
    payload = payload.read_bytes()
    with api.handle(api.array_import,api.array_destroy,c.byref(cfg),payload,len(payload)) as p:
        assert api.array_rate(p) == metadata['effective_rate']
        n = api.array_count(p)
        assert n == math.prod(shape)
        output.write_bytes(bytes(array_values(api,p,n,TYPES[dtype][2])))


def array_case(root,api,lib,req):
    dtype,shape = req['type'],req['shape']
    cfg = config(dtype,shape,'rate',req['requested_rate'])
    n = math.prod(shape)
    assert dtype == 'f64' and shape == [13]
    initial, logical_after_update = array_input(req)
    values = (c.c_double*n)(*initial)
    idx,start = req['point_index'],req['range_start']
    changes = (c.c_double*len(req['range_values']))(*req['range_values'])
    reserve_request = 16384
    with api.handle(api.array_create,api.array_destroy,c.byref(cfg),values,c.sizeof(values)) as p:
        rate, payload_size = api.array_rate(p),api.array_compressed_size(p)
        assert rate == 32 and payload_size == 64 and api.array_count(p) == n
        assert api.array_cache_size(p) == 0
        before_buffer,before_count = c.create_string_buffer(payload_size),SIZE()
        assert api.array_export(p,before_buffer,payload_size,c.byref(before_count)) == 0 and before_count.value == payload_size
        before = before_buffer.raw
        baseline = list(array_values(api,p,n))
        assert max(abs(a-b) for a,b in zip(baseline,initial,strict=True)) <= req['max_observed_error']
        val = c.c_double(req['point_value']); out = c.c_double()
        assert api.array_set(p,idx,c.byref(val)) == 0
        assert api.array_get(p,idx,c.byref(out)) == 0 and out.value == val.value
        cached_point = out.value
        cache_after_set = api.array_cache_size(p)
        assert cache_after_set == 256*8
        # Moving to another block flushes the first one. Compare post-quantization rather than assuming exactness.
        assert api.array_get(p,n-1,c.byref(out)) == 0 and out.value == baseline[-1]
        assert api.array_get(p,idx,c.byref(out)) == 0
        evicted_point = out.value
        assert 0 < abs(evicted_point-val.value) <= req['max_observed_error']
        assert api.array_set_range(p,start,len(changes),changes,c.sizeof(changes)) == 0
        assert api.array_get(p,start+len(changes)-1,c.byref(out)) == 0 and out.value == changes[-1]
        assert api.array_set_cache_size(p,reserve_request) == 0
        after_set_size = api.array_cache_size(p)
        assert after_set_size == 0
        assert api.array_get(p,start,c.byref(out)) == 0 and api.array_cache_size(p) == cache_after_set
        assert api.array_flush_cache(p) == 0
        after_flush = api.array_cache_size(p)
        assert after_flush == 0
        assert api.expect('point_oob',api.array_get(p,n,c.byref(out)),1) == 1
        assert api.expect('nonfinite_write',api.array_set(p,idx,c.byref(c.c_double(math.nan))),1) == 1
        assert api.expect('range_oob',api.array_get_range(p,n-1,2,changes,16),1) == 1
        assert api.array_flush(p) == 0
        b,used = c.create_string_buffer(payload_size),SIZE()
        assert api.expect('export_capacity',api.array_export(p,b,payload_size-1,c.byref(used)),1) == 1 and used.value == 0
        assert api.array_export(p,b,payload_size,c.byref(used)) == 0 and used.value == payload_size
        data = b.raw
        expected_export = bytes(array_values(api,p,n))
    paths = {k:root/v for k,v in req['artifacts'].items()}
    assert rate == req['effective_rate']
    metadata = canonical_bytes(array_metadata(req))
    for path,raw in ((paths['before'],before),(paths['after'],data),(paths['metadata'],metadata)):
        path.write_bytes(raw)
    for src,dst in (('before','baseline'),('after','restored')):
        run_worker(root,[sys.executable,'-I','-B',__file__,'--array',lib,paths['metadata'],paths[src],paths[dst]])
    assert paths['restored'].read_bytes() == expected_export and typed_values('f64',paths['baseline'].read_bytes()) == baseline
    restored = typed_values('f64',paths['restored'].read_bytes())
    errors = [abs(a-b) for a,b in zip(restored,logical_after_update,strict=True)]
    assert max(errors) <= req['max_observed_error']
    assert restored[8:] == baseline[8:]
    for name, conf, size in (
        ('truncated_raw',cfg,len(data)-1),('wrong_derived_size',config(dtype,[8],'rate',req['requested_rate']),len(data)),
        ('wrong_mode',config(dtype,shape),len(data)),
    ):
        with api.handle(api.array_import,api.array_destroy,c.byref(conf),data,size,status=1,name=name):
            pass
    return {'requested_rate':req['requested_rate'],'effective_rate':rate,'max_abs_error_vs_updated_original':max(errors),
            'cached_point':cached_point,'evicted_point':evicted_point,'cache_size_request':reserve_request,
            'observed_cache_bytes_when_populated':cache_after_set,'cache_bytes_after_set_size':after_set_size,
            'cache_bytes_after_explicit_flush':after_flush,
            'artifacts':{k:ref(path.name,path.read_bytes()) for k,path in paths.items()},
            'all_required_bytes':len(data)+len(metadata),'rejected':{k:api.statuses[k] for k in ARRAY_REJECTIONS}}


def main(worker,module,library,omp,report):
    bundle, real = plan_zfp(ROOT)
    bound_window = bundle['window']
    with tempfile.TemporaryDirectory(prefix='tsbench-zfp-moved-') as temp:
        root = Path(temp)
        for directory in ('catalog','schemas','plugins','include','cmake','tools','third_party'):
            shutil.copytree(ROOT/directory,root/directory)
        for p in (worker,module,library,omp):
            shutil.copy2(p,root/p.name)
        lock = create_build_lock(root,worker.name,{PLUGIN:module.name})
        bound = resolve_worker(root,lock,PLUGIN,{})
        lib = root/library.name
        api = Native(lib)
        cuda = {'backend_info':api.backend_info().decode(),'built':api.cuda_built(),
                'device_available':api.cuda_available(),'runtime_visible':api.cuda_runtime_available()}
        assert cuda == {'backend_info':'cpu-only','built':0,'device_available':0,'runtime_visible':0}
        def invoke(op,*args,check=True,options='{}'):
            return run_worker(root,[bound['worker'],op,bound['library'],PLUGIN,options,*map(str,args)],check=check)
        batch = [batch_case(root,invoke,api,name,dtype,raw,lineage)
                 for name,dtype,raw,lineage in batch_inputs(real,bound_window)]
        (root/'schema').write_bytes(b'{}'); (root/'input').write_bytes(b'')
        inputs = {'empty':rejects(root,invoke,'encode',[10,'input','schema','frame'],1,['frame'])}
        (root/'input').write_bytes(bytes(8))
        inputs['wrong_dtype'] = rejects(root,invoke,'encode',[8,'input','schema','frame'],1,['frame'])
        inputs['unknown_options'] = rejects(root,invoke,'encode',[10,'input','schema','frame'],3,['frame'],options='{"mode":"rate"}')
        (root/'input').unlink(); (root/'schema').unlink()
        fields = [api.original_field(root,lib,req,real) for req in bundle['fields']]
        invalid_requests = [('i32',[5],'accuracy',.1,Options(0,1,0,(c.c_ssize_t*4)())),
                            ('f32',[5],'precision',33,Options(0,1,0,(c.c_ssize_t*4)())),
                            ('f64',[5,5],'reversible',0,Options(0,1,0,(c.c_ssize_t*4)(1,1))),
                            ('f64',[5],'rate',16,Options(2,1,0,(c.c_ssize_t*4)()))]
        for name,(dtype,shape,mode,param,options) in zip(FIELD_REJECTIONS,invalid_requests,strict=True):
            conf = config(dtype,shape,mode,param)
            with api.handle(api.create_ex,api.destroy,c.byref(conf),c.byref(options),status=1,name=name):
                pass
        invalid_fields = {k:api.statuses[k] for k in FIELD_REJECTIONS}
        openmp = openmp_case(root,root/omp.name,lib,real,bundle['openmp'])
        arrays = array_case(root,api,lib,bundle['array'])
        (root/WEATHER).write_bytes(real)
        files = {name:(root/name).read_bytes() for name in retained_paths(bundle)}
    doc = {'schema':'bmk.m0-zfp-control/2','diagnostic_id':uuid.uuid4().hex,'config_id':bundle['config_id'],'bundle_id':bundle['bundle_id'],
           'definitions':digest(Path(__file__)),'build':lock,'formal_qualification':False,'formal_performance':False,
           'window':bound_window,'batch':batch,'batch_rejected_inputs':inputs,'fields':fields,'invalid_field_configs':invalid_fields,
           'openmp':openmp,'array':arrays,'cuda':{**cuda,'state':'not_tested_cpu_build'}}
    with tempfile.TemporaryDirectory(dir=report.parent,prefix='.zfp-report-') as temp:
        path = Path(temp)/'report.json'
        path.write_bytes(canonical_bytes(doc)+b'\n')
        for name,data in files.items():
            (Path(temp)/name).write_bytes(data)
        for name in files:
            (Path(temp)/name).replace(report.parent/name)
        path.replace(report)


if __name__ == '__main__':
    if sys.argv[1] in ('--field','--array','--omp-restore'):
        _,op,lib,*args = sys.argv
        f = {'--field':detached_field,'--array':detached_array,'--omp-restore':detached_omp}[op]
        f(Native(Path(lib)),*map(Path,args))
    else:
        main(*(Path(p).resolve() for p in sys.argv[1:]))
