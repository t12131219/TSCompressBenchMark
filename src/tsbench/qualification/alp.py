"""Validate ALP branch, process restore, dispatch and side-information evidence offline."""
from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..planner.alp import AVX512, DIR, HEADER, ID, METHOD, REAL, RG, SPECIAL, SPECIAL_POS, fixtures, retained_paths, sha
from .alp_wire import analyze, corrupt_positions
from .probe_build import verify_probe_build_lock


def _exact(actual, expected, message):
    require(canonical_bytes(actual) == canonical_bytes(expected), message)


def _read(out, name, minimum, maximum):
    file = local_file(out, f'{DIR}/{name}')
    require(minimum <= file.stat().st_size <= maximum, 'ALP evidence length differs from bound')
    return file.read_bytes()


def _backends(support):
    require(isinstance(support, dict) and support.keys() == {'32','64'}, 'ALP width closure differs')
    for width, caps in support.items():
        verify_backend_width(width,caps)


def verify_backend_width(width,caps):
    require(isinstance(caps,dict) and caps.keys() == ID.keys(), 'ALP backend closure differs')
    for backend, cap in caps.items():
        require(isinstance(cap,dict) and type(cap.get('built_for_width')) is bool and type(cap.get('available')) is bool,
                'invalid ALP native backend evidence')
        built, available = cap['built_for_width'], cap['available']
        if backend in ('falp-neon', 'falp-sve'):
            reason = 'platform_not_selected'
            require(not built, 'ALP ARM backend was not selected for x86-64')
        elif width == '32' and backend in ('falp-avx2',AVX512):
            reason = 'width_unsupported'
            require(not built, 'ALP fused x86 backend was not defined for f32')
        else:
            reason = 'not_built' if not built else 'runtime_unavailable' if not available else None
            if backend not in ('falp-avx2',AVX512):
                require(built and available, 'ALP lost a required scalar or Auto backend')
        expected = {'built_for_width':built,'available':reason is None,'reason':reason}
        if width == '64' and backend == AVX512:
            require(built, 'ALP lost compiled AVX512BW')
            expected['runtime_state'] = 'available' if available else 'pending_supported_runtime'
        _exact(cap, expected, 'ALP native backend state differs from availability policy')


def verify_alp(bundle, build, driver_sha256, out, *, ffi_sha256, sealed_paths=None):
    require(bundle['bundle_id'] == content_id({k:v for k,v in bundle.items() if k != 'bundle_id'}), 'ALP bundle identity differs')
    wanted = {bundle['evidence_path'], *retained_paths(bundle)}
    require(sealed_paths is None or {p for p in sealed_paths if p.startswith(DIR+'/')} == wanted,
            'ALP sealed artifact closure differs')
    doc = load_json(local_file(out,bundle['evidence_path']))
    require(isinstance(doc,dict) and doc.keys() == {'schema','config_id','bundle_id','case_ids','definitions','build',
            'native_version','formal_performance','formal_qualification','backend_conditions','cases','fenv'} and
            doc['schema'] == 'bmk.m0-alp-control/2' and doc['config_id'] == bundle['config_id'] and
            doc['bundle_id'] == bundle['bundle_id'] and doc['case_ids'] == [c['case_id'] for c in bundle['cases']] and
            doc['definitions'] == {'probe_sha256':driver_sha256,'ffi_sha256':ffi_sha256} and
            doc['formal_performance'] is False and doc['formal_qualification'] is False and
            isinstance(doc['native_version'],str) and doc['native_version'].startswith('alp-native '),'ALP report binding differs')
    verify_probe_build_lock(doc['build'], build, METHOD, dependency_count=1)
    support = doc['backend_conditions']
    _backends(support)
    synthetic = {(width,label): values for width in (32,64) for label,values,_ in fixtures(width)}
    rows = doc['cases']
    require(isinstance(rows,list) and len(rows) == len(bundle['fixtures']), 'ALP evidence case closure differs')
    for case,row in zip(bundle['fixtures'],rows,strict=True):
        width,label,n = case['width'],case['label'],case['count']
        dtype = 9 if width == 32 else 10
        schema = case['schema'].encode('ascii')
        total = case['input_bytes']
        raw = _read(out,bundle['raw_weather'],total,total) if label == REAL else synthetic[width,label]
        require(len(raw) == total and sha(raw) == case['input_sha256'], 'ALP original-domain input differs')
        prefix = HEADER.size + len(schema)
        full = _read(out,case['frame'],prefix+6,prefix+total+(n+RG-1)//RG+16)
        payload = full[prefix:]
        require(HEADER.unpack_from(full) == (b'BMKALP\1\0',dtype,n,len(schema),len(payload)) and
                full[HEADER.size:prefix] == schema,'ALP frame envelope differs')
        positions = []
        layout = analyze(payload,raw,width,positions=positions)
        dec, rd, raw_count = case['decimal_rd_raw_vectors']
        require(layout['rowgroup_kinds'] == case['expected_kinds'] and
                [layout['coded_decimal_vectors'],layout['coded_rd_vectors'],layout['raw_vectors']] == [dec,rd,raw_count],
                'ALP emitted branch work differs from frozen case')
        if label == 'mixed-decimal-raw':
            _exact(layout['special_exception_bits'], [{'index':i,'bits':hex(v)} for i,v in zip(SPECIAL_POS,SPECIAL[width],strict=True)],
                   'ALP decimal exception raw bit pattern differs')
        caps = support[str(width)]
        outcomes = []
        for req in bundle['requests']:
            if not caps[req]['available']:
                outcomes.append({'request':req,'state':'rejected_unavailable','reason':caps[req]['reason'],'abi_status':1})
                continue
            dispatch = next(b for b in (AVX512,'falp-avx2','falp-scalar') if caps[b]['available']) if req == 'falp-auto' else req
            counter = dec if dispatch != AVX512 else None
            outcomes.append({'request':req,'dispatch':dispatch,'state':'restored_bit_exact',
                            'decimal_vectors_in_wire':dec,'native_decimal_kernel_vectors':counter,
                            'native_execution_confirmation':('no_decimal_work_in_wire' if not dec else
                                  'measured_counter' if counter is not None else 'dispatch_only_no_native_counter'),
                            'rd_vectors':rd,'raw_vectors':raw_count,
                            'restored':{'dtype':dtype,'count':n,'input_sha256':sha(raw),'schema_sha256':sha(schema)}})
        side_info = {}
        if label == 'mixed-decimal-raw':
            for name,(offset,bad) in corrupt_positions(payload,positions).items():
                side_info[name] = {'payload_offset':offset,'frame_sha256':sha(full[:prefix]+bad),'abi_status':5,
                                   'diagnostic':'plugin status 5: decode failed (5): invalid exception position'}
        expected = {'case':label,'width':width,'count':n,'input_bytes':total,'input_sha256':sha(raw),
                    'native_bytes':len(payload),'native_sha256':sha(payload),'envelope_bytes':len(full),
                    'envelope_sha256':sha(full),'schema_bytes':len(schema),'wire':layout,'backends':outcomes,
                    'rejected_artifacts':3,'side_info':side_info}
        if 'window' in case:
            expected['window'] = case['window']
        _exact(row,expected,'ALP restore, native path or side-information rejection evidence differs')
    _exact(doc['fenv'], {'before':0,'changed':0x400,'after':0,
            'encode':{'status':1,'written':0,'message':'compression requires FE_TONEAREST'},
            'decode':{'status':1,'written':0,'message':'decompression requires FE_TONEAREST'}},
           'ALP floating-point rounding evidence differs')
