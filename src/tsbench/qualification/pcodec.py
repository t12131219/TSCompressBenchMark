"""Replay pcodec proof bindings without loading a codec or the source corpus."""
from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..planner.pcodec import C_NATIVE, HEADER, MAGIC, SOURCE, TYPES, identity, page_spans


def _exact(actual, expected, message):
    require(canonical_bytes(actual) == canonical_bytes(expected),message)


def _read(out,path,minimum,maximum):
    f = local_file(out,path)
    require(minimum <= f.stat().st_size <= maximum,'pcodec retained file exceeds frozen limits')
    return f.read_bytes()


def _verify_batch(method, specs, rows, out):
    require(isinstance(rows,list) and len(rows) == len(specs),'pcodec batch fixture denominator differs')
    for spec,row in zip(specs,rows,strict=True):
        name,dtype,n = (spec[k] for k in ('case','dtype','count'))
        if spec['frame'] is None:
            require(method == C_NATIVE and dtype == 'f16','missing pcodec frame binding')
            _exact(row,{'case':name,'dtype':dtype,'native_status':5,'abi_status':1},'pcodec C f16 rejection differs')
            continue
        schema = spec['schema'].encode('ascii')
        frame = _read(out,spec['frame'],HEADER.size+len(schema)+4,HEADER.size+len(schema)+spec['plain']['bytes']+65536)
        magic,bmk,count,schema_n,payload_n = HEADER.unpack_from(frame)
        split = HEADER.size+schema_n
        require((magic,bmk,count,schema_n,payload_n) == (MAGIC[method],TYPES[dtype][0],n,len(schema),len(frame)-split) and
                frame[HEADER.size:split] == schema and frame[split:split+4] == b'pco!',
                'pcodec frame identity, schema, count or native payload signature differs')
        wire = identity(frame[split:])
        rejected = dict.fromkeys(('envelope_trailing','payload_trailing','payload_truncated','missing_payload_metadata',
                                  'count_too_large','other_format'),5)
        if n:
            rejected['count_too_small'] = 7
        _exact(row,{'case':name,'dtype':dtype,'count':n,'input':spec['plain'],'frame':identity(frame),'payload':wire,
                    'schema':identity(schema),'restored':spec['plain'],'restored_schema':identity(schema),
                    'encode_entry':'pc_compress' if method == SOURCE else 'pc_compress_native',
                    'decode_entry':'pc_decompress_bounded','decode_backend':'rust-source',
                    'rust_reference_encoded':wire if method == SOURCE else None,'rust_reference_decoded':spec['plain'],
                    'native_count_limit':6 if n else None,'rejected':rejected},
               'pcodec batch entry, payload, exact restore or rejection evidence differs')


def _verify_pages(route, spec, row, out):
    meta = _read(out,spec['meta'],2,65536)
    pages = [_read(out,p['page'],1,p['plain']['bytes']+65536) for p in spec['pages']]
    counts = [p['count'] for p in spec['pages']]
    lengths = list(map(len,pages))
    sidecar = _read(out,spec['sidecar'],2,4096)
    require(sidecar == canonical_bytes({'counts':counts,'lengths':lengths,'dtype':spec['dtype'],
                                        'capacity':spec['capacity'],'meta_bytes':len(meta)}),
            'pcodec detached-page sidecar geometry differs')
    native = route == 'native-pages'
    require(isinstance(row,dict) and isinstance(row.get('state'),dict),'missing pcodec wrapped metadata evidence')
    state = row['state']
    require(state.get('backend') == ('native-c11' if native else 'source-rust-repaired') and
            (not native or state.get('auto_policy') == 'NativeAuto') and
            all(type(state.get(k)) is int for k in ('mode','delta')),'pcodec page backend/mode evidence differs')
    detached = [{'index':i,'spans':spec['pages'][i]['spans'],'restored':spec['pages'][i]['plain']}
                for i in reversed(range(len(pages)))]
    rejected = {'missing_meta':1 if native else 3,'first_page_small_quota':6,'early_next_page':1,
                'read_capacity_255':1,'after_first_with_second_quota':6 if native else 0,'trailing_at_drain':4,
                'read_after_error':1,'truncated_page':{'stage':'drain','status':3}}
    _exact(row,{'meta':identity(meta),'pages':[identity(p) for p in pages],'sidecar':identity(sidecar),
                'state':state,'detached':detached,'caller_buffer_overwrite_restore':spec['pages'][0]['plain'] if native else None,
                'total_bytes_in_probe':len(meta)+len(sidecar)+sum(lengths),'rejected':rejected},
           'pcodec page identity, detached spans, ownership, byte charge or rejection differs')


def intmult_wire_header(frame):
    """Read the first standalone v3 / wrapped v4.1 unsigned chunk metadata prefix.

    Layout comes from the frozen pco standalone/compressor.rs and metadata/{mode,chunk}.rs.
    This deliberately does not walk entropy data or assert exact stream closure; the detached
    native decoder drains the entire stream and separately supplies the chunk count and restore.
    """
    require(len(frame) >= 15 and frame[:5] == b'pco!\x03' and frame[5] in (0,1,2) and frame[-1] == 0,
            'invalid pcodec IntMult standalone prefix/footer marker')
    bits = 48  # magic, standalone version, uniform type

    def take(n):
        nonlocal bits
        require(bits+n <= (len(frame)-1)*8,'truncated pcodec IntMult header')
        start, end = bits//8,(bits+n+7)//8
        value = (int.from_bytes(frame[start:end],'little') >> (bits%8)) & ((1<<n)-1)
        bits += n
        return value

    width = take(6)+1
    hint = take(width)
    require(hint > 0 and hint.bit_length() == width and take((-bits)%8) == 0,'noncanonical pcodec count hint')
    require((take(8),take(8)) == (4,1),'unexpected pcodec wrapped wire version')
    t = take(8)
    require(t in (1,2) and frame[5] in (0,t),'pcodec chunk dtype disagrees with file header')
    count = take(24)+1
    require(count == hint,'pcodec chunk count disagrees with file hint')
    mode = take(4)
    require(mode in (0,1),'unexpected pcodec IntMult comparison mode')
    base = take(32 if t == 1 else 64) if mode == 1 else None
    require((mode == 0 or base > 0) and take(4) == 0,'unexpected pcodec IntMult base or delta')
    return {'dtype':'u32' if t == 1 else 'u64','count':count,'mode':mode,'base':base,'delta':0}


def _verify_intmult(spec, row, out):
    params = spec['parameters']
    frames = []
    for job in spec['frames']:
        frame = _read(out,job['frame'],15,job['plain']['bytes']+65536)
        mode,base = job['wire_mode'],job['wire_base']
        count,dtype = job['count'],job['dtype']
        _exact(intmult_wire_header(frame),{'dtype':dtype,'count':count,'mode':mode,'base':base,'delta':params['delta']},
               'pcodec IntMult emitted mode or exact integer base differs')
        chunk = {'backend':'source-rust-repaired','mode':mode,
                 'mode_detail':f'IntMult({dtype.upper()}({base}))' if mode == 1 else 'Classic',
                 'delta':params['delta'],'delta_detail':'NoOp'}
        frames.append({'case':job['case'],'artifact':identity(frame),
                       'fresh_process':{'restored':job['plain'],'spans':page_spans(count,params['read_capacity'])+[0],
                                        'state':{'backend':'source-rust-repaired','kind':'standalone',
                                                 'decoded_chunk_headers':[chunk]}}})
    rejected = [{**x,'status':1,'output_bytes':0,'output_pointer_null':True} for x in spec['rejected']]
    _exact(row,{'entry':'pc_compress_intmult','parameters':params,'frames':frames,'rejected':rejected},
           'pcodec IntMult artifact, terminal drain, exact restore or rejected input differs')


def verify_pcodec(bundle, build, driver, out, *, sealed_paths=None):
    require(bundle['bundle_id'] == content_id({k:v for k,v in bundle.items() if k != 'bundle_id'}),
            'pcodec bundle identity differs')
    expected = {bundle['evidence_path'],*bundle['binary']}
    require(sealed_paths is None or {p for p in sealed_paths if p.startswith('pcodec-')} == expected,
            'pcodec sealed artifact closure differs')
    report = load_json(local_file(out,bundle['evidence_path']))
    require(isinstance(report,dict) and report.keys() == {'schema','bundle_id','case_ids','config_id','archive_sha256',
            'definitions','build','window','formal_performance','formal_qualification','standalone','pages','intmult'},
            'pcodec report shape differs')
    _exact({k:v for k,v in report.items() if k not in {'standalone','pages','intmult'}},
           {'schema':f'bmk.m0-pcodec-control/{3 if "intmult" in bundle else 2}','bundle_id':bundle['bundle_id'],
            'case_ids':[x['case_id'] for x in bundle['cases']], 'config_id':bundle['config_id'],
            'archive_sha256':bundle['archive_sha256'],'definitions':driver,'build':build,'window':bundle['window'],
            'formal_performance':False,'formal_qualification':False},'pcodec report bindings differ')
    for key,specs,verify in (('standalone',bundle['batch'],_verify_batch),('pages',bundle['page'],_verify_pages)):
        rows = report[key]
        require(isinstance(rows,dict) and rows.keys() == specs.keys(),f'pcodec {key} route closure differs')
        for route,spec in specs.items():
            verify(route,spec,rows[route],out)
    if 'intmult' in bundle:
        _verify_intmult(bundle['intmult'],report['intmult'],out)
