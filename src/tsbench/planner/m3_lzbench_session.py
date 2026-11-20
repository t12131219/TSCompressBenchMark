"""Bind the whole-object Zstd/XZ native session routes to the shared Unique build."""
from pathlib import PurePosixPath

from ..assets import digest, local_file, require, verify_asset
from .lzbench_session import ROUTES

DRIVER = 'lzbench-corpus-session/1'
TARGET = 'tsbench_lzbench_corpus_session_control'
INPUT_SPAN, OUTPUT_SPAN = 307, 521
RETAIN_BYTES = 1 << 20
SOURCES = ('cmake/lzbench-corpus.cmake', 'plugins/codecs/zstd/corpus_session_control.cpp',
           'src/tsbench/planner/m3_lzbench_session.py', 'src/tsbench/application/m3_lzbench_session.py')


def bind(root, build):
    zstd, xz = (build['plugins'].get(n) for n in ('zstd', 'xz-baseline'))
    if zstd is None or xz is None:
        return None
    folder = PurePosixPath(zstd['library']['path']).parent
    exe = (folder / TARGET).as_posix()
    if not (root / exe).is_file():
        return None
    dep = (folder / 'liblzbench_native.so').as_posix()
    require(PurePosixPath(xz['library']['path']).parent == folder and zstd['dependencies'] == xz['dependencies'] and
            [r['path'] for r in zstd['dependencies']] == [dep], 'lzbench session build does not share the locked Unique library')
    verify_asset(root, zstd['dependencies'][0])

    def ref(rel):
        path = local_file(root, rel)
        return {'path': rel, 'bytes': path.stat().st_size, 'sha256': digest(path)}

    return {'executable': ref(exe), 'dependency': ref(dep), 'code': {p: digest(local_file(root, p)) for p in SOURCES}}


def check_route(binding):
    options = {'input_span_bytes': INPUT_SPAN, 'output_span_bytes': OUTPUT_SPAN}
    options.update({'block_bytes':32768} if binding['route']=='xz-session' else {'level':3})
    require(binding['view']=='v_bytes_interleaved' and binding['operation']=='session_roundtrip' and
            binding['partition']=='full' and binding['missing']=='preserve' and
            all(binding.get(k) is None for k in ('rows_per_unit','bytes_per_unit')) and binding['options']==options,
            'lzbench corpus session scope differs from the frozen route')


def input_size(item, entry):
    scope = item['input']; size = entry['rows'] * entry['value_count'] * 8
    ranges = scope['row_ranges']; estimate = scope['size_estimate']
    require(item['dataset_id']==entry['id'] and item['canonical_object_id']==entry['canonical']['object_id'] and
            item['applicability']=='input_domain_matches' and scope['representation']=='v_bytes_interleaved' and
            scope['full_extent_of_file_rows_and_value_columns'] and not scope['skipped_row_ranges'] and
            scope['value_column_range']==[0,entry['value_count']] and len(ranges)==1 and
            (ranges[0]['partition'],ranges[0]['start'],ranges[0]['end'])==('full',0,entry['rows']) and size>0 and
            (estimate['input_units'],estimate['native_input_bytes_one_pass'])==(1,size),
            'lzbench session must consume one complete frozen V object')
    return size
