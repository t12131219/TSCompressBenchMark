"""Freeze the real-corpus Zstd trained-dictionary route and its source partitions."""
from pathlib import PurePosixPath

from ..assets import digest, local_file, require, verify_asset

KEY = (40,'zstd-dictionary')
DRIVER = 'zstd-dictionary-corpus/1'
LIMIT = 65536
SOURCES = ('plugins/codecs/zstd/CMakeLists.txt','src/tsbench/planner/m3_zstd_dictionary.py',
           'src/tsbench/application/m3_zstd_dictionary.py','src/tsbench/qualification/lzbench.py')
PROFILE = {'profile':'zstd_two_extents_train_v1','max_samples':128,'max_sample_bytes':2048,'min_samples':8,
           'min_total_bytes':8192,'short_train':{'capacity_bytes':256,'sample_bytes':32,'min_samples':8}}


def bind(root,build):
    plugin = build['plugins'].get('zstd')
    if plugin is None:
        return None
    # Frozen CMake places the feature control beside the selected native DSO.
    exe = PurePosixPath(plugin['library']['path']).with_name('tsbench_lzbench_feature_control').as_posix()
    if not (root/exe).is_file():
        return None
    dep, = plugin['dependencies']
    require(PurePosixPath(dep['path']).name=='liblzbench_native.so','Zstd trainer dependency differs from locked native library')
    verify_asset(root,dep)
    p = local_file(root,exe)
    return {'executable':{'path':exe,'bytes':p.stat().st_size,'sha256':digest(p)},
            'dependency':{**dep,'bytes':local_file(root,dep['path']).stat().st_size},
            'code':{f:digest(local_file(root,f)) for f in SOURCES}}


def check_route(binding):
    require(binding['view']=='v_bytes_interleaved' and binding['operation']=='train_then_test_roundtrip' and
            binding['partition']=='train_test' and binding['options']=={'capacity_bytes':2048,'level':3} and
            binding['missing']=='preserve' and binding['training']==PROFILE and binding['bytes_per_unit']==LIMIT,
            'Zstd dictionary training or held-out contract differs')


def extents(item,entry):
    train, _, test = entry['partitions']
    width = entry['value_count']*8
    scope = item['input']; spec = scope['training']
    train_bytes = (train['end']-train['start'])*width
    tier = 'short' if train_bytes < PROFILE['min_total_bytes'] else 'standard'
    each = 32 if tier=='short' else min(2048, train_bytes//64*8)
    count = min(128,train_bytes//each)
    consumed = each*count; test_bytes = (test['end']-test['start'])*width
    evaluation = spec['evaluation']; estimate = scope['size_estimate']
    require(item['dataset_id']==entry['id'] and item['canonical_object_id']==entry['canonical']['object_id'] and
            item['applicability']=='input_domain_matches' and scope['representation']=='v_bytes_interleaved' and
            scope['value_column_range']==[0,entry['value_count']] and train['end']<=test['start'] and
            spec['origin']=='same_file_only' and spec['profile']==PROFILE and spec['extent_tier']==tier and
            spec['partition']=='train' and spec['partition_object_id']==train['canonical']['object_id'] and
            spec['coordinate']=='canonical_row_major_v_bytes_relative_to_train_partition' and
            spec['dictionary_capacity_bytes']==(256 if tier=='short' else 2048) and count>=8 and
            spec['sample_geometry']=={'first_byte':0,'count':count,'bytes_each':each,'stride_bytes':each} and
            spec['consumed_byte_range']==[0,consumed] and spec['unconsumed_train_byte_range']==[consumed,train_bytes] and
            evaluation=={'partition':'test','partition_object_id':test['canonical']['object_id'],
                         'absolute_rows':[test['start'],test['end']],'frame_input_limit_bytes':LIMIT} and
            (estimate['native_input_bytes_one_pass'],estimate['input_units'])==(consumed+test_bytes,1+(test_bytes+LIMIT-1)//LIMIT),
            'Zstd train and held-out source extents do not match frozen input contract')
    return ((train['start']*width,train['start']*width+consumed),(test['start']*width,test['end']*width)),each,count
