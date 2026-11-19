"""Check frozen ZFP payload identities, detached restores and observed work.

Raw ZFP is not independently decoded here. Native recovery is performed in
fresh processes at execution; replay verifies the sealed outputs and oracles.
"""
import math
import re
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..planner.zfp import (DIAGNOSTIC, HEADER, MAGIC, PLUGIN, TYPE_LAYOUT, array_input, array_metadata, batch_inputs,
                           field_input, field_layout, field_metadata, ref, retained_paths, values)
from .probe_build import verify_probe_build_lock


def exact(actual, expected, message):
    require(canonical_bytes(actual) == canonical_bytes(expected), message)


def read(out, path, cap):
    file = local_file(out,path)
    require(file.stat().st_size <= cap, f'ZFP artifact exceeds frozen storage bound: {path}')
    return file.read_bytes()


def compare_numeric(original, restored, limit, label):
    require(len(original) == len(restored) and len(original) > 0 and all(math.isfinite(x) for x in restored),
            f'ZFP nonfinite or incomplete restore: {label}')
    errors = [abs(a-b) for a,b in zip(original,restored,strict=True)]
    require(max(errors) <= limit, f'ZFP original-domain error exceeds frozen bound: {label}')
    return max(errors), math.sqrt(sum(e*e for e in errors)/len(errors))


def _verify_batch(bundle, report, read_file, weather):
    require(isinstance(report['batch'],list) and len(report['batch']) == len(bundle['batch']), 'ZFP batch closure differs')
    names = batch_inputs(weather,bundle['window'])
    primary = None
    for spec, row, (case,dtype,raw,lineage) in zip(bundle['batch'],report['batch'],names,strict=True):
        dtype_id, ftype = TYPE_LAYOUT[dtype]
        count = len(raw)//struct.calcsize('<'+ftype)
        original = ref('frozen:'+case,raw)
        expected_identity = {'case':case,'dtype':dtype,'input':original,'artifact':spec['artifact'],**lineage}
        exact(spec,expected_identity,'ZFP frozen batch input differs')
        schema = canonical_bytes({'column':'value','dtype':dtype})
        wire = read_file(spec['artifact'])
        pos = HEADER.size+len(schema)
        native = wire[pos:]
        require(len(native) > 0 and len(native) % 8 == 0 and
                wire[:pos] == HEADER.pack(MAGIC,dtype_id,count,len(schema),len(native))+schema,
                f'ZFP envelope, native word alignment or detached schema differs: {case}')
        wanted = {**expected_identity,'artifact':ref(spec['artifact'],wire),'count':count,'native_bytes':len(native),
                  'native_sha256':ref('',native)['sha256'],'restored_sha256':original['sha256'],
                  'schema_sha256':ref('',schema)['sha256'],'descriptor':{'dtype':dtype_id,'count':count},
                  'rejected_envelopes':bundle['rejections']['batch_wire']}
        exact(row,wanted,f'ZFP batch results or positive/negative evidence differs: {case}')
        if case == 'weather-test-co2':
            primary = native
    require(primary is not None, 'ZFP serial comparison field missing')
    return primary


def _verify_fields(bundle, rows, read_file, weather):
    require(isinstance(rows,list) and len(rows) == len(bundle['fields']), 'ZFP field evidence closure differs')
    for spec,row in zip(bundle['fields'],rows,strict=True):
        case,dtype,mode = spec['id'],spec['type'],spec['mode']
        raw = field_input(spec,weather)
        exact(ref('frozen:'+case,raw),spec['input'],'ZFP frozen original field bits differ')
        layout = field_layout(spec)
        names = spec['artifacts']
        meta,wire,span = (read_file(names[k]) for k in ('metadata','payload','restored_span'))
        require(meta == canonical_bytes(field_metadata(spec)) and bool(wire) and len(wire)%8 == 0 and
                len(span) == layout['span_count']*struct.calcsize('<'+TYPE_LAYOUT[dtype][1]),
                f'ZFP field metadata, raw word length or span differs: {case}')
        offsets = set(layout['offsets'])
        cells = values(dtype,span)
        require(all(c == 8191 for i,c in enumerate(cells) if i not in offsets), f'ZFP field padding was modified: {case}')
        maximum,rmse = compare_numeric(values(dtype,raw),[cells[i] for i in layout['offsets']],spec['max_observed_error'],case)
        want = {'case':case,'dtype':dtype,'mode':mode,'shape':spec['shape'],'strides_elements':layout['strides'],
                'offset_bounds':layout['offset_bounds'],'origin_elements':layout['origin'],'input':spec['input'],
                'logical_bytes':len(raw),'requested_parameter':spec['requested'],'effective_parameter':float(spec['effective']),
                'observed_max_abs_error':maximum,'observed_rmse':rmse,'predeclared_case_error_limit':spec['max_observed_error'],
                'bad_origin_status':1,'payload':ref(names['payload'],wire),'metadata':ref(names['metadata'],meta),
                'restored_span':ref(names['restored_span'],span)}
        exact(row,want,f'ZFP field report disagrees with retained results: {case}')


def work_counts(work, threads, blocks, caller):
    require(type(caller) is int and caller > 0 and isinstance(work,list) and len(work) == threads and
            all(isinstance(w,dict) and w.keys() == {'tid','blocks'} and type(w['tid']) is int and w['tid'] > 0 and
                type(w['blocks']) is int and w['blocks'] > 0 for w in work), 'ZFP invalid native block work record')
    tids = {w['tid'] for w in work}
    require(len(tids) == threads and caller in tids and sum(w['blocks'] for w in work) == blocks,
            'ZFP native participants or total block work differs')


def _verify_openmp(bundle, row, read_file, primary, observer, source):
    spec = bundle['openmp']
    profiles = row.get('profiles') if isinstance(row,dict) else None
    require(isinstance(profiles,list) and len(profiles) == len(spec['profiles']), 'ZFP OpenMP profile closure differs')
    exact({k:v for k,v in row.items() if k != 'profiles'}, {
        'observation':'ELF_interposed_native_full_block_functions_not_timing','omp_env':spec['env'],
        'diagnostic_executable_sha256':observer,'diagnostic_source_sha256':source}, 'ZFP OpenMP identity or environment differs')
    blocks = spec['count']//4
    for want,actual in zip(spec['profiles'],profiles,strict=True):
        policy, threads = want['policy'],want['threads']
        wire = read_file(want['payload'])
        require(wire == primary, 'ZFP OpenMP and serial same-field payloads differ')
        enc, dec, caller = (actual.get(k) for k in ('encode_block_work','decode_block_work','caller_tid'))
        work_counts(enc,threads,blocks,caller)
        work_counts(dec,1,blocks,caller)
        exact({k:v for k,v in actual.items() if k not in {'encode_block_work','decode_block_work','caller_tid'}},
              {'policy':policy,'configured_threads':threads,'chunk_blocks':0 if policy == 'serial' else spec['chunk_blocks'],
               'omp_dynamic':0,'omp_thread_limit':2,'serial_decode_reported':True,'reversible_bits_verified':True,
               'detached_restored_sha256':bundle['weather']['sha256'],'payload':ref(want['payload'],wire)},
              'ZFP OpenMP requested versus effective field policy or detached recovery differs')


def _verify_array(bundle, array, read_file):
    spec = bundle['array']
    n = spec['shape'][0]
    wire = {key:read_file(name) for key,name in spec['artifacts'].items()}
    require(wire['metadata'] == canonical_bytes(array_metadata(spec)) and
            len(wire['restored']) == len(wire['baseline']) == n*8,
            'ZFP array external metadata or restore size differs')
    # ZFP fixed-rate array uses whole word-aligned blocks; a raw field does not
    # contain these update/persistence semantics or identify its own shape.
    words_block = math.ceil(math.floor(4*spec['requested_rate']+.5)/64)
    block_bytes = 8*words_block
    require(block_bytes*8/4 == spec['effective_rate'] and
            len(wire['before']) == len(wire['after']) == math.ceil(n/4)*block_bytes, 'ZFP array rate/storage differs')
    before,after = array_input(spec)
    baseline,restored = (values('f64',wire[k]) for k in ('baseline','restored'))
    compare_numeric(before,baseline,spec['max_observed_error'],'initial fixed-rate array')
    max_error,_ = compare_numeric(after,restored,spec['max_observed_error'],'persisted fixed-rate array')
    touched = {spec['point_index']//4,*(i//4 for i in range(spec['range_start'],spec['range_start']+len(spec['range_values'])))}
    for block in set(range(math.ceil(n/4)))-touched:
        require(wire['before'][block*block_bytes:(block+1)*block_bytes] == wire['after'][block*block_bytes:(block+1)*block_bytes] and
                wire['baseline'][block*32:(block+1)*32] == wire['restored'][block*32:(block+1)*32],
                'ZFP untouched array blocks differ')
    observed_eviction = array.get('evicted_point') if isinstance(array,dict) else None
    require(type(observed_eviction) in (int,float) and 0 < abs(observed_eviction-spec['point_value']) <= spec['max_observed_error'],
            'ZFP dirty-block eviction does not match frozen write and quality bound')
    wanted = {'requested_rate':spec['requested_rate'],'effective_rate':float(spec['effective_rate']),
              'max_abs_error_vs_updated_original':max_error,'cached_point':spec['point_value'],'evicted_point':observed_eviction,
              'cache_size_request':16384,'observed_cache_bytes_when_populated':256*8,
              'cache_bytes_after_set_size':0,'cache_bytes_after_explicit_flush':0,
              'artifacts':{k:ref(spec['artifacts'][k],w) for k,w in wire.items()},
              'all_required_bytes':len(wire['after'])+len(wire['metadata']),'rejected':bundle['rejections']['array']}
    exact(array,wanted,'ZFP array persistence, cache or rejection report differs')


def verify_zfp(bundle, build, driver, source, out, *, sealed_paths=None):
    require(bundle['bundle_id'] == content_id({k:v for k,v in bundle.items() if k != 'bundle_id'}), 'ZFP bundle identity differs')
    require(sealed_paths is None or retained_paths(bundle)|{bundle['evidence_path']} <= sealed_paths, 'ZFP evidence is not sealed')
    report = load_json(local_file(out,bundle['evidence_path']))
    require(isinstance(report,dict) and {'batch','fields','openmp','array'} <= report.keys() and
            isinstance(report.get('diagnostic_id'),str) and re.fullmatch('[a-f0-9]{32}',report['diagnostic_id']) and
            DIAGNOSTIC in build, 'ZFP diagnostic closure differs')
    excluded = {'batch','fields','openmp','array','build','diagnostic_id'}
    exact({k:v for k,v in report.items() if k not in excluded},
          {'schema':'bmk.m0-zfp-control/2','config_id':bundle['config_id'],'bundle_id':bundle['bundle_id'],
           'definitions':driver,'formal_qualification':False,'formal_performance':False,'window':bundle['window'],
           'batch_rejected_inputs':bundle['rejections']['batch_input'],'invalid_field_configs':bundle['rejections']['field'],
           'cuda':{'backend_info':'cpu-only','built':0,'device_available':0,'runtime_visible':0,'state':'not_tested_cpu_build'}},
          'ZFP build scope, policy or recorded rejections differ')
    verify_probe_build_lock(report.get('build'),{k:v for k,v in build.items() if k != DIAGNOSTIC},PLUGIN,dependency_count=1)
    def read_file(name):
        return read(out,name,bundle['data_artifact_max_bytes'])
    weather = read_file(bundle['weather']['path'])
    exact(ref(bundle['weather']['path'],weather),bundle['weather'],'ZFP original climate window identity differs')
    primary = _verify_batch(bundle,report,read_file,weather)
    _verify_fields(bundle,report['fields'],read_file,weather)
    _verify_openmp(bundle,report['openmp'],read_file,primary,build[DIAGNOSTIC],source)
    _verify_array(bundle,report['array'],read_file)
