"""Execute precisely the frozen train prefix and all independent Zstd held-out frames."""
from hashlib import sha256
import shutil
import subprocess

from ..assets import ContractError, digest, local_file, parse_json, require
from ..corpus_ingress import read_batches
from ..planner.m3_zstd_dictionary import DRIVER, LIMIT, extents
from ..qualification.lzbench import zstd_frame
from .lzbench_profiles import _wrong_dictionary


def _call(exe,args,work,*,reject=None):
    p = subprocess.run([str(exe),*map(str,args)],cwd=work,env={'LC_ALL':'C'},capture_output=True,text=True,timeout=30)
    if reject:
        require(p.returncode==2 and not p.stdout and p.stderr.strip()==reject,'Zstd expected dictionary mismatch did not occur')
        return {'status':'expected_rejection','reason':reject,'returncode':p.returncode}
    require(p.returncode==0 and not p.stderr,f'Zstd dictionary {args[0]}: {p.stderr.strip() or p.returncode}')
    return parse_json(p.stdout,'Zstd native wrapper observation')


def _frame(exe,work,raw,encoded,decoded,size,dictionary,*,encode=False,reject=None):
    return _call(exe,['roundtrip' if encode else 'decode','zstd','frame',3,307,521,LIMIT,'reuse',1,
                     dictionary or '-',raw,encoded,decoded,size],work,reject=reject)


def _stage(root,item,entry,work):
    spans,each,count = extents(item,entry)
    width = entry['value_count']*8
    train = bytearray(); held = work/'test.v'
    with held.open('xb') as sink:
        for b in read_batches(root,entry):
            start = b.start*width; end = start+len(b.values)
            for (lo,hi),emit in zip(spans,(train.extend,sink.write),strict=True):
                if start<hi and lo<end:
                    emit(b.values[max(lo,start)-start:min(hi,end)-start])
    identity = {'bytes':held.stat().st_size,'sha256':digest(held)}
    test = entry['partitions'][2]
    require(len(train)==each*count and identity=={'bytes':spans[1][1]-spans[1][0],'sha256':test['canonical']['values_sha256']},
            'staged dictionary inputs differ from frozen train prefix or held-out object')
    paths = [work/f'train-{i:03d}' for i in range(count)]
    for i,path in enumerate(paths):
        path.write_bytes(train[i*each:(i+1)*each])
    return paths,sha256(train).hexdigest(),held,identity


def run_dictionary(root,plan,item,entry,work,run):
    exe = local_file(root,plan['build']['zstd_dictionary']['executable']['path'])
    train,train_hash,held,test = _stage(root,item,entry,work)
    spec = item['input']['training']; cap = spec['dictionary_capacity_bytes']; dictionary = work/'dict'
    base = {'driver':DRIVER,'tier':spec['extent_tier'],'sample_geometry':spec['sample_geometry'],
            'train_prefix_sha256':train_hash,'train_bytes':spec['consumed_byte_range'][1],'holdout':test,
            'holdout_object_id':spec['evaluation']['partition_object_id'],'timing_admitted':False,'fallback_used':False}
    try:
        observed = _call(exe,['train',cap,dictionary,*train],work)
    except (ContractError,OSError,subprocess.TimeoutExpired) as exc:
        return {**base,'failed_units':1,'phase':'native_training_failed','failure_reason':str(exc),'test_attempted':False,'frames':[]}
    d = dictionary.read_bytes(); did = int.from_bytes(d[4:8],'little')
    require(8<=len(d)<=cap and d[:4]==b'\x37\xa4\x30\xec' and did>1 and observed['dictionary_bytes']==len(d) and
            type(observed['training_ns']) is int and observed['training_ns']>=0,'Zstd trained dictionary has invalid identity or extent')
    wrong = work/'wrong-dict'; wrong.write_bytes(_wrong_dictionary(d))
    rel = f"retained/{item['work_item_id']}"
    artifacts = run/rel; artifacts.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(dictionary,artifacts/'trained.zdict')
    retained_dict = {'path':rel+'/trained.zdict','bytes':len(d),'sha256':sha256(d).hexdigest(),'id':did}
    frames=[]; total_frames=0; cursor=0; retained_frame=None; negatives=None
    with held.open('rb') as source:
        while data := source.read(LIMIT):
            unit = {'index':len(frames),'holdout_byte_range':[cursor,cursor+len(data)],'logical_bytes':len(data),
                    'input_sha256':sha256(data).hexdigest()}
            cursor += len(data)
            try:
                raw,wire,roundtrip,copied,restored = (work/p for p in ('original','wire','same','copied','restored'))
                raw.write_bytes(data)
                enc = _frame(exe,work,raw,wire,roundtrip,len(data),dictionary,encode=True)
                native = wire.read_bytes()
                header = zstd_frame(native)
                require(header['dictionary_id']==did and not header['checksum'] and header['content_size'] in (None,len(data)) and
                        enc['input_bytes']==len(data) and enc['encoded_bytes']==len(native) and roundtrip.read_bytes()==data,
                        'Zstd held-out frame or dictionary header differs')
                raw.unlink()
                _frame(exe,work,wire,copied,restored,len(data),dictionary)
                require(restored.read_bytes()==data and copied.read_bytes()==native,'Zstd held-out detached restore differs')
                if retained_frame is None:
                    miss,changed = {},{}
                    for label,arg,target in [('missing',None,miss),('wrong_id',wrong,changed)]:
                        before = (work/f'{label}-wire',work/f'{label}-raw')
                        event = _frame(exe,work,wire,*before,len(data),arg,reject='Dictionary mismatch')
                        require(not any(p.exists() for p in before),'rejected dictionary control published output')
                        target.update(event)
                    negatives = {'missing':miss,'wrong_id':changed}
                    shutil.copyfile(wire,artifacts/'sample.zst')
                    retained_frame = {'path':rel+'/sample.zst','bytes':len(native),'sha256':sha256(native).hexdigest(),
                                      'index':unit['index']}
                unit.update(status='verified',bytes=len(native),sha256=sha256(native).hexdigest(),dictionary_id=did,
                            restored_sha256=digest(restored))
                total_frames += len(native)
            except (ContractError,OSError,subprocess.TimeoutExpired) as exc:
                unit.update(status='failed',reason=str(exc))
            frames.append(unit)
    require(cursor==test['bytes'] and len(frames)+1==item['input']['size_estimate']['input_units'],'Zstd holdout frame coverage differs')
    failed = sum(u['status']=='failed' for u in frames)
    return {**base,'failed_units':failed,'phase':'heldout_validation','test_attempted':True,'frames':frames,
            'dictionary':retained_dict,'training_native_ns':observed['training_ns'],'negative_controls':negatives,
            'retained_frame':retained_frame,'verified_frame_bytes':total_frames,
            'verified_frame_bytes_plus_shared_dictionary_once':total_frames+len(d),'decode_scope':'frame_and_serialized_dictionary_only'}
