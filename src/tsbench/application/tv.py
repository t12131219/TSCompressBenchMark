"""Execute and independently replay a frozen, single-run complete-object development suite."""
from collections import Counter
from pathlib import Path, PurePosixPath
import os
import re
import struct
import subprocess
import tempfile
import uuid
import zlib

from ..assets import ContractError, canonical_bytes, content_id, load_json, local_file, require, verify_asset
from ..contracts import compile_contract, load_contract
from ..ingress import canonical_id
from ..planner.comparison import SCHEMA as COMPARE
from ..planner.gorilla import sha
from ..planner.recipe import SCHEMA as RECIPE, check_sealed_recipe, compile_recipe
from ..planner.tv import (FRAME_MAX, GROUPED, LIMB_SCHEMA, PLAN_SCHEMAS, PROVIDERS_PLAN,
                          _comparisons, _methods, _slots, compile_tv, exact_ticks, ingress_groups,
                          measurement, suite_schema_name, uses_ingress)
from ..qualification.value_groups import inspect_group, check_execution
from ..recovery import DIRECTORY, check_recovery, stage_recovery
from ..runtime import resolve_worker
from ..supervisor.process import invoke
from .restore import BWRAP, _diagnostic
from .smoke import _line, _publish, _ref, _rows, _worker_json, utc, write_new

HEADER = struct.Struct('<8s6I64s')
ENTRY = struct.Struct('<4I2Q2I')
MAGIC = b'BMKTVB\x01\x00'
BASE = ('plan.json','suite-schema.json','comparison-schema.json','runtime.json','observations.jsonl')


def _fields(plan, slot):
    case = plan['cases'][slot['case']]
    method = plan['methods'][slot['method']]
    cols = len(case['column_sha256'])
    roles = ['joint'] if method['layout']=='pair' else ['timestamp']+['value']*(1 if method['layout']==GROUPED else cols-1)
    profiles = [plan['profiles'][method['routes'][r]] for r in roles]
    return case, method, cols, profiles


def _directory(case, method, chunk):
    n = case['rows']
    cols = len(case['column_sha256'])
    for low in range(0,max(1,n),chunk):
        count = min(chunk,n-low)
        if method['layout']=='pair':
            yield low,count,0,2
        elif method['layout']==GROUPED:
            yield low,count,0,1
            yield low,count,1,cols-1
        else:
            for i in range(cols):
                yield low,count,i,1


def _group_payload(payload, case, method, row, rows, width, chunk):
    spec = method['method_spec']
    dims, fmt = spec['encoded_channels'],spec['value_format']
    native = inspect_group(fmt,payload,rows,dims,LIMB_SCHEMA,case['limb_input_crc32'][row//chunk])
    return {'logical_value_columns':width,'encoded_channels':dims,'format':fmt,**native}


def inspect_bundle(data, case, method, chunk):
    require(HEADER.size<=len(data)<=FRAME_MAX,'invalid TV frame size')
    magic, rows, cols, stride, n, sch_size, crc, method_id = HEADER.unpack_from(data)
    layout = list(_directory(case,method,chunk))
    require((magic,rows,cols,stride,n,method_id)==(MAGIC,case['rows'],len(case['column_sha256']),chunk,len(layout),
                                                  method['method_id'].encode('ascii')), 'bundle method or layout differs')
    start = HEADER.size + n*ENTRY.size
    off = start+sch_size
    require(off<=len(data),'truncated bundle schema')
    schema = data[start:off]
    require(schema==canonical_bytes(case['schema']) and zlib.crc32(schema)==crc,'bundle schema differs')
    streams = []
    for i, expected in enumerate(layout):
        row,num,first,width,offset,length,checksum,reserved = ENTRY.unpack_from(data,HEADER.size+i*ENTRY.size)
        require((row,num,first,width)==expected and offset==off and 0<length<=len(data)-off and not reserved,
                'bundle stream directory differs')
        payload = data[off:off+length]
        require(zlib.crc32(payload)==checksum,'bundle stream CRC differs')
        streams.append({'row':row,'rows':num,'first_column':first,'column_count':width,'offset':off,'bytes':length,'sha256':sha(payload)})
        if method['layout']==GROUPED and first:
            streams[-1]['packed_value'] = _group_payload(payload,case,method,row,num,width,chunk)
        off += length
    require(off==len(data),'trailing bundle data')
    return {'bundle_bytes':len(data),'container_bytes':start,'schema_bytes':sch_size,
            'stream_bytes':sum(s['bytes'] for s in streams),'streams':streams}


def _args(plan, slot, direction, artifact, schema, paths, worker, libraries):
    case, method, cols, profiles = _fields(plan,slot)
    branches = [arg for p in profiles for arg in (libraries[p['plugin']],p['plugin'],canonical_bytes(p['options']).decode('utf-8'))]
    return [worker,direction,artifact,schema,method['method_id'],str(case['rows']),str(plan['suite']['chunk_rows']),
            method['layout'],str(cols),*branches,*paths]


def _restored(folder, plan, slot):
    case, _, cols, _ = _fields(plan,slot)
    expected = {f'column-{i}.bin' for i in range(cols)}|{'schema.json'}
    require({p.name for p in folder.iterdir()}==expected,'missing or extra restored TV fields')
    values = [local_file(folder,f'column-{i}.bin').read_bytes() for i in range(cols)]
    schema = local_file(folder,'schema.json').read_bytes()
    original = exact_ticks(values[0],'ms',case['schema']['time_axis']['original_unit'])
    facts = {'column_sha256':[sha(x) for x in values],'schema_sha256':sha(schema),'original_timestamp_sha256':sha(original)}
    require(all(len(a)==case['rows']*8 for a in values) and all(case[k]==v for k,v in facts.items()),
            'restored TV dtype domain, ordered columns, schema or timestamps differ')
    if 'ingress' in case['source']:
        lineage = case['lineage']
        facts['canonical_dataset_hash'] = canonical_id(lineage['ingestion']['object'],[sha(original),*facts['column_sha256'][1:]])
        require(facts['canonical_dataset_hash']==lineage['canonical_dataset_hash'],'restored canonical identity differs')
    return facts


def _facts(log, layout, case, direction):
    [observation] = _worker_json(log,1)
    require(set(observation)=={'rows','columns','streams'} and observation['rows']==case['rows'] and
            observation['columns']==len(case['column_sha256']) and len(observation['streams'])==len(layout['streams']),
            'actual TV execution shape differs')
    require(all(r.get('operation')==direction and r.get('threads')==1 and r.get('mode')=='batch'
                for r in observation['streams']),'unbound TV branch execution mode')
    for fact, stream in zip(observation['streams'], layout['streams'], strict=True):
        if p := stream.get('packed_value'):
            check_execution(p['format'],fact,direction,p['encoded_channels'])
    return observation['streams']


def _one(root, run, workspace, plan, slot, raw, cancelled):
    sid = slot['slot_id']
    row = {**slot,'status':'cancelled','reason':'cancel requested before slot','operations':[],'artifact':None,
           'accounting':None,'restored':None,'execution':None}
    if cancelled():
        return row
    case, method, cols, profiles = _fields(plan,slot)
    try:
        files = {}
        for profile in {p['configuration_id']:p for p in profiles}.values():
            binding = resolve_worker(root,plan['build'],profile['plugin'],profile['options'])
            require(binding['configuration_id']==profile['configuration_id'],'role configuration changed')
            files[profile['plugin']] = binding['library']
        worker = binding['worker']
    except (ContractError,OSError) as exc:
        return {**row,'status':'dependency_failed','reason':str(exc)}
    in_dir, out_dir = workspace/'input', workspace/'output'
    in_dir.mkdir(); out_dir.mkdir(); logs = run/'slots'/sid/'logs'; logs.mkdir(parents=True)
    names = [f'column-{i}.bin' for i in range(cols)]
    for name, data in zip(names,raw,strict=True):
        (in_dir/name).write_bytes(data)
    (in_dir/'schema.json').write_bytes(canonical_bytes(case['schema']))
    artifact = run/'slots'/sid/'object.tvb'
    for direction, location in (('encode',in_dir),('decode',out_dir)):
        args = _args(plan,slot,direction,artifact,location/'schema.json',[location/name for name in names],worker,files)
        op = invoke(args,workspace,logs,direction,plan['suite']['timeout_seconds'],cancelled,observe_process=True,capture_usage=True)
        row['operations'].append(op)
        if artifact.is_file():
            row['artifact'] = _ref(run,artifact)
        if op['status']!='completed':
            return {**row,'status':op['status'],'reason':op['reason']}
        try:
            if direction=='encode':
                require(artifact.is_file() and artifact.stat().st_size<=FRAME_MAX,'bundle missing or oversized')
                layout = inspect_bundle(artifact.read_bytes(),case,method,plan['suite']['chunk_rows'])
                e = _facts(logs/'encode.stdout',layout,case,'encode')
                for p in in_dir.iterdir():
                    p.unlink()
                in_dir.rmdir()
            else:
                d = _facts(logs/'decode.stdout',layout,case,'decode')
                row.update(restored=_restored(out_dir,plan,slot),accounting=layout,execution={'encode':e,'decode':d})
        except (ContractError,OSError,TypeError,KeyError) as exc:
            return {**row,'status':'validation_failed','reason':str(exc)}
    return {**row,'status':'verified','reason':''}


def _capacity(run, plan, slot):
    fs = os.statvfs(run)
    available = fs.f_bavail*fs.f_frsize
    return {'available_bytes':available,'required_bytes':32*1024*1024+FRAME_MAX+plan['cases'][slot['case']]['logical_bytes'],
            'available_inodes':fs.f_favail,'required_inodes':64}


def run_tv(root: Path, plan: dict, *, cancelled=lambda:False) -> dict:
    require(isinstance(plan,dict) and plan.get('schema') in PLAN_SCHEMAS.values(),
            'tv-run requires an executable TV plan, not a service scope or resolution')
    root = root.resolve(strict=True)
    prepared, ingress_stats = {}, {}
    build, recovery = plan['build'], plan['recovery']
    setup = dict(prepared=prepared, ingress_stats=ingress_stats)
    if 'recipe_binding' in plan:
        expected = compile_recipe(root,plan['recipe_binding']['path'],build,recovery,**setup)
    else:
        expected = compile_tv(root,plan['suite_path'],build,recovery,**setup)
    require(expected==plan, 'frozen TV plan differs from current contracts')
    target = root/'results'
    require(not target.is_symlink(),'results root may not be symlinked')
    target.mkdir(exist_ok=True)
    rid = uuid.uuid4().hex
    run = target/rid
    run.mkdir(mode=0o700)
    write_new(run/'plan.json',plan)
    if ingress_stats:
        write_new(run/'ingress-setup.json',{'schema':'bmk.dev-tv-ingress-setup/1',
                                           'scope':'source_verification_parse_and_exact_input_conversion_before_worker_clock',
                                           'cases':ingress_stats})
    for name,schema in (('suite-schema.json',suite_schema_name(plan['suite'])),('comparison-schema.json',COMPARE)):
        write_new(run/name,load_contract(root,schema).document)
    if 'recipe_binding' in plan:
        write_new(run/'recipe-schema.json',load_contract(root,RECIPE).document)
    # Optional custody for this run, not a substitute for per-slot build or restore checks.
    try:
        space = os.statvfs(run)
        files = plan['recovery']['files']
        require(space.f_bavail*space.f_frsize>=32*1024*1024+sum(v['bytes'] for v in files.values()) and
                space.f_favail>=64+len(files)+3, 'insufficient capacity to stage TV runtime')
        stage_recovery(root,run,plan['recovery'])
        ready, reason = True,''
    except (ContractError,OSError) as exc:
        ready, reason = False,str(exc)
    write_new(run/'runtime.json',{'ready':ready,'reason':reason,'run_id':rid,'started':utc()})
    with (run/'observations.jsonl').open('xb') as ledger:
        for slot in plan['slots']:
            with tempfile.TemporaryDirectory(prefix='.tv-slot-',dir=run) as tmp:
                workspace = Path(tmp)
                cap = _capacity(run,plan,slot)
                if cap['available_bytes']<cap['required_bytes'] or cap['available_inodes']<cap['required_inodes']:
                    row = {**slot,'status':'resource_blocked','reason':'insufficient results filesystem capacity','operations':[],
                           'artifact':None,'accounting':None,'restored':None,'execution':None}
                else:
                    row = _one(root,run,workspace,plan,slot,prepared[slot['case']],cancelled)
                retained = []
                if row['status']!='verified' or not ready:
                    for f in sorted(workspace.rglob('*')):
                        if f.is_file():
                            dst = run/'slots'/slot['slot_id']/'retained'/f.relative_to(workspace)
                            dst.parent.mkdir(parents=True,exist_ok=True)
                            f.rename(dst)
                            retained.append(_ref(run,dst))
                _line(ledger,{**row,'guard':cap,'retained':retained})
    refs = [_ref(run,p) for p in sorted(run.rglob('*')) if p.is_file()]
    seal = {'schema':'bmk.dev-tv-seal/1','run_id':rid,'plan_content_id':plan['plan_content_id'],'files':refs}
    write_new(run/'completion.json',{**seal,'seal_id':content_id(seal)})
    result = report_tv(run)
    _publish(run/'report.json',result)
    return result


def _read_report(run):
    seal = load_json(local_file(run,'completion.json'))
    require(seal['schema']=='bmk.dev-tv-seal/1' and seal['seal_id']==content_id({k:v for k,v in seal.items() if k!='seal_id'}),
            'invalid TV run seal')
    sealed = {ref['path']:ref for ref in seal['files']}
    require(len(sealed)==len(seal['files']) and set(BASE)<=sealed.keys(),'incomplete TV evidence')
    for ref in sealed.values():
        require(verify_asset(run,ref).stat().st_size==ref['bytes'],'invalid TV evidence size')
    plan = load_json(run/'plan.json')
    suite_name = suite_schema_name(plan['suite'])
    require(plan['schema']==PLAN_SCHEMAS[suite_name] and plan['measurement']==measurement(plan['suite']) and plan['qualification_granted'] is False and
            plan['plan_content_id']==seal['plan_content_id']==content_id({k:v for k,v in plan.items() if k!='plan_content_id'}),
            'invalid TV plan identity')
    suite_schema = compile_contract(suite_name,load_json(run/'suite-schema.json'))
    compare_schema = compile_contract(COMPARE,load_json(run/'comparison-schema.json'))
    require(plan['suite_schema_id']==suite_schema.document_id and plan['comparison_schema_id']==compare_schema.document_id,'missing TV contract snapshot')
    suite = plan['suite']
    suite_schema.validate(suite,'sealed TV suite')
    profiles, build = plan['profiles'], plan['build']
    require(build['build_id']==content_id({k:v for k,v in build.items() if k!='build_id'}) and
            all(p['route_id']==content_id({k:v for k,v in p.items() if k!='route_id'}) for p in profiles.values()) and
            _methods(suite,profiles,build)==plan['methods'], 'TV method or build identity differs')
    grouped,schedule = _comparisons(compare_schema,suite,plan['cases'],plan['methods'],build,profiles)
    require(grouped==plan['comparisons'] and _slots(plan['cases'],plan['methods'],schedule)==plan['slots'],
            'TV comparison or schedule is incomplete')
    require(('recipe_binding' in plan)==('recipe-schema.json' in sealed),'missing or unexpected sealed recipe schema')
    if 'recipe_binding' in plan:
        check_sealed_recipe(compile_contract(RECIPE,load_json(run/'recipe-schema.json')),plan)
    runtime = load_json(run/'runtime.json')
    require(runtime['run_id']==seal['run_id'] and type(runtime['ready']) is bool and bool(runtime['reason'])!=runtime['ready'],
            'invalid TV runtime result')
    spec = plan['recovery']
    check_recovery(spec,plan['build'],{p['plugin'] for p in plan['profiles'].values()})
    expected = {f'{DIRECTORY}/{path}':{'path':f'{DIRECTORY}/{path}','sha256':v['sha256'],'bytes':v['bytes']} for path,v in spec['files'].items()}
    require({p:r for p,r in sealed.items() if p.startswith(DIRECTORY+'/')}==(expected if runtime['ready'] else {}),
            'TV recovery package differs from plan')
    rows = _rows(run/'observations.jsonl')
    require(len(rows)==len(plan['slots']),'missing TV terminal rows')
    sessions = set()
    for row, slot in zip(rows,plan['slots'],strict=True):
        require({k:row[k] for k in slot}==slot,'TV terminal row differs from schedule')
        prefix = f"slots/{slot['slot_id']}/"
        case, method, _, _ = _fields(plan,slot)
        artifact = row['artifact']
        if artifact:
            require(artifact['path']==prefix+'object.tvb' and sealed.get(artifact['path'])==artifact,'wrong TV frame reference')
        require({r['path']:r for r in row['retained']}=={p:r for p,r in sealed.items() if p.startswith(prefix+'retained/')},
                'wrong retained TV workspace')
        guard = row['guard']
        blocked = guard['available_bytes']<guard['required_bytes'] or guard['available_inodes']<guard['required_inodes']
        require(type(guard['available_bytes']) is int and guard['available_bytes']>=0 and
                type(guard['available_inodes']) is int and guard['available_inodes']>=0 and guard['required_inodes']==64 and
                guard['required_bytes']==32*1024*1024+FRAME_MAX+case['logical_bytes'] and
                blocked==(row['status']=='resource_blocked'), 'TV capacity evidence differs')
        ops = row['operations']
        require([r['operation'] for r in ops]==['encode','decode'][:len(ops)] and len(ops)<=2,'invalid TV worker operation sequence')
        if len(ops)==2:
            require(ops[0]['status']=='completed' and artifact is not None,'TV decode without encoded input')
        for op in ops:
            if op['pid'] is not None:
                require(op['process_wall_ns']>0 and op['session_id'] not in sessions and min(op['child_usage'].values())>=0,
                        'invalid or repeated TV process observation')
                sessions.add(op['session_id'])
                for kind in ('stdout','stderr'):
                    require(prefix+f"logs/{op['operation']}.{kind}" in sealed,'missing worker log')
        if row['status']=='verified':
            require(artifact and len(ops)==2 and all(o['status']=='completed' for o in ops) and not row['reason'],
                    'TV success without both operations')
            layout = inspect_bundle((run/artifact['path']).read_bytes(),case,method,suite['chunk_rows'])
            e,d = (_facts(run/prefix/f'logs/{op}.stdout',layout,case,op) for op in ('encode','decode'))
            restored = {k:case[k] for k in ('column_sha256','schema_sha256','original_timestamp_sha256')}
            if 'ingress' in case['source']:
                restored['canonical_dataset_hash'] = case['lineage']['canonical_dataset_hash']
            require(row['accounting']==layout and row['execution']=={'encode':e,'decode':d} and row['restored']==restored,
                    'TV restoration or byte accounting differs')
        else:
            status = row['status']
            require((not ops and status in {'cancelled','resource_blocked','dependency_failed'} and artifact is None) or
                    (ops and status in {'failed','timeout','cancelled','crash','dependency_failed'} and status==ops[-1]['status']) or
                    (ops and status=='validation_failed' and ops[-1]['status']=='completed'), 'invalid TV terminal status')
            require(row['reason'] and all(row[k] is None for k in ('accounting','restored','execution')),
                    'failed TV slot cannot grant verification')
    setup = None
    if uses_ingress(suite):
        require('ingress-setup.json' in sealed, 'missing sealed ingress setup measurement')
        setup = load_json(run/'ingress-setup.json')
        require(set(setup)=={'schema','scope','cases'} and setup['schema']=='bmk.dev-tv-ingress-setup/1' and
                setup['scope']=='source_verification_parse_and_exact_input_conversion_before_worker_clock' and
                setup['cases'].keys()==plan['cases'].keys(), 'invalid ingress setup measurement')
        for name, elapsed in setup['cases'].items():
            case = plan['cases'][name]['lineage']
            require(set(elapsed)=={'wall_ns','ingestion_id','source_file_hash'} and
                    type(elapsed['wall_ns']) is int and elapsed['wall_ns']>0 and
                    all(elapsed[k]==case[k] for k in ('ingestion_id','source_file_hash')), 'unbound ingress setup observation')
    return plan, seal, runtime, rows, setup


def report_tv(run: Path) -> dict:
    plan, seal, runtime, rows, setup = _read_report(run)
    report = {'schema':'bmk.dev-tv-report/1','run_id':seal['run_id'],'plan_content_id':plan['plan_content_id'],
            'seal_id':seal['seal_id'],'statuses':dict(Counter(r['status'] for r in rows)),
            'verified':all(r['status']=='verified' for r in rows),'recovery':runtime,'measurement':plan['measurement'],
            'comparisons':plan['comparisons'],'slots':rows,'qualification_granted':False}
    if 'recipe_binding' in plan:
        report['recipe_binding_id'] = plan['recipe_binding']['recipe_binding_id']
    if groups := ingress_groups(plan['suite'],plan['cases']):
        keyed = {(r['case'],r['method']):r for r in rows}
        for group in groups.values():
            members = {v['case'] for v in group['formats'].values()}
            methods = sorted({method for case,method in keyed if case in members})
            group['methods'] = {}
            for method in methods:
                slots = [keyed[case,method] for case in sorted(members)]
                verified = all(r['status']=='verified' for r in slots)
                identical = len({r['artifact']['sha256'] for r in slots})==1 if verified else None
                group['methods'][method] = {'verified_all_formats':verified,'byte_identical_bundle':identical,
                                            'slots':[r['slot_id'] for r in slots]}
                report['verified'] &= verified and bool(identical)
        versioned_providers = plan['schema']==PROVIDERS_PLAN
        report['schema'] = 'bmk.dev-tv-report/3' if versioned_providers else 'bmk.dev-tv-report/2'
        report['ingress_setup'] = setup
        if versioned_providers:
            for group in groups.values():
                group['providers'] = group.pop('formats')
        key, unit = ('source_equivalence','per_provider') if versioned_providers else ('format_equivalence','per_format')
        report[key] = {'groups':groups,'logical_dataset_weights':len(groups),
                       'policy':f'one_weight_per_canonical_object_not_{unit}; diagnostic_not_primary_timing'}
    return report


def _slot_dependencies(spec, build, plugins):
    """Mount the selected branches and their reachable closure, not other providers."""
    pending = {spec['worker'],spec['loader']}
    for plugin in plugins:
        pending.add(spec['plugins'][plugin])
        pending.update('lib/'+PurePosixPath(ref['path']).name for ref in build['plugins'][plugin]['dependencies'])
    paths = set()
    while pending:
        path = pending.pop()
        if path not in paths:
            require(path in spec['files'],'selected TV branch has an undeclared dependency')
            paths.add(path)
            pending.update('lib/'+name for name in spec['files'][path]['needed'])
    return sorted(paths)


def _replay_bundle(run, plan, slot, artifact, work):
    """Attempt one isolated decode with only this artifact and the selected method's closure."""
    spec = plan['recovery']
    _, _, cols, profiles = _fields(plan,slot)
    mounted = _slot_dependencies(spec,plan['build'],{r['plugin'] for r in profiles})
    argv = [BWRAP,'--unshare-net','--unshare-pid','--unshare-ipc','--die-with-parent','--clearenv','--cap-drop','ALL']
    for path in mounted:
        argv += ['--ro-bind',str((run/DIRECTORY/path).resolve(strict=True)),'/recovery/'+path]
    outputs = work/'out'; outputs.mkdir()
    argv += ['--ro-bind',str(artifact),'/input.tvb','--bind',str(outputs),'/out','--chdir','/out','--',
             '/recovery/'+spec['loader'],'--inhibit-cache','--library-path','/recovery/lib']
    argv += _args(plan,slot,'decode','/input.tvb','/out/schema.json',[f'/out/column-{i}.bin' for i in range(cols)],
                  '/recovery/'+spec['worker'],{k:'/recovery/'+v for k,v in spec['plugins'].items()})
    try:
        with (work/'stdout').open('wb') as out, (work/'stderr').open('wb') as err:
            r = subprocess.run(argv,env={},stdin=subprocess.DEVNULL,stdout=out,stderr=err,check=False,timeout=plan['suite']['timeout_seconds'])
    except subprocess.TimeoutExpired as exc:
        raise ContractError('isolated TV restore deadline exceeded') from exc
    return r.returncode, mounted


def restore_tv(run: Path) -> dict:
    plan,seal,runtime,rows,_ = _read_report(run)
    require(runtime['ready'],'run has no sealed recovery closure')
    results = []
    for slot in (r for r in rows if r['status']=='verified'):
        artifact = verify_asset(run,slot['artifact'])
        with tempfile.TemporaryDirectory(prefix='tv-audit-') as temp:
            work = Path(temp)
            returncode,mounted = _replay_bundle(run,plan,slot,artifact,work)
            require(returncode==0,'isolated TV restore failed: '+_diagnostic(work/'stderr'))
            require(_facts(work/'stdout',slot['accounting'],plan['cases'][slot['case']],'decode')==slot['execution']['decode'],
                    'isolated TV restore actual operation changed')
            results.append({'slot_id':slot['slot_id'],'artifact':slot['artifact'],'mounted_decoder_files':mounted,
                            **_restored(work/'out',plan,slot)})
    require(results,'no verified TV object to restore')
    return {'schema':'bmk.dev-tv-restore/1','run_id':seal['run_id'],'seal_id':seal['seal_id'],'restored_slots':len(results),
            'isolation':'files_only_bubblewrap','slots':results,'qualification_granted':False}
