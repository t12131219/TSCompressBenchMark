"""Recheck Huff0 development evidence without loading its native library.

Entropy decoding is witnessed by detached native processes. This verifier
rebuilds the byte/CRC ledger and checks the compressed layout, not Huff symbols.
"""
from binascii import crc32
from collections import Counter
import re
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..planner.huff0 import (BLOCK, CONTROL, DECODE_API, ENVELOPE, FEC, MAGIC, MODE, PLUGIN, RECORD, TABLE,
                             fec_inputs, ref, retained_paths, table_inputs, train_input)
from .probe_build import verify_probe_build_lock


def _exact(actual, expected, message):
    require(canonical_bytes(actual) == canonical_bytes(expected), message)


def _weights_size(raw):
    require(bool(raw), 'missing Huff0 weights')
    tag = raw[0]
    n = tag if tag < 128 else (tag - 126) // 2
    require(0 < n < len(raw), 'invalid Huff0 weights extent')
    return n + 1


def _bitstreams(raw, streams):
    if streams == 1:
        require(bool(raw) and raw[-1] != 0, 'invalid Huff0 1X stream termination')
        return
    require(streams == 4 and len(raw) >= 10, 'invalid Huff0 4X jump table')
    first = struct.unpack_from('<HHH', raw)
    last = len(raw) - 6 - sum(first)
    require(min(*first, last) > 0, 'invalid Huff0 4X stream extent')
    end = 6
    for n in (*first, last):
        end += n
        require(raw[end - 1] != 0, 'invalid Huff0 4X stream termination')


def _calls(row, runtime, slot, count, streams=0, log=0):
    compiled, cpu = runtime
    bmi2 = int(compiled and cpu)
    backend = 'runtime-bmi2' if bmi2 else 'runtime-portable' if compiled else 'portable'
    calls = [[0, 0] for _ in DECODE_API]
    calls[slot][bmi2] = count
    _exact(row, {'implementation':'upstream-original','cpu_backend':backend,'dynamic_bmi2_compiled':compiled,
                 'cpu_bmi2_available':cpu,'completed_decode_calls':calls,'streams':streams,
                 'effective_table_log':log,'table_encode_calls':[0,0]}, 'Huff0 native decode entry or count differs')
    return {key:{'bmi2_arg_0':a, 'bmi2_arg_1':b} for key,(a,b) in zip(DECODE_API,calls,strict=True)}


def _batch(spec, row, plain, name, window, modes, read, runtime, policy):
    schema = canonical_bytes({'dtype':'u8','column':'v','case':name})
    input_ref = ref('frozen:'+name,plain)
    _exact((spec['name'],spec['input'],spec['window'],spec['modes']), (name,input_ref,window,modes), 'Huff0 FEC1 case differs')
    wire = read(spec['artifact'])
    at = ENVELOPE.size + len(schema)
    require(len(wire) >= at+FEC.size and ENVELOPE.unpack_from(wire) == (MAGIC,2,len(plain),len(schema),len(wire)-at) and
            wire[ENVELOPE.size:at] == schema, 'invalid Huff0 FEC1 envelope')
    payload = wire[at:]
    require(FEC.unpack_from(payload) == (b'FEC1',2,b'\0'*3,BLOCK,len(plain),len(modes)), 'invalid Huff0 FEC1 header')
    records, at = [], FEC.size
    for i, mode in enumerate(modes):
        require(at+RECORD.size <= len(payload), 'truncated Huff0 FEC1 record')
        tag,n,c,checksum = RECORD.unpack_from(payload,at)
        at += RECORD.size
        raw = plain[i*BLOCK:(i+1)*BLOCK]
        body = payload[at:at+c]
        require(tag == MODE.index(mode) and 0 < n == len(raw) and len(body) == c and checksum == crc32(raw),
                'Huff0 FEC1 source extent, mode or CRC differs')
        if mode == 'raw':
            require(body == raw, 'Huff0 FEC1 raw bytes differ')
        elif mode == 'rle':
            require(c == 1 and body*n == raw, 'Huff0 FEC1 RLE bytes differ')
        else:
            require(0 < c < n, 'invalid Huff0 FEC1 compressed extent')
            _bitstreams(body[_weights_size(body):],4)
        records.append({'mode':mode,'decoded_bytes':n,'encoded_bytes':c,'crc32':checksum})
        at += c
    require(at == len(payload), 'Huff0 FEC1 payload does not account for all bytes')
    count = Counter(modes)
    direct = row.get('direct_backend')
    entries = _calls(direct,runtime,0,count['huffman'])
    seen = dict(mode='batch',threads=1,blocks=len(modes),fallback=bool(count['raw']),
                **{f'{m}_blocks':count[m] for m in MODE})
    _exact(row, {'name':name,'window':window,'input':input_ref,'artifact':ref(spec['artifact'],wire),
                 'fec_sha256':ref('',payload)['sha256'],'direct_restored_sha256':input_ref['sha256'],
                 'restored_sha256':input_ref['sha256'],'restored_schema_sha256':ref('',schema)['sha256'],
                 'decoded_bytes':len(plain),'envelope_header_bytes':ENVELOPE.size,'schema_bytes':len(schema),
                 'fec_header_bytes':FEC.size,'fec_record_bytes':len(modes)*RECORD.size,'fec_bytes':len(payload),
                 'blocks':records,'rejected':{**policy['fec1'],**(policy['nonempty_fec1'] if modes else {})},
                 'direct_backend':direct,'decode_entries':entries,
                 'worker_encode':dict(seen,backend='huff0-reference-encode',operation='encode'),
                 'worker_decode':dict(seen,backend=direct['cpu_backend'] if count['huffman'] else 'no-huffman-decode',operation='decode')},
           'Huff0 FEC1 direct restore, byte ledger or rejection differs')


def _model(raw, streams):
    require(9 <= len(raw) <= 1024 and raw[:5] == b'ETB1\x02' and 9 <= raw[5] <= 12 and
            raw[6:8] == bytes([streams,0]) and _weights_size(raw[8:]) == len(raw)-8, 'invalid Huff0 ETB1 model header')
    return raw[5]


def _profile(spec, row, train, name, streams, blocks, modes, read, runtime, policy):
    source = ref('frozen:'+name+'-training',train_input(name,train))
    _exact((spec['profile'],spec['streams'],spec['training']), (name,streams,source), 'Huff0 ETB1 training binding differs')
    model, alternate = read(spec['model']), read(spec['other_model'])
    model_ref, other_ref = ref(spec['model'],model), ref(spec['other_model'],alternate)
    log, other_log = _model(model,streams), _model(alternate,streams)
    require(model_ref['sha256'] != other_ref['sha256'], 'Huff0 ETB1 alternate must have independent identity')
    expected, raw_mutation = [], None
    require(len(spec['blocks']) == len(blocks), 'Huff0 ETB1 planned block count differs')
    for i,(item,plain,mode) in enumerate(zip(spec['blocks'],blocks,modes,strict=True)):
        artifact = item['artifact']
        input_ref = ref(f'frozen:{name}-block-{i}',plain)
        _exact(item, {'index':i,'input':input_ref,'mode':mode,'artifact':artifact}, 'Huff0 ETB1 frozen block differs')
        wire = read(artifact)
        require(len(wire) >= TABLE.size, 'truncated Huff0 ETB1 block header')
        tag,n,c = TABLE.unpack_from(wire)
        body = wire[TABLE.size:]
        require(tag == int(mode == 'huffman') and n == len(plain) and c == len(body), 'Huff0 ETB1 stored lengths or tag differ')
        if mode == 'huffman':
            require(0 < c < n, 'invalid Huff0 ETB1 compressed extent')
            _bitstreams(body,streams)
        else:
            require(body == plain, 'Huff0 ETB1 raw bytes differ')
            if plain and raw_mutation is None:
                changed = bytes([body[0]^1])+body[1:]
                raw_mutation = {'index':i,'decoded_sha256':ref('',changed)['sha256'],'frozen_sha256':input_ref['sha256']}
        expected.append({'index':i,'mode':mode,'original_bytes':n,'artifact_bytes':len(wire),'header_bytes':TABLE.size,
                         'encoded_bytes':c,'artifact':ref(artifact,wire),'model_sha256':model_ref['sha256'],
                         'input':input_ref,'restored_sha256':input_ref['sha256']})
    direct, alt = row.get('direct_backend'), row.get('alternate_load')
    slot = 1 if streams == 1 else 2
    entries = _calls(direct,runtime,slot,modes.count('huffman'),streams,log)
    _calls(alt,runtime,slot,0,streams,other_log)
    calls = [0,0]
    calls[slot-1] = sum(len(x)>1 for x in blocks)
    size = sum(b['artifact_bytes'] for b in expected)
    _exact(row, {'profile':name,'streams':streams,'training':source,'model':model_ref,'other_model':other_ref,
                 'effective_table_log':log,'block_artifact_bytes':size,'blocks':expected,
                 'decode_order':list(reversed(range(len(blocks)))),'model_plus_all_blocks_bytes':size+len(model),
                 'rejected':policy['table'],'different_valid_asset_rejected_by_sha256':True,'raw_mutation':raw_mutation,
                 'table_encode_calls':calls,'direct_backend':direct,'decode_entries':entries,'alternate_load':alt},
           'Huff0 ETB1 identity, detached restore, byte ledger or rejection differs')


def verify_huff0(bundle, build, driver, source, out, *, sealed_paths=None):
    require(bundle['bundle_id'] == content_id({k:v for k,v in bundle.items() if k!='bundle_id'}), 'Huff0 bundle identity differs')
    require(sealed_paths is None or retained_paths(bundle)|{bundle['evidence_path']} <= sealed_paths, 'Huff0 evidence is not sealed')
    report = load_json(local_file(out,bundle['evidence_path']))
    require(isinstance(report,dict) and isinstance(report.get('diagnostic_id'),str) and
            re.fullmatch('[a-f0-9]{32}',report['diagnostic_id']) and CONTROL in build, 'Huff0 report closure differs')
    skip = {'diagnostic_id','build','fec1_cases','etb1_profiles'}
    _exact({k:v for k,v in report.items() if k not in skip},
           {'schema':'bmk.m0-huff0-control/2','config_id':bundle['config_id'],'bundle_id':bundle['bundle_id'],
            'input_rejections':bundle['rejections']['input'],'definitions':{'probe_sha256':driver,'native_probe_sha256':source,
            'instrumented_binary_sha256':build[CONTROL]},'train_window':bundle['train_window'],'test_window':bundle['test_window'],
            'formal_performance':False,'formal_qualification':False}, 'Huff0 definition, runtime observer or input boundary differs')
    verify_probe_build_lock(report.get('build'),{k:v for k,v in build.items() if k!=CONTROL},PLUGIN,dependency_count=1)

    def read(name):
        path = local_file(out,name)
        require(path.stat().st_size <= bundle['data_artifact_max_bytes'], 'Huff0 retained artifact exceeds bound')
        return path.read_bytes()

    train, heldout = (read(bundle[key]['path']) for key in ('training','heldout'))
    for key,raw in (('training',train),('heldout',heldout)):
        _exact(ref(bundle[key]['path'],raw),bundle[key],'Huff0 retained input differs')
    batches, profiles = report.get('fec1_cases'),report.get('etb1_profiles')
    require(isinstance(batches,list) and len(batches)==len(bundle['fec1'])==5 and isinstance(profiles,list) and
            len(profiles)==len(bundle['etb1'])==4 and all(isinstance(row,dict) for row in batches+profiles),
            'Huff0 observation count differs')
    cpu = batches[0].get('direct_backend')
    require(isinstance(cpu,dict), 'Huff0 backend detection missing')
    runtime = (cpu.get('dynamic_bmi2_compiled'),cpu.get('cpu_bmi2_available'))
    require(all(type(x) is bool for x in runtime), 'Huff0 BMI2 build and host claims must be boolean')
    for spec,row,(name,raw,window,modes) in zip(bundle['fec1'],batches,fec_inputs(heldout,bundle['test_window']),strict=True):
        _batch(spec,row,raw,name,window,modes,read,runtime,bundle['rejections'])
    for spec,row,(name,streams,blocks,modes) in zip(bundle['etb1'],profiles,table_inputs(heldout),strict=True):
        _profile(spec,row,train,name,streams,blocks,modes,read,runtime,bundle['rejections'])
