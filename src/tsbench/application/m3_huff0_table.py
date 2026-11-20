"""Train, load and reuse a native ETB1 table on each disjoint held-out object."""
import filecmp
from hashlib import sha256
import shutil
import subprocess

from ..assets import ContractError, canonical_bytes, digest, local_file, parse_json, require
from ..corpus_ingress import read_batches
from ..planner.huff0 import BLOCK, TABLE
from ..planner.m3_huff0_table import DRIVER, RETAIN_MAX, STREAMS, inputs
from ..qualification.huff0 import _bitstreams, _model


def asset(path):
    return {'bytes':path.stat().st_size,'sha256':digest(path)}


def stage(root,item,entry,work):
    spans=inputs(item,entry); width=8*entry['value_count']
    train=work/'train.v'; held=work/'holdout.v'
    with train.open('xb') as trainer,held.open('xb') as out:
        for batch in read_batches(root,entry):
            first=batch.start*width; end=first+len(batch.values)
            for (a,b),sink in zip(spans,(trainer,out),strict=True):
                if first<b and a<end:
                    sink.write(batch.values[max(a,first)-first:min(b,end)-first])
    training,holdout=asset(train),asset(held)
    require(training['bytes']==spans[0][1]-spans[0][0] and
            holdout=={'bytes':spans[1][1]-spans[1][0],'sha256':entry['partitions'][2]['canonical']['values_sha256']},
            'ETB1 staged data do not match the frozen extents')
    return train,held,training,holdout


def call(exe,*argv,cwd):
    trial=subprocess.run([str(exe),*map(str,argv)],cwd=cwd,env={'LC_ALL':'C'},capture_output=True,text=True,timeout=180)
    require(trial.returncode==0 and not trial.stderr,f'ETB1 {argv[0]}: {trial.stderr.strip() or trial.returncode}')
    return parse_json(trial.stdout,'ETB1 corpus observation')


def layout(wire,streams,total,*,original=None):
    records=[]; extent=0
    with wire.open('rb') as src:
        while h:=src.read(TABLE.size):
            require(len(h)==TABLE.size,'ETB1 partial record header')
            tag,n,c=TABLE.unpack(h)
            require(tag in (0,1) and n==min(BLOCK,total-extent)>0 and (0<c<n if tag else c==n),
                    'ETB1 record size/mode differs from frozen held-out blocks')
            data=src.read(c)
            require(len(data)==c,'ETB1 truncated record')
            if tag: _bitstreams(data,streams)
            if original is not None and not tag:
                original.seek(extent)
                require(original.read(n)==data,'ETB1 raw payload differs from original')
            records.append({'original_bytes':n,'body_bytes':c,'mode':'huffman' if tag else 'raw','sha256':sha256(h+data).hexdigest()})
            extent+=n
    require(extent==total and records,'ETB1 held-out coverage incomplete')
    return records


def binding(streams,model,wire):
    return canonical_bytes({'schema':'bmk.etb1-corpus-binding/1','streams':streams,'model':model,'block_sequence':wire})+b'\n'


def checked_identity(sidecar,streams,model,frame):
    require(sidecar==binding(streams,model,frame),'ETB1 SHA-256 model/block binding mismatch')


def run_table(root,plan,item,entry,work,run):
    exe=local_file(root,plan['build']['huff0_table']['executable']['path'])
    train,held,training,holdout=stage(root,item,entry,work)
    rows={}; paths={}; errors=[]
    for streams in STREAMS:
        folder=work/str(streams); folder.mkdir()
        model,wire,decoded=(folder/k for k in ('model.etb1','test.blocks','restored.v'))
        try:
            t=call(exe,'train',streams,train,model,cwd=folder)
            log=_model(model.read_bytes(),streams); mid=asset(model)
            require(t=={'streams':streams,'effective_table_log':log,'raw_bytes':training['bytes'],'wire_bytes':mid['bytes'],
                        'context_count':1,'blocks':0},'ETB1 native trainer accounting differs')
            e=call(exe,'encode',model,held,wire,cwd=folder)
            fid=asset(wire); sidecar=binding(streams,mid,fid)
            with held.open('rb') as original:
                blocks=layout(wire,streams,holdout['bytes'],original=original)
            require(sum(TABLE.size+b['body_bytes'] for b in blocks)==fid['bytes'] and
                    len(blocks)+1==item['input']['size_estimate']['input_units'],'ETB1 frame budget or block count differs')
            checked_identity(sidecar,streams,asset(model),asset(wire))
            d=call(exe,'decode',model,wire,decoded,cwd=folder)
            require(d==e=={'streams':streams,'effective_table_log':log,'blocks':len(blocks),'raw_bytes':holdout['bytes'],
                           'wire_bytes':fid['bytes'],'context_count':1} and filecmp.cmp(decoded,held,shallow=False),
                    'ETB1 file-only restore or native reuse evidence differs')
            retained={}
            if fid['bytes']<=RETAIN_MAX:
                rel=f"retained/{item['work_item_id']}/{streams}x"
                out=run/rel; out.mkdir(parents=True,exist_ok=False)
                for p,ref in ((model,mid),(wire,fid)):
                    shutil.copyfile(p,out/p.name)
                    retained[p.name]={'path':f'{rel}/{p.name}',**ref}
                (out/'binding.json').write_bytes(sidecar)
                retained['binding.json']={'path':f'{rel}/binding.json',**asset(out/'binding.json')}
            paths[streams]=(mid,fid,sidecar)
            rows[str(streams)]={'status':'verified','model':mid,'frame':fid,'binding':{'bytes':len(sidecar),'sha256':sha256(sidecar).hexdigest()},
                               'blocks':blocks,'train':t,'encode':e,'decode':d,'recovered':holdout,'retained':retained,
                               'complete_bytes':fid['bytes']+mid['bytes']+len(sidecar)}
        except (ContractError,OSError,subprocess.TimeoutExpired) as exc:
            rows[str(streams)]={'status':'failed','reason':str(exc)}
            errors.append(f'{streams}X: {exc}')
    if not errors:
        for streams in STREAMS:
            _,fid,sidecar=paths[streams]
            alternate=paths[4 if streams==1 else 1][0]
            try:
                checked_identity(sidecar,streams,alternate,fid)
            except ContractError as exc:
                rows[str(streams)]['different_valid_model_binding_rejection']={'status':'expected_rejection','reason':str(exc),
                       'native_decode_started':False}
            else:
                errors.append(f'{streams}X: different model matched SHA-256 binding')
    return {'driver':DRIVER,'training':training,'holdout':holdout,'profiles':rows,'errors':errors,
            'verification':'detached_decode_model_plus_etb1_blocks_and_preflight_hash_binding','timing_admitted':False}
