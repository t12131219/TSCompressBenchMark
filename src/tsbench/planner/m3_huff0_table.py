"""Bind both ETB1 stream variants to the same frozen train/holdout extents."""
from pathlib import PurePosixPath

from ..assets import digest, local_file, require, verify_asset
from .huff0 import BLOCK
from .huff0_execution import SHARED

KEY=(29,SHARED)
DRIVER='huff0-etb1-corpus/1'
TARGET='tsbench_huff0_corpus_table_control'
STREAMS=(1,4)
RETAIN_MAX=1 << 20
PROFILE={'profile':'huff0_bounded_train_v1','max_train_bytes':BLOCK,'streams':list(STREAMS)}
SOURCES=('cmake/huff0-corpus.cmake','plugins/codecs/huff0-reference/corpus_table_control.cpp',
         'src/tsbench/planner/m3_huff0_table.py','src/tsbench/application/m3_huff0_table.py',
         'src/tsbench/qualification/huff0.py')


def bind(root,build):
    plugin=build['plugins'].get('huff0-reference')
    if plugin is None:
        return None
    folder=PurePosixPath(plugin['library']['path']).parent
    exe=(folder/TARGET).as_posix()
    if not (root/exe).is_file():
        return None
    dep,=plugin['dependencies']
    require(dep['path']==(folder/'libreference.so').as_posix(),'ETB1 control does not use the frozen Huff0 library')
    verify_asset(root,dep)
    def ref(rel):
        p=local_file(root,rel)
        return {'path':rel,'bytes':p.stat().st_size,'sha256':digest(p)}
    return {'executable':ref(exe),'dependency':ref(dep['path']),'code':{p:digest(local_file(root,p)) for p in SOURCES}}


def check_route(rule):
    require(rule['view']=='v_bytes_interleaved' and rule['operation']=='train_then_test_roundtrip' and
            rule['partition']=='train_test' and rule['missing']=='preserve' and rule['options']=={} and
            rule['training']==PROFILE and rule['bytes_per_unit']==BLOCK,'ETB1 input policy differs from the frozen route')


def inputs(item,entry):
    scope=item['input']; spec=scope['training']; train,_,test=entry['partitions']; width=entry['value_count']*8
    tbytes=(train['end']-train['start'])*width; used=min(tbytes,BLOCK); held=(test['end']-test['start'])*width
    a=train['start']*width; b=test['start']*width
    require(item['dataset_id']==entry['id'] and item['canonical_object_id']==entry['canonical']['object_id'] and
            item['applicability']=='input_domain_matches' and used>0 and held>0 and train['end']<=test['start'] and
            scope['representation']=='v_bytes_interleaved' and scope['value_column_range']==[0,entry['value_count']] and
            spec['profile']==PROFILE and spec['origin']=='same_file_only' and spec['partition']=='train' and
            spec['partition_object_id']==train['canonical']['object_id'] and
            spec['coordinate']=='canonical_row_major_v_bytes_relative_to_train_partition' and
            spec['consumed_byte_range']==[0,used] and spec['unconsumed_train_byte_range']==[used,tbytes] and
            spec['sample_geometry']=={'first_byte':0,'count':1,'bytes_each':used,'stride_bytes':used} and
            spec['evaluation']=={'partition':'test','partition_object_id':test['canonical']['object_id'],
                                 'absolute_rows':[test['start'],test['end']],'frame_input_limit_bytes':BLOCK} and
            (scope['size_estimate']['native_input_bytes_one_pass'],scope['size_estimate']['input_units'])==
            (used+held,1+(held+BLOCK-1)//BLOCK),'ETB1 train and holdout identities differ from frozen extents')
    return (a,a+used),(b,b+held)
