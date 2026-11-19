"""Frozen complete-object T+V development suite and role-based method routing."""
from pathlib import Path
import struct
from time import perf_counter_ns
import zlib

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..contracts import load_contract
from ..corpus import TIME
from ..ingress import canonical_id, load_typed_source, names, source_file_hash, validate_object
from ..plugins import discover, resolve
from ..recovery import check_recovery, plan_recovery
from ..runtime import SCHEMA as BUILD_SCHEMA
from .comparison import SCHEMA as COMPARE, freeze_comparison
from .corpus_windows import bind_window, read_tv_window
from .gorilla import sha

SUITE = 'configs/suites/dev_tv_composition_v1/suite.json'
SUITE_SCHEMA = 'tv-composition-suite'
INGRESS_SUITE_SCHEMA = 'tv-ingress-suite'
PROVIDERS_SUITE_SCHEMA = 'tv-ingress-providers-suite'
PLAN = 'bmk.dev-tv-plan/1'
INGRESS_PLAN = 'bmk.dev-tv-plan/2'
PROVIDERS_PLAN = 'bmk.dev-tv-plan/3'
PLAN_SCHEMAS = {SUITE_SCHEMA:PLAN, INGRESS_SUITE_SCHEMA:INGRESS_PLAN, PROVIDERS_SUITE_SCHEMA:PROVIDERS_PLAN}


def suite_schema_name(suite):
    return {'bmk.dev-tv-suite/2':INGRESS_SUITE_SCHEMA, 'bmk.dev-tv-suite/3':PROVIDERS_SUITE_SCHEMA}.get(suite.get('schema'),SUITE_SCHEMA)


def uses_ingress(suite):
    return suite_schema_name(suite) in (INGRESS_SUITE_SCHEMA, PROVIDERS_SUITE_SCHEMA)


FORMAT = 'bmk.tv-bundle/1'
FRAME_MAX = 2 * 1024 * 1024
MAX_STREAMS = 256
GROUPED = 'grouped-limbs'
LIMBS = 'f64-le-limbs-row-major/1'
PACKED_U16 = 'dense-u16-interleaved'
LIMB_SCHEMA = b'{"dtype":"u16","layout":"f64-le-limbs-row-major"}'
MEASUREMENT = {'scope':'process_complete_object_encode_or_decode', 'cache':'uncontrolled',
               'before_clock':['checked_input_conversion','canonical_file_staging','build_resolution'],
               'inside_clock':['worker_start','dlopen','file_input','routing','block_reset','codec_calls','container','file_output','process_exit'],
               'after_clock':['original_domain_bitwise_validation','evidence_commit'], 'threads_requested':1,
               'resource_enforcement':'per_process_deadline_and_bounded_frame_not_core_or_memory_isolation'}
ROLES = {'timestamp':'timestamp','value':'value','joint':'timestamp_value'}


def measurement(suite):
    result = MEASUREMENT
    if any('value_transform' in refs for refs in suite['methods'].values()):
        inside = result['inside_clock']
        result = {**result, 'inside_clock':inside[:4]+['f64_bit_limb_pack_or_unpack']+inside[4:]}
    if uses_ingress(suite):
        result = {**result,'ingress':'canonical_memory_setup_then_canonical_column_file_worker',
                  'before_clock':['verify_raw_source_and_parse_typed_batches',*result['before_clock']],
                  'source_file_timing':False,'typed_object_restore_only':True}
    return result


def limb_crc(columns, count, chunk):
    # Independent expected wire order: parse words, shift, and serialize u16s.
    # This reference is only used for post-clock evidence, never as codec input.
    return [zlib.crc32(b''.join(struct.pack('<H',(struct.unpack_from('<Q',col,8*r)[0]>>shift)&65535)
                              for r in range(row,min(count,row+chunk)) for col in columns for shift in (0,16,32,48)))
            for row in range(0,max(1,count),chunk)]


def exact_ticks(values: bytes, origin: str, target: str) -> bytes:
    units = {'s':10**9,'ms':10**6,'us':10**3,'ns':1}
    require(origin in units and target in units and len(values)%8==0, 'unknown unit or invalid i64 timestamps')
    out = bytearray()
    for (v,) in struct.iter_unpack('<q',values):
        q, r = divmod(v * units[origin], units[target])
        require(not r and -2**63<=q<2**63, 'non-exact or overflowing timestamp conversion')
        out.extend(struct.pack('<q',q))
    return bytes(out)


def _ingress_worker_schema(spec, original_timestamp_sha256):
    axis, count = spec['timestamp'], spec['rows']
    unit = axis['unit']
    axis_id = content_id(['bmk.canonical-tv-axis/1',axis,count,original_timestamp_sha256])
    return {'time_axis':{**{k:v for k,v in axis.items() if k not in ('name','dtype','unit')},
                            'axis_id':axis_id,'unit':'millisecond','original_unit':unit},
              'columns':[{'name':n,'dtype':'i64' if i==0 else 'f64','role':'timestamp' if i==0 else 'value','axis_id':axis_id}
                         for i,n in enumerate(names(spec))]}


def _load_ingress_case(root, suite, src):
    lineage, (original,*values) = load_typed_source(root,src['ingress']['manifest'])
    spec = lineage['ingestion']['object']
    count = spec['rows']
    ticks = exact_ticks(original,spec['timestamp']['unit'],'ms')
    packed = [ticks,*values]
    schema = _ingress_worker_schema(spec,sha(original))
    fact = {'rows':count,'source':src,'lineage':lineage,'schema':schema,'schema_sha256':sha(canonical_bytes(schema)),
            'column_sha256':[sha(x) for x in packed],'original_timestamp_sha256':sha(original),
            'logical_bytes':sum(map(len,packed))}
    if any('value_transform' in m for m in suite['methods'].values()):
        fact['limb_input_crc32'] = limb_crc(values,count,suite['chunk_rows'])
    return fact,packed


def ingress_groups(suite, cases):
    if not uses_ingress(suite):
        return {}
    require(cases.keys()==suite['cases'].keys(), 'missing ingress cases')
    groups = {}
    for name,fact in sorted(cases.items()):
        src = suite['cases'][name]
        lineage = fact['lineage']
        ingest, files = lineage['ingestion'], lineage['files']
        spec = ingest['object']
        validate_object(spec)
        hashes = [fact['original_timestamp_sha256'],*fact['column_sha256'][1:]]
        canonical = canonical_id(spec,hashes)
        group_id = content_id(['bmk.canonical-source-group/1',canonical])
        schema = _ingress_worker_schema(spec,hashes[0])
        require(fact['source']==src and fact['rows']==spec['rows'] and len(hashes)==len(names(spec)) and
                fact['schema']==schema and fact['schema_sha256']==sha(canonical_bytes(schema)) and
                fact['logical_bytes']==spec['rows']*8*len(hashes) and lineage['source_column_sha256']==hashes and
                lineage['canonical_dataset_hash']==canonical and lineage['source_group_id']==group_id and
                lineage['ingestion_id']==content_id(ingest) and lineage['source_file_hash']==source_file_hash(files) and
                lineage['source_bytes']==sum(f['bytes'] for f in files) and
                lineage['manifest_id']==content_id({'schema':'bmk.typed-tv-source/1','plugin':ingest['plugin'],
                                                     'object':spec,'options':ingest['options'],'files':files}),
                'inconsistent ingress identity or logical accounting')
        label = src['ingress']['group']
        group = groups.setdefault(label,{'canonical_dataset_hash':canonical,'source_group_id':group_id,
                                        'logical_bytes':fact['logical_bytes'],'logical_weight':1,'formats':{}})
        require(group['canonical_dataset_hash']==canonical,'canonical mismatch across source formats')
        plugin = ingest['plugin']
        require(plugin not in group['formats'],'duplicate format in source equivalence group')
        group['formats'][plugin] = {'case':name, **{k:lineage[k] for k in ('source_file_hash','source_bytes','ingestion_id')}}
    require(len({g['source_group_id'] for g in groups.values()})==len(groups), 'same canonical object split into multiple weights')
    declared = suite['source_groups'] if suite_schema_name(suite)==PROVIDERS_SUITE_SCHEMA else None
    if declared is not None:
        require(declared.keys()==groups.keys(),'source provider group declarations do not match scheduled groups')
    for label, group in groups.items():
        providers = group['formats']
        distinct = len({f['source_file_hash'] for f in providers.values()})
        if declared is None:
            require(set(providers)=={'csv','npy','txt'} and distinct==3,
                    'source equivalence group requires three distinct CSV/NPY/TXT byte identities')
        else:
            require(set(declared[label])==providers.keys() and distinct==len(providers),
                    f'source provider group {label} must match declared providers with distinct byte identities')
    for comparison in suite['comparisons'].values():
        selected = set(comparison['cases'])
        for g in groups.values():
            members = {v['case'] for v in g['formats'].values()}
            require(not members & selected or members <= selected,'comparison must exercise all formats in each selected group')
    require(set().union(*(set(c['cases']) for c in suite['comparisons'].values()))==cases.keys(),
            'every ingress case must have an actual execution slot')
    return groups


def load_case(root, suite, src):
    if 'ingress' in src:
        return _load_ingress_case(root,suite,src)
    if 'fixture' in src:
        bits = [0,0x8000000000000000,1,0x7ff8000000000019,0xfff0000000000000,0x7ff0000000000000]
        stamps = [-2**63,2**63-1,-1,-1,-7,0]
        if src['fixture']=='five-value-edge-bits':
            count = 515
            bits += [0x7fefffffffffffff,0xfff800000000a001,0x3ff04c019302b403]
            original = b''.join(struct.pack('<q',stamps[r%len(stamps)]) for r in range(count))
            values = [b''.join(struct.pack('<Q',bits[(r+c)%len(bits)]) for r in range(count)) for c in range(5)]
            names = [f'v{i+1}' for i in range(5)]
        else:
            count = 0 if src['fixture']=='empty' else len(stamps)
            original = b''.join(struct.pack('<q',x) for x in stamps[:count])
            values = [b''.join(struct.pack('<Q',x) for x in bits[:count])]
            names = ['v']
        lineage = {'fixture':src['fixture']}
        axis = {'interpretation':'synthetic_i64_millisecond_coordinate','unit':'ms'}
        unit = 'ms'
    else:
        req = src['window']
        names, count = req['columns'], req['count']
        fields = {k:v for k,v in req.items() if k!='columns'}
        refs = [bind_window(root,suite['corpus'],suite['corpus_id'],{**fields,'column':name}) for name in names]
        original, values = read_tv_window(root,refs[0]); values = [values]
        for ref in refs[1:]:
            t, v = read_tv_window(root,ref)
            require(t==original and all(ref[k]==refs[0][k] for k in ('asset','partition_canonical_id','offset','count')),
                    'incompatible value time axis')
            values.append(v)
        lineage = {'windows':refs}
        axis, unit = TIME, 's'
    ticks = exact_ticks(original,unit,'ms')
    require(exact_ticks(ticks,'ms',unit)==original, 'timestamp conversion was not reversible')
    packed = [ticks,*values]
    require(all(len(a)==count*8 for a in packed), 'T/V rows differ')
    axis_id = content_id({'lineage':lineage['windows'][0]['partition_canonical_id'] if 'windows' in lineage else lineage,
                          'offset':src['window']['offset'] if 'window' in src else 0,
                          'rows':count,'semantics':axis,'source_timestamp_sha256':sha(original)})
    schema = {'time_axis':{**axis,'axis_id':axis_id,'unit':'millisecond','original_unit':unit},
              'columns':[{'name':'timestamp','dtype':'i64','role':'timestamp','axis_id':axis_id}]+
                        [{'name':n,'dtype':'f64','role':'value','axis_id':axis_id} for n in names]}
    fact = {'rows':count,'source':src,'lineage':lineage,'schema':schema,'schema_sha256':sha(canonical_bytes(schema)),
            'column_sha256':[sha(x) for x in packed],'original_timestamp_sha256':sha(original),
            'logical_bytes':sum(map(len,packed))}
    if any('value_transform' in m for m in suite['methods'].values()):
        fact['limb_input_crc32'] = limb_crc(values,count,suite['chunk_rows'])
    return fact, packed


def _comparisons(contract, suite, cases, methods, build, profiles):
    grouped, schedule = {}, {}
    timing = measurement(suite)
    ingress_groups(suite,cases)
    for label,item in sorted(suite['comparisons'].items()):
        require(set(item['cases'])<=cases.keys() and set(item['methods'])<=methods.keys(),'unknown comparison case or method')
        control = item['control']
        require((item['task']=='shared_t_controlled')==(control=='fixed_timestamp_route'), 'task differs from fixed T/V control')
        fixed = None
        if control:
            role, other = ('timestamp','value') if control=='fixed_timestamp_route' else ('value','timestamp')
            routes = [methods[n]['routes'] for n in item['methods']]
            require(all(role in r and other in r for r in routes), 'fixed route requires separate T/V branches')
            keys = lambda k: {profiles[r[k]]['route_id'] for r in routes}
            require(len(keys(role))==1 and len(keys(other))>=2, 'comparison does not hold one route fixed and vary the other')
            fixed = {'kind':control,'route_id':next(iter(keys(role)))}
        grouped[label] = {}
        for case_name in item['cases']:
            facts = cases[case_name]
            columns = len(facts['column_sha256'])
            ds = {}
            for direction in ('encode','decode'):
                spec = {'schema':'bmk.comparison-contract/1','purpose':'development_diagnostic','track':'original_task',
                        'original':{'object_id':(facts['lineage']['canonical_dataset_hash'] if 'ingress' in facts['source'] else content_id(facts)),'schema_id':facts['schema_sha256'],'logical_bytes':facts['logical_bytes']},
                        'representation':None,'task':item['task'],'control':fixed,
                        'quality':{'kind':'bitwise_exact','exact_components':['T','V'],'max_abs_by_column':{},'exception_policy':'preserve_bits'},
                        'access':{'mode':'batch_whole','mechanism':'any_qualified','stream':None,
                                  'ingress_id':content_id(timing.get('ingress','canonical_column_files')), 'partition_id':content_id(['uniform_aligned_rows',suite['chunk_rows']]),
                                  'workload_id':content_id('whole_tv_object')},
                        'resource':{'hardware_group_id':None,'physical_cores':None,'peak_resident_bytes':None,
                                    'participant_threads':1,'max_serialized_bytes':FRAME_MAX,'deadline_ns':suite['timeout_seconds']*10**9},
                        'boundary':{'direction':direction,'extent':'pipeline_service','lifecycle':'process','state':'reset_per_message',
                                    'state_protocol_id':content_id('fresh_context_per_branch_and_aligned_block'),
                                    'cache_policy_id':content_id(timing['cache']),'ownership':'copied_return','completion':'result_ready',
                                    'output_boundary_id':content_id(['complete_tv_bundle_or_restored_columns_and_schema',build['worker']['sha256']]),
                                    'size_scope':'bundle','size_accounting_id':content_id([FORMAT,'all_serialized_bytes']),
                                    'measurement_protocol_id':content_id(timing)},
                        'validation':{'strength':'artifact_each','placement':'outside_extent','protocol_id':content_id('fresh_process_and_validate_columns_schema_inverse_unit')},
                        'retention':{'samples_per_case_method':1,'independent_restore':True,'retain_failures':True,
                                     'dependency_policy_id':content_id('sealed_glibc_closure_requiring_compatible_cpu')}}
                ds[direction] = freeze_comparison(contract,spec)
            grouped[label][case_name] = ds
            for name in item['methods']:
                count = max(1,(facts['rows']+suite['chunk_rows']-1)//suite['chunk_rows'])
                method = methods[name]
                require(method['layout']!='pair' or columns==2,'native paired route requires exactly one value column')
                if method['layout']==GROUPED:
                    require(columns-1==method['method_spec']['logical_value_columns'],'grouped V column count differs from configured lanes')
                require(count*({'pair':1,GROUPED:2}.get(method['layout'],columns))<=MAX_STREAMS,'TV directory budget exceeded')
                schedule.setdefault((case_name,name),[]).append(label)
    require({k[0] for k in schedule}==cases.keys() and {k[1] for k in schedule}==methods.keys(), 'unused case or method')
    return grouped,schedule


def _methods(suite, profiles, build):
    methods = {}
    for name,route in suite['methods'].items():
        refs = {k:v for k,v in route.items() if k!='value_transform'}
        transform = route.get('value_transform')
        require(all(p in profiles and profiles[p]['role']==ROLES[r] for r,p in refs.items()),'method erases or swaps codec roles')
        require(all(not profiles[p].get('value_representation') or (r=='value' and transform) for r,p in refs.items()),
                'typed value codec needs an explicit compatible transform')
        layout = 'pair' if 'joint' in refs else GROUPED if transform else 'separate'
        body = {'layout':layout,'routes':refs}
        ident = {'layout':body['layout'],'branches':{r:profiles[p]['route_id'] for r,p in refs.items()},
                 'container':FORMAT,'chunk_rows':suite['chunk_rows'],'route':'one_axis_timestamp_once_values_in_schema_order',
                 'conversion':'aligned_dense_exact_i64_ms_f64','worker_sha256':build['worker']['sha256']}
        if transform:
            v = profiles[refs['value']]
            n = transform['value_columns']
            require(transform['id']==LIMBS and v.get('value_representation')==PACKED_U16 and v['options'].get('lanes')==4*n,
                    'grouped transform must bind four u16 lanes per logical value column')
            ident.update(route='one_axis_timestamp_once_one_grouped_value_stream', conversion=LIMBS,
                         logical_value_columns=n,encoded_channels=4*n,value_format=v['format'],
                         physical_value_schema_sha256=sha(LIMB_SCHEMA))
        methods[name] = {**body,'method_spec':ident,'method_id':content_id(ident)}
    return methods


def _slots(cases, methods, schedule):
    return [{'case':case,'method':method,'comparisons':groups,
              'slot_id':content_id([content_id(cases[case]),methods[method]['method_id'],case,method,groups])}
             for (case,method),groups in sorted(schedule.items())]


def compile_tv(root, suite_path, build, recovery=None, *, prepared=None, ingress_stats=None):
    suite = load_json(local_file(root,suite_path))
    suite_schema = load_contract(root,suite_schema_name(suite))
    compare = load_contract(root,COMPARE)
    suite_schema.validate(suite,suite_path)
    require(build['schema']==BUILD_SCHEMA and build['build_id']==content_id({k:v for k,v in build.items() if k!='build_id'}), 'invalid TV build lock')
    plugins = {p['plugin'] for p in suite['profiles'].values()}
    require(plugins<=build['plugins'].keys(), 'incomplete TV build lock')
    registry = discover(root,selected=plugins)
    profiles = {}
    for name,spec in suite['profiles'].items():
        p, role = spec['plugin'], spec['role']
        resolved = resolve(root,p,spec['options'],registry=registry)
        manifest = registry[p]['manifest']
        locked = build['plugins'][p]
        require(role in manifest['roles'] and all(resolved[k]==locked[k] for k in ('manifest_id','options_schema_id')),
                'plugin role or build configuration incompatible')
        route = {'plugin':p,'role':role,'format':manifest['format_id'],'options':resolved['options'],
                 'configuration_id':resolved['configuration_id'],'library':locked['library'],'dependencies':locked['dependencies'],
                 'state':'new_context_per_aligned_chunk','chunk_rows':suite['chunk_rows']}
        if 'value_representation' in manifest:
            route['value_representation'] = manifest['value_representation']
        profiles[name] = {**route,'route_id':content_id(route)}
    methods = _methods(suite,profiles,build)
    cases = {}
    for name,src in suite['cases'].items():
        timed = ingress_stats is not None and 'ingress' in src
        started = perf_counter_ns() if timed else 0
        facts, data = load_case(root,suite,src)
        if timed:
            ingress_stats[name] = {'wall_ns':perf_counter_ns()-started, 'ingestion_id':facts['lineage']['ingestion_id'],
                                   'source_file_hash':facts['lineage']['source_file_hash']}
        cases[name] = facts
        if prepared is not None:
            prepared[name] = data
    # Execute each declared case/method once; a result may participate in multiple declared controls.
    comparisons,schedule = _comparisons(compare,suite,cases,methods,build,profiles)
    slots = _slots(cases,methods,schedule)
    require(len(slots)<=128 and len({m['method_id'] for m in methods.values()})==len(methods),'too many TV slots or duplicate methods')
    if recovery is None:
        recovery = plan_recovery(root,build,plugins)
    else:
        check_recovery(recovery,build,plugins)
    body = {'schema':PLAN_SCHEMAS[suite_schema.name],'suite_path':suite_path,'suite':suite,'suite_schema_id':suite_schema.document_id,
            'comparison_schema_id':compare.document_id,'cases':cases,'profiles':profiles,'methods':methods,
            'build':build,'recovery':recovery,'slots':slots,'comparisons':comparisons,'measurement':measurement(suite),
            'qualification_granted':False}
    return {**body,'plan_content_id':content_id(body)}


def plan_tv(root: Path, build_lock: str, suite_path: str = SUITE) -> dict:
    return compile_tv(root,suite_path,load_json(local_file(root,build_lock)))
