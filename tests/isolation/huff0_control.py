#!/usr/bin/env python3
"""Observe Huff0 FEC1 and ETB1 without inheriting a model or claiming timed results."""
import binascii
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import ContractError, canonical_bytes, digest, verify_asset
from tsbench.planner.huff0 import (BLOCK, DECODE_API, ENVELOPE, FEC, MAGIC, MODE, PLUGIN, RECORD, TABLE, TRAIN, WEATHER,
                                  fec_inputs, plan_huff0, ref, retained_paths, table_inputs, train_input)
from tsbench.runtime import create_build_lock, resolve_worker


def sha(data):
    return sha256(data).hexdigest()


def observe(call, slot, count):
    assert call['implementation'] == 'upstream-original'
    bmi2 = int(call['dynamic_bmi2_compiled'] and call['cpu_bmi2_available'])
    expected_backend = 'runtime-bmi2' if bmi2 else 'runtime-portable' if call['dynamic_bmi2_compiled'] else 'portable'
    assert call['cpu_backend'] == expected_backend
    expected_calls = [[0,0] for _ in DECODE_API]
    expected_calls[slot][bmi2] = count
    assert call['completed_decode_calls'] == expected_calls
    return {key:{'bmi2_arg_0':n[0],'bmi2_arg_1':n[1]} for key,n in zip(DECODE_API,expected_calls)}


def fec_blocks(data,payload):
    count = (len(data)+BLOCK-1)//BLOCK
    assert FEC.unpack_from(payload) == (b'FEC1',2,b'\0'*3,BLOCK,len(data),count)
    at, out = FEC.size,[]
    for off in range(0,len(data),BLOCK):
        mode,n,c,crc = RECORD.unpack_from(payload,at)
        at += RECORD.size
        src,body = data[off:off+BLOCK],payload[at:at+c]
        assert n == len(src) and c == len(body) and crc == binascii.crc32(src)
        if mode == 0:
            assert body == src
        elif mode == 1:
            assert c == 1 and body*n == src
        else:
            assert mode == 2 and 0 < c < n
        at += c
        out.append({'mode':MODE[mode],'decoded_bytes':n,'encoded_bytes':c,'crc32':crc})
    assert at == len(payload)
    return out


def reject(result,status,root,*files):
    assert result.returncode == 3 and result.stderr.startswith(f'plugin status {status}:'.encode()), result.stderr
    assert not any((root/f).exists() for f in files)
    return status


def batch_case(root,run,direct,spec,data):
    name,window = spec['name'],spec['window']
    schema = canonical_bytes({'dtype':'u8','column':'v','case':name})
    for path,content in [('input',data),('schema',schema)]:
        (root/path).write_bytes(content)
    encode_info = json.loads(run('encode',{},2,'input','schema','frame').stdout)
    direct('fec-encode','input','fec')
    payload,full = (root/'fec').read_bytes(),(root/'frame').read_bytes()

    def make(p,count=len(data)):
        return ENVELOPE.pack(MAGIC,2,count,len(schema),len(p))+schema+p

    assert full == make(payload)
    blocks = fec_blocks(data,payload)
    modes = Counter(b['mode'] for b in blocks)
    seen = dict(mode='batch',threads=1,blocks=len(blocks),fallback=bool(modes['raw']),
                **{f'{k}_blocks':modes[k] for k in MODE})
    assert encode_info == dict(seen,backend='huff0-reference-encode',operation='encode')
    (root/'input').unlink(); (root/'schema').unlink()
    direct_decode = direct('fec-decode','fec','direct.out')
    direct_result = (root/'direct.out').read_bytes()
    assert direct_result == data
    (root/'direct.out').unlink()
    counters = observe(direct_decode,0,modes['huffman'])
    desc,decode_info = map(json.loads,run('decode',{},'frame','decoded','schema.out').stdout.splitlines())
    assert desc == {'dtype':2,'count':len(data)}
    assert decode_info == dict(seen,operation='decode',backend=direct_decode['cpu_backend'] if modes['huffman'] else 'no-huffman-decode')
    recovered, recovered_schema = (root/'decoded').read_bytes(),(root/'schema.out').read_bytes()
    assert recovered == data and recovered_schema == schema
    (root/'decoded').unlink(); (root/'schema.out').unlink()

    invalid = {'envelope-truncated':full[:-1],'unexpected-algorithm':make(payload[:4]+b'\x01'+payload[5:]),
               'declared-size-mismatch':make(payload[:12]+struct.pack('<Q',len(data)+1)+payload[20:]),
               'trailing-byte':make(payload+b'\0'),'envelope-size-limit':make(payload,count=(64<<20)+1)}
    if blocks:
        at = FEC.size
        invalid['illegal-mode'] = make(payload[:at]+b'\xff'+payload[at+1:])
        # Leave the valid compressed payload alone and change the expected CRC.
        pos = at+9
        invalid['crc-mismatch'] = make(payload[:pos]+bytes([payload[pos]^1])+payload[pos+1:])
    statuses = {}
    for label,bad in invalid.items():
        (root/'frame').write_bytes(bad)
        statuses[label] = reject(run('decode',{},'frame','decoded','schema.out',check=False),
                                 7 if label == 'envelope-size-limit' else 5,root,'decoded','schema.out')
    (root/'frame').unlink()
    (root/spec['artifact']).write_bytes(full)
    return {'name':name,'window':window,'input':ref('frozen:'+name,data),'artifact':ref(spec['artifact'],full),
            'fec_sha256':sha(payload),'direct_restored_sha256':sha(direct_result),'restored_sha256':sha(recovered),
            'restored_schema_sha256':sha(recovered_schema),'decoded_bytes':len(data),'envelope_header_bytes':ENVELOPE.size,
            'schema_bytes':len(schema),'fec_header_bytes':FEC.size,'fec_record_bytes':len(blocks)*RECORD.size,
            'fec_bytes':len(payload),'blocks':blocks,'rejected':statuses,'direct_backend':direct_decode,
            'decode_entries':counters,'worker_encode':encode_info,'worker_decode':decode_info}


def table_profile(root,direct,spec,train,blocks):
    name,streams = spec['profile'],spec['streams']
    source = 'training'
    (root/source).write_bytes(train)
    training = direct('train',streams,source,'model')
    model = (root/'model').read_bytes()
    (root/spec['model']).write_bytes(model)
    (root/source).unlink()
    assert model[:8] == b'ETB1'+bytes([2,training['effective_table_log'],streams,0])
    assert training['streams'] == streams and 9 <= training['effective_table_log'] <= 12
    assert 9 <= len(model) <= 1024
    source_args,decode_args,cases = [],[],[]
    for i,src in enumerate(blocks):
        source_args.extend((f'input-{i}',f'block-{i}'))
        (root/f'input-{i}').write_bytes(src)
    enc = direct('table-encode','model',*source_args)
    assert enc['streams'] == streams and enc['effective_table_log'] == training['effective_table_log']
    assert enc['table_encode_calls'] == ([sum(len(b)>1 for b in blocks),0] if streams == 1 else [0,sum(len(b)>1 for b in blocks)])
    for i,src in enumerate(blocks):
        block = (root/f'block-{i}').read_bytes()
        mode,n,c = TABLE.unpack_from(block)
        assert n == len(src) and len(block) == TABLE.size+c
        assert (mode == 0 and block[TABLE.size:] == src) or (mode == 1 and 0 < c < n)
        cases.append({'index':i,'mode':'huffman' if mode else 'raw','original_bytes':n,'artifact_bytes':len(block),
                      'header_bytes':TABLE.size,'encoded_bytes':c,'artifact':ref(spec['blocks'][i]['artifact'],block),
                      'model_sha256':sha(model),'input':ref(f'frozen:{name}-block-{i}',src)})
        (root/spec['blocks'][i]['artifact']).write_bytes(block)
        (root/f'input-{i}').unlink()
    # Model identity is part of the recovery contract; block files do not carry it.
    # Stage a different, valid Huff0 model of the same profile to separate identity
    # checks from ETB1 structural checks.
    model_id = sha(model)
    target_model = {'path':'model','sha256':model_id}
    (root/'other-training').write_bytes(b'\xff'*BLOCK)
    direct('train',streams,'other-training','other-model')
    (root/'other-training').unlink()
    other = (root/'other-model').read_bytes()
    (root/spec['other_model']).write_bytes(other)
    # A valid empty raw block exercises model loading even for all-Huffman profiles.
    (root/'empty-block').write_bytes(TABLE.pack(0,0,0))
    alternate_load = direct('table-decode','other-model','empty-block','alternate.out')
    assert (root/'alternate.out').read_bytes() == b'' and alternate_load['streams'] == streams
    observe(alternate_load,1 if streams == 1 else 2,0)
    try:
        verify_asset(root,{**target_model,'path':'other-model'})
    except ContractError as exc:
        assert 'SHA-256 mismatch' in str(exc)
    else:
        raise AssertionError('a different valid model satisfied the planned asset identity')
    verify_asset(root,target_model)

    # Decode in reverse order with one loaded DTable and without training/staged values.
    order = list(reversed(range(len(blocks))))
    for i in order:
        decode_args.extend((f'block-{i}',f'restored-{i}'))
    dec = direct('table-decode','model',*decode_args)
    compressed = sum(b['mode']=='huffman' for b in cases)
    counters = observe(dec,1 if streams == 1 else 2,compressed)
    assert dec['streams'] == streams and dec['effective_table_log'] == training['effective_table_log']
    for i,src in enumerate(blocks):
        restored = (root/f'restored-{i}').read_bytes()
        assert restored == src
        cases[i]['restored_sha256'] = sha(restored)
        (root/f'restored-{i}').unlink()

    which = next(i for i,c in enumerate(cases) if c['mode']=='huffman')
    artifact = (root/f'block-{which}').read_bytes()
    invalid = {'missing-table':('missing-model',f'block-{which}'),
               'unexpected-stream-tag':('bad-model',f'block-{which}'),
               'truncated-model':('short-model',f'block-{which}'),
               'block-truncated':('model','truncated-block'), 'invalid-length-field':('model','bad-length'),
               'decoded-value-limit':('model','bad-decoded-count')}
    (root/'bad-model').write_bytes(model[:6]+b'\x02'+model[7:])
    (root/'short-model').write_bytes(model[:7])
    (root/'truncated-block').write_bytes(artifact[:-1])
    (root/'bad-length').write_bytes(artifact[:5]+struct.pack('<I',len(artifact)-TABLE.size+1)+artifact[TABLE.size:])
    (root/'bad-decoded-count').write_bytes(artifact[:1]+struct.pack('<I',BLOCK+1)+artifact[5:])
    statuses = {}
    for label,(model_path,block_path) in invalid.items():
        p = direct('table-decode',model_path,block_path,'failed.out',check=False)
        assert p.returncode == 1 and not (root/'failed.out').exists(), p.stderr
        statuses[label] = p.returncode

    # Unlike FEC1, a TableCodec block has no CRC. Demonstrate the boundary on a
    # valid raw block: a changed literal survives native decode but fails oracle.
    raw_case = next((c for c in cases if c['mode']=='raw' and c['original_bytes']),None)
    raw_mutation = None
    if raw_case:
        i = raw_case['index']
        raw = (root/f'block-{i}').read_bytes()
        changed = bytes([raw[TABLE.size]^1])+raw[TABLE.size+1:]
        (root/'changed-raw-block').write_bytes(raw[:TABLE.size]+changed)
        direct('table-decode','other-model',f'block-{i}','structural-model.out')
        assert (root/'structural-model.out').read_bytes() == blocks[i]
        observed = direct('table-decode','model','changed-raw-block','mutated.out')
        assert (root/'mutated.out').read_bytes() == changed != blocks[i]
        observe(observed,1 if streams==1 else 2,0)
        raw_mutation = {'index':i,'decoded_sha256':sha(changed),'frozen_sha256':sha(blocks[i])}

    return {'profile':name,'streams':streams,'training':ref('frozen:'+name+'-training',train),
            'model':ref(spec['model'],model),'other_model':ref(spec['other_model'],other),
            'effective_table_log':training['effective_table_log'],'block_artifact_bytes':sum(b['artifact_bytes'] for b in cases),
            'blocks':cases,'decode_order':order,'model_plus_all_blocks_bytes':len(model)+sum(b['artifact_bytes'] for b in cases),
            'rejected':statuses,'different_valid_asset_rejected_by_sha256':True,'raw_mutation':raw_mutation,
            'table_encode_calls':enc['table_encode_calls'],'direct_backend':dec,'decode_entries':counters,
            'alternate_load':alternate_load}


def main(worker,module,library,control,report):
    bundle,data = plan_huff0(ROOT)
    with tempfile.TemporaryDirectory(prefix='tsbench-huff0-moved-') as temp:
        root = Path(temp)
        for name in ('catalog','schemas','plugins','include','cmake','tools','third_party'):
            shutil.copytree(ROOT/name,root/name)
        for file in (worker,module,library,control):
            shutil.copy2(file,root/file.name)
        lock = create_build_lock(root,worker.name,{PLUGIN:module.name})
        binding = resolve_worker(root,lock,PLUGIN,{})

        def run(op,options,*args,check=True):
            return run_worker(root,[binding['worker'],op,binding['library'],PLUGIN,canonical_bytes(options).decode(),*map(str,args)],check=check)

        def direct(*args,check=True):
            result = run_worker(root,[str(root/control.name),*map(str,args)],check=check,library_dir=root)
            return json.loads(result.stdout) if check else result

        fec = [batch_case(root,run,direct,spec,raw) for spec,(_,raw,_,_) in
               zip(bundle['fec1'],fec_inputs(data['test'],bundle['test_window']),strict=True)]
        assert [[b['mode'] for b in row['blocks']] for row in fec] == [s['modes'] for s in bundle['fec1']]
        (root/'input').write_bytes(b'\0'*8); (root/'schema').write_bytes(b'{}')
        statuses = {'wrong_dtype':reject(run('encode',{},10,'input','schema','frame',check=False),1,root,'frame'),
                    'unbound_option':reject(run('encode',{'table_log':9},2,'input','schema','frame',check=False),3,root,'frame')}
        (root/'input').unlink(); (root/'schema').unlink()
        profiles = [table_profile(root,direct,spec,train_input(name,data['train']),blocks) for spec,(name,_,blocks,_) in
                    zip(bundle['etb1'],table_inputs(data['test']),strict=True)]
        assert all([b['mode'] for b in p['blocks']] == [b['mode'] for b in s['blocks']]
                   for p,s in zip(profiles,bundle['etb1'],strict=True))
        (root/WEATHER).write_bytes(data['test'])
        (root/TRAIN).write_bytes(data['train'])
        retained = {name:(root/name).read_bytes() for name in retained_paths(bundle)}
    record = {'schema':'bmk.m0-huff0-control/2','diagnostic_id':uuid.uuid4().hex,'config_id':bundle['config_id'],
              'bundle_id':bundle['bundle_id'],'input_rejections':statuses,
              'definitions':{'probe_sha256':digest(Path(__file__)), 'native_probe_sha256':digest(ROOT/'tests/native/huff0_control.cpp'),
                             'instrumented_binary_sha256':digest(control)},'build':lock,'fec1_cases':fec,'etb1_profiles':profiles,
              'train_window':bundle['train_window'],'test_window':bundle['test_window'],
              'formal_performance':False,'formal_qualification':False}
    with tempfile.TemporaryDirectory(dir=report.parent,prefix='.huff0-report-') as temp:
        path = Path(temp)/'report.json'
        path.write_bytes(canonical_bytes(record)+b'\n')
        for name,raw in retained.items():
            (Path(temp)/name).write_bytes(raw)
        for name in retained:
            (Path(temp)/name).replace(report.parent/name)
        path.replace(report)


if __name__ == '__main__':
    main(*(Path(p).resolve() for p in sys.argv[1:]))
