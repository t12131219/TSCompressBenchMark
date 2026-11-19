"""Freeze Huff0 framed and shared-model development cases without mixing identities."""
from hashlib import sha256
from pathlib import Path
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from .corpus_windows import bind_training_window, bind_window, read_window

CONFIG = 'configs/suites/dev_huff0_v1/cases.json'
PLUGIN, BLOCK = 'huff0-reference', 32768
TEST, REPORT, CONTROL = 'tsbench.worker.huff0.profiles', 'huff0-control.json', 'tsbench_huff0_control'
WEATHER = 'huff0-weather-heldout.u8'
TRAIN = 'huff0-weather-training.u8'
ENVELOPE, FEC, RECORD, TABLE = (struct.Struct(f) for f in ('<8sIQIQ','<4sB3sIQI','<BIII','<BII'))
MAGIC = b'BMKHUF\x01\0'
MODE = ('raw','rle','huffman')
DECODE_API = ('FEC1_4X_hufOnly_wksp','ETB1_1X_usingDTable','ETB1_4X_usingDTable')
CHECKS = {
    'huff0-reference': ('fec1_fixed_4x_etb1_stream_boundary','empty_flat_and_incompressible','native_stream_observed',
                        'adaptive_modes','full_frame_independent_restore','length_corruption_and_size_reject'),
    'huff0-shared-table': ('etb1_holdout_table_identity','account_table_and_payload','stored_original_length',
                           'independent_restore_with_table','reject_unbound_table_and_bad_lengths'),
}
INPUT_REJECTIONS = {'wrong_dtype':1,'unbound_option':3}
FEC_REJECTIONS = {'envelope-truncated':5,'unexpected-algorithm':5,'declared-size-mismatch':5,
                  'trailing-byte':5,'envelope-size-limit':7}
NONEMPTY_FEC_REJECTIONS = {'illegal-mode':5,'crc-mismatch':5}
TABLE_REJECTIONS = {'missing-table':1,'unexpected-stream-tag':1,'truncated-model':1,'block-truncated':1,
                    'invalid-length-field':1,'decoded-value-limit':1}


def ref(path, raw):
    return {'path':path,'bytes':len(raw),'sha256':sha256(raw).hexdigest()}


def skew(n, phase):
    return bytes((i//11+phase)%5 if i%31 else (i//31+phase)%172 for i in range(n))


def fec_inputs(heldout, window):
    plain = bytes(range(256))*(BLOCK//256)
    yield 'empty', b'', None, []
    yield 'raw', plain, None, ['raw']
    yield 'rle', b'Z'*BLOCK, None, ['rle']
    yield 'mixed-stored-branches', plain+b'Z'*BLOCK+skew(BLOCK,7)+b'x', None, ['raw','rle','huffman','raw']
    yield 'weather-heldout-u8', heldout, window, ['huffman','huffman']


def table_inputs(heldout):
    plain = bytes(range(256))*(BLOCK//256)
    for streams in (1,4):
        yield 'synthetic', streams, [skew(BLOCK,1),skew(4093,2),plain,b'',b'z'], ['huffman','huffman','raw','raw','raw']
        yield 'weather-chronological', streams, [heldout[:BLOCK],heldout[BLOCK:]], ['huffman','huffman']


def train_input(name, train):
    return skew(BLOCK,0) if name == 'synthetic' else train


def retained_paths(bundle):
    paths = {WEATHER, TRAIN, *(b['artifact'] for b in bundle['fec1'])}
    for p in bundle['etb1']:
        paths.update((p['model'],p['other_model'],*(b['artifact'] for b in p['blocks'])))
    return paths


def plan_huff0(root: Path):
    cfg = load_json(local_file(root,CONFIG))
    require(isinstance(cfg,dict) and cfg.keys() == {'schema','selection','batch','table','fixture','validator','corpus',
            'corpus_id','transform','train','test'} and cfg['schema'] == 'bmk.dev-huff0-cases/1' and cfg['selection'] == 29 and
            cfg['fixture'] == 'skew_byte_v1' and cfg['validator'] == 'huff0_fec1_crc_and_etb1_detached_byte_exact_v1' and
            cfg['transform'] == 'canonical_f64_le_bytes_as_u8_v1', 'invalid Huff0 profile identity')
    require(canonical_bytes(cfg['batch']) == canonical_bytes({'plugin':PLUGIN,'role':'value','dtype':'u8',
            'options':{},'format':'FEC1','block_bytes':BLOCK}) and canonical_bytes(cfg['table']) == canonical_bytes({
            'model':'ETB1','block_header_bytes':TABLE.size,'table_log':0,'streams':[1,4],'max_training_bytes':BLOCK}),
            'invalid Huff0 stream or model policy')
    train = bind_training_window(root,cfg['corpus'],cfg['corpus_id'],cfg['train'])
    test = bind_window(root,cfg['corpus'],cfg['corpus_id'],cfg['test'])
    require(train['count'] == 4096 and test['count'] == 4103 and train['partition_end'] <= test['partition_start'] and
            all(train[k] == test[k] for k in ('dataset','column','profile','asset')),'Huff0 train/held-out partition differs')
    data = {kind:read_window(root,window) for kind,window in (('train',train),('test',test))}
    batch = []
    for name, raw, window, modes in fec_inputs(data['test'],test):
        batch.append({'name':name,'input':ref('frozen:'+name,raw),'window':window,
                      'artifact':f'huff0-{name}.bmk','modes':modes})
    profiles = []
    for name,streams,blocks,modes in table_inputs(data['test']):
        label = f'{name}-{streams}x'
        profiles.append({'profile':name,'streams':streams,'training':ref('frozen:'+name+'-training',train_input(name,data['train'])),
                         'model':f'huff0-{label}.etb1','other_model':f'huff0-alternate-{streams}x.etb1',
                         'blocks':[{'index':i,'input':ref(f'frozen:{name}-block-{i}',v),'mode':modes[i],
                                    'artifact':f'huff0-{label}-{i}.blk'} for i,v in enumerate(blocks)]})
    body = {'schema':'bmk.huff0-cases/1','test':TEST,'evidence_path':REPORT,'config_id':content_id(cfg),
            'train_window':train,'test_window':test,'training':ref(TRAIN,data['train']),
            'heldout':ref(WEATHER,data['test']),'fec1':batch,'etb1':profiles,
            'transform':cfg['transform'],'fixture':cfg['fixture'],'data_artifact_max_bytes':8*BLOCK,
            'rejections':{'input':INPUT_REJECTIONS,'fec1':FEC_REJECTIONS,'nonempty_fec1':NONEMPTY_FEC_REJECTIONS,
                          'table':TABLE_REJECTIONS},'qualification_granted':False}
    policy = content_id(body)
    body['cases'] = []
    for route,names in CHECKS.items():
        for check in names:
            row = {'name':check.replace('_','-'),'selection':29,'route':route,'check':check,'policy_id':policy}
            body['cases'].append({**row,'case_id':content_id(row)})
    return {**body,'bundle_id':content_id(body)}, data
