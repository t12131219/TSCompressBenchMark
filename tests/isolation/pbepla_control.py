#!/usr/bin/env python3
"""Validate original-domain error, independent prefixes and real replay I/O."""
from binascii import crc32
import ctypes as c
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest
from tsbench.planner.pbepla_progressive import WORD_MAGIC, boundary_source, plan_pbepla_progressive, schema_bytes
from tsbench.qualification.pbepla_progressive import MAGIC, OUTER, PBEP, quality
from tsbench.runtime import create_build_lock, resolve_worker

PLUGIN = 'pbepla-rr'
EMIT = c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_double)


def sha(data):
    return sha256(data).hexdigest()


class Buffer(c.Structure):
    _fields_ = [('data',c.c_void_p),('bytes',c.c_size_t),('count',c.c_size_t)]


class Options(c.Structure):
    _fields_ = [('eps',c.POINTER(c.c_double)),('layers',c.c_size_t),('resolutions',c.POINTER(c.c_uint)),
                ('has_source_range',c.c_int),('source_min',c.c_double),('source_max',c.c_double),
                ('max_delay',c.c_uint64),('connected',c.c_int),('symmetric_band',c.c_int)]


class Info(c.Structure):
    _fields_ = [('value_count',c.c_size_t),('header_bytes',c.c_size_t),('payload_bytes',c.c_size_t),
                ('layer_count',c.c_uint),('layer_present',c.c_uint),('max_delay',c.c_uint64),
                ('connected',c.c_int),('symmetric_band',c.c_int),('grid_min',c.c_double),('grid_max',c.c_double),
                ('effective_eps',c.c_double*16),('resolutions',c.c_uint*16),('payload_bits',c.c_uint64*16)]


class Native:
    def __init__(self,path):
        self.lib = c.CDLL(str(path))
        p,n,i,u,b = c.c_void_p,c.c_size_t,c.c_int,c.c_uint,c.POINTER(Buffer)
        self.defaults = self.function('pbepla_defaults',Options,c.POINTER(c.c_double),n)
        self.encode = self.function('pbepla_encode_ex',i,p,n,c.POINTER(Options),c.POINTER(Info),b,p,n)
        self.inspect = self.function('pbepla_inspect',i,p,n,c.POINTER(Info),p,n)
        self.prefix = self.function('pbepla_prefix',i,p,n,u,b,p,n)
        self.decode = self.function('decode',i,i,p,n,u,n,b,p,n)
        self.approximate = self.function('pbepla_approximate',i,p,n,c.c_double,n,c.POINTER(u),c.POINTER(i),b,p,n)
        self.decode_stream = self.function('pbepla_decode_stream',i,p,n,u,n,p,EMIT,p,n)
        self.free = self.function('free',None,b)

    def function(self,name,result,*args):
        f = getattr(self.lib,'tba_'+name)
        f.restype,f.argtypes = result,args
        return f

    def allocated(self,f,*args,ok=True):
        obj,err = Buffer(),c.create_string_buffer(256)
        rc = f(*args,c.byref(obj),err,len(err))
        try:
            if ok:
                assert rc == 0,err.value
                return (c.string_at(obj.data,obj.bytes) if obj.bytes else b''),obj.count
            assert rc == -1 and not obj.data and not obj.bytes and not obj.count,err.value
            return err.value.decode()
        finally:
            self.free(c.byref(obj))

    def pack(self,raw,eps,**config):
        count = len(raw)//8
        src = (c.c_double*count).from_buffer_copy(raw)
        e = (c.c_double*len(eps))(*eps)
        opts = self.defaults(e,len(eps))
        resolutions = config.pop('resolutions',None)
        if resolutions:
            res = (c.c_uint*len(resolutions))(*resolutions)
            opts.resolutions = res
        for key,value in config.items():
            setattr(opts,key,value)
        info = Info()
        out,n = self.allocated(self.encode,src,count,c.byref(opts),c.byref(info))
        assert n == count
        return out,info

    def unpack(self,payload,layers,count,ok=True):
        return self.allocated(self.decode,1,payload,len(payload),layers,count,ok=ok)

    def describe(self,payload):
        inf,err = Info(),c.create_string_buffer(256)
        assert self.inspect(payload,len(payload),c.byref(inf),err,len(err)) == 0,err.value
        return inf

    def emitted(self,payload,layers,count,abort=False):
        seen = []
        @EMIT
        def emit(_,value):
            seen.append(value)
            return int(abort)
        err = c.create_string_buffer(256)
        rc = self.decode_stream(payload,len(payload),layers,count,None,emit,err,len(err))
        if abort:
            assert rc == -1 and len(seen) == 1 and b'emit failed' in err.value
        else:
            assert rc == 0 and len(seen) == count,err.value
        return struct.pack(f'<{len(seen)}d',*seen)


def wire_info(data,info):
    magic,version,flags,k,m,count,delay,lo,hi = PBEP.unpack_from(data)
    assert magic == b'PBEP' and version == 1 and 1 <= m <= k <= 16
    assert flags == (not info.connected)+2*info.symmetric_band
    assert (count,k,m,delay,lo,hi) == (info.value_count,info.layer_count,info.layer_present,info.max_delay,info.grid_min,info.grid_max)
    eps = list(struct.unpack_from(f'<{k}d',data,36))
    resolutions = list(data[36+8*k:36+9*k]); at = 36+9*k
    bits = list(struct.unpack_from(f'<{m}Q',data,at)); at += 8*m
    body_crc,head_crc = struct.unpack_from('<II',data,at)
    header = at+8
    assert header == info.header_bytes and len(data)-header == info.payload_bytes
    assert crc32(data[header:]) == body_crc and crc32(data[:at+4]) == head_crc
    assert eps == list(info.effective_eps[:k]) and resolutions == list(info.resolutions[:k]) and bits == list(info.payload_bits[:m])
    assert all(math.isfinite(e) and e>0 for e in eps) and all(a>b for a,b in zip(eps,eps[1:]))
    layer_bytes = [(b+7)//8 for b in bits]
    assert sum(layer_bytes) == len(data)-header
    return dict(count=count,flags=flags,stored=m,declared=k,delay=delay,eps=eps,resolutions=resolutions,
                header_bytes=header,payload_bytes=sum(layer_bytes),layer_bytes=layer_bytes,bits=bits)


def measure(original,actual,epsilon):
    maximum, row = quality(original, actual)
    assert maximum <= epsilon, (maximum,epsilon)
    return row


def worker_result(root,run,label,artifact,n,schema):
    (root/'frame').write_bytes(artifact)
    asc,info = map(json.loads,run('decode','{}','frame','out','out.schema').stdout.splitlines())
    assert asc == {'dtype':10,'count':n} and (root/'out.schema').read_bytes() == schema, label
    out = (root/'out').read_bytes()
    (root/'out').unlink(); (root/'out.schema').unlink()
    return out,info


def reject(r,status,root,*outs):
    absent = not any((root/p).exists() for p in outs)
    assert r.returncode == 3 and r.stderr.startswith(f'plugin status {status}:'.encode()) and absent,r.stderr
    return {'exit_status':r.returncode,'plugin_status':int(r.stderr.split(b':',1)[0].split()[-1]),'outputs_absent':absent}


def progressive(root,run,api,spec,raw,retained):
    name, n, eps, batch_config = (spec[k] for k in ('name','count','requested_eps','geometry'))
    native,info = api.pack(raw,eps,**(batch_config or {}))
    d = wire_info(native,info)
    assert wire_info(native,api.describe(native)) == d and n == d['count']
    assert d['stored'] == len(eps) and all(e<=r for e,r in zip(d['eps'],eps,strict=True))
    schema = schema_bytes(name)

    def envelope(payload):
        return OUTER.pack(MAGIC,10,n,len(schema),len(payload))+schema+payload

    if batch_config is None:
        (root/'input').write_bytes(raw); (root/'schema').write_bytes(schema)
        enc = json.loads(run('encode',canonical_bytes({'eps':eps}).decode(),10,'input','schema','encoded').stdout)
        assert enc['layers_stored'] == d['stored'] and (root/'encoded').read_bytes() == envelope(native)
        (root/'input').unlink(); (root/'schema').unlink(); (root/'encoded').unlink()

    layers,results = [],[]
    for layer in range(1,len(eps)+1):
        restored,count = api.unpack(native,layer,n)
        assert count == n
        p,pc = api.allocated(api.prefix,native,len(native),layer)
        w = wire_info(p,api.describe(p))
        assert w['stored']==layer and w['declared']==len(eps) and pc==n and w['bits']==d['bits'][:layer]
        assert p[w['header_bytes']:] == native[d['header_bytes']:d['header_bytes']+w['payload_bytes']]
        assert w['header_bytes']==44+9*len(eps)+8*layer
        artifact = envelope(p)
        out,dec_info = worker_result(root,run,name,artifact,n,schema)
        assert out == restored and dec_info['layers_stored']==layer and dec_info['native_payload_bytes']==w['payload_bytes']
        q = measure(raw,out,d['eps'][layer-1])
        results.append(out)
        retained[spec['frame_paths'][layer-1]] = artifact
        layers.append({'layer':layer,'frame_sha256':sha(artifact),'decode_info':dec_info,'effective_eps':d['eps'][layer-1],'prefix_sha256':sha(p),
                       'prefix_header_bytes':w['header_bytes'],'incremental_payload_bytes':w['layer_bytes'][-1],
                       'cumulative_payload_bytes':w['payload_bytes'],'detached_prefix_bytes':len(p),
                       'worker_frame_bytes':len(artifact),**q})

    retained[spec['word_path']] = WORD_MAGIC+raw+b''.join(results)

    # Approximate selects the first advertised bound that satisfies the request;
    # inability to meet the request is explicit, even when it can return the finest.
    targets = []
    for target in [*d['eps'],d['eps'][-1]/2]:
        used,met = c.c_uint(),c.c_int()
        blob,count = api.allocated(api.approximate,native,len(native),target,n,c.byref(used),c.byref(met))
        chosen = next((i for i,e in enumerate(d['eps'],1) if e<=target),len(eps))
        assert (used.value,met.value,count,blob) == (chosen,int(d['eps'][chosen-1]<=target),n,results[chosen-1])
        targets.append({'requested':target,'layers_used':used.value,'bound_met':bool(met.value)})

    native_rejects = {'zero_layers':api.unpack(native,0,n,ok=False),'absent_layer':api.unpack(native,len(eps)+1,n,ok=False)}
    worker_rejects = {}
    def bad_frame(case, data):
        (root/'frame').write_bytes(data)
        worker_rejects[case] = {'sha256':sha(data),**reject(run('decode','{}','frame','out','out.schema',check=False),
                                                           5,root,'out','out.schema')}
    if n:
        native_rejects['value_budget'] = api.unpack(native,1,n-1,ok=False)
    if d['payload_bytes']:
        changed = native[:-1]+bytes([native[-1]^1])
        err = api.unpack(changed,1,n,ok=False)
        assert 'payload checksum mismatch' in err  # layer-1 recovery still validates later bytes
        native_rejects['later_crc_even_for_layer1'] = err
        bad_frame('payload_crc',envelope(changed))
    bad_frame('truncated_native',envelope(native[:-1]))
    bad_frame('zero_stored_layer',envelope(native[:7]+b'\0'+native[8:]))
    return native,{'name':name,'input_id':spec['input_id'],'input_sha256':sha(raw),'native_sha256':sha(native),'requested_eps':eps,'wire':d,
                   'layers':layers,'targets':targets,'native_rejects':native_rejects,'worker_rejects':worker_rejects,
                   'full_container_crc_scope':'all_payload_bytes'}


def replay_cases(root,exe,api,normal,policy,delay,scope,retained):
    def invoke(mode,raw,eps,limit):
        (root/'replay.source').write_bytes(raw)
        cmd = [str(exe),mode,'replay.source','replay.pbep',str(limit),str(delay),*map(str,eps)]
        p = run_worker(root,cmd)
        out = (root/'replay.pbep').read_bytes()
        (root/'replay.source').unlink(); (root/'replay.pbep').unlink()
        state = json.loads(p.stdout)
        assert state['sink_bytes']==len(out) and state['temp_files_created']==state['temp_files_closed']
        return out,state,p.stderr.decode().strip()

    stats = []
    for name,raw,eps,batch in normal:
        n = len(raw)//8
        out,log,err = invoke('normal',raw,eps,n)
        assert not err and log['result']==0 and log['native_value_count']==n
        retries = log['native_numerical_retries']
        passes = 3+retries if n else 1
        assert log['rewind_calls']==log['eof_passes']==log['native_passes']==log['first_sink_after_pass']==passes
        assert log['source_bytes_read']==passes*len(raw)
        assert log['native_buffer_slots']==(len(eps)*(delay+2) if n else 0)
        d = wire_info(out,api.describe(out))
        assert log['temp_bytes_read']==3*d['payload_bytes'] and log['temp_seeks']==(3*len(eps) if n else 0)
        assert log['temp_bytes_written']>=d['payload_bytes'] and log['temp_peak_live_bytes']>=d['payload_bytes']
        if not retries:
            assert log['temp_bytes_written']==log['temp_peak_live_bytes']==d['payload_bytes']
        checks = []
        for k,e in enumerate(d['eps'],1):
            bits,count = api.unpack(out,k,n)
            assert count==n and api.emitted(out,k,n)==bits
            checks.append({'layer':k,**measure(raw,bits,e)})
        if n: api.emitted(out,1,n,abort=True)
        stats.append({'name':name,'scope':scope,'same_bytes_as_batch':out==batch,'payload_sha256':sha(out),'wire':d,'io':log,'quality':checks})

    _,raw,eps,_ = next(x for x in normal if x[0]==policy['fault_input'])
    neg = []
    for name in policy['fault_modes']:
        limit = len(raw)//8 - (name=='value-limit')
        out,log,err = invoke('normal' if name=='value-limit' else name,raw,eps,limit)
        assert log['result']==-1 and err
        if name=='sink-fail':
            assert out.startswith(b'PBEP') and log['sink_calls']==2 and len(out)==44+17*len(eps)
            retained[policy['partial']] = out
            partial = {'sha256':sha(out),'bytes':len(out),'native_layer1_rejection':api.unpack(out,1,len(raw)//8,ok=False)}
        else:
            assert not out and log['sink_calls']==0
            partial = None
        neg.append({'case':name,'error':err,'io':log,'partial_artifact':partial,'source_sha256':sha(raw),'max_values':limit})
    return stats,neg


def budget_and_input_rejections(root,run,api,policy,raw,retained):
    def encode(data,schema,options,dtype,expected):
        (root/'input').write_bytes(data); (root/'schema').write_bytes(schema)
        result = run('encode',options,dtype,'input','schema','encoded',check=expected==0)
        (root/'input').unlink(); (root/'schema').unlink()
        if expected:
            return reject(result,expected,root,'encoded')
        output = (root/'encoded').read_bytes()
        (root/'encoded').unlink()
        return output

    boundary = []
    for spec in policy['boundary']:
        n,eps = spec['count'],spec['requested_eps']
        data,schema = boundary_source(n),schema_bytes(spec['name'])
        assert sha(data)==spec['input_sha256']
        opts = canonical_bytes({'eps':eps}).decode()
        over = n*len(eps) > policy['work_limit']
        outcome = encode(data,schema,opts,10,7 if over else 0)
        row = {'name':spec['name'],'count':n,'value_layers':n*len(eps),'source_sha256':sha(data)}
        if over:
            native,info = api.pack(data,eps)
            assert info.layer_present==len(eps) and info.value_count==n
            frame = OUTER.pack(MAGIC,10,n,len(schema),len(native))+schema+native
            (root/'frame').write_bytes(frame)
            row.update(encode=outcome,decode=reject(run('decode','{}','frame','out','out.schema',check=False),7,root,'out','out.schema'))
        else:
            frame = outcome
            restored,info = worker_result(root,run,spec['name'],frame,n,schema)
            assert info['layers_stored']==len(eps)
            native = frame[OUTER.size+len(schema):]
            retained[policy['restored']] = restored
            row.update(encode={'plugin_status':0},decode={'plugin_status':0,
                       **measure(data,restored,api.describe(native).effective_eps[len(eps)-1])})
        retained[spec['frame']] = frame
        boundary.append({**row,'frame_sha256':sha(frame)})

    weather = raw['weather']
    opts = ['{"eps":[1]}',b'{}']
    return {'boundary':boundary,
            'options':[{'options':o,'source_sha256':sha(weather),**encode(weather,opts[1],o,10,3)} for o in policy['options']],
            'dtype':{'dtype':policy['reject_dtype'],'source_sha256':sha(weather),**encode(weather,opts[1],opts[0],policy['reject_dtype'],1)},
            'nonfinite':[{'u64':bits,'source_sha256':sha(struct.pack('<Q',bits)),
                         **encode(struct.pack('<Q',bits),opts[1],opts[0],10,2)} for bits in policy['nonfinite_u64']]}


def main(worker,module,library,replay,report):
    bundle, cfg, raw = plan_pbepla_progressive(ROOT)
    window = next(s['source']['window'] for s in bundle['inputs'] if s['name'] == 'weather')
    retained = {}
    with tempfile.TemporaryDirectory(prefix='tsbench-pbepla-moved-') as temp:
        root = Path(temp)
        for name in ('catalog','schemas','plugins','include','cmake','tools','third_party'):
            shutil.copytree(ROOT/name,root/name)
        for file in (worker,module,library,replay):
            shutil.copy2(file,root/file.name)
        lock = create_build_lock(root,worker.name,{PLUGIN:module.name})
        binding = resolve_worker(root,lock,PLUGIN,{'eps':cfg['window_eps']})
        api = Native(root/library.name)

        def run(op,option,*args,check=True):
            return run_worker(root,[binding['worker'],op,binding['library'],PLUGIN,option,*map(str,args)],check=check)

        results,inputs = [],[]
        for spec in bundle['inputs']:
            name = spec['name']
            data = raw[name]
            payload,item = progressive(root,run,api,spec,data,retained)
            results.append(item)
            if spec['replay']:
                inputs.append((name,data,spec['requested_eps'],payload))
        policy = bundle['failure_policy']
        stream,failures = replay_cases(root,root/replay.name,api,inputs,policy,cfg['method']['max_delay'],
                                      bundle['replay_policy']['scope'],retained)
        rejects = budget_and_input_rejections(root,run,api,policy,raw,retained)
    evidence = {'schema':'bmk.m0-pbepla-control/3','diagnostic_id':uuid.uuid4().hex,'config_id':bundle['config_id'],'build':lock,
                'progressive_bundle_id':bundle['bundle_id'],'cases':[c['case_id'] for c in bundle['cases']],
                'window':window,'batch_and_prefix':results,'replay':stream,'replay_failures':failures,
                'input_rejections':rejects,'probe_hashes':[digest(Path(__file__)),digest(replay)],
                'formal_performance':False,'formal_qualification':False}
    with tempfile.TemporaryDirectory(dir=report.parent,prefix='.pbepla-report-') as temp:
        path = Path(temp)/'report.json'
        path.write_bytes(canonical_bytes(evidence)+b'\n')
        for name, data in retained.items():
            (Path(temp)/name).write_bytes(data)
        for name in retained:
            (Path(temp)/name).replace(report.parent/name)
        path.replace(report)


if __name__ == '__main__':
    main(*(Path(p).resolve() for p in sys.argv[1:]))
