"""Freeze selected ALP Auto branch and dispatch cases without performing a build."""
import hashlib
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from .corpus_windows import bind_window, read_tv_window

METHOD = 'alp-auto'
AVX512 = 'falp-avx512bw'
HEADER = struct.Struct('<8sIQIQ')
V, RG = 1024, 102400
ID = {'scalar-unfused':0,'falp-scalar':1,'falp-auto':3,'falp-avx2':2,'falp-avx512bw':4,'falp-neon':5,'falp-sve':6}
SPECIAL = {32:(0x80000000,0x7fc00123,0x7f800000,1,0xff800000,0x7f800123),
           64:(0x8000000000000000,0x7ff8000000000123,0x7ff0000000000000,1,0xfff0000000000000,0x7ff0000000000123)}
SPECIAL_POS = (3,5,7,11,13,15)  # outside the first-level sample at multiples of 32


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fixtures(width):
    item = width//8
    f,u,shift,exponent = ('f','I',23,127) if width == 32 else ('d','Q',52,1023)
    plain = b''.join(struct.pack('<'+f,(i%161-80)/10) for i in range(V))
    mixed = bytearray(plain)
    for i,bits in zip(SPECIAL_POS,SPECIAL[width],strict=True):
        struct.pack_into('<'+u,mixed,i*item,bits)
    entropy = hashlib.shake_256(b'alp/dev/branches-v1').digest(2*V*item)
    mask = (1<<shift)-1
    rd = b''.join(struct.pack('<'+u,(exponent<<shift)|(x&mask)) for x, in struct.iter_unpack('<'+u,entropy))
    return [('mixed-decimal-raw',bytes(mixed)+entropy[:V*item],['decimal']),('rd-only',rd,['rd']),
            ('raw-group',entropy,['raw']),('decimal-then-rd-rowgroup',plain*(RG//V)+rd,['decimal','rd'])]

CONFIG = 'configs/suites/dev_alp_v1/cases.json'
TEST = 'tsbench.worker.alp-auto.branches'
DIR = 'alp-native-control'
REAL = 'weather-co2-tail'
REAL_INPUT = 'weather-co2-tail.f64le'


def plan_alp(root):
    cfg = load_json(local_file(root, CONFIG))
    choices = ['mixed-decimal-raw', 'rd-only', 'raw-group', 'decimal-then-rd-rowgroup']
    require(cfg['schema'] == 'bmk.dev-alp-cases/1' and cfg['selection'] == 9 and
            cfg['method'] == {'plugin': METHOD, 'role':'value', 'encode_mode':'ALPN_AUTO', 'threads':1} and
            cfg['format'] == {'native':'ALN1', 'vector_size':V, 'rowgroup_size':RG} and
            cfg['fixtures'] == {'generator':'decimal_exception_rd_entropy_v1','widths':[32,64],'cases':choices} and
            cfg['validator'] == 'aln1_structure_and_bit_exact_in_new_process_v1' and cfg['decode_requests'] == list(ID)[:5],
            'unexpected ALP diagnostic config')
    window = bind_window(root, cfg['corpus'], cfg['corpus_id'], cfg['window'])
    _, weather = read_tv_window(root, window)
    names = []
    raw = {}
    cases = []
    for width in (32, 64):
        for label, values, kinds in [*fixtures(width), *([(REAL, weather, ['decimal'])] if width == 64 else [])]:
            name = f'f{width}-{label}'
            schema = canonical_bytes({'dtype':f'f{width}', 'column':'v'})
            vectors = {choices[0]:[1,0,1], choices[1]:[0,2,0], choices[2]:[0,0,2], choices[3]:[100,2,0], REAL:[1,0,1]}[label]
            fixture = {'name':name, 'width':width, 'label':label, 'frame':name+'.bmk', 'schema':schema.decode('ascii'),
                       'expected_kinds':kinds, 'decimal_rd_raw_vectors':vectors,
                       'count':len(values)//(width//8), 'input_bytes':len(values), 'input_sha256':sha(values)}
            if label == REAL:
                require(window['count'] == 1029, 'ALP weather tail case differs')
                fixture['window'] = window
            names.append(name)
            raw[name] = values
            cases.append(fixture)
    by_name = {c['name']:c for c in cases}
    def matching(*labels):
        return [c['name'] for c in cases if c['label'] in labels]
    groups = {
        'auto-batch': {
            'f32_f64_decimal_rd_and_raw': matching(*choices[:3]),
            'decimal_exception_bits': matching(choices[0]),
            'rowgroup_regime_switch': matching(choices[3]),
            'rounding_mode_controls': matching(REAL),
            'corrupt_side_info': matching(choices[0]),
        },
        'decode-backends': {
            'scalar_and_auto_dispatch': matching(choices[0]),
            'effective_backend_and_branch_counts': names,
            'unavailable_configuration_rejected': matching(choices[0]),
            'rd_raw_no_decimal_work': matching(*choices[1:3]),
        },
    }
    bound = []
    for route, checks in groups.items():
        for check, refs in checks.items():
            row = {'name':'alp-'+check.replace('_','-'), 'route':route, 'check':check, 'selection':9,
                   'criteria':{'fixtures':[by_name[x] for x in refs], 'decode_requests':cfg['decode_requests']}}
            bound.append({**row, 'case_id':content_id(row)})
    body = {'config_id':content_id(cfg), 'test':TEST, 'evidence_path':f'{DIR}/report.json', 'requests':cfg['decode_requests'],
            'fixtures':cases, 'cases':bound, 'raw_weather':REAL_INPUT,
            'binary':[c['frame'] for c in cases]+[REAL_INPUT]}
    return {**body, 'bundle_id':content_id(body)}, raw


def retained_paths(bundle):
    return [f'{DIR}/{name}' for name in bundle['binary']]
