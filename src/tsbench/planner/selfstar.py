"""Freeze ordered SElf* V1 cases, state boundaries and retained artifacts."""
from hashlib import sha256
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from .corpus_windows import bind_window, read_window

CONFIG = 'configs/suites/dev_selfstar_v1/cases.json'
PLUGIN, ALGORITHM, BLOCK = 'selfstar-batch', 3, 512
TEST, REPORT = 'tsbench.worker.selfstar-batch.ordered', 'selfstar-control.json'
WEATHER = 'selfstar-weather-original.f64'
MAGIC, HEADER, BITLEN = b'BMKSEL\x01\0', struct.Struct('<8sIQIQ'), struct.Struct('<I')
DTYPE_ID = {32:9,64:10}
BYTE_LIMIT, NATIVE_MAX_COUNT = 256 << 10, 1000
NATIVE_WORKSPACE = 25000
CHECKS = {
    'selfstar-batch': ('block_boundary_512_empty_tail','bits_and_canonical_nan_policy','block_reset_order',
                       'independent_native_compare','exception_or_domain_reject'),
    'selfstar-incremental': ('add_finish_and_replay_bits','state_reset_and_exception',
                             'full_finalized_block_recovery','incremental_state_bounds'),
}
INPUT_REJECTIONS = {'f32-qnan-tail':2,'f32-snan-tail':2,'f64-qnan-tail':2,'f64-snan-tail':2,
                    'empty':2,'unsupported-dtype':1,'unsupported-block-option':3}
FRAME_REJECTIONS = {'frame-truncated':5,'block-truncated':5,'zero-bit-length':5,'oversize-bit-length':5,
                    'trailing-byte':5,'zero-values':5,'unsupported-dtype':5}
NATIVE_REJECTIONS = {'batch-empty':1,'batch-1001':1,'batch-qnan':1,'batch-snan':1,'live-empty-finish':1,
                     'live-single-add-1001':1,'live-qnan':1,'live-snan':1,'live-cumulative-1001':1,
                     'live-capacity':2,'finish-after-capacity':5}
SPECIAL = {32: (0, 0x80000000, 1, 0x80000001, 0x00800000, 0x7f7fffff, 0x7f800000, 0xff800000),
           64: (0, 0x8000000000000000, 1, 0x8000000000000001, 0x0010000000000000,
                0x7fefffffffffffff, 0x7ff0000000000000, 0xfff0000000000000)}
NAN = {32: (0x7fc00123, 0x7f800123), 64: (0x7ff8000000000123, 0x7ff0000000000123)}


def sha(data):
    return sha256(data).hexdigest()


def fixture(width, count):
    """Deterministic, IEEE typed before calling native; no float coercion in the adapter."""
    f = struct.Struct('<f' if width == 32 else '<d')
    item = width // 8
    output = bytearray()
    for i in range(count):
        block, j = divmod(i,BLOCK)
        if j < len(SPECIAL[width]):
            output += SPECIAL[width][j].to_bytes(item,'little')
        elif block % 3 == 0:
            output += f.pack((j % 19)*0.001 - 0.009)
        elif block % 3 == 1:
            # Deterministic high-mantissa-entropy bit shapes, never NaN.
            n = (i ^ (i << 19)) * 0x2545f4914f6cdd1d
            m = 23 if width == 32 else 52
            bits = ((n >> m) & 1) << (width-1) | (126 if width == 32 else 1022) << m | (n & ((1 << m)-1))
            output += bits.to_bytes(item,'little')
        else:
            output += f.pack((j % 113)*0.25 + 99)
    return bytes(output)



def ref(path, raw):
    return {'path':path,'bytes':len(raw),'sha256':sha(raw)}


def case_inputs(fixtures, weather):
    for width in fixtures['widths']:
        for count in fixtures['object_counts']:
            yield width, f'fixture-{count}', fixture(width,count)
    yield 64, 'weather-co2-heldout', weather


def schema_bytes(width, name):
    return canonical_bytes({'dtype':f'f{width}','column':'v','case':name})


def retained_paths(bundle):
    paths = {WEATHER, *(b['artifact'] for b in bundle['objects']), *(b['artifact'] for b in bundle['limits'])}
    for row in bundle['objects']:
        if row['ordered']:
            paths.update((row['snapshot'],row['fresh_second']))
    return paths


def plan_selfstar(root):
    cfg = load_json(local_file(root,CONFIG))
    require(isinstance(cfg,dict) and cfg.keys() == {'schema','selection','method','fixtures','incremental','validator',
                                                   'corpus','corpus_id','window'} and
            cfg['schema'] == 'bmk.dev-selfstar-cases/1' and cfg['selection'] == 4 and
            cfg['validator'] == 'selfstar_native_wire_parity_state_replay_and_bit_exact_v1','invalid SElf* case contract')
    method, fixtures, inc = (cfg[k] for k in ('method','fixtures','incremental'))
    require(canonical_bytes(method) == canonical_bytes({'plugin':PLUGIN,'role':'value','algorithm':'SF_SELF_STAR',
            'options':{},'threads':1,'block_values':BLOCK}) and canonical_bytes(fixtures) == canonical_bytes({
            'generator':'selfstar_finite_regime_and_special_bits_v1','widths':[32,64],'object_counts':[1,512,1591,2049]}) and
            canonical_bytes(inc) == canonical_bytes({'add_schedule':[1,7,63,121],'native_limits':[1,NATIVE_MAX_COUNT],
             'initial_state':'fresh_directional_context','end':'drain_through_has_value_zero'}),'invalid SElf* width or block policy')
    window = bind_window(root,cfg['corpus'],cfg['corpus_id'],cfg['window'])
    require(window['count'] == 1543,'SElf* frozen short tail differs')
    weather = read_window(root,window)
    objects = []
    for width,name,plain in case_inputs(fixtures,weather):
        key = f'selfstar-f{width}-{name}'
        count = len(plain)//(width//8)
        row = {'case':name,'width':width,'count':count,'input':ref('frozen:'+key,plain),
               'artifact':key+'.bmk','ordered':count>BLOCK}
        if row['ordered']:
            row.update(snapshot=key+'.prefix',fresh_second=key+'.fresh')
        objects.append(row)
    limits = [{'width':w,'artifact':f'selfstar-f{w}-native-max.raw',
               'input':ref(f'frozen:f{w}-native-max',fixture(w,NATIVE_MAX_COUNT))} for w in fixtures['widths']]
    body = {'schema':'bmk.selfstar-cases/1','test':TEST,'evidence_path':REPORT,'config_id':content_id(cfg),
            'method':method,'fixtures':fixtures,'incremental':inc,'window':window,'weather':ref(WEATHER,weather),
            'objects':objects,'limits':limits,'data_artifact_max_bytes':BYTE_LIMIT,'native_workspace_bytes':NATIVE_WORKSPACE,
            'rejections':{'input':INPUT_REJECTIONS,'frame':FRAME_REJECTIONS,'native':NATIVE_REJECTIONS},
            'qualification_granted':False}
    policy = content_id(body)
    body['cases'] = []
    for route,checks in CHECKS.items():
        for check in checks:
            row = {'name':check.replace('_','-'),'selection':4,'route':route,'check':check,'policy_id':policy}
            body['cases'].append({**row,'case_id':content_id(row)})
    return {**body,'bundle_id':content_id(body)}, weather
