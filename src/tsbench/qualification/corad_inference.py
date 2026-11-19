"""Cross-check CORAD inference evidence without a worker, corpus or model directory."""
from hashlib import sha256
import re
import struct
from pathlib import Path

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..corad_quality import assess, calibrate
from ..planner.corad_deployment import NATIVE
from ..planner.corad_inference import METHOD, retained_paths
from .corad_wire import interpret, quality
from .probe_build import verify_probe_build_lock

HEADER = struct.Struct('<8sIIQ')


def _bytes(out, path, limit):
    file = local_file(out,path)
    require(0 < file.stat().st_size <= limit,f'CORAD retained artifact outside bounds: {path}')
    return file.read_bytes()


def _sha(raw):
    return sha256(raw).hexdigest()


def verify_bounds(out, policy, columns, heldout):
    require(policy['policy_id'] == content_id({k:v for k,v in policy.items() if k!='policy_id'}),
            'CORAD frozen quality policy identity differs')
    spec = policy['calibration']
    windows = spec['windows']
    require(len(windows) == len(heldout) == len(columns) and
            all(w['partition']=='train' and t['partition']=='test' and w['count']==spec['rows'] and
                w['column']==t['column']==name and w['partition_canonical_id']!=t['partition_canonical_id'] and
                all(w[k]==t[k] for k in ('asset','corpus_id','dataset','source_cluster'))
                for w,t,name in zip(windows,heldout,columns,strict=True)), 'CORAD quality requires disjoint ordered train/test')
    width = 8 * spec['rows']
    require(8 <= width <= 8192*8 and spec['bytes'] == width*len(columns), 'CORAD quality calibration extent differs')
    raw = _bytes(out,spec['path'],spec['bytes'])
    require(len(raw)==spec['bytes'] and _sha(raw)==spec['sha256'],'CORAD quality calibration sample differs')
    limits = calibrate(columns,[raw[i:i+width] for i in range(0,len(raw),width)],policy['definition'])
    require(canonical_bytes(limits)==canonical_bytes(policy['bounds']),'CORAD predeclared quality bounds differ from calibration')
    return limits


def verify_corad_inference(bundle: dict, build: dict, driver_sha256: str, out: Path, *,
                           sealed_paths: set[str] | None = None, source_oracle_sha256: str) -> None:
    require(bundle['bundle_id'] == content_id({k:v for k,v in bundle.items() if k != 'bundle_id'}),
            'CORAD inference bundle identity differs')
    require(sealed_paths is None or set(retained_paths(bundle)) <= sealed_paths,'CORAD retention differs from sealed evidence')
    doc = load_json(local_file(out,bundle['evidence_path']))
    policy = bundle.get('quality_policy')
    has_gate = isinstance(policy,dict)
    keys = {'schema','diagnostic_id','config_id','bundle_id','probe_sha256','source_oracle_sha256',
            'formal_qualification','formal_performance','model_quality_gate_evaluated','build','deployments',
            'heldout_windows','cases','rejections'}
    require(isinstance(doc,dict) and doc.keys() == keys | ({'quality_gate'} if has_gate else set()) and
            doc['schema'] == f'bmk.corad-worker-control/{3 if has_gate else 2}' and
            doc['config_id'] == bundle['config_id'] and doc['bundle_id'] == bundle['bundle_id'] and
            isinstance(doc['diagnostic_id'],str) and re.fullmatch(r'[a-f0-9]{32}',doc['diagnostic_id']) and
            doc['probe_sha256'] == driver_sha256 and doc['source_oracle_sha256'] == source_oracle_sha256 and
            all(doc[k] is False for k in ('formal_qualification','formal_performance')) and
            doc['model_quality_gate_evaluated'] is has_gate and
            doc['deployments'] == [m['definition'] for m in bundle['models']] and doc['heldout_windows'] == bundle['window'],
            'CORAD evidence is not bound to its driver, model, input or scope')
    verify_probe_build_lock(doc['build'],build,METHOD,dependency_count=1)
    src = bundle['input']
    raw = _bytes(out,src['path'],src['bytes'])
    require(len(raw) == src['bytes'] and _sha(raw) == src['sha256'],'CORAD original input differs from frozen window')
    require(isinstance(doc['cases'],list) and len(doc['cases']) == len(bundle['frames']),'CORAD result closure differs')
    limits = verify_bounds(out,policy,src['columns'],bundle['window']) if has_gate else None
    results = {}
    for spec, row in zip(bundle['frames'],doc['cases'],strict=True):
        original,restored = _verify_frame(out,raw,src,spec,row)
        if has_gate and spec['case']=='held-out':
            require(spec['route'] not in results, 'duplicate CORAD quality route')
            results[spec['route']] = assess(limits,original,restored)
    if has_gate:
        require(results.keys()=={m['definition']['training']['route'] for m in bundle['models']} and
                canonical_bytes(doc['quality_gate'])==canonical_bytes({'policy_id':policy['policy_id'],'heldout':results}),
                'CORAD empirical quality decisions differ from predeclared bounds')
    failures = doc['rejections']
    require(isinstance(failures,dict) and failures.keys() == bundle['rejections'].keys(),'CORAD refusal closure differs')
    for name,status in bundle['rejections'].items():
        result = failures[name]
        require(isinstance(result,dict) and result.keys() == {'status','returncode','no_outputs','diagnostic'} and
                type(result['status']) is int and result['status'] == status and type(result['returncode']) is int and
                result['returncode'] == 3 and result['no_outputs'] is True and isinstance(result['diagnostic'],str) and
                result['diagnostic'].startswith(f'plugin status {status}:'),f'CORAD expected refusal differs: {name}')


def _verify_frame(out, raw, src, spec, row):
    frame = _bytes(out,spec['path'],spec['max_frame_bytes'])
    original,restored,expect = frame_evidence(frame,raw,src,spec)
    require(canonical_bytes(row) == canonical_bytes(expect),f'CORAD reported restore, metrics or accounting differs: {spec["path"]}')
    return original,restored


def frame_evidence(frame, raw, src, spec):
    require(0 < len(frame) <= spec['max_frame_bytes'],'CORAD frame exceeds frozen retention limit')
    schema = bytes.fromhex(spec['schema_hex'])
    base = HEADER.size + len(schema)
    require(len(frame) >= base+NATIVE.size and HEADER.unpack_from(frame) ==
            (b'BMKCRD\x01\0',len(schema),0,len(frame)-base) and frame[HEADER.size:base] == schema,
            f'CORAD envelope or ordered schema differs: {spec["path"]}')
    payload = frame[base:]
    decoded, sections, embedded = interpret(payload)
    _,rows,cols,width,atoms,nonzero,threshold,_ = NATIVE.unpack_from(payload)
    native_config = dict(rows=rows,columns=cols,tricklet=width,atoms=atoms,nonzero=nonzero,threshold=threshold)
    model = NATIVE.pack(b'CRD1',0,cols,width,atoms,nonzero,threshold,NATIVE.size+len(embedded))+embedded
    require(native_config == spec['native_configuration'] and _sha(model) == spec['model_sha256'] and
            len(model) == spec['model_asset_bytes'],'CORAD embedded model or native configuration differs')
    original = [raw[i*src['rows']*8:i*src['rows']*8+rows*8] for i in range(cols)]
    restored = [decoded[i*rows*8:(i+1)*rows*8] for i in range(cols)]
    source_sha = _sha(b''.join(original))
    tail = rows%width*8
    require(source_sha == spec['source_sha256'] and
            (not tail or all(a[-tail:] == b[-tail:] for a,b in zip(original,restored,strict=True))),
            'CORAD original sample or exact tail differs')
    heldout = spec['case'] == 'held-out'
    require(not heldout or (sections['references']>0 and sections['sparse_records']>0),'CORAD held-out path lost a native branch')
    encode = dict(backend='corad-c-frozen',mode='batch',operation='encode',threads=1,columns=cols,rows=rows,
                  tricklet=width,fallback=False,embedded_model_bytes=len(embedded),tail_rows=rows%width,
                  external_deployment_loaded=True)
    expect = {k:spec[k] for k in ('path','case','route','deployment_id','encode_configuration_id','decode_configuration_id',
                                  'model_sha256','model_asset_bytes','columns')}
    expect.update(schema_sha256=_sha(schema),schema_bytes=len(schema),frame_header_bytes=HEADER.size,frame_bytes=len(frame),
                  native_bytes=len(payload),frame_sha256=_sha(frame),native_sha256=_sha(payload),logical_bytes=rows*cols*8,
                  source_sha256=source_sha,restored_sha256=_sha(decoded),descriptor={'columns':[{'dtype':10,'count':rows}]*cols},
                  quality_observed=quality(original,restored,spec['columns']),sections=sections,config=native_config,
                  encode=encode,decode={**encode,'operation':'decode','external_deployment_loaded':False},
                  pinned_decode={**encode,'operation':'decode'} if heldout else None)
    return original,restored,expect
