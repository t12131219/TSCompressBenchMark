"""Freeze baseline and native span-session test cases for the shared Unique build."""
from hashlib import sha256, shake_256

from ..assets import content_id, digest, load_json, local_file, require

DIR = 'lzbench-native-probe'
TEST = 'tsbench.control.lzbench'
INVENTORY = 'catalog/selections/first_batch_native.json'
ARCHIVE = 'third_party/archives/lzbench-native-source-unique-v1.tar.gz'
BASE_SIZES = (0, 1, 65535, 65536)
XZ_GUARD_NAME = 'xz-dictionary-over-budget.xz'
SPAN_LIMITS = {
    'encode-first': ('first', 4093, 7),
    'encode-second-after-reset': ('second', 947, 11),
    'decode-second-fresh': ('second', 17, 113),
    'decode-first': ('first', 19, 127),
    'decode-second-after-reset': ('second', 13, 251),
    'decode-second-after-failure-and-reset': ('second', 17, 71),
}


def sample(n, salt):
    return bytes((i//19 + (i%29)*salt) & 255 for i in range(n))


def source(n, salt):
    return {'bytes': n, 'sha256': sha256(sample(n,salt)).hexdigest(), 'salt': salt}


def byte_identity(data):
    return {'bytes':len(data), 'sha256':sha256(data).hexdigest()}


def dictionary_sample(partition, index):
    template = f'device={index % 13:02};unit=power;state=running;window=aggregate;'.encode()
    return (template + shake_256(f'{partition}:{index}'.encode()).digest(12)) * (8 + index % 5)


def worker_input(codec, size):
    return shake_256(f'tsbench-lzbench-{codec}-workers/v1'.encode()).digest(size)


def _dictionary_plan():
    split = {partition:[byte_identity(dictionary_sample(partition,i)) for i in range(count)]
             for partition,count in (('train',128),('held-out',31))}
    train, held = ({x['sha256'] for x in split[p]} for p in ('train','held-out'))
    require(len(train) == 128 and len(held) == 31 and train.isdisjoint(held), 'dictionary train/held-out overlap')
    return {'generator':'device-template-shake256-v1', 'training_samples':split['train'], 'held_out_samples':split['held-out'],
            'held_out':byte_identity(b''.join(dictionary_sample('held-out',i) for i in range(31))),
            'capacity':2048,'bad_capacities':[255,2**31], 'dictionary_path':'trained.zdict','frame_path':'dictionary.zst',
            'parameters':{'content_size':1,'checksum':0,'job_size':0,'level':3,'pledged_size':-1,'strategy':0,'window_log':0,'workers':0},
            'span_profiles':{'train_not_timed':True,'roundtrip':[307,521],'fresh_decode':[181,619]}}


def _worker_plan(codec):
    is_zstd = codec == 'zstd'
    size = ((5 if is_zstd else 2) << 20) + 297
    profiles = (0,2) if is_zstd else (1,2)
    ext = 'zst' if is_zstd else 'xz'
    return {'input':byte_identity(worker_input(codec,size)), 'parameter':'workers' if is_zstd else 'threads',
            'frame_paths':{str(n):f'workers-{n}.{ext}' for n in profiles}, 'settings':list(profiles),
            'base':{'job_size':524288} if is_zstd else {'block_size':131072,'memory_limit':134217728,'check':4},
            'level':3 if is_zstd else 1,'span_profile':[262139,65521],
            'xz_same_frame_decode_spans':[size+65536,131071] if not is_zstd else None,
            **({} if is_zstd else {'synchronous': {
                'frame_path':'workers-sync.xz','encoder':'lzma_block_encoder','decoder':'lzma_stream_decoder',
                'inner_input_span_bytes':16384,'filter_id':0x21,'dictionary_property':0x10,'dict_size':1<<20,
                'fallback_blocks':0}})}


def plan_lzbench(root):
    inv = load_json(local_file(root, INVENTORY))
    entries = {e['selection']:e for e in inv['entries'] if e['selection'] in (39,40)}
    lock = load_json(local_file(root, 'third_party/sources.lock.json'))
    archive = lock['sources']['lzbench-native']['archive']
    require(archive['path'] == ARCHIVE and entries.keys() == {39,40} and
            all(e['archive_sha256'] == archive['sha256'] and e['target'] == 'lzbench_native' for e in entries.values()),
            'lzbench selected source and inventory differ')
    baseline = [{'frame':f'zstd-legacy-{n}.zst','input':source(n,7)} for n in BASE_SIZES]
    baseline.append({'frame':'zstd-upstream.zst','input':source(BASE_SIZES[-1],7)})
    xz_baseline = {'frames':[{'frame':f'xz-legacy-{n}.xz','input':source(n,7)} for n in BASE_SIZES],
                   'preset':6,'encoder_threads':1,'check':0,'dictionary_property':22,'decoder_memlimit':256<<20,
                   'oversize':source(BASE_SIZES[-1]+1,7)}
    inputs = {'first':source(136013,9), 'second':source(7919,13)}
    sessions = {codec:{'files':{key:f'session-{key}.{ext}' for key in inputs},'inputs':inputs,
                       'span_limits':{name:list(values) for name,values in SPAN_LIMITS.items()},
                       'level': -1 if codec == 'zstd' else 1,
                       'parameters': {'workers':0,'checksum':1} if codec == 'zstd' else
                           {'block_size':32768,'check':4,'filter0':3,'filter0_distance':4,'memory_limit':64<<20,'threads':1}}
                for codec,ext in (('zstd','zst'),('xz','xz'))}
    dictionary = _dictionary_plan()
    workers = {codec:_worker_plan(codec) for codec in ('zstd','xz')}
    xz_guard = {'base_frame':'xz-legacy-1.xz','frame':XZ_GUARD_NAME,'dictionary_property':33,
                'advertised_dictionary_bytes':384<<20,'output_bytes':1,
                'legacy_decoder_memlimit':xz_baseline['decoder_memlimit'],
                'session_decoder_memlimit':sessions['xz']['parameters']['memory_limit'],
                'session_encoder_bad_budget':1,'session_bad_filter':127}
    sessions['xz']['dictionary_property'] = 16
    cases = []
    for selection, route, checks, criteria in (
        (40,'zstd-baseline', ['empty_and_short','native_frame_flags','correct_output_length_and_truncation','independent_upstream_frame'],
         {'level':3,'frames':baseline}),
        (40,'zstd-session', ['caller_span_progress','first_bytes_finish_drain','directional_reset','independent_frame_restore','truncation_and_batch_only_reject'],
         sessions['zstd']),
        (39,'xz-baseline', ['byte_block_boundary_triplet','empty_and_short','preset_threads_and_check',
                            'correct_output_size','memlimit_and_truncation'], {**xz_baseline,'negative':xz_guard}),
        (39,'xz-session', ['caller_span_progress','finish_drain_and_reset','multiblock_lzma2',
                           'check_and_filter_independent_decode','low_memlimit_and_unsupported_filters'],
         {**sessions['xz'],'negative':xz_guard}),
        (40,'zstd-dictionary', ['disjoint_training_and_holdout','trainer_bounds','exact_dictionary_identity_and_charge',
                               'independent_restore_with_dictionary','missing_and_wrong_dictionary_rejected'],
         {'dictionary_path':dictionary['dictionary_path'],'frame_path':dictionary['frame_path'],
          'held_out_sha256':dictionary['held_out']['sha256'],'dictionary_plan_id':content_id(dictionary)}),
        (40,'zstd-workers', ['synchronous_control','same_frame_options','independent_decode'], workers['zstd']),
        (39,'xz-workers', ['synchronous_control','multiblock_frames_under_matched_options','identical_original_bytes'], workers['xz']),
    ):
        for check in checks:
            row = {'name':f'{route}-{check.replace("_","-")}', 'selection':selection,'route':route,'check':check,'criteria':criteria}
            cases.append({**row,'case_id':content_id(row)})
    body = {'test':TEST,'evidence_path':f'{DIR}/report.json','archive_sha256':archive['sha256'],
            'inventory_sha256':digest(local_file(root,INVENTORY)),
            'groups':[{'selection':e['selection'],'selection_id':e['selection_id'],'group':op['route']}
                      for e in (entries[40],entries[39]) for op in e['operations']],
            'baseline':baseline,'xz_baseline':xz_baseline,'xz_guard':xz_guard,'sessions':sessions,
            'dictionary':dictionary,'workers':workers,'cases':cases,
            'binary':[x['frame'] for x in baseline]+[f for x in sessions.values() for f in x['files'].values()] +
            [dictionary['dictionary_path'],dictionary['frame_path']] +
            [f for x in workers.values() for f in x['frame_paths'].values()] +
            [workers['xz']['synchronous']['frame_path']] +
            [x['frame'] for x in xz_baseline['frames']] + [xz_guard['frame']]}
    return {**body,'bundle_id':content_id(body)}


def retained_paths(bundle):
    return [f'{DIR}/{p}' for p in bundle['binary']]


def probe_schema(bundle):
    if 'synchronous' in bundle.get('workers',{}).get('xz',{}):
        return 'bmk.m0-lzbench-native-probe/5'
    if 'xz_baseline' in bundle and 'xz_guard' in bundle:
        return 'bmk.m0-lzbench-native-probe/4'
    if 'dictionary' in bundle and 'workers' in bundle:
        return 'bmk.m0-lzbench-native-probe/3'
    return 'bmk.m0-lzbench-native-probe/2'
