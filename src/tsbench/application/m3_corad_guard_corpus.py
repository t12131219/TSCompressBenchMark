"""Test the opt-in CORAD guard against every frozen r40 held-out frame."""
from collections import Counter, defaultdict
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from ..assets import content_id, digest, load_json, local_file, parse_json, require, verify_asset
from ..planner.corad_corpus import INFERENCE, TRAINERS
from ..qualification.corad_wire import HEADER, interpret
from ..recovery import stage_recovery, plan_recovery
from ..supervisor.isolated_worker import launcher_lock
from .corad_corpus_execution import LIMITS, TOOL, _identity, _native, judge_quality
from .m3_corad import FOLDER, prepare
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-corad-guard-corpus/1'
COST = ('header_bytes', 'embedded_model_bytes', 'tricklet_record_bytes', 'tail_bytes')
CODE = ('tools/m3_corad_guard_corpus.py', 'src/tsbench/application/m3_corad_guard_corpus.py',
        'plugins/codecs/corad-frozen/corpus_control.c', 'src/tsbench/application/corad_corpus_execution.py',
        'src/tsbench/application/m3_corad.py', 'src/tsbench/qualification/corad_wire.py',
        'src/tsbench/planner/m3_corad_ingress.py', 'src/tsbench/recovery.py', 'src/tsbench/supervisor/isolated_worker.py')
POLICY = {'training': 'reuse every sealed r40 model; no retraining, model selection or withheld data access by training',
          'encoding': 'same checked corpus control with only the candidate encoder library changed',
          'restore': 'unmodified Unique decoder with the candidate CRD1 as sole mount, plus independent parser',
          'quality': 'unchanged disjoint train-only gates, recomputed from source; baseline quality status preserved',
          'timing': 'functional diagnostic only; no timings compared; no new formal stage run'}


def ref(root, path):
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def check(root, reference):
    path = verify_asset(root, reference)
    require(path.stat().st_size == reference['bytes'], 'CORAD guard reference byte count differs')
    return path


def _elf(row):
    return {'path': row['source'], 'sha256': row['sha256'], 'bytes': row['bytes']}


def freeze(root, source_file, source_run, build_file, pilot, dataset=None):
    source, build = load_json(source_file), load_json(build_file)
    ledger, seal = full_run_source(source, source_run)
    require(build['build_id'] == content_id({k:v for k,v in build.items() if k != 'build_id'}) and
            build['base_build_id'] == source['build']['build_id'], 'guard corpus build identity differs')
    pilot_plan, pilot_report, pilot_seal = (local_file(pilot, n) for n in ('plan.json', 'report.json', 'completion.json'))
    proof, ps, pr = load_json(pilot_plan), load_json(pilot_seal), load_json(pilot_report)
    require(proof['source_seal'] == seal and proof['build_lock'] == ref(root, build_file) and proof['plan_id'] == ps['plan_id'] == pr['plan_id'] and
            ps['seal_id'] == content_id({k:v for k,v in ps.items() if k != 'seal_id'}) and
            all(ps['files'][p.name] == _identity(p.read_bytes()) for p in (pilot_plan, pilot_report)) and
            all(pr['cases'][f'{p}-heldout']['guard']['quality']['decision'] == 'passed' for p in ('c-lars','source-sklearn')),
            'guard corpus requires both candidate pilot holdouts to pass under the same seal and build')
    groups, excluded = {}, []
    for row, item in full_run_rows(source, ledger):
        if 'entry_kind' in row or row['selection'] != 80 or dataset not in (None, row['dataset_id']):
            continue
        if item['applicability'] != 'input_domain_matches':
            excluded.append({k:row[k] for k in ('dataset_id', 'route', 'work_item_id', 'status', 'reason')})
        else:
            groups.setdefault(row['dataset_id'], {})[row['route']] = (row, item)
    require(groups and (dataset is not None or (len(groups), len(excluded)) == (13, 30)), 'unexpected CORAD corpus decisions')
    cases = []
    for dataset_id, group in groups.items():
        require(set(group) == {INFERENCE, *TRAINERS}, 'corpus must bind all three decisions for each candidate file')
        infer, _ = group[INFERENCE]
        data = infer['evidence']
        require(not data['execution_errors'] and data['training_decisions'] == {p:group[p][0]['work_item_id'] for p in TRAINERS},
                'frozen corpus producer and consumer linkage differs')
        fits, variants = defaultdict(dict), defaultdict(lambda: defaultdict(list))
        for producer in TRAINERS:
            trained = group[producer][0]['evidence']['fits']
            for fit in trained:
                bid, req = fit['input_binding_id'], fit['deployment']
                require(producer not in fits[bid] and fit['status'] == 'verified' and req['producer'] == producer and
                        req['deployment_id'] == content_id({k:v for k,v in req.items() if k != 'deployment_id'}), 'invalid frozen CORAD model')
                fits[bid][producer] = req
            for evaluation in data['evaluations'][producer]:
                variants[evaluation['input_binding_id']][producer].append(evaluation)
        members = []
        for bind in data['input_bindings']:
            bid = bind['input_binding_id']
            require(set(fits[bid]) == set(variants[bid]) == set(TRAINERS), 'CORAD cohort lacks one frozen producer/consumer')
            outputs = {}
            for p in TRAINERS:
                stored = fits[bid][p]
                reference = variants[bid][p]
                require(stored['input_binding_id'] == bid and stored['ordered_columns'] == bind['ordered_columns'] and
                        stored['train'] == bind['train'] and stored['producer_binding_id'] == bind['producer_binding_ids'][p] and
                        len(reference) == len(bind['test_frames']), 'CORAD frozen model data partition differs')
                for frame, row in zip(bind['test_frames'], reference, strict=True):
                    require(row['frame_range'] == frame['absolute_rows'] and row['deployment_id'] == stored['deployment_id'] and
                            row['status'] in ('verified','quality_rejected') and row['logical_value_bytes'] == frame['values']['bytes'] and
                            row['quality_gates'] == bind['train_only_quality_bounds'], 'CORAD frozen held-out observation differs')
                outputs[p] = {'model': stored['model'], 'deployment_id': stored['deployment_id'],
                              'frames': [{k:r[k] for k in ('status','frame','restore','frame_accounting','original_domain_metrics')} for r in reference]}
            members.append({'binding': bind, 'producers': outputs})
        require(len(members) == len(fits) == len(variants), 'CORAD unbound corpus cohort')
        cases.append({'dataset_id': dataset_id, 'work_items': {p:item['work_item_id'] for p,(_,item) in group.items()},
                      'original_decisions': {p:row['status'] for p,(row,_) in group.items()}, 'members': members})
    cohort_count = sum(len(c['members']) for c in cases)
    frames = sum(len(m['binding']['test_frames']) * len(TRAINERS) for c in cases for m in c['members'])
    require(dataset is not None or (cohort_count, frames) == (346, 1174), 'CORAD guard corpus does not exhaust the r40 frames')
    original = source['build']['corad_corpus']['decoder']
    lib = _elf(original['files']['lib/libcorad_c.so'])
    tool = _elf(original['files'][original['tools'][TOOL]])
    require(build['base_dependency']['sha256'] == lib['sha256'], 'guard does not repair the r40 native library')
    closures = {}
    for kind, native in (('candidate', build['guard']['library']), ('original', lib)):
        check(root, native)
        closures[kind] = plan_recovery(root, {}, (), tools={TOOL:{k:tool[k] for k in ('path','sha256')}},
                                       libraries=[{k:native[k] for k in ('path','sha256')}])
    body = {'schema':SCHEMA,'source_plan':ref(root,source_file),'source_run':source_run.relative_to(root).as_posix(),
            'source_seal':seal,'build_lock':ref(root,build_file),'pilot':ref(root,pilot_seal),'dataset_projection':dataset,
            'cases':cases,'excluded_decisions':excluded,'cohorts':cohort_count,'frame_count':frames,'closures':closures,
            'limits':LIMITS,'launchers':launcher_lock(),'policy':POLICY,'code':{n:digest(local_file(root,n)) for n in CODE},
            'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}
    return {**body, 'plan_id':content_id(body)}


def _bind(root, plan):
    source_file = check(root, plan['source_plan'])
    source_run = (root / plan['source_run']).resolve(strict=True)
    require(source_run.is_relative_to(root) and
            plan == freeze(root, source_file, source_run, check(root, plan['build_lock']), check(root, plan['pilot']).parent,
                           plan['dataset_projection']), 'guard corpus plan does not independently refreeze')
    source = load_json(source_file)
    entries = _entry_map(root,load_json(check(root,source['definition']['plan'])))
    return source_run/FOLDER, entries, {i['work_item_id']:i for i in source['work_items']}


def _jobs(root, plan, context):
    original, entries, work_items = context
    for case in plan['cases']:
        dataset = case['dataset_id']
        material = prepare(root, entries[dataset], {r:work_items[w] for r,w in case['work_items'].items()})
        require(len(material) == len(case['members']), 'CORAD selected cohorts differ after re-ingress')
        for stored, (binding, _, values) in zip(case['members'], material, strict=True):
            require(binding == stored['binding'], 'CORAD input identity, partition or train-only bounds differ after re-ingress')
            bid = binding['input_binding_id']
            for producer in TRAINERS:
                p = stored['producers'][producer]
                model = check(original,p['model'])
                for i,(window,raw,old) in enumerate(zip(binding['test_frames'],values,p['frames'],strict=True)):
                    key = {'dataset_id':dataset,'input_binding_id':bid,'producer':producer,'deployment_id':p['deployment_id'],
                           'row_range':window['absolute_rows'],'source':window['values'],'model':p['model']}
                    yield f'{bid}/{producer}/{i:04d}', key, raw, model, (binding['ordered_columns'],binding['train_only_quality_bounds']), old


def _measure(run, plan, address, key, raw, model, limits, old):
    folder = run/'products'/address
    logs = folder/'logs'
    logs.mkdir(parents=True)
    rows = key['row_range'][1]-key['row_range'][0]
    dims = [str(rows),str(len(limits[0]))]
    record = {'case':key,'processes':{}}
    with TemporaryDirectory(prefix='guard-',dir=folder) as tmp:
        work = Path(tmp)
        p = work/'test'; p.write_bytes(raw)
        native, enc = _native(run/'candidate',{'decoder':plan['closures']['candidate']},work,logs,'encode',
                              {'model':model,'test':p},['encode','/inputs/model','/inputs/test',*dims],'frame',record['processes'])
    if native is None:
        return {**record,'status':'native_rejected' if enc else 'encode_process_failed'}
    frame = folder/'frame.crd1'; frame.write_bytes(native)
    with TemporaryDirectory(prefix='guard-restore-',dir=folder) as tmp:
        restored,_ = _native(run/'original',{'decoder':plan['closures']['original']},Path(tmp),logs,'restore',{'frame':frame},
                             ['decode','/inputs/frame',*dims],'values',record['processes'])
    record['frame'] = ref(run,frame)
    if restored is None:
        return {**record,'status':'restore_failed'}
    stored, meta, arrays = interpret(native,max_values=131072)
    model_data = model.read_bytes()
    require(stored == restored and arrays == model_data[HEADER.size:] and model_data[8:24] == native[8:24] and
            (meta['rows'],meta['columns']) == (rows,len(limits[0])), 'candidate altered the model or native restore differs from parser')
    metrics, accepted = judge_quality(raw,restored,*limits)
    return {**record,'status':'verified' if accepted else 'quality_rejected','restore':_identity(restored),
            'reference_records':meta['references'],'frame_accounting':{k:meta[k] for k in COST},
            'original_domain_metrics':metrics,'baseline_status':old['status']}


def _recompute(root, run, plan, context):
    sessions, roots, results = set(), set(), defaultdict(lambda:defaultdict(Counter))
    original = context[0]
    for kind, closure in plan['closures'].items():
        for name, r in closure['files'].items():
            check(run,{'path':f'{kind}/recovery/{name}','bytes':r['bytes'],'sha256':r['sha256']})
    with local_file(run,'trials.jsonl').open('rb') as ledger:
        for address,key,raw,model,limits,old in _jobs(root,plan,context):
            row = parse_json(ledger.readline(), 'CORAD candidate corpus trial')
            require(row['case'] == key and _identity(raw) == key['source'], 'CORAD candidate trial order or input source differs')
            folder = f'products/{address}'
            roots.add(folder)
            old_file = check(original,old['frame'])
            old_bytes = old_file.read_bytes()
            o, meta0, embedded = interpret(old_bytes,max_values=131072)
            require(_identity(o) == old['restore'] and embedded == model.read_bytes()[HEADER.size:] and
                    {k:meta0[k] for k in COST} == old['frame_accounting'], 'original frame, model or restore no longer matches r40')
            result = results[key['dataset_id']][key['producer']]
            result['baseline:'+old['status']] += 1
            result['baseline_bytes'] += len(old_bytes)
            result['baseline_reference_records'] += meta0['references']
            r = row['status']
            required = ('encode',) if r in ('native_rejected','encode_process_failed') else ('encode','restore')
            require(r in ('native_rejected','encode_process_failed','restore_failed','verified','quality_rejected') and
                    set(row['processes']) == set(required), 'invalid CORAD candidate terminal')
            require(('frame' in row) == ('restore' in required), 'candidate failure or decode frame population differs')
            nbytes = 0
            if 'frame' in row:
                require(row['frame']['path'] == folder+'/frame.crd1', 'candidate frame escaped its planned location')
                frame = check(run,row['frame']).read_bytes()
                nbytes = len(frame)
            else:
                require(required == ('encode',), 'candidate decode has no frame')
            for op in required:
                state = row['processes'][op]
                native = state.get('native')
                if state.get('pid') is not None:
                    wanted = {'model':{k:key['model'][k] for k in ('bytes','sha256')},'test':key['source']} if op == 'encode' else {'frame':_identity(frame)}
                    require(state['session_id'] and state['session_id'] not in sessions and state['input_mounts'] == wanted,
                            'CORAD candidate used an unplanned mount or reused a process')
                    sessions.add(state['session_id'])
                require(state['operation'] == op, 'CORAD candidate process operation differs')
                if native is not None:
                    success = ('restore' in required) if op == 'encode' else r in ('verified','quality_rejected')
                    require((native['native_status'] == 0) == success and
                            (native['rows'],native['columns']) == (key['row_range'][1]-key['row_range'][0],len(limits[0])) and
                            not local_file(run,f'{folder}/logs/{op}.stderr').stat().st_size and
                            native == load_json(local_file(run,f'{folder}/logs/{op}.stdout')) and
                            state['status'] == 'completed' and state['returncode'] == 0 and
                            ((native['native_status'] == 0 and native['output_bytes'] == (nbytes if op=='encode' else len(raw))) or
                             (native['native_status'] != 0 and native['output_bytes'] == 0)), 'CORAD candidate native transcript differs')
                else:
                    require(state['status'] != 'completed' and
                            (op == 'encode' and r == 'encode_process_failed' or op == 'restore' and r == 'restore_failed'),
                            'CORAD candidate process failure terminal differs')
            require(r != 'native_rejected' or row['processes']['encode']['native']['native_status'] != 0,
                    'CORAD candidate native failure must have a native status')
            result['candidate:'+r] += 1
            result['candidate_bytes'] += nbytes
            result['transition:'+old['status']+'->'+r] += 1
            if r in ('verified','quality_rejected'):
                restored, meta, arrays = interpret(frame,max_values=131072)
                expected = (key['row_range'][1]-key['row_range'][0], len(limits[0]))
                require((meta['rows'],meta['columns']) == expected and arrays == embedded and frame[8:24] == old_bytes[8:24] and
                        all(row['processes'][op]['native']['native_status'] == 0 for op in required) and
                        row['restore'] == _identity(restored) and row['reference_records'] == meta['references'] and
                        row['baseline_status'] == old['status'], 'candidate recovered scope, model, or baseline identity changed')
                charges = {k:meta[k] for k in COST}
                metrics, accepted = judge_quality(raw,restored,*limits)
                require(charges == row['frame_accounting'] and sum(charges.values()) == nbytes and
                        row['original_domain_metrics'] == metrics and r == ('verified' if accepted else 'quality_rejected'),
                        'candidate byte or quality report does not recompute')
                result['candidate_reference_records'] += meta['references']
        require(not ledger.read(1), 'unexpected trailing CORAD candidate trial')
    require(roots == {p.parent.relative_to(run).as_posix() for p in (run/'products').rglob('logs')},
            'unexpected CORAD candidate artifact roots')
    totals = {p:sum((tables[p] for tables in results.values()), Counter()) for p in TRAINERS}
    outcomes = {p:{ds:('failed' if any(t[p]['candidate:'+x] for x in ('native_rejected','encode_process_failed','restore_failed')) else
                     'quality_rejected' if t[p]['candidate:quality_rejected'] else 'verified') for ds,t in results.items()} for p in TRAINERS}
    return {'schema':SCHEMA+'-report','plan_id':plan['plan_id'],'source_seal':plan['source_seal'],'dataset_projection':plan['dataset_projection'],
            'files':len(results),'cohorts':plan['cohorts'],'frames':plan['frame_count'],'observed_processes':len(sessions),
            'summaries':totals,'per_file':results,'candidate_producer_heldout_outcomes':outcomes,
            'excluded_decisions':plan['excluded_decisions'],'timing_admitted':False,'qualification_granted':False,'stage_accepted':False}


def _seal(run,plan):
    body = {'schema':SCHEMA+'-seal','plan_id':plan['plan_id'],
            'files':{n:ref(run,local_file(run,n)) for n in ('plan.json','trials.jsonl','report.json')}}
    return {**body,'seal_id':content_id(body)}


def execute(root, plan, run):
    context = _bind(root,plan)
    require(run.is_relative_to(root), 'candidate corpus output must be inside workspace')
    run.mkdir(parents=True)
    anticipated = sum(f['values']['bytes']*2 for c in plan['cases'] for m in c['members'] for f in m['binding']['test_frames'])
    require(shutil.disk_usage(run).free > anticipated*2 + (256 << 20), 'candidate corpus free disk budget too small')
    for k, closure in plan['closures'].items():
        lane = run/k; lane.mkdir()
        stage_recovery(root,lane,closure)
    write_new(run/'plan.json',plan)
    with (run/'trials.jsonl').open('xb') as ledger:
        current = None
        for job in _jobs(root,plan,context):
            _,key,*_ = job
            if current is not None and current != key['dataset_id']:
                print(f'recorded {current}',flush=True)
            current = key['dataset_id']
            _line(ledger,_measure(run,plan,*job))
        print(f'recorded {current}',flush=True)
    write_new(run/'report.json', _recompute(root,run,plan,context))
    write_new(run/'completion.json', _seal(run,plan))


def verify(root, run):
    plan = load_json(local_file(run,'plan.json'))
    require(load_json(local_file(run,'completion.json')) == _seal(run,plan), 'candidate corpus seal differs')
    report = _recompute(root,run,plan,_bind(root,plan))
    require(report == load_json(local_file(run,'report.json')), 'candidate corpus report does not recompute')
    return report
