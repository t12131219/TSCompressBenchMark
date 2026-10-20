#!/usr/bin/env python3
"""Independent fresh-source comparison and full-column real-corpus validation.
No imports from Benchmark. All emitted objects include source and frame costs.
"""
import argparse
import csv
import hashlib
import json
import pathlib
import random
import struct
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = ['ETTh1', 'ETTh2', 'ETTm1', 'ETTm2', 'exchange_rate', 'national_illness', 'weather']

def sha(data):
    return hashlib.sha256(data).hexdigest()

def run(command, log):
    start = time.perf_counter_ns()
    p = subprocess.run([str(x) for x in command], capture_output=True, text=True)
    entry = {'argv': [str(x) for x in command], 'returncode': p.returncode,
             'stdout': p.stdout, 'stderr': p.stderr, 'wall_ns': time.perf_counter_ns()-start}
    log.append(entry)
    if p.returncode:
        raise RuntimeError(json.dumps(entry))
    return p.stdout

def methods_in(frame):
    # Parse lengths independently to account for actual adaptive branch count.
    d = frame[8]; n = struct.unpack_from('<Q', frame, 12)[0]; at = 32
    branches = {'ALP': 0, 'ALP_RD': 0, 'RAW': 0}
    for start in range(0, n, 102400):
        scheme, right, left, dictionary, group = struct.unpack_from('<BBBBI', frame, at)
        at += 32
        branches['ALP_RD' if scheme == 1 else 'ALP'] += (group+1023)//1024
        for k in range(0, group, 1024):
            logical, ec, bw, fac, exp, zero, base = struct.unpack_from('<HHBBBBQ', frame, at)
            at += 16
            at += (right+left)*128 + ec*4 if scheme == 1 else bw*128 + ec*(2+d)
    if at != len(frame):
        raise RuntimeError('independent frame accounting mismatch')
    return branches

def undefined_source_factors(frame):
    # Fixed source-defect predicate, not a blanket exemption for differences.
    d=frame[8]; n=struct.unpack_from('<Q',frame,12)[0]; at=32;bad=[]
    for start in range(0,n,102400):
        scheme,right,left,ds,group=struct.unpack_from('<BBBBI',frame,at);at+=32
        for k in range(0,group,1024):
            logical,ec,bw,fac,exp,zero,base=struct.unpack_from('<HHBBBBQ',frame,at)
            if scheme==2 and fac >= (10 if d==4 else 19):
                bad.append({'offset':start+k,'factor':fac,'exponent':exp})
            at+=16+((right+left)*128+ec*4 if scheme==1 else bw*128+ec*(2+d))
    return bad

def fixtures():
    rng = random.Random(0x414c5031)
    for dtype in ['f32', 'f64']:
        pack = '<f' if dtype == 'f32' else '<d'
        for name, values in [
            ('empty', []), ('single', [1.25]), ('signed', [0.0, -0.0]),
            ('decimal_tail', [(i-512)/100 for i in range(1025)]),
            ('rowgroup_tail', [(i%10007-5000)/100 for i in range(102401)]),
            ('mixed', [rng.uniform(-10000, 10000) for _ in range(2049)]),
        ]:
            yield f'synthetic_{name}_{dtype}', dtype, b''.join(struct.pack(pack,x) for x in values), {'kind': 'synthetic', 'seed': '0x414c5031'}
        bits = ([0,0x80000000,0x7f800000,0xff800000,0x7fc00042,0x7f800001,1,0x80000001,0x7f7fffff,0xff7fffff]
                if dtype == 'f32' else [0,0x8000000000000000,0x7ff0000000000000,0xfff0000000000000,0x7ff8000000000042,0x7ff0000000000001,1,0x8000000000000001,0x7fefffffffffffff,0xffefffffffffffff])
        bp = '<I' if dtype == 'f32' else '<Q'
        yield f'synthetic_ieee_{dtype}', dtype, b''.join(struct.pack(bp,bits[i%len(bits)]) for i in range(2049)), {'kind':'synthetic','source_encode_methods':['alp-rd'], 'reason':'upstream decimal encode has UB on these inputs'}

def corpus(directory):
    for name in FILES:
        path = directory / (name+'.csv')
        source_hash = sha(path.read_bytes())
        with path.open(newline='') as f:
            rows = csv.reader(f); header = next(rows); columns = [[] for _ in header[1:]]
            for row in rows:
                if len(row) != len(header):
                    raise RuntimeError('ragged source row')
                for out, field in zip(columns,row[1:]):
                    out.append(float(field))
        for idx, values in enumerate(columns):
            for dtype,pack in [('f64','<d'),('f32','<f')]:
                yield f'{name}_c{idx}_{dtype}', dtype, b''.join(struct.pack(pack,x) for x in values), {'kind':'real','source_file':str(path),'source_sha256':source_hash,'column':header[idx+1],'column_index':idx+1,'rows':len(values),'conversion':'Python float parsing then explicit IEEE packing '+pack,'selection':'all rows, all numeric columns, original order'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out', type=pathlib.Path, required=True)
    parser.add_argument('--corpus', type=pathlib.Path)
    parser.add_argument('--cli', type=pathlib.Path, default=ROOT/'build/release/alp_cli')
    parser.add_argument('--oracle', type=pathlib.Path, default=ROOT/'build/release/alp_upstream_oracle')
    parser.add_argument('--other-cli', type=pathlib.Path, action='append', default=[])
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    commands=[];cases=[];failures=[]
    report={'standard':'v3.0','route':'NATIVE_PORT','date':'2026-10-17','source_commit':'31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce','evidence_kind':'fresh independent unmodified upstream public API execution', 'source_UB_caveat':'Unmodified release execution is empirical evidence only on source UB paths. No universal BYTE_IDENTICAL claim; source defects recorded separately.', 'executables':{str(x):sha(x.read_bytes()) for x in [args.cli,args.oracle]+args.other_cli},'cases':cases,'failures':failures}
    selected=list(fixtures())
    if args.corpus: selected.extend(corpus(args.corpus))
    for name,dtype,data,metadata in selected:
        d=4 if dtype=='f32' else 8;directory=args.out/name;directory.mkdir(exist_ok=True)
        raw=directory/'input.raw';raw.write_bytes(data)
        for mode in ['alp','alp-rd']:
            row={'case':name,'dtype':dtype,'method':mode,'count':len(data)//d,'input_sha256':sha(data),'input_bytes':len(data), **metadata}
            cases.append(row)
            try:
                target=directory/(mode+'.frame');decoded=directory/(mode+'.decoded')
                run([args.cli,'encode',dtype,mode,raw,target,1],commands)
                run([args.cli,'decode',dtype,mode,target,decoded,1],commands)
                row['target_roundtrip']=decoded.read_bytes()==data
                frame=target.read_bytes();row.update({'frame_sha256':sha(frame),'final_bytes':len(frame),'FinalBits':len(frame)*8,'branches':methods_in(frame)})
                # A separate source decoder always consumes target output. The
                # source encoder is skipped only on frozen known UB-domain IEEE.
                source_decoded=directory/(mode+'.source-decoded')
                run([args.oracle,'decode',dtype,mode,target,source_decoded],commands)
                row['source_decodes_target']=source_decoded.read_bytes()==data
                if mode in metadata.get('source_encode_methods',['alp','alp-rd']):
                    source=directory/(mode+'.source-frame');cross=directory/(mode+'.cross-decoded')
                    run([args.oracle,'encode',dtype,mode,raw,source],commands)
                    source_bytes=source.read_bytes();row['source_frame_sha256']=sha(source_bytes)
                    row['raw_byte_identical']=source_bytes[32:]==frame[32:]
                    bad=undefined_source_factors(source_bytes)
                    if bad:
                        row['source_defect']='FACT_ARRAY_OUT_OF_BOUNDS'
                        row['source_undefined_factors']=bad
                        cp=subprocess.run([str(args.cli),'decode',dtype,mode,str(source),str(cross),'1'],capture_output=True,text=True)
                        commands.append({'argv':[str(args.cli),'decode',dtype,mode,str(source),str(cross),'1'],'returncode':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr,'expected':'malformed rejection of source UB factor'})
                        if cp.returncode!=1 or cp.stderr.strip()!='malformed':
                            raise RuntimeError('unsafe source frame was not rejected')
                        row['target_decodes_source']='EXPECTED_REJECTION_SOURCE_UB'
                    else:
                        run([args.cli,'decode',dtype,mode,source,cross,1],commands)
                        row['target_decodes_source']=cross.read_bytes()==data
                else: row['source_encode']='NOT_RUN_FROZEN_SOURCE_UB_DOMAIN'
                row['other_profiles']=[]
                for ci,other in enumerate(args.other_cli):
                    of=directory/f'{mode}.other{ci}.frame';od=directory/f'{mode}.other{ci}.decoded'
                    run([other,'encode',dtype,mode,raw,of,1],commands)
                    run([other,'decode',dtype,mode,target,od,1],commands)
                    row['other_profiles'].append({'cli':str(other),'byte_identical':of.read_bytes()==frame,'cross_decode':od.read_bytes()==data})
                required=[row['target_roundtrip'],row['source_decodes_target'],row.get('target_decodes_source',True) in (True,'EXPECTED_REJECTION_SOURCE_UB')]
                required += [x['cross_decode'] for x in row['other_profiles']]
                if not all(required):raise RuntimeError('semantic/cross decode mismatch')
                row['status']='PASS'
                # Retain canonical input/frames; decoded copies are redundant.
                for file in directory.glob('*decoded'):file.unlink()
            except Exception as e:
                row['status']='FAIL';row['error']=str(e);failures.append(row['case']+'/'+mode)
        print(name,flush=True)
        (args.out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        (args.out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    report['totals']={'cases':len(cases),'pass':sum(x.get('status')=='PASS' for x in cases),'fail':len(failures),'values':sum(x['count'] for x in cases),'raw_byte_identical':sum(x.get('raw_byte_identical',False) for x in cases),'raw_byte_compared':sum('raw_byte_identical' in x for x in cases),'source_UB_frames_rejected':sum('source_defect' in x for x in cases),'FinalBits':sum(x.get('FinalBits',0) for x in cases)}
    (args.out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['totals']))
    return bool(failures)

if __name__=='__main__':
    raise SystemExit(main())
