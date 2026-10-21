"""Finite component/column/chunk schemes, independent native sessions per part."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import numpy as np
from .artifact import EncodedObject, pack_bundle, read_bundle_prefix, validate_descriptor, checked_array
from .data import TimeSeriesObject, array_descriptor, array_order, canonical_json, fingerprint
from .errors import Unsupported, Unavailable
from .registry import Registry
from .transforms import forward, inverse

ASSET_ROOT = Path(__file__).resolve().parents[3]


def _roots(asset_root=None,build_root=None):
    root=Path(asset_root or ASSET_ROOT).resolve()
    return root,Path(build_root or root/'build/tsbench').resolve()


def _route(method,name,roles):
    entries=method.get('components',{})
    if name in entries: return entries[name]
    if roles.get(name,name)=='mask': return {'codec':'raw-store','params':{}}
    return {'codec':method['codec'],'params':method.get('params',{}),'transform':method.get('transform')}


def _parts(a,method):
    chunk=method.get('chunk_rows',max(a.shape[0],1))
    spans=list(range(0,a.shape[0],chunk)) or [0]
    if method.get('channelwise',False) and a.ndim==2 and a.shape[1]>0:
        for channel in range(a.shape[1]):
            for start in spans:
                stop=min(start+chunk,a.shape[0])
                yield np.ascontiguousarray(a[start:stop,channel]),start,stop,channel
    else:
        for start in spans:
            stop=min(start+chunk,a.shape[0])
            yield np.array(a[start:stop],copy=True,order=array_order(a)),start,stop,None


@lru_cache(maxsize=128)
def _bridge(root,key,build_root):
    from .bridges import create_bridge
    return create_bridge(root,key,build_root=build_root)


def capability(method,obj,task,profile,asset_root=None,build_root=None):
    root,build_root=_roots(asset_root,build_root)
    if task.get('boundary') in {'native_core','native_api'}:
        from .native import capability as native_capability
        return native_capability(method,obj,task,profile,root,build_root)
    reg=Registry(root)
    roles=obj.schema.get('roles',{})
    libraries=[];deps=[];models=[];threads=1;identities=[]
    try:
        if method['codec'] == 'gorilla-prometheus-xor':
            from .bridges.gorilla import validate_method
            arrays,_,_=validate_method(method,obj)
            if task.get('kind') != 'records':
                raise Unsupported('Gorilla joint scheme requires task.kind=records',stage='capability')
            items=[arrays['V']]
        else:
            if any(entry['codec']=='gorilla-prometheus-xor' for entry in method.get('components',{}).values()):
                raise Unsupported('Gorilla is a joint T/V method, not a component codec',stage='capability')
            items=obj.components.items()
        for name,a in items:
            route=_route(method,name,roles);spec=reg.get(route['codec']);params=reg.resolve_params(spec.key,route.get('params',{}))
            spec.require_enabled()
            if spec.key=='deepzip':
                model_record=spec.document['adapter']['models'][params['model_key']]
                model_path=root/model_record['path']
                if not model_path.is_file():raise Unavailable(f'DeepZip model missing: {model_path}',stage='capability')
                with model_path.open('rb') as f:model_hash=hashlib.file_digest(f,'sha256').hexdigest()
                if model_hash!=model_record['sha256']:raise Unavailable('DeepZip selected model hash mismatch',stage='capability')
                models.append({'path':str(model_path),'sha256':model_hash})
            if spec.lossy and roles.get(name,name)!='V': raise Unsupported(f'{name}: timestamps and masks require bitwise codecs',stage='capability')
            if spec.lossy and task.get('fidelity','bitwise') in {'bitwise','numeric_equivalent'}: raise Unsupported(f'{spec.key}: needs a quality task',stage='capability')
            if spec.key in {'abba','fabba','qabba'} and task.get('fidelity')!='empirical_quality': raise Unsupported(f'{spec.key}: tolerance is empirical; use empirical_quality',stage='capability')
            if spec.key in {'pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized'}:
                fidelity = task.get('fidelity')
                if params['quality_mode'] == 'compatible' and fidelity != 'empirical_quality':
                    raise Unsupported(f'{spec.key}: compatible mode requires empirical_quality', stage='capability')
                if fidelity not in {'bounded_abs', 'empirical_quality'}:
                    raise Unsupported(f'{spec.key}: only absolute or empirical quality is qualified', stage='capability')
            if spec.key=='dzip':
                threads=max(threads,3)

            isa=params.get('isa','SCALAR')
            flags=set()
            cpuinfo=Path('/proc/cpuinfo')
            if cpuinfo.is_file():
                for line in cpuinfo.read_text().splitlines():
                    if line.startswith('flags'):
                        flags=set(line.partition(':')[2].split());break
            required={'SSE4_1':{'sse4_1'},'AVX2':{'avx2'},'AVX':{'avx'},'AVX2_BMI2_LZCNT':{'avx2','bmi2','abm'},'AVX2_BMI1_BMI2_LZCNT_POPCNT':{'avx2','bmi1','bmi2','abm','popcnt'}}.get(isa,set())
            if required and not required.issubset(flags):raise Unavailable(f'{spec.key}: CPU ISA {isa} unavailable or unverified',stage='capability')
            for part,_,_,_ in _parts(a,method):
                transformed,_=forward(part,route.get('transform'))
                spec.validate_array(transformed)
            if spec.key!='raw-store':
                from .build import artifact_path, sha
                path=artifact_path(root,spec.key,build_root=build_root)
                if not path.is_file(): raise Unavailable(f'{spec.key}: shared library missing; run tsbench build {spec.key}',stage='capability')
                libraries.append(str(path));identities.append(sha(path))
                record=path.parent/'build.json'
                if record.exists():deps.extend(json.loads(record.read_text()).get('runtime_dependencies',[]))
            else:identities.append('builtin:raw-store-v1')
        if profile.get('native_threads',1)!=threads:
            raise Unsupported(f'this scheme requires native_threads={threads} (DZip uses caller + 2 Eigen workers)',stage='profile')
        implementation='sha256:'+hashlib.sha256(canonical_json({'libraries':identities,'methods':method})).hexdigest()
        return {'supported':True,'status':'ok','reason':None,'implementation_id':implementation,
                'library_path':libraries[0] if len(libraries)==1 else None,'library_paths':libraries,'runtime_dependencies':deps,'model_dependencies':models,
                'effective_native_threads':threads,'thread_evidence':'frozen source contract; DZip caller+two Eigen workers' if threads==3 else 'frozen single-thread API contract',
                'executor_features':{'object':True,'stream':False,'query':False,'gpu':False}}
    except Exception as e:
        if isinstance(e,(Unsupported,Unavailable,ValueError,KeyError)):
            return {'supported':False,'status':getattr(e,'status','unsupported'),'reason':str(e),'stage':getattr(e,'stage','capability')}
        raise


class ObjectScheme:
    def __init__(self,method,asset_root=None,build_root=None):
        self.method=method
        self.root,self.build_root=_roots(asset_root,build_root)
        self.registry=Registry(self.root)
    def prepare(self,obj):
        # Preload installed implementations; no transformed buffers or codec state survive.
        if self.method['codec']=='gorilla-prometheus-xor':
            _bridge(str(self.root),'gorilla-prometheus-xor',str(self.build_root))
            return
        roles=obj.schema.get('roles',{})
        routes=[_route(self.method,name,roles) for name in obj.components]
        for route in routes:
            key=self.registry.get(route['codec']).key
            if key!='raw-store':_bridge(str(self.root),key,str(self.build_root))
    def encode_once(self,obj):
        if self.method['codec']=='gorilla-prometheus-xor':
            from .bridges.gorilla import encode_object
            bridge=_bridge(str(self.root),'gorilla-prometheus-xor',str(self.build_root))
            return encode_object(obj,self.method,bridge)
        body=bytearray();components=[];input_ids=[];input_bytes=0;intermediate_ids=[];intermediate_bytes=0
        roles=obj.schema.get('roles',{})
        for name,a in obj.components.items():
            c={'name':name,'role':roles.get(name,name),**array_descriptor(a),'parts':[]}
            route=_route(self.method,name,roles);key=self.registry.get(route['codec']).key
            params=self.registry.resolve_params(key,route.get('params',{}))
            for part,start,stop,channel in _parts(a,self.method):
                part,transform=forward(part,route.get('transform'))
                if key=='raw-store':
                    payload=part.tobytes(order=array_order(part))
                    actual={'content_sha256':hashlib.sha256(payload).hexdigest(),'dtype':part.dtype.str,'shape':list(part.shape),'layout':array_order(part),'nbytes':part.nbytes,'abi':'builtin-raw-v1'}
                else:
                    bridge=_bridge(str(self.root),key,str(self.build_root))
                    payload=bridge.encode(part,params)
                    actual=bridge.last_input_identity.copy()
                input_bytes+=actual['nbytes'];intermediate_bytes+=part.nbytes
                input_identity={'component':name,**array_descriptor(part),'content_sha256':hashlib.sha256(part.tobytes(order=array_order(part))).hexdigest(),
                                'row_start':start,'row_stop':stop,'channel':channel}
                intermediate_ids.append(input_identity)
                actual.update(component=name,row_start=start,row_stop=stop,channel=channel)
                input_ids.append(actual)
                p={'codec':key,'format_version':1,'params':params,**array_descriptor(part),'row_start':start,'row_stop':stop,'channel':channel,
                   'offset':len(body),'length':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
                if transform is not None:p['transform']=transform
                body.extend(payload);c['parts'].append(p)
            components.append(c)
        transforms={name:_route(self.method,name,roles).get('transform') for name in obj.components if _route(self.method,name,roles).get('transform') not in {None,'identity'}}
        transformation={'version':1,'chunk_rows':self.method.get('chunk_rows'),'channelwise':self.method.get('channelwise',False),'layout':'native-bridge-adaptation','transforms':transforms}
        desc={'schema_version':'tsbench.object/1','schema':dict(obj.schema),'components':components,
              'raw_object_id':fingerprint(obj),'codec_input_id':'sha256:'+hashlib.sha256(canonical_json(input_ids)).hexdigest(),
              'codec_input_bytes':input_bytes,'codec_input_scope':'actual native input, including bridge framing and actual dtype/layout',
              'intermediate_input_id':'sha256:'+hashlib.sha256(canonical_json(intermediate_ids)).hexdigest(),'intermediate_input_bytes':intermediate_bytes,
              'identity_cost_policy':'actual input and payload checksums computed in object encode boundary',
              'transform_id':'identity' if not self.method.get('chunk_rows') and not self.method.get('channelwise') and not transforms else 'sha256:'+hashlib.sha256(canonical_json(transformation)).hexdigest(),
              'partition':transformation,'dependency_policy':'standalone; RW native frame includes required model data'}
        return EncodedObject(pack_bundle(desc,bytes(body)))


def decode_once(encoded,asset_root=None,build_root=None):
    root,build_root=_roots(asset_root,build_root)
    desc,body=read_bundle_prefix(encoded.wire)
    if desc.get('schema_version')=='tsbench.gorilla-records/1':
        from .bridges.gorilla import decode_object
        return decode_object(desc,body,_bridge(str(root),'gorilla-prometheus-xor',str(build_root)))
    components=validate_descriptor(desc,body)
    output={}
    for c in components:
        shape=tuple(c['shape']);parts=c['parts'];groups={}
        channelwise=any(p.get('channel') is not None for p in parts)
        if channelwise and len(shape)!=2: raise ValueError('channelwise payload requires matrix')
        for p in parts:
            channel=p.get('channel');start=p.get('row_start');stop=p.get('row_stop')
            if type(start) is not int or type(stop) is not int or not 0<=start<=stop<=shape[0]: raise ValueError('invalid row range')
            if p['dtype']!=c['dtype']: raise ValueError('part dtype differs from component')
            if p.get('format_version')!=1:raise ValueError('unsupported native format version')
            expected=(stop-start,) if channelwise else (stop-start,*shape[1:])
            if channelwise and (type(channel) is not int or not 0<=channel<shape[1]): raise ValueError('invalid channel')
            if not channelwise and channel is not None:raise ValueError('mixed channel partition')
            if tuple(p['shape'])!=expected:raise ValueError('part shape disagrees with partition')
            groups.setdefault(channel,[]).append((start,stop,p))
        expected_groups=set(range(shape[1])) if channelwise else {None}
        if set(groups)!=expected_groups:raise ValueError('missing channels')
        for group in groups.values():
            end=0
            for start,stop,p in sorted(group,key=lambda x:x[0]):
                if start!=end or stop==start and shape[0]!=0:raise ValueError('partition overlap or gap')
                end=stop
            if end!=shape[0]:raise ValueError('incomplete partition')
        a=np.empty(shape,dtype=c['dtype'],order=c['order'])
        for group in groups.values():
            for start,stop,p in group:
                payload=body[p['offset']:p['offset']+p['length']]
                if p['codec']=='raw-store':
                    if len(payload)!=checked_array(p):raise ValueError('raw payload size mismatch')
                    part=np.frombuffer(payload,dtype=p['dtype']).reshape(p['shape'],order=p['order']).copy(order=p['order'])
                else:
                    Registry(root).resolve_params(p['codec'],p['params'])
                    part=_bridge(str(root),p['codec'],str(build_root)).decode(payload,p['dtype'],tuple(p['shape']),p['params'])
                    if part.dtype.str!=p['dtype'] or part.shape!=tuple(p['shape']):raise ValueError('native output descriptor mismatch')
                part=inverse(part,p.get('transform'))
                if channelwise:a[start:stop,p['channel']]=part
                else:a[start:stop]=part
        output[c['name']]=a
    return TimeSeriesObject(output,desc['schema'])
