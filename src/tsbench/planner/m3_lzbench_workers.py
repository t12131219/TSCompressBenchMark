"""Bind the real-object lzbench worker matrix without promoting configuration into observation."""
from pathlib import PurePosixPath

from ..assets import digest, local_file, require, verify_asset
from .lzbench_profiles import XZ, ZSTD
from .m3_lzbench_session import input_size as whole_size

DRIVER = 'lzbench-corpus-workers/1'
ROUTES = {(40,ZSTD),(39,XZ)}
TARGET = 'tsbench_lzbench_corpus_worker_control'
MINIMUM = {'zstd':(5<<20)+297, 'xz':(2<<20)+297}
MAX_FRAME_RETAINED = 8 << 20
BLOCK_SIZE, JOB_SIZE, MEMORY_BYTES = 131072, 524288, 134217728
OPTIONS = {ZSTD:{'level':3,'job_bytes':JOB_SIZE,'workers':[0,2]},
           XZ:{'preset':1,'block_bytes':BLOCK_SIZE,'threads':[1,2],'decoder_memory_limit_bytes':MEMORY_BYTES}}
SOURCES = ('cmake/lzbench-workers.cmake','plugins/codecs/zstd/corpus_worker_control.cpp',
           'src/tsbench/planner/m3_lzbench_workers.py','src/tsbench/application/m3_lzbench_workers.py',
           'src/tsbench/planner/m3_lzbench_session.py','src/tsbench/qualification/lzbench.py')


def bind(root,build):
    zstd, xz = (build['plugins'].get(key) for key in ('zstd','xz-baseline'))
    if zstd is None or xz is None:
        return None
    folder = PurePosixPath(zstd['library']['path']).parent
    exe = (folder/TARGET).as_posix()
    if not (root/exe).is_file():
        return None
    dep = (folder/'liblzbench_native.so').as_posix()
    require(PurePosixPath(xz['library']['path']).parent==folder and zstd['dependencies']==xz['dependencies'] and
            len(zstd['dependencies'])==1 and zstd['dependencies'][0]['path']==dep,'lzbench worker dependency differs')
    verify_asset(root,zstd['dependencies'][0])
    def ref(rel):
        path=local_file(root,rel)
        return {'path':rel,'bytes':path.stat().st_size,'sha256':digest(path)}
    return {'executable':ref(exe),'dependency':ref(dep),'code':{p:digest(local_file(root,p)) for p in SOURCES}}


def check_route(row):
    r = row['route']; codec=r.split('-')[0]
    operation='encode_worker_comparison' if r==ZSTD else 'same_frame_decode_and_encode_worker_comparison'
    require(row['view']=='v_bytes_interleaved' and row['partition']=='full' and row['missing']=='preserve' and
            row['operation']==operation and row['options']==OPTIONS[r] and row['min_payload']==MINIMUM[codec] and
            all(row.get(k) is None for k in ('rows_per_unit','bytes_per_unit')),
            'lzbench worker scope or effective options differ from frozen inputs')


def input_size(item,entry):
    size=whole_size(item,entry)
    require(size>=MINIMUM[item['route'].split('-')[0]],'lzbench worker input below frozen threshold; padding prohibited')
    return size
