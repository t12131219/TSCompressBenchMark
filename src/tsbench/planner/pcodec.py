"""Bind pcodec native fixtures to the frozen Unique selection."""
from hashlib import sha256, shake_256
import struct

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, require
from .corpus_windows import bind_window, read_tv_window

CONFIG = 'configs/suites/dev_pcodec_v1/cases.json'
TEST = 'tsbench.worker.pcodec.recovery'
REPORT = 'pcodec-control.json'
HEADER = struct.Struct('<8sIQIQ')
SOURCE, C_NATIVE = 'pcodec-source-auto', 'pcodec-c-native-auto'
MAGIC = {SOURCE:b'BMKPCS\1\0', C_NATIVE:b'BMKPCN\1\0'}
TYPES = {'i8':(1,11,'b'), 'u8':(2,10,'B'), 'i16':(3,8,'h'), 'u16':(4,7,'H'),
         'i32':(5,3,'i'), 'u32':(6,1,'I'), 'i64':(7,4,'q'), 'u64':(8,2,'Q'),
         'f32':(9,5,'I'), 'f64':(10,6,'Q'), 'f16':(12,9,'H')}
TRAFFIC = 'traffic-test-value'
DEFAULTS = {'level':8,'mode':-1,'delta':-1,'chunk_n':262144}
BATCH_CHECKS = {
    'source-auto':('rust_source_dispatch','all_declared_dtypes','f16_special_bits','frame_identity',
                   'output_count_bound','missing_metadata_and_corrupt_rejection'),
    'c-native-auto':('c_native_encoder_rust_source_decoder','all_declared_dtypes','explicit_f16_rejection',
                     'output_count_bound','separate_format'),
}
PAGE_CHECKS = {
    'source-pages':('train_chunk_header_separately','full_page_required','bounded_incremental_drain',
                    'detached_page_with_metadata','missing_metadata_rejected','source_page_output_limit'),
    'native-pages':('native_page_ownership','full_page_required','bounded_incremental_drain',
                    'detached_page_with_metadata','cumulative_decoder_quota','invalid_page_and_drain_rejected'),
}
INTMULT_CHECKS = {
    'emitted_intmult':'multiples', 'exact_uint64_base':'wide-base',
    'classic_size_fallback':'high-entropy', 'invalid_base_and_float_rejected':None,
}


def pack(code, values):
    return b''.join(struct.pack('<'+code,v) for v in values)


def identity(data):
    return {'bytes':len(data),'sha256':sha256(data).hexdigest()}


def fixture_cases():
    yield 'empty','f64',b''
    for dtype, (_,_,code) in TYPES.items():
        if dtype.startswith('f'):
            mantissa, exponent = {'f16':(10,5),'f32':(23,8),'f64':(52,11)}[dtype]
            inf = ((1 << exponent)-1) << mantissa
            sign = 1 << (mantissa+exponent)
            values = [0,sign,1,sign|1,inf,sign|inf,inf|(1<<(mantissa-1))|7,inf|3]
        else:
            bits = struct.calcsize(code)*8
            low,high = (-(1<<(bits-1)),(1<<(bits-1))-1) if dtype.startswith('i') else (0,(1<<bits)-1)
            values = [low,high,low+1,high-1,0,1]
        yield dtype+'-extreme-bits',dtype,pack(code,values*45+values[:1])


def page_spans(count,cap):
    return [cap]*(count//cap)+([count%cap] if count%cap else [])


INTMULT_CONFIG = {
    'dtype':'u32','count':2048,'base':4093,'u64_count':513,'u64_base':2**53+1,
    'level':8,'delta':0,'chunk_n':262144,'read_capacity':256,
    'validator':'intmult_domain_wire_mode_and_detached_bits_v2',
}


def intmult_inputs(cfg):
    require(canonical_bytes(cfg) == canonical_bytes(INTMULT_CONFIG), 'unexpected pcodec IntMult case config')
    base,big = cfg['base'],cfg['u64_base']
    n,wide = cfg['count'],cfg['u64_count']
    data = {'multiples':pack('I',((i*611%2048)*base for i in range(n))),
            'high-entropy':shake_256(b'tsbench-pcodec-intmult-fallback/v1').digest(n*4),
            'wide-base':pack('Q',(i*big for i in range(wide)))}
    frames = []
    for name,dtype,count,requested,emitted in (('multiples','u32',n,base,base),
                                               ('high-entropy','u32',n,base,None),
                                               ('wide-base','u64',wide,big,big)):
        frames.append({'case':name,'dtype':dtype,'count':count,'base':requested,'wire_base':emitted,
                       'wire_mode':int(emitted is not None),'plain':identity(data[name]),
                       'frame':f'pcodec-intmult-{name}.pco'})
    rejected = [
        {'case':'zero-base','dtype':'u32','base':0,'plain':identity(bytes(4))},
        {'case':'base-exceeds-u32','dtype':'u32','base':2**32,'plain':identity(bytes(4))},
        {'case':'float-input','dtype':'f64','base':base,'plain':identity(bytes(8))},
    ]
    parameters = {k:cfg[k] for k in ('level','delta','chunk_n','read_capacity')}
    return {'frames':frames,'rejected':rejected,'parameters':parameters}, data


def plan_pcodec(root):
    cfg = load_json(local_file(root, CONFIG))
    require(cfg['schema'] == 'bmk.dev-pcodec-cases/1' and type(cfg['selection']) is int and cfg['selection'] == 11 and
            cfg['batch'] == {'role':'value','methods':[SOURCE,C_NATIVE],'options':{},
                             'validator':'direct_standalone_payload_and_isolated_value_bits_v1'},'unexpected pcodec case config')
    window = bind_window(root,cfg['corpus'],cfg['corpus_id'],cfg['window'])
    _, values = read_tv_window(root,window)
    inputs = list(fixture_cases())+[(TRAFFIC,'f64',values)]
    archive = load_json(local_file(root,'third_party/sources.lock.json'))['sources']['pcodec-native']['archive']
    require(digest(local_file(root,archive['path'])) == archive['sha256'],'pcodec frozen archive identity differs')
    pages = cfg['pages']
    counts,cap = pages['page_counts'],pages['read_capacity']
    require(pages['routes'] == list(PAGE_CHECKS) and counts == [513,260] and cap == 256 and sum(counts)*8 == len(values),
            'unexpected pcodec page case config')
    batches = {}
    for method in (SOURCE,C_NATIVE):
        rows = []
        for name,dtype,data in inputs:
            width = struct.calcsize(TYPES[dtype][2]); assert len(data)%width == 0
            rows.append({'case':name,'dtype':dtype,'count':len(data)//width,'plain':identity(data),
                         'schema':canonical_bytes({'column':'value','dtype':dtype}).decode('ascii'),
                         'frame':None if method == C_NATIVE and dtype == 'f16' else f'{method}-{name}.bmk'})
        batches[method] = rows
    page_specs = {}
    for route in pages['routes']:
        cursor = 0
        rows = []
        for i,count in enumerate(counts):
            src = values[cursor:cursor+count*8]
            rows.append({'page':f'pcodec-{route}-{i}.page','count':count,'plain':identity(src),'spans':page_spans(count,cap)})
            cursor += count*8
        page_specs[route] = {'meta':f'pcodec-{route}.meta','sidecar':f'pcodec-{route}.sidecar','pages':rows,
                             'capacity':cap,'dtype':TYPES['f64'][1],'input':identity(values)}
    cases = []
    for route, checks in {**BATCH_CHECKS,**PAGE_CHECKS}.items():
        criteria = (dict(batch=batches['pcodec-'+route],defaults=DEFAULTS) if route in BATCH_CHECKS else
                    dict(binding=page_specs[route],window=window))
        for check in checks:
            row = {'name':f'pcodec-{route}-{check.replace("_","-")}','selection':11,'route':route,'check':check,'criteria':criteria}
            cases.append({**row,'case_id':content_id(row)})
    binary = [x['frame'] for rows in batches.values() for x in rows if x['frame']]
    binary += [path for spec in page_specs.values() for path in (spec['meta'],spec['sidecar'],*(x['page'] for x in spec['pages']))]
    intmult, _ = intmult_inputs(cfg['intmult'])
    by_name = {spec['case']:spec for spec in intmult['frames']}
    for check,name in INTMULT_CHECKS.items():
        row = {'name':'pcodec-intmult-'+check.replace('_','-'),'selection':11,'route':'intmult','check':check,
               'criteria':{'parameters':intmult['parameters'],
                           **({'frame':by_name[name]} if name else {'rejected':intmult['rejected']})}}
        cases.append({**row,'case_id':content_id(row)})
    binary += [row['frame'] for row in intmult['frames']]
    body = {'test':TEST,'evidence_path':REPORT,'config_id':content_id(cfg),'archive_sha256':archive['sha256'],
            'window':window,'batch':batches,'defaults':DEFAULTS,'page':page_specs,'intmult':intmult,
            'cases':cases,'binary':binary}
    return {**body,'bundle_id':content_id(body)},inputs
