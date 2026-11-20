"""Execute matched worker lanes; restore each encoded frame via a new native process."""
import filecmp
from mmap import ACCESS_READ, mmap
import shutil
import subprocess

from ..assets import digest, local_file, parse_json, require
from ..planner.m3_lzbench_workers import BLOCK_SIZE, DRIVER, JOB_SIZE, MAX_FRAME_RETAINED, MEMORY_BYTES, input_size
from ..qualification.lzbench import xz_blocks, zstd_frame

LANES = {'zstd':('0','2'), 'xz':('synchronous','1','2')}
ZERO = {'jobs':0,'worker_threads':0,'caller_jobs':0}


class _Wire:
    """Supply the read-only buffer operations needed by the audited wire parsers."""
    def __init__(self,mapping): self.mapping=mapping
    def __len__(self): return len(self.mapping)
    def __getitem__(self,key): return self.mapping[key]
    def startswith(self,prefix): return self.mapping[:len(prefix)]==prefix
    def endswith(self,suffix): return self.mapping[-len(suffix):]==suffix


def wire_info(path,codec,size):
    with path.open('rb') as fd,mmap(fd.fileno(),0,access=ACCESS_READ) as mm:
        wire=_Wire(mm)
        if codec=='zstd':
            h=zstd_frame(wire)
            require(h['dictionary_id']==0 and not h['checksum'] and h['content_size'] in (None,size),
                    'Zstd worker frame changed common wire options')
            return h
        blocks=xz_blocks(wire)
        require(mm[7]==4 and [b['raw'] for b in blocks]==[min(BLOCK_SIZE,size-at) for at in range(0,size,BLOCK_SIZE)] and
                all(b['filters'] in ([(0x21,b'\x10')],[(0x21,b'\x00')]) for b in blocks),
                'XZ worker frame Index, check or LZMA2 property differs')
        return {'block_bytes':BLOCK_SIZE,'check':4,'blocks':len(blocks),
                'preset_dictionary_blocks':sum(b['filters']==[(0x21,b'\x10')] for b in blocks),
                'fallback_dictionary_blocks':sum(b['filters']==[(0x21,b'\x00')] for b in blocks)}


def invoke(exe,codec,operation,lane,source,dest,cap):
    p=subprocess.run([str(exe),codec,operation,lane,str(source),str(dest),str(cap)],cwd=dest.parent,
                     env={'LC_ALL':'C'},capture_output=True,text=True,timeout=300)
    require(p.returncode==0 and not p.stderr,f'lzbench worker {codec} {operation}/{lane}: {p.stderr.strip() or p.returncode}')
    proof=parse_json(p.stdout,'native lzbench worker observation')
    require(proof['input_bytes']==source.stat().st_size and proof['output_bytes']==dest.stat().st_size and
            0<proof['output_bytes']<=cap and proof['calls']>0,'lzbench native worker extents differ')
    return proof


def _obs(doc,want,entry,length,out):
    work=doc['jobs']
    require(doc['entry']==entry and (doc['input_bytes'],doc['output_bytes'])==(length,out) and
            work.keys()==ZERO.keys() and all(type(n) is int and n>=0 for n in work.values()) and
            work['worker_threads']+work['caller_jobs']<=work['jobs'] and isinstance(doc['effective_parameters'],dict),
            'lzbench native worker observation or API identity differs')
    observed=work['worker_threads']
    return observed==want and (want!=0 or work==ZERO)


def outcome(proof):
    """Recompute the acceptance of observed work separately from wire/recovery success."""
    codec=proof['codec']; source=proof['source']; size=source['bytes']
    enc=proof['encode']; dec=proof['decode_own']; common=proof['decode_shared']; options=[]; misses=[]
    require(set(enc)==set(dec)==set(LANES[codec]) and set(common)==(set(LANES['xz']) if codec=='xz' else set()),
            'lzbench worker observation denominator differs')
    api='lzbench_native::session::process'
    for lane in LANES[codec]:
        record=enc[lane]; obs=record['observed']; frame=record['frame']; requested=0 if lane=='synchronous' else int(lane)
        synchronous=lane=='synchronous'; shape=record['wire']
        if not _obs(obs,requested,'lzma_block_encoder' if synchronous else api,size,frame['bytes']):
            misses.append('encode:'+lane)
        e=obs['effective_parameters']
        if codec=='zstd':
            require(all(e.get(k)==v for k,v in {'level':3,'job_size':JOB_SIZE,'workers':requested,'checksum':0}.items()) and
                    not shape['checksum'] and shape['dictionary_id']==0 and shape['content_size'] in (None,size),
                    'Zstd effective worker/wire options differ')
            options.append({k:v for k,v in e.items() if k!='workers'})
        else:
            require(all(e.get(k)==v for k,v in {'block_size':BLOCK_SIZE,'preset':1,'memory_limit':MEMORY_BYTES,'check':4,
                                               'dict_size':1<<20}.items()) and shape['check']==4 and
                    shape['blocks']==(size+BLOCK_SIZE-1)//BLOCK_SIZE==shape['preset_dictionary_blocks']+shape['fallback_dictionary_blocks'],
                    'XZ common block, preset, filter or memory options differ')
            if synchronous:
                require(e['filter_id']==0x21 and 0<e['raw_encoder_memory_bytes']<=MEMORY_BYTES and
                        obs['blocks']==shape['blocks'] and obs['uncompressed_fallback_blocks']==shape['fallback_dictionary_blocks'],
                        'XZ caller Block properties differ')
            else:
                require(e['threads']==requested and 0<e['encoder_memory_bytes']<=MEMORY_BYTES and
                        all(e[f'filter{i}']==0 for i in range(3)),'XZ worker effective encoder options differ')
                options.append({k:v for k,v in e.items() if k not in {'threads','encoder_memory_bytes'}})
        own=dec[lane]; own_obs=own['observed']; entry='lzma_stream_decoder' if synchronous else api
        require(own['source_frame']==frame and own['restored']==source,'lzbench worker own-frame restoration binding differs')
        if codec=='zstd' or synchronous:
            if not _obs(own_obs,0,entry,frame['bytes'],size): misses.append('decode-own:'+lane)
        else:
            workers=own_obs['jobs']['worker_threads']
            require(workers<=requested,'XZ worker own-frame decoder exceeded profile budget')
            _obs(own_obs,workers,entry,frame['bytes'],size)
        if codec=='xz':
            shared=common[lane]; match=enc['2']['frame']
            require(shared['source_frame']==match and shared['restored']==source,'XZ shared decode did not use the same frame')
            if not _obs(shared['observed'],requested,entry,match['bytes'],size): misses.append('decode-shared:'+lane)
    require(options[0]==options[1],'lzbench worker lanes diverged in additional effective encoder parameters')
    return misses


def artifact(path):
    return {'bytes':path.stat().st_size,'sha256':digest(path)}


def run_workers(root,plan,item,entry,staged,work,run):
    size=input_size(item,entry)
    raw,=staged['paths']
    identity=artifact(raw)
    require(identity=={'bytes':size,'sha256':entry['canonical']['values_sha256']},'worker input differs from frozen complete V object')
    codec=item['route'].split('-')[0]
    exe=local_file(root,plan['build']['lzbench_workers']['executable']['path'])
    source_frames={}; enc={}; own={}; shared={}
    output=work/'restored.bin'
    def restore(lane,path,frame):
        observed=invoke(exe,codec,'decode',lane,path,output,size)
        require(filecmp.cmp(raw,output,shallow=False),'lzbench worker detached restoration differs bitwise')
        return {'source_frame':frame,'observed':observed,'restored':identity}
    for lane in LANES[codec]:
        path=work/f'{lane}.frame'
        observed=invoke(exe,codec,'encode',lane,raw,path,size+size//10+65536)
        frame=artifact(path); wire=wire_info(path,codec,size)
        source_frames[lane]=path
        enc[lane]={'observed':observed,'frame':frame,'wire':wire}
        decode_lane=lane if codec=='xz' else '0'
        if not (codec=='xz' and lane=='2'):
            own[lane]=restore(decode_lane,path,frame)
    if codec=='xz':
        for lane in LANES[codec]: shared[lane]=restore(lane,source_frames['2'],enc['2']['frame'])
        own['2']=shared['2']  # One independent restore meets both identities; no double charge.
    retained={}
    for lane,path in source_frames.items():
        frame=enc[lane]['frame']
        if frame['bytes']<=MAX_FRAME_RETAINED:
            rel=f"retained/{item['work_item_id']}/{lane}.frame"
            dest=run/rel; dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,dest)
            retained[lane]={'path':rel,**frame}
    proof={'driver':DRIVER,'codec':codec,'source':identity,'encode':enc,'decode_own':own,'decode_shared':shared,
           'retained':retained,'all_encoded_frames_equal':len({rec['frame']['sha256'] for rec in enc.values()})==1,
           'timing_admitted':False,'parallelism_evidence':'distinct native worker-hook thread ids per process and direction'}
    proof['unmet_worker_observations']=outcome(proof)
    return proof
