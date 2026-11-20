"""Full-file cohorts of frozen Titchy native packet, indexed and range work."""
from contextlib import ExitStack
import os
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..qualification.titchy_wire import TSC1, TSTR
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import invoke_isolated_tool, launcher_lock, validate_limits
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_real_corpus_execution import _entry_map
from .m3_sprintz_query import _stage as stage_columns
from .m3_sprintz_timing import check, ref, relative
from .m3_titchy_access import CHUNK_ROWS, validate_access
from .m3_titchy_stream import validate_stream

SCHEMA = 'bmk.m3-titchy-grouped-population/1'
ROUTES = ('packet-stream', 'loaded-file-access', 'batch-range')
DIRS = ('encode', 'decode')
TOOL = 'titchy-grouped'
LIMITS = {'address_space_bytes':512 << 20, 'file_bytes':8 << 20, 'wall_seconds':60}
RUNTIME_CAP = 1024
CODE = ('native/measurement/titchy_grouped/main.cpp', 'native/measurement/titchy_grouped/CMakeLists.txt',
        'plugins/codecs/titchy-batch/corpus_stream_control.cpp', 'plugins/codecs/titchy-batch/corpus_access_control.cpp',
        'src/tsbench/application/m3_titchy_grouped.py', 'src/tsbench/application/m3_titchy_access.py',
        'src/tsbench/application/m3_titchy_stream.py', 'src/tsbench/application/m3_sealed_ledger.py',
        'src/tsbench/application/m3_sprintz_query.py', 'src/tsbench/application/m3_sprintz_timing.py',
        'src/tsbench/qualification/titchy_wire.py', 'src/tsbench/corpus_ingress.py', 'src/tsbench/recovery.py',
        'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py', 'tools/m3_titchy_grouped.py')


def is_stream(c):
    return c['route'] == 'packet-stream'


def facts(value):
    """Remove only known per-invocation clocks/resource samples; counters stay exact."""
    if isinstance(value, dict):
        dynamic = {'wall_ns', 'first_packet_ns', 'process_peak_rss_bytes'}
        return {k:facts(v) for k,v in value.items() if k not in dynamic}
    if isinstance(value, list):
        return [facts(v) for v in value]
    return value


def key(col, span):
    return (col, *span)


def extent(item, entry, control):
    scope = item['input']
    cols, total = entry['value_count'], entry['rows']
    require(item['canonical_object_id'] == entry['canonical']['object_id'] and
            scope['row_ranges'] == [{'object_id':item['canonical_object_id'], 'partition':'full', 'start':0, 'end':total}] and
            scope['value_column_range'] == [0,cols] and not scope['skipped_row_ranges'] and
            scope['representation'] == 'u64_bitcast_per_f64_column' and scope['full_extent_of_file_rows_and_value_columns'] and
            scope['slice_extent']['max_per_unit'] == (None if is_stream(item) else CHUNK_ROWS), 'Titchy full-file extent differs')
    cap = total if is_stream(item) else CHUNK_ROWS
    out = [(col, lo, min(total,lo+cap)) for col in range(cols) for lo in range(0,total,cap)]
    estimate = scope['size_estimate']
    require(0 < len(out) <= RUNTIME_CAP and estimate['input_units'] == len(out) == len(control['units']) and
            out == [key(u['column'],u['row_range']) for u in control['units']] and control['columns'] == cols and
            estimate['native_input_bytes_one_pass'] == control['input_bytes'] == 8*total*cols,
            'Titchy controller did not consume the frozen units')
    return out


def project(item, entry, control, batch_refs):
    stream = is_stream(item)
    require(control['driver'] == ('titchy-stream-control/1' if stream else 'titchy-access-control/1'), 'unexpected Titchy source driver')
    units = []
    for (col,lo,hi), u in zip(extent(item,entry,control), control['units'], strict=True):
        count = hi-lo
        nbytes = count*8
        require(u['logical_input_bytes'] == nbytes, 'Titchy unit logical bytes differ')
        if stream:
            bill = {k:u[k] for k in ('payload_bytes','archive_framing_bytes','config_bytes')}
            require(bill['config_bytes'] == TSC1.size and bill['archive_framing_bytes'] >= TSTR.size, 'Titchy packet envelope differs')
            parts = {'wire':{'bytes':u['artifact_bytes']-bill['config_bytes'], 'sha256':u['archive_sha256']},
                     'config':{'bytes':bill['config_bytes'], 'sha256':u['config_sha256']}}
            original = {'bytes':nbytes, 'sha256':u['restored_sha256']}
            native = {k:facts(u[k]) for k in DIRS}
        else:
            bill = {k:u[k] for k in ('header_bytes','index_bytes','dictionary_and_payload_bytes')}
            other = batch_refs[col,lo,hi]
            # The public ABI batch archive has an outer envelope. Only its native
            # payload is the same artifact as the frozen access controller uses.
            require(other['native_sha256'] == u['sha256'] and other['native_frame_bytes'] == u['artifact_bytes'] and
                    other['logical_input_bytes'] == nbytes, 'Titchy access and original bitcast frame identity differ')
            parts = {'wire':{'bytes':u['artifact_bytes'], 'sha256':u['sha256']}}
            original = {'bytes':nbytes, 'sha256':other['restored_sha256']}
            native = {'encode':facts(u['encode']), 'decode':facts(u['access'])}
        require(sum(bill.values()) == u['artifact_bytes'] == sum(v['bytes'] for v in parts.values()) and
                all(0 < v['bytes'] <= LIMITS['file_bytes'] for v in (*parts.values(),original)), 'Titchy unit output would exceed isolated limits')
        units.append({'column':col,'row_range':[lo,hi],'original':original,'parts':parts,'cost':bill,'native':native})
    require(control['artifact_bytes'] == sum(v['bytes'] for u in units for v in u['parts'].values()), 'Titchy charged extent differs')
    return units


def freeze(root, source_file, source_run, tool):
    validate_limits(LIMITS,file_ceiling=LIMITS['file_bytes'])
    source = load_json(source_file)
    ledger, seal = full_run_source(source,source_run)
    entries = _entry_map(root,load_json(check(root,source['definition']['plan'])))
    selection, original, excluded = [], {}, []
    for row,item in full_run_rows(source,ledger):
        if 'entry_kind' in row or row['selection'] != 85:
            continue
        ds = row['dataset_id']
        if row['route'] == 'batch' and row['status'] == 'verified':
            old = row['evidence']['units']
            original[ds] = {key(u['column'],u['row_range']):u for u in old}
            require(len(original[ds]) == len(old), 'duplicate Titchy native batch unit')
        if row['route'] in ROUTES:
            selected = {k:item[k] for k in ('dataset_id','work_item_id','route','operation','operation_config_id','canonical_object_id')}
            if row['status'] == 'verified':
                selection.append((selected,item,row['evidence']))
            else:
                excluded.append({**selected,'status':row['status'],'reason':row['reason']})
    cases = []
    for common,item,proof in selection:
        entry = entries[item['dataset_id']]
        units = project(item,entry,proof,original.get(item['dataset_id'],{}))
        body = {**common,'configuration':item['input'],'source_file':entry['file'],'units':units}
        cases.append({**body,'case_id':content_id(body)})
    require({c['route'] for c in cases} == set(ROUTES), 'missing native Titchy route evidence')
    bound = source['build']
    dependency = bound['titchy_stream']['dependency']
    require(dependency == bound['titchy_access']['dependency'], 'Titchy codec identities differ across mechanisms')
    exe = relative(root,tool)
    runtime = plan_recovery(root,{},(),tools={TOOL:{k:exe[k] for k in ('path','sha256')}},libraries=[dependency])
    body = {'schema':SCHEMA,'source_plan':relative(root,source_file),'source_seal':seal,
            'source_run':source_run.relative_to(root).as_posix(),'definition':source['definition']['plan'],
            'runtime':runtime,'worker':exe,'limits':LIMITS,'launchers':launcher_lock(),
            'code':{p:digest(local_file(root,p)) for p in CODE},'cases':cases,'excluded':excluded,
            'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}
    return {**body,'population_id':content_id(body)}


def filename(i,part):
    return f'u{i:04d}.{part}'


def manifest(case):
    return ''.join(f'{hi-lo}\n' for lo,hi in (u['row_range'] for u in case['units'])).encode('ascii')


def expected(case,part):
    if part == 'raw':
        return {filename(i,'raw'):u['original'] for i,u in enumerate(case['units'])}
    results = {filename(i,k):v for i,u in enumerate(case['units']) for k,v in u['parts'].items()}
    if not is_stream(case):
        from .m3_abi_corpus_timing import br
        results['rows'] = br(manifest(case))
    return results


def files(folder, identities):
    require({p.name for p in folder.iterdir()} == identities.keys(),'Titchy grouped file inventory differs')
    out = {k:local_file(folder,k) for k in identities}
    require({k:ref(p) for k,p in out.items()} == identities,'Titchy grouped file identity differs')
    return out


def prepare(root, entry, case, work):
    require(entry['file'] == case['source_file'] and entry['canonical']['object_id'] == case['canonical_object_id'],
            'Titchy grouped source changed')
    cols = stage_columns(root,entry,work/'columns')
    raw = work/'raw'
    raw.mkdir()
    with ExitStack() as stack:
        sources = [stack.enter_context(c.open('rb')) for c in cols]
        for i,u in enumerate(case['units']):
            f = sources[u['column']]
            lo,hi = u['row_range']
            require(f.tell() == lo*8,'Titchy grouped unit position differs')
            (raw/filename(i,'raw')).write_bytes(f.read((hi-lo)*8))
        require(all(not f.read(1) for f in sources),'Titchy grouped staging left unread rows')
    return files(raw,expected(case,'raw'))


def read_observations(case, direction, log, cpu):
    result = []
    with log.open(encoding='utf-8') as stream:
        for i,u in enumerate(case['units']):
            d = parse_json(stream.readline(),f'Titchy grouped observation {i}')
            require(facts(d) == u['native'][direction],'Titchy grouped output changed mechanism or query result')
            result.append(d)
        require(parse_json(stream.readline(),'Titchy grouped CPU and extent') == {'units':len(result),'cpu_endpoints':[cpu,cpu]} and
                not stream.read(1),'Titchy grouped CPU or output extent differs')
    return result


def invoke(pop, bundle, case, direction, inputs, work):
    cpu, = os.sched_getaffinity(0)
    raw, wire = expected(case,'raw'), expected(case,'wire')
    work.mkdir()
    out, proc = invoke_isolated_tool(bundle,pop['runtime'],TOOL,LIMITS,work,work,direction,inputs,
                                     [case['route'],direction,str(len(case['units']))],lambda:False,
                                     observe=True,file_ceiling=LIMITS['file_bytes'])
    stderr = work/(direction+'.stderr')
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and stderr.stat().st_size == 0,
            f"{case['dataset_id']} Titchy {case['route']} {direction}: {proc['status']}: {stderr.read_text()[:300]}")
    require(proc['input_mounts'] == (raw if direction == 'encode' else wire), 'Titchy grouped isolation mounts differ')
    if direction == 'encode' and not is_stream(case):
        (out/'rows').write_bytes(manifest(case))
    result = files(out,wire if direction == 'encode' else raw)
    obs = read_observations(case,direction,work/(direction+'.stdout'),cpu)
    return result,obs,proc


def certify(case, raw, wire, restored, enc, dec):
    """Verify the a priori frozen products and re-run the host original-domain validator."""
    for i,u in enumerate(case['units']):
        original = raw[filename(i,'raw')].read_bytes()
        full = restored[filename(i,'raw')].read_bytes()
        frame = wire[filename(i,'wire')].read_bytes()
        require(original == full,'Titchy grouped independent recovery changed original bits')
        if is_stream(case):
            facts = validate_stream(len(original)//8,frame,wire[filename(i,'config')].read_bytes(),enc[i],dec[i])
        else:
            facts = validate_access(case['route'],original,frame,full,enc[i],dec[i])
        require(all(facts[k] == v for k,v in u['cost'].items()), 'Titchy grouped validation changed artifact charging')
