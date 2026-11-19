"""Audit retained Zstd/XZ products and bounded span ledgers without the build."""
from hashlib import sha256
import lzma
from zlib import crc32

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..planner.lzbench import BASE_SIZES, DIR, probe_schema, retained_paths


def _exact(actual, expected, message):
    require(canonical_bytes(actual) == canonical_bytes(expected), message)


def _record(row, fields, message):
    require(isinstance(row, dict) and set(fields) <= row.keys(), message)


def zstd_frame(data):
    """Read one standard frame's header, block extents and trailer, not its payload."""
    require(len(data) >= 6 and data[:4] == b'\x28\xb5\x2f\xfd','not a standard Zstd frame')
    at = 4
    def take(n):
        nonlocal at
        require(at+n <= len(data),'truncated Zstd frame field')
        at += n
        return int.from_bytes(data[at-n:at],'little')
    desc = take(1)
    require(not desc & 0x18,'unexpected Zstd header bits')
    single = bool(desc & 32)
    checksum = bool(desc & 4)
    window = None
    if not single:
        wd = take(1)
        base = 1 << (10 + (wd >> 3))
        window = base + (base//8)*(wd&7)
    dict_id = take((0,1,2,4)[desc&3])
    fcs_len = (int(single),2,4,8)[desc>>6]
    fcs = take(fcs_len) + (256 if fcs_len == 2 else 0) if fcs_len else None
    if single:
        window = fcs
    for _ in range(len(data)//3):
        block = take(3)
        kind, size = (block >> 1) & 3, block >> 3
        require(kind != 3 and size <= min(128 << 10,window),'invalid Zstd block header')
        at += 1 if kind == 1 else size
        require(at <= len(data),'truncated Zstd block payload')
        if block & 1:
            break
    else:
        require(False,'missing Zstd final block')
    require(at + (4 if checksum else 0) == len(data),'Zstd trailer or frame count differs')
    return {'content_size':fcs,'checksum':checksum,'dictionary_id':dict_id,'window':window}


def verify_spans(calls, length, result, offered_cap, produced_cap):
    require(isinstance(calls,list) and 1 <= len(calls) <= 50_000,'invalid session span denominator')
    read = written = idle = finish_n = 0
    first = None
    drain = False
    span_end = min(offered_cap,length)
    for i, call in enumerate(calls):
        require(isinstance(call,list) and len(call) == 5 and all(type(v) is int for v in call), 'invalid session span row')
        offered, used, made, finishing, finished = call
        require(offered == span_end-read and 0 <= used <= offered and 0 <= made <= produced_cap and
                finishing == int(span_end == length) and finished == int(i == len(calls)-1), 'session caller span or finish accounting differs')
        idle = 0 if used or made else idle+1
        require(idle < 10_000, 'session spans stall')
        if made and first is None:
            first = i
        drain |= bool(finishing and not used and made)
        finish_n += finishing
        read += used
        written += made
        require(written <= result,'session output quota exceeded')
        if read == span_end:
            span_end = min(span_end+offered_cap,length)
    require(read == length and written == result and finish_n and first is not None,'session byte totals or effective output differ')
    return first,finish_n,drain


def _retained(out, refs, files):
    require(isinstance(refs,list) and len(refs) == len(files),'lzbench retained artifact denominator differs')
    result = {}
    for (name, original), ref in zip(files,refs,strict=True):
        path = local_file(out,f'{DIR}/{name}')
        require(1 <= path.stat().st_size <= original['bytes']+65536,'lzbench retained artifact exceeds frame cap')
        data = path.read_bytes()
        _exact(ref,{'path':name,'frame':{'bytes':len(data),'sha256':sha256(data).hexdigest()},
                    'fresh_process_restore':{k:original[k] for k in ('bytes','sha256')}},'lzbench artifact digest or fresh restore differs')
        result[name] = data
    return result


def verify_lzbench(bundle, build, definitions, out, *, sealed_paths=None):
    require(bundle['bundle_id'] == content_id({k:v for k,v in bundle.items() if k != 'bundle_id'}),'lzbench bundle identity differs')
    expected = {bundle['evidence_path'],*retained_paths(bundle)}
    require(sealed_paths is None or {p for p in sealed_paths if p.startswith(DIR+'/')} == expected,'lzbench sealed frame closure differs')
    report = load_json(local_file(out,bundle['evidence_path']))
    extended = 'dictionary' in bundle and 'workers' in bundle
    xz_bound = 'xz_baseline' in bundle and 'xz_guard' in bundle
    schema = probe_schema(bundle)
    require(isinstance(report,dict) and report.keys() == {'schema','bundle_id','case_ids','source_archive','inventory','build',
            'diagnostic_definitions','formal_performance','formal_qualification','observations'} and
            report['schema'] == schema and report['bundle_id'] == bundle['bundle_id'] and
            report['case_ids'] == [case['case_id'] for case in bundle['cases']] and report['build'] == build and
            report['diagnostic_definitions'] == definitions and report['formal_performance'] is False and
            report['formal_qualification'] is False,'lzbench report bindings differ')
    for key, sha_key in (('source_archive','archive_sha256'),('inventory','inventory_sha256')):
        _record(report[key], {'sha256'}, 'lzbench source identity is malformed')
        require(report[key]['sha256'] == bundle[sha_key],'lzbench source identity differs')
    obs = report['observations']
    require(isinstance(obs,list) and len(obs) == len(bundle['groups']),'lzbench operation group closure differs')
    seen = {}
    for group, row in zip(bundle['groups'],obs,strict=True):
        _record(row, {'observed','group'}, 'malformed lzbench observation')
        _exact({k:v for k,v in row.items() if k!='observed'},
               {**group,'status':'diagnostic_verified','qualification':'not_run'},'lzbench operation identity differs')
        seen[row['group']] = row['observed']
    baseline = seen['zstd-baseline']
    _record(baseline, {'artifacts'}, 'missing Zstd baseline artifacts')
    _exact({k:v for k,v in baseline.items() if k != 'artifacts'},
           {'roundtrip_sizes':list(BASE_SIZES),'oversize_and_short_capacity_rejected':True,'invalid_level_rejected':True,
            'wrong_length_and_truncated':[[4,4],[4,4],[4,4],[1,4]],'legacy_decodes_upstream':True},'Zstd legacy length/rejection differs')
    files = [(c['frame'],c['input']) for c in bundle['baseline']]
    retained = _retained(out,baseline['artifacts'],files)
    for name, src in files:
        _exact(zstd_frame(retained[name]), {'content_size':src['bytes'],'checksum':False,'dictionary_id':0,'window':src['bytes']},
               'Zstd legacy frame flags differ')
    if xz_bound:
        _verify_xz_baseline(bundle['xz_baseline'],bundle['xz_guard'],seen['xz-baseline'],out)
    for codec,spec in bundle['sessions'].items():
        session = seen[f'{codec}-session']
        require(isinstance(session,dict) and 'artifacts' in session and 'calls' in session,'missing native session evidence')
        files = [(spec['files'][key], spec['inputs'][key]) for key in sorted(spec['files'])]
        retained = _retained(out,session['artifacts'],files)
        for key, name in spec['files'].items():
            wire = retained[name]
            if codec == 'zstd':
                header = zstd_frame(wire)
                require(header['checksum'] and header['dictionary_id']==0 and header['content_size'] in (None,spec['inputs'][key]['bytes']),
                        'native span Zstd frame flags differ')
            else:
                params = spec['parameters']
                _xz_restore(wire,spec['inputs'][key],params['check'],params['memory_limit'])
                if xz_bound:
                    n = spec['inputs'][key]['bytes']
                    step = params['block_size']
                    expected = [min(n-i,step) for i in range(0,n,step)]
                    filters = [(params['filter0'],bytes([params['filter0_distance']-1])),
                               (0x21,bytes([spec['dictionary_property']]))]
                    blocks = xz_blocks(wire)
                    require([b['raw'] for b in blocks] == expected and all(b['filters'] == filters for b in blocks),
                            'XZ session multiblock LZMA2/Delta filter evidence differs')
        calls = session['calls']
        require(isinstance(calls,dict) and calls.keys() == spec['span_limits'].keys(),'session direction/reset call closure differs')
        for label, (key, inside, outside) in spec['span_limits'].items():
            raw = spec['inputs'][key]['bytes']; frame = len(retained[spec['files'][key]])
            length, result = (raw, frame) if label.startswith('encode-') else (frame, raw)
            first,finish_n,drain = verify_spans(calls[label],length,result,inside,outside)
            if label == 'encode-first':
                require(first >= 0 and finish_n>1 and drain and finish_n==session['encode_finish_calls'],'native session finish drain differs')
        _exact({k:v for k,v in session.items() if k not in {'calls','artifacts','encode_finish_calls'}},
               {'input_bytes':spec['inputs']['first']['bytes'],'frame_bytes':len(retained[spec['files']['first']]),
                'independent_reset_decode':True,'truncation_and_reset_verified':True,'overlap_and_zero_capacity_rejected':True,
                'reject':['use process for native stream/frame','use process for stream/frame','truncated stream','reset required after failure'],
                'configured_level':spec['level'],'configured_parameters':spec['parameters']},'native session state and guard evidence differs')
    if extended:
        _verify_dictionary(bundle['dictionary'],seen['zstd-dictionary'],out)
        for codec,spec in bundle['workers'].items():
            _verify_workers(codec,spec,seen[f'{codec}-workers'],out)


_ZERO_JOBS = {'jobs':0,'worker_threads':0,'caller_jobs':0}


def _size_identity(blob):
    return {'bytes':len(blob),'sha256':sha256(blob).hexdigest()}


def _read_bound(out, name, lo, hi):
    if isinstance(out,dict):
        wire = out[name]
        require(type(wire) is bytes and lo <= len(wire) <= hi,'lzbench retained dictionary or worker frame exceeds frozen bound')
        return wire
    p = local_file(out,f'{DIR}/{name}')
    require(lo <= p.stat().st_size <= hi,'lzbench retained dictionary or worker frame exceeds frozen bound')
    return p.read_bytes()


def _jobs(data, workers):
    require(isinstance(data,dict) and data.keys() == _ZERO_JOBS.keys() and
            all(type(v) is int and v >= 0 for v in data.values()) and data['worker_threads'] == workers and
            data['jobs'] >= workers + data['caller_jobs'], 'lzbench worker trace identity/census differs')


def _feature(codec, size, encoded, level):
    return {'codec':codec,'input_bytes':size,'encoded_bytes':encoded,'level':level,
            'mode':'frame','native_stream':True,'repeats':1}


def _verify_dictionary(spec, row, out):
    dictionary = _read_bound(out,spec['dictionary_path'],8,spec['capacity'])
    dict_id = int.from_bytes(dictionary[4:8],'little')
    require(dictionary.startswith(b'\x37\xa4\x30\xec') and dict_id > 1,'Zstd trained dictionary identity differs')
    expected_train = spec['training_samples']
    train_ids = {r['sha256'] for r in expected_train}
    held_out_ids = {r['sha256'] for r in spec['held_out_samples']}
    require(len(train_ids) == len(expected_train) == 128 and len(held_out_ids) == len(spec['held_out_samples']) == 31 and
            train_ids.isdisjoint(held_out_ids) and sum(r['bytes'] for r in spec['held_out_samples']) == spec['held_out']['bytes'],
            'Zstd train/held-out partition closure differs')
    original = spec['held_out']
    frame = _read_bound(out,spec['frame_path'],1,original['bytes']+65536)
    flags = zstd_frame(frame)
    require(flags['dictionary_id'] == dict_id and not flags['checksum'] and flags['content_size'] in (None,original['bytes']),
            'Zstd dictionary frame dependency or flags differ')
    stats = {**_feature('zstd',original['bytes'],len(frame),3),'encode_jobs':_ZERO_JOBS,'decode_jobs':_ZERO_JOBS}
    _exact(row,{'training_samples':expected_train,'sample_set_identity':{'train':'train','held_out':'held-out'},
                'training_capacity_bytes':spec['capacity'],
                'trainer_rejected':{str(x):{'error':'dictionary training size','exit_status':2} for x in spec['bad_capacities']},
                'dictionary':{**_size_identity(dictionary),'id':dict_id},'held_out':original,'encoded':_size_identity(frame),
                'serialized_bytes_including_dictionary':len(dictionary)+len(frame),
                'roundtrip':{**stats,'effective_parameters':spec['parameters']},
                'fresh_process_decode':{**stats,'effective_parameters':{}}, 'fresh_process_restored':original,
                'negative_dictionary_id':dict_id ^ 1,
                'rejected':{k:{'error':'Dictionary mismatch','exit_status':2} for k in ('missing','wrong_id')}},
           'Zstd dictionary sample, training limit, dependency charge or restore evidence differs')


def _xz_vli(data, at, limit):
    value = 0
    for shift in range(0,63,7):
        require(at < limit,'XZ variable integer truncated')
        byte = data[at]
        at += 1
        value |= (byte&127) << shift
        if byte < 128:
            require(shift == 0 or byte != 0,'XZ noncanonical integer')
            return value,at
    require(False,'XZ variable integer overflow')


def _uint(buf):
    return int.from_bytes(buf,'little')


def _xz_index(frame):
    """Walk a single XZ stream's record extents, with stream and index CRC."""
    require(32 <= len(frame) and len(frame)%4 == 0 and frame.startswith(b'\xfd7zXZ\0') and frame.endswith(b'YZ'),
            'invalid XZ stream envelope')
    flags = frame[6:8]
    footer = frame[-12:]
    require(flags[0] == 0 and flags[1] <= 15 and crc32(flags) == _uint(frame[8:12]) and
            footer[8:10] == flags and crc32(footer[4:10]) == _uint(footer[:4]),
            'XZ header/footer CRC or flags differ')
    length = (1+_uint(footer[4:8]))*4
    require(8 <= length <= len(frame)-24,'XZ index extent differs')
    index = frame[-12-length:-12]
    require(index[0] == 0 and crc32(index[:-4]) == _uint(index[-4:]),'XZ index indicator or CRC differs')
    limit = len(index)-4
    count,at = _xz_vli(index,1,limit)
    require(count <= (len(index)-4-at)//2,'XZ index record count exceeds extent')
    records = []
    end = 12
    for _ in range(count):
        unpadded,at = _xz_vli(index,at,limit)
        raw,at = _xz_vli(index,at,limit)
        require(unpadded >= 5 and end < len(frame)-12-length and frame[end] != 0,
                'invalid XZ block extent')
        records.append((end,unpadded,raw))
        end += (unpadded+3)//4*4
    require(end == len(frame)-12-length and limit-at < 4 and not any(index[at:limit]),'XZ block/index extents differ')
    return flags[1],records


def xz_block_sizes(frame):
    return [size for _,_,size in _xz_index(frame)[1]]


def xz_blocks(frame):
    """Parse CRC-checked filter property fields without decoding compressed data."""
    check,records = _xz_index(frame)
    check_bytes = {0:0,1:4,4:8,10:32}
    require(check in check_bytes,'unsupported frozen XZ integrity check')
    blocks = []
    for start,unpadded,raw in records:
        width = (frame[start]+1)*4
        comp_size = unpadded-width-check_bytes[check]
        require(comp_size > 0,'XZ block header exceeds indexed block')
        limit = start+width-4
        require(crc32(frame[start:limit]) == _uint(frame[limit:limit+4]),'XZ block header CRC differs')
        flags = frame[start+1]
        require(not flags&0x3c,'XZ block header has reserved bits')
        at = start+2
        for mask,size in ((0x40,comp_size),(0x80,raw)):
            if flags&mask:
                observed,at = _xz_vli(frame,at,limit)
                require(observed == size,'XZ block size field disagrees with Index')
        filters,properties = [],[]
        for _ in range((flags&3)+1):
            filter_id,at = _xz_vli(frame,at,limit)
            n,at = _xz_vli(frame,at,limit)
            require(n <= limit-at,'XZ filter properties exceed block header')
            properties.append(at)
            filters.append((filter_id,bytes(frame[at:at+n])))
            at += n
        require(not any(frame[at:limit]),'XZ block header padding differs')
        blocks.append({'raw':raw,'filters':filters,'property_offsets':properties,'header':(start,limit)})
    return blocks


def xz_advertise_dictionary(wire, code):
    blocks = xz_blocks(wire)
    require(len(blocks) == 1 and len(blocks[0]['filters']) == 1 and blocks[0]['filters'][0][0] == 0x21 and
            len(blocks[0]['filters'][0][1]) == 1 and 0 <= code < 40,'XZ dictionary guard requires one LZMA2 property')
    start,limit = blocks[0]['header']
    data = bytearray(wire)
    data[blocks[0]['property_offsets'][0]] = code
    data[limit:limit+4] = crc32(data[start:limit]).to_bytes(4,'little')
    return bytes(data)


def _xz_restore(wire, expected, check, memlimit):
    try:
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=memlimit)
        data = dec.decompress(wire,max_length=expected['bytes']+1)
    except lzma.LZMAError as e:
        require(False,f'invalid retained XZ stream: {e}')
    require(dec.eof and not dec.unused_data and dec.check == check and len(data) == expected['bytes'] and
            sha256(data).hexdigest() == expected['sha256'],'XZ independent restore differs')


def _verify_xz_baseline(spec, guard, row, out):
    _record(row, {'artifacts','encode_jobs','guards'}, 'missing XZ baseline evidence')
    _exact({k:v for k,v in row.items() if k not in {'artifacts','encode_jobs','guards'}},
           {'roundtrip_sizes':list(BASE_SIZES),'oversize_and_short_capacity_rejected':True,'invalid_level_rejected':True,
            'wrong_length_and_truncated':[[4,4],[4,4],[4,4],[1,4]],'configured_preset':spec['preset']},
           'XZ baseline size, preset or truncation evidence differs')
    files = [(f['frame'],f['input']) for f in spec['frames']]
    retained = _retained(out,row['artifacts'],files)
    jobs = row['encode_jobs']
    require(isinstance(jobs,list) and len(jobs) == len(files),'XZ baseline encoder job denominator differs')
    for job,(path,expected) in zip(jobs,files,strict=True):
        _jobs(job,spec['encoder_threads'] if expected['bytes'] else 0)
        require(job['caller_jobs'] == 0 and job['jobs'] == int(expected['bytes'] != 0),'XZ baseline job counts differ')
        wire = retained[path]
        _xz_restore(wire,expected,spec['check'],spec['decoder_memlimit'])
        blocks = xz_blocks(wire)
        if expected['bytes']:
            require(len(blocks) == 1 and blocks[0]['raw'] == expected['bytes'] and
                    blocks[0]['filters'] == [(0x21,bytes([spec['dictionary_property']]))],
                    'XZ baseline did not have one preset-6 LZMA2 block')
        else:
            require(not blocks,'empty XZ baseline contains a block')
    bad = _read_bound(out,guard['frame'],32,255)
    code = guard['dictionary_property']
    require(bad == xz_advertise_dictionary(retained[guard['base_frame']],code) and
            (2|code&1) << (code//2+11) == guard['advertised_dictionary_bytes'], 'XZ oversized control frame differs')
    for k in ('legacy_decoder_memlimit','session_decoder_memlimit'):
        try:
            dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=guard[k])
            dec.decompress(bad,max_length=guard['output_bytes']+1)
        except lzma.LZMAError as exc:
            require(str(exc) == 'Memory usage limit exceeded','XZ oversized control did not fail on memory limit')
        else:
            require(False,'XZ oversized control unexpectedly decoded')
    _exact(row['guards'], {'frame':_size_identity(bad),'legacy_status':4,'legacy_produced':0,'decoder_budget':'XZ code: 6',
                          'encoder_budget':'XZ encoder memory/configuration limit','unsupported_filter':'XZ BCJ filter id'},
           'XZ legacy/session budget or filter rejection evidence differs')


def _verify_workers(codec, spec, row, out):
    original = spec['input']
    n_bytes = original['bytes']
    expected = {'input':original,'profile_parameter':spec['parameter'],'configured_base':spec['base']}
    _record(row, {'observed'}, 'missing lzbench worker observations')
    excluded = {'observed'}
    if codec == 'xz' and 'synchronous' in spec:
        _record(row, {'synchronous'}, 'missing XZ synchronous worker control')
        excluded.add('synchronous')
    _exact({k:v for k,v in row.items() if k not in excluded},expected,'lzbench worker input/configuration differs')
    lanes = row['observed']
    require(isinstance(lanes,dict) and lanes.keys() == spec['frame_paths'].keys(),'lzbench worker profile closure differs')
    fields = {'frame','encode_jobs','decode_jobs','effective_parameters'}
    for lane in lanes.values():
        _record(lane, fields | ({'same_multiblock_frame_decode'} if codec == 'xz' else set()),
                'malformed lzbench worker profile')
        _record(lane['frame'], {'bytes','sha256'}, 'malformed lzbench worker frame identity')
        require(type(lane['frame']['bytes']) is int and 1 <= lane['frame']['bytes'] <= n_bytes+65536,
                'lzbench worker frame identity exceeds bound')
    matched = []
    headers = []
    for n in spec['settings']:
        name = str(n)
        lane = lanes[name]
        file_name = spec['frame_paths'][name]
        wire = _read_bound(out,file_name,1,n_bytes+65536)
        expected = {**_feature(codec,n_bytes,len(wire),spec['level']),'frame_path':file_name,
                    'frame':_size_identity(wire),'fresh_process_restored':original}
        _exact({k:v for k,v in lane.items() if k not in {'effective_parameters','encode_jobs','decode_jobs','same_multiblock_frame_decode'}},
               expected,'lzbench worker frame/build/restore identity differs')
        params = lane['effective_parameters']
        require(isinstance(params,dict) and all(type(x) is int for x in params.values()) and
                params.get(spec['parameter']) == n and all(params.get(k) == v for k,v in spec['base'].items()),
                'lzbench worker effective configuration differs')
        _jobs(lane['encode_jobs'],n)
        if codec == 'zstd':
            require('same_multiblock_frame_decode' not in lane,'unexpected Zstd parallel decode claim')
            _exact(lane['decode_jobs'],_ZERO_JOBS,'Zstd decode cannot claim native worker jobs')
            if n == 0:
                _exact(lane['encode_jobs'],_ZERO_JOBS,'Zstd synchronous control has background jobs')
            _exact(params, {'level':spec['level'],'content_size':1,'checksum':0,'pledged_size':-1,
                            'strategy':0,'window_log':0,**spec['base'],'workers':n},'Zstd frame parameters differ')
            header = zstd_frame(wire)
            require(not header['checksum'] and header['dictionary_id'] == 0 and header['content_size'] in (None,n_bytes),
                    'Zstd worker frame options differ')
            headers.append(header)
        else:
            require(params.keys() == {'block_size','check','depth','dict_size','encoder_memory_bytes','filter0','filter1',
                    'filter2','lc','lp','lzma_mode','match_finder','memory_limit','nice_len','pb','preset','threads','timeout_ms'} and
                    params['preset'] == spec['level'] and 0 < params['encoder_memory_bytes'] <= spec['base']['memory_limit'],
                    'XZ preset or encoder-memory observation differs')
            block = spec['base']['block_size']
            require(xz_block_sizes(wire) == [min(n_bytes-i,block) for i in range(0,n_bytes,block)],'XZ multi-block index differs')
            try:
                dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=spec['base']['memory_limit'])
                data = dec.decompress(wire,max_length=n_bytes+1)
            except lzma.LZMAError as exc:
                require(False,f'XZ worker offline decode failed: {exc}')
            require(dec.eof and not dec.unused_data and dec.check == lzma.CHECK_CRC64 and _size_identity(data) == original,
                    'XZ worker offline original-domain or checksum differs')
            # Own-frame worker counts are recorded, but only the same-frame experiment is controlled.
            _record(lane['decode_jobs'], {'worker_threads'}, 'malformed XZ decoder job evidence')
            own_count = lane['decode_jobs']['worker_threads']
            require(type(own_count) is int and 0 <= own_count <= n,'XZ own-frame decode worker count exceeds request')
            _jobs(lane['decode_jobs'],own_count)
            same = lane['same_multiblock_frame_decode']
            _record(same, {'decode_jobs'}, 'malformed XZ same-frame decoder evidence')
            shared = lanes['2']['frame']
            _exact({k:v for k,v in same.items() if k != 'decode_jobs'},
                   {**_feature('xz',n_bytes,shared['bytes'],spec['level']),'source_frame':shared,
                    'fresh_process_restored':original,'effective_parameters':{},'encode_jobs':_ZERO_JOBS},
                   'XZ decoder profiles did not share one frame')
            _jobs(same['decode_jobs'],n)
        ignored = {spec['parameter']} | ({'encoder_memory_bytes'} if codec == 'xz' else set())
        matched.append({k:v for k,v in params.items() if k not in ignored})
    require(matched[0] == matched[1] and (not headers or headers[0] == headers[1]),'lzbench worker lanes changed unmatched options')
    if 'synchronous' in excluded:
        _verify_xz_synchronous(spec,row['synchronous'],lanes,matched[0],out)


def _verify_xz_synchronous(spec, row, lanes, mt_options, out):
    control = spec['synchronous']
    original = spec['input']
    n_bytes = original['bytes']
    frame_path = control['frame_path']
    wire = _read_bound(out,frame_path,1,n_bytes+65536)
    identity = _size_identity(wire)
    _record(row, {'encode','decode'}, 'missing XZ synchronous encoder/decoder evidence')
    _exact({k:v for k,v in row.items() if k not in {'encode','decode'}},
           {'frame_path':frame_path,'frame':identity},'XZ synchronous frame identity differs')
    # This fixed workload tests matched block reservation/encoding, not general bitstream equivalence.
    require(all(wire == _read_bound(out,spec['frame_paths'][n],1,n_bytes+65536) for n in ('1','2')),
            'XZ synchronous and MT frame bytes differ on the locked control input')
    require(mt_options['dict_size'] == control['dict_size'] and all(mt_options[f'filter{i}'] == 0 for i in range(3)),
            'XZ synchronous and MT LZMA2 dictionary/filter options differ')
    block = spec['base']['block_size']
    sizes = [min(n_bytes-at,block) for at in range(0,n_bytes,block)]
    blocks = xz_blocks(wire)
    require(_xz_index(wire)[0] == spec['base']['check'] and [b['raw'] for b in blocks] == sizes and
            all(b['filters'] == [(control['filter_id'],bytes([control['dictionary_property']]))] for b in blocks),
            'XZ synchronous Index, CRC64 or LZMA2 filter properties differ')
    encode = row['encode']
    _record(encode, {'raw_encoder_memory_bytes'}, 'missing XZ raw encoder memory estimate')
    memory = encode['raw_encoder_memory_bytes']
    require(type(memory) is int and 0 < memory <= spec['base']['memory_limit'],'XZ raw encoder memory estimate exceeds limit')
    _exact({k:v for k,v in encode.items() if k != 'raw_encoder_memory_bytes'},
           {'entry':control['encoder'],'input_bytes':n_bytes,'frame_bytes':len(wire),
            'fallback_blocks':control['fallback_blocks'],'inner_input_span_bytes':control['inner_input_span_bytes'],
            'block_input_bytes':sizes,'parameters':{**spec['base'],'preset':spec['level'],
                'filter_id':control['filter_id'],'dict_size':control['dict_size']},'mt_worker_hooks':_ZERO_JOBS},
           'XZ synchronous encoder options, Index or MT worker hooks differ')
    _exact(row['decode'], {role:{'entry':control['decoder'],'input_bytes':frame['bytes'],'restored_bytes':n_bytes,
                               'memory_limit':spec['base']['memory_limit'],'mt_worker_hooks':_ZERO_JOBS,
                               'source_frame_path':name,'source_frame':frame,'fresh_process_restored':original}
                           for role,name,frame in (('own',frame_path,identity),
                                                   ('shared',spec['frame_paths']['2'],lanes['2']['frame']))},
           'XZ synchronous decoder frame, recovery or MT worker hooks differ')
