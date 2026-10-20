#!/usr/bin/env python3
"""Read-only codec audit against independent, unmodified lzbench source wrappers.

Run with PYTHONPATH=benchmark/src. Writes only a new evidence directory and
content-addressed Bench builds. No codec source/registry changes. Oracle XZ uses
upstream CMake's static liblzma; other libraries use Makefile-style release flags.
This is a source-wrapper oracle, not a run of the lzbench performance executable.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE_DEFAULT = Path('/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/inikep_lzbench')
KEYS = ['zstd-frame','lz4-frame','snappy-raw','deflate-zlib','brotli-stream','bzip2-stream','xz-stream','lzsse2-raw','lzsse8-raw','lzss-raw','lzss-dipperstein-c']
IDS = {'zstd-frame':0,'lz4-frame':1,'snappy-raw':2,'deflate-zlib':3,'brotli-stream':4,'bzip2-stream':5,'xz-stream':6,'lzsse2-raw':7,'lzsse8-raw':8}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(b): return hashlib.sha256(b).hexdigest()
def dump(p, v): Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')

def run(cmd, cwd=None):
    p=subprocess.run(list(map(str,cmd)),cwd=cwd,capture_output=True,text=True,timeout=600)
    if p.returncode: raise RuntimeError(f'{cmd}\n{p.stdout}\n{p.stderr}')
    return p.stdout+p.stderr


def inventory(base, output):
    rows=[]
    for k in IDS:
        card=json.loads((ROOT/'registry/sources'/f'{k}-lzbench.artifact.json').read_text())
        folder=ROOT/'adapters'/k.replace('-','_')/'vendor'
        files=[]
        for p in sorted(folder.rglob('*')):
            if not p.is_file():continue
            rel=p.relative_to(folder)
            target=base/'lz'/rel if k.startswith('lzsse') else base/card['identity']['benchmark_path']/Path(*rel.parts[1:])
            files.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p),'upstream':str(target.relative_to(base)),
                          'upstream_sha256':sha(target) if target.is_file() else None,'equal':target.is_file() and sha(p)==sha(target)})
        rows.append({'key':k,'source_identity':card['identity'],'files':files})
    dump(output/'source_inventory.json',rows)
    return rows


def build_oracle(base, output):
    """Compile complete upstream wrapper TUs, disabling unrelated codec groups."""
    work=output/'oracle';work.mkdir()
    cxx=shutil.which('c++');cc=shutil.which('cc')
    keep={'ZSTD','LZ4','SNAPPY','ZLIB','BROTLI','BZIP2','XZ','LZSSE'}
    wrappers=[base/'bench/lz_codecs.cpp',base/'bench/symmetric_codecs.cpp']
    macro_text='\n'.join(p.read_text() for p in [*wrappers,base/'bench/codecs.h'])
    disabled=sorted(set(re.findall(r'BENCH_REMOVE_\w+',macro_text))-{f'BENCH_REMOVE_{s}' for s in keep})
    flags=['-O3','-DNDEBUG','-fPIC','-fomit-frame-pointer','-fstrict-aliasing','-ffast-math',
           '-Wno-unknown-pragmas','-Wno-sign-compare','-Wno-conversion']
    common=['-I'+str(base),'-I'+str(base/'lz'),'-I'+str(base/'lz/brotli/include')]
    commands=[]
    def command(cmd):
        commands.append(list(map(str,cmd)))
        return run(cmd,base)
    # XZ source is independent of Bench. Record CMake differences explicitly.
    xz=base/'lz/xz';xzbuild=work/'xz'
    command(['cmake','-S',xz,'-B',xzbuild,'-DCMAKE_BUILD_TYPE=Release','-DBUILD_SHARED_LIBS=OFF',
             '-DCMAKE_POSITION_INDEPENDENT_CODE=ON','-DXZ_TOOL_XZ=OFF','-DXZ_TOOL_XZDEC=OFF',
             '-DXZ_TOOL_LZMADEC=OFF','-DXZ_TOOL_LZMAINFO=OFF','-DXZ_TOOL_SCRIPTS=OFF',
             '-DXZ_DOC=OFF','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'])
    command(['cmake','--build',xzbuild,'--target','liblzma','--parallel','2'])
    sources=[]
    def add(paths, extra=()):
        for p in paths:sources.append((p,list(extra)))
    z=base/'lz/zstd/lib'
    add(sorted(p for d in ['common','compress','decompress','dictBuilder'] for p in (z/d).glob('*.c')),['-DZSTD_MULTITHREAD'])
    add([z/'decompress/huf_decompress_amd64.S'])
    l=base/'lz/lz4/lib';add([l/n for n in ['lz4.c','lz4hc.c','lz4frame.c','xxhash.c']])
    s=base/'lz/snappy';add([s/n for n in ['snappy.cc','snappy-sinksource.cc','snappy-stubs-internal.cc']],['-DHAVE_BUILTIN_CTZ'])
    z=base/'lz/zlib';add([z/n for n in ['adler32.c','compress.c','crc32.c','deflate.c','gzclose.c','gzlib.c','gzread.c','gzwrite.c','infback.c','inffast.c','inflate.c','inftrees.c','trees.c','uncompr.c','zutil.c']],['-DZ_HAVE_UNISTD_H'])
    b=base/'lz/brotli';add(sorted(p for d in ['common','enc','dec'] for p in (b/d).glob('*.c')))
    b=base/'bwt/bzip2';add([b/n for n in ['blocksort.c','huffman.c','crctable.c','randtable.c','compress.c','decompress.c','bzlib.c']])
    add([base/f'lz/lzsse/lzsse{n}/lzsse{n}.cpp' for n in [2,4,8]],['-msse4.1'])
    add(wrappers,['-D'+m for m in disabled])
    bridge=work/'bridge.cpp'
    bridge.write_text('''#include "bench/codecs.h"
#include "lz/lz4/lib/lz4frame.h"
#include "lz/xz/src/liblzma/api/lzma.h"
#include <stdint.h>
extern "C" {
void* audit_init(int id, size_t n, int level) {
 switch(id) {case 0:return lzbench_zstd_init(n,level,0);case 7:return lzbench_lzsse2_init(n,level,0);case 8:return lzbench_lzsse8_init(n,level,0);default:return nullptr;}
}
void audit_free(int id, char* c) {switch(id){case 0:lzbench_zstd_deinit(c);break;case 7:lzbench_lzsse2_deinit(c);break;case 8:lzbench_lzsse8_deinit(c);break;}}
int64_t audit_call(int id,int decode,char* in,size_t n,char* out,size_t cap,int level,int param,int threads,char* state) {
 codec_options_t c{level,param,state,threads};
#define CALL(N) return decode?lzbench_##N##_decompress(in,n,out,cap,&c):lzbench_##N##_compress(in,n,out,cap,&c)
 switch(id){case 0:CALL(zstd);case 1:CALL(lz4);case 2:CALL(snappy);case 3:CALL(zlib);case 4:CALL(brotli);case 5:CALL(bzip2);case 6:CALL(xz);case 7:CALL(lzsse2);case 8:CALL(lzsse8);default:return -999;}
}
// Supplementary references: these are explicitly NOT lzbench table entries.
size_t audit_lz4_frame(char* in,size_t n,char* out,size_t cap,int level) {
 LZ4F_preferences_t p{};p.compressionLevel=level;p.frameInfo.blockSizeID=LZ4F_max64KB;
 p.frameInfo.blockMode=LZ4F_blockIndependent;p.frameInfo.contentChecksumFlag=LZ4F_contentChecksumEnabled;
 p.frameInfo.contentSize=n;LZ4F_compressionContext_t ctx;
 if(LZ4F_isError(LZ4F_createCompressionContext(&ctx,LZ4F_VERSION)))return SIZE_MAX;
 size_t a=LZ4F_compressBegin(ctx,out,cap,&p),b=0,c=0;
 if(!LZ4F_isError(a))b=LZ4F_compressUpdate(ctx,out+a,cap-a,in,n,nullptr);
 if(!LZ4F_isError(a)&&!LZ4F_isError(b))c=LZ4F_compressEnd(ctx,out+a+b,cap-a-b,nullptr);
 LZ4F_freeCompressionContext(ctx);if(LZ4F_isError(a)||LZ4F_isError(b)||LZ4F_isError(c))return SIZE_MAX;return a+b+c;
}
size_t audit_xz_easy(char* in,size_t n,char* out,size_t cap,int level) {
 size_t pos=0;auto s=lzma_easy_buffer_encode(level,LZMA_CHECK_NONE,nullptr,(const uint8_t*)in,n,(uint8_t*)out,&pos,cap);return s==LZMA_OK?pos:SIZE_MAX;
}
size_t audit_lz4_frame_decode(char* in,size_t n,char* out,size_t cap) {
 LZ4F_decompressionContext_t ctx;LZ4F_createDecompressionContext(&ctx,LZ4F_VERSION);
 size_t a=0,b=0,next=1;
 while(next){size_t x=n-a,y=cap-b;next=LZ4F_decompress(ctx,out+b,&y,in+a,&x,nullptr);a+=x;b+=y;if(LZ4F_isError(next)||(!x&&!y)){b=SIZE_MAX;break;}}
 LZ4F_freeDecompressionContext(ctx);return a==n?b:SIZE_MAX;
}
}
''')
    add([bridge],['-D'+m for m in disabled])
    def compile_one(job):
        i,(source,extra)=job;obj=work/f'{i:03d}.o';dep=obj.with_suffix('.d')
        compiler=cxx if source.suffix in {'.cc','.cpp'} else cc
        cmd=[compiler,*flags,*common,*extra,'-MD','-MF',dep,'-c',source,'-o',obj]
        return obj,cmd,run(cmd,base)
    jobs=list(enumerate(sources));objects=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for obj,cmd,log in pool.map(compile_one,jobs):objects.append(obj);commands.append(list(map(str,cmd)))
    lib=work/'liblzbench_oracle.so'
    command([cxx,'-shared','-Wl,-Bsymbolic-functions','-Wl,--no-undefined',*objects,xzbuild/'liblzma.a','-pthread','-lm','-o',lib])
    dependencies=set()
    for p in work.glob('*.d'):
        import shlex
        dependencies.update(Path(x).resolve() for x in shlex.split(p.read_text().replace('\\\n','').split(':',1)[1]))
    xzcommands=json.loads((xzbuild/'compile_commands.json').read_text())
    for entry in xzcommands:dependencies.add(Path(entry['file']).resolve())
    record={'kind':'INDEPENDENT_UNMODIFIED_LZBENCH_WRAPPER_SOURCE_ORACLE','upstream':str(base),'commit':run(['git','rev-parse','HEAD'],base).strip(),
            'status':run(['git','status','--short'],base),'library':str(lib),'library_sha256':sha(lib),
            'commands':commands,'compilers':{s:run([s,'--version']).splitlines()[0] for s in [cc,cxx]},
            'sources':[{'path':str(p),'sha256':sha(p)} for p,_ in sources],
            'dependencies':[{'path':str(p),'sha256':sha(p)} for p in sorted(dependencies)],
            'xz_compile_commands':xzcommands,'limitations':['Wrapper oracle; not the full performance executable.','XZ uses upstream CMake configuration, not lzbench Makefile configuration.','No -march=native; optional platform-specific branches beyond this build are not claimed.']}
    dump(work/'build.json',record)
    return lib


class Oracle:
    def __init__(self,p):
        self.lib=C.CDLL(str(p),mode=os.RTLD_LOCAL)
        self.lib.audit_init.argtypes=[C.c_int,C.c_size_t,C.c_int];self.lib.audit_init.restype=C.c_void_p
        self.lib.audit_free.argtypes=[C.c_int,C.c_void_p]
        self.lib.audit_call.argtypes=[C.c_int,C.c_int,C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.c_int,C.c_int,C.c_int,C.c_void_p];self.lib.audit_call.restype=C.c_int64
        for name in ['audit_lz4_frame','audit_xz_easy']:
            f=getattr(self.lib,name);f.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.c_int];f.restype=C.c_size_t
        self.lib.audit_lz4_frame_decode.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t];self.lib.audit_lz4_frame_decode.restype=C.c_size_t
    def call(self,key,decode,data,n,level,param=0):
        i=IDS[key];ctx=self.lib.audit_init(i,max(1,n),level)
        assert i not in (0,7,8) or ctx
        cap=max(1024,n*2+65536) if not decode else max(1,n)
        out=C.create_string_buffer(cap);src=C.create_string_buffer(data)
        try:used=self.lib.audit_call(i,int(decode),src,len(data),out,n if decode else cap,level,param,1,ctx)
        finally:self.lib.audit_free(i,ctx)
        if used<0 or used>cap:raise RuntimeError(f'oracle {key} decode={decode} returned {used}')
        return out.raw[:used]
    def extra(self,name,data,n,level=0):
        cap=max(1024,n*2+65536);out=C.create_string_buffer(cap);src=C.create_string_buffer(data)
        f=getattr(self.lib,name)
        used=f(src,len(data),out,cap,level) if name!='audit_lz4_frame_decode' else f(src,len(data),out,cap)
        if used>cap:raise RuntimeError(f'{name}: {used}')
        return out.raw[:used]


def inputs(output):
    items=[];rng=random.Random(20261017)
    for n in [0,1,15,31,32,63,64,257,4096,65536,65537,131073]:
        for kind in ['zero','random','pattern']:
            if n>4096 and kind=='zero':continue
            data=bytes(n) if kind=='zero' else rng.randbytes(n) if kind=='random' else (b'0123456789 time-series ALPHA\0'*((n+26)//27))[:n]
            assert len(data)==n
            items.append((f'{kind}-{n}',data,{'kind':kind}))
    old=ROOT/'runs/lzbench-payload-check-20261015/results.json'
    if old.exists():
        d=json.loads(old.read_text())
        # The historical file explicitly separates input bytes from compressed artifacts.
        seen=set()
        for entry in d['cases']:
            p=old.parent/entry['input']['path']
            assert sha(p)==entry['input']['sha256']
            if sha(p) not in seen:
                seen.add(sha(p));items.append((f'real-{len(seen)}',p.read_bytes(),
                    {'kind':'historical_real_window','source':str(p),'dataset':entry['dataset'],
                     'dtype':entry['dtype'],'shape':entry['shape'],'order':entry['order']}))
    target=output/'inputs';target.mkdir()
    rows=[]
    for name,data,meta in items:
        p=target/f'{name}.bin';p.write_bytes(data);rows.append({'name':name,'path':str(p),'bytes':len(data),'sha256':digest(data),**meta})
    dump(output/'inputs.json',rows)
    return items


def check(output, library, cases):
    import numpy as np
    from tsbench import native
    from tsbench.build import build_codec
    from tsbench.registry import Registry
    from tsbench.config import DEFAULT_TASK,DEFAULT_PROFILE,DEFAULT_EXECUTION
    from tsbench.data import TimeSeriesObject
    build_root=ROOT/'build/tsbench'
    builds={}
    for key in KEYS:
        builds[key]=build_codec(ROOT,key)
        print('Bench build verified:',key,flush=True)
    native.ensure_driver(ROOT,build_root)
    dump(output/'bench_builds.json',builds)
    oracle=Oracle(library);reg=Registry(ROOT);rows=[]
    for key in KEYS:
        variants=[('default',{})]
        if key=='zstd-frame':variants.append(('lzbench-checksum-off',{'content_checksum':False}))
        if key in {'deflate-zlib','brotli-stream','bzip2-stream','xz-stream'}:variants.append(('level1',{'compression_level':1}))
        if key=='deflate-zlib':variants.append(('window9',{'window_bits':9}))
        if key=='brotli-stream':variants.append(('window18',{'window_bits':18}))
        for variant,overrides in variants:
            for name,data,meta in cases:
                where=output/'cases'/key/variant/name;where.mkdir(parents=True)
                params={**reg.resolve_params(key),**overrides}
                method={'id':key,'codec':key,'params':params}
                task={**DEFAULT_TASK,'boundary':'native_core','lifecycle':'prepared'}
                execution={**DEFAULT_EXECUTION,'native_loops':2,'native_warmup_loops':1,'native_batch_memory_mb':64,'timeout_s':90}
                obj=TimeSeriesObject({'V':np.frombuffer(data,dtype='u1').copy()},{'roles':{'V':'V'},'masked_value_policy':'preserve_all_bits'})
                support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,build_root)
                row={'codec':key,'variant':variant,'case':name,'input_bytes':len(data),'input_sha256':digest(data),'parameters':params}
                try:
                    assert support['supported'],support
                    h=native.NativeMeasurement(method,task,execution,support,ROOT,build_root);h.prepare(obj)
                    measured,_=h.measure(obj,independent=True,artifact_dir=where/'bench')
                    assert measured['status']=='ok' and measured['verification']['passed'] and measured['independent_recovery']['passed'],measured
                    payload=Path(measured['artifact_path']).read_bytes()
                    row.update(bench_roundtrip=True,bench_cold_decode=True,bench_complete_bytes=len(payload),bench_sha256=digest(payload))
                    dump(where/'bench_row.json',measured)
                    if key in IDS:
                        level=params.get('compression_level',0);param=params.get('window_bits',0) if key=='brotli-stream' else 0
                        reference=oracle.call(key,False,data,len(data),level,param)
                        (where/'oracle.bin').write_bytes(reference)
                        row.update(oracle_bytes=len(reference),oracle_sha256=digest(reference),complete_equal=payload==reference,
                                   oracle_roundtrip=oracle.call(key,True,reference,len(data),level,param)==data)
                        native_payload=payload[8:] if key.startswith('lzsse') else payload
                        row['core_payload_equal']=native_payload==reference
                        row['cross_reference']='SUPPLEMENTARY_LZ4_FRAME_API' if key=='lz4-frame' else 'LZBENCH_WRAPPER_RAW_PAYLOAD_WITH_LENGTH_PREFIX_RECONSTRUCTED' if key.startswith('lzsse') else 'LZBENCH_WRAPPER_COMPLETE_STREAM'
                        # Frame vs raw has no shared stream format. Confirm each separately.
                        if key=='lz4-frame':
                            alt=oracle.extra('audit_lz4_frame',data,len(data),level)
                            row['matched_frame_reference_equal']=alt==payload
                            row['oracle_decode_bench']=oracle.extra('audit_lz4_frame_decode',payload,len(data))==data
                            cross=alt
                        else:
                            row['oracle_decode_bench']=oracle.call(key,True,native_payload,len(data),level,param)==data
                            cross=len(data).to_bytes(8,'little')+reference if key.startswith('lzsse') else reference
                        if key=='xz-stream':row['matched_easy_reference_equal']=oracle.extra('audit_xz_easy',data,len(data),level)==payload
                        # A cold driver with empty config consumes independent oracle output.
                        crosspath=where/'cross-input.bin';crosspath.write_bytes(cross)
                        empty=where/'empty-config';empty.write_bytes(b'{}')
                        cmd=[h.record['binary'],'--abi',h.abi,'--library',support['library_path'],'--codec',key,
                             '--input',str(crosspath),'--config-file',str(empty),'--output-bytes',str(len(data)),
                             '--decode-only','--loops','1','--warmup','0','--result-dir',str(where/'cross-decode'),
                             '--memory-bytes',str(64<<20)]
                        if h.abi=='core':cmd+=['--dtype-code','2','--shape',str(len(data))]
                        result=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
                        dump(where/'cross-process.json',{'command':cmd,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
                        restored=list((where/'cross-decode').glob('*restored*.bin'))
                        row['bench_decode_oracle']=result.returncode==0 and len(restored)==1 and restored[0].read_bytes()==data
                    else:row['lzbench_comparator']='NOT_REGISTERED'
                    for field in ['bench_roundtrip','bench_cold_decode','oracle_roundtrip','bench_decode_oracle','oracle_decode_bench','matched_frame_reference_equal','matched_easy_reference_equal']:
                        if field in row:assert row[field] is True,(field,row)
                except Exception as error:
                    row['error']=str(error)
                rows.append(row)
                dump(output/'results.json',rows)
        subset=[r for r in rows if r['codec']==key]
        print(key,'cases',len(subset),'errors',sum('error'in r for r in subset),'complete equal',sum(r.get('complete_equal',False) for r in subset),'cross',sum(r.get('bench_decode_oracle',False) for r in subset),flush=True)
    return rows


def main():
    p=argparse.ArgumentParser();p.add_argument('--upstream',type=Path,default=BASE_DEFAULT);p.add_argument('--output',type=Path,required=True);p.add_argument('--reuse-oracle',type=Path);a=p.parse_args()
    output=a.output.resolve();base=a.upstream.resolve()
    output.mkdir(parents=True,exist_ok=False);inventory(base,output)
    shutil.copy2(__file__,output/'audit_script.py')
    if a.reuse_oracle:
        library=a.reuse_oracle.resolve();record=json.loads(library.with_name('build.json').read_text())
        assert record['library_sha256']==sha(library)
        assert all(sha(r['path'])==r['sha256'] for r in record['sources'])
        dump(output/'oracle_reference.json',{'path':str(library),'sha256':sha(library),'build_record':str(library.with_name('build.json')),'build_record_sha256':sha(library.with_name('build.json'))})
    else:library=build_oracle(base,output)
    cases=inputs(output)
    rows=check(output,library,cases)
    dump(output/'summary.json',{'script_sha256':sha(__file__),'cases':len(rows),'errors':[r for r in rows if 'error'in r],
         'per_codec':{k:{'cases':len([r for r in rows if r['codec']==k]),'complete_equal':sum(r.get('complete_equal',False) for r in rows if r['codec']==k),
                        'core_payload_equal':sum(r.get('core_payload_equal',False) for r in rows if r['codec']==k),
                        'cross_decode':sum(r.get('bench_decode_oracle',False) and r.get('oracle_decode_bench',False) for r in rows if r['codec']==k)} for k in KEYS}})

    if any('error' in r for r in rows):raise SystemExit(1)

if __name__=='__main__':main()
