"""Independently time C11 Gorilla directions against the current functional decision."""
from hashlib import sha256
from pathlib import Path
from random import Random
import shutil
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns

import numpy as np

from ..assets import digest, load_json, local_file, require
from ..planner.m3_in_run_measurement_v4 import GORILLA, REPEATS, SEED, WARMUPS
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_gorilla_corpus_clock as clock
from .m3_fixed_batch_corpus import _sync
from .m3_gorilla import HEADER, LENGTH, PAIR, RECORD, _head, read_frame, stage

DIRECTORY = 'measurement-gorilla-anchors'


def schedule(case_id, route):
    rng = Random(SEED ^ int(case_id[:16], 16))
    lanes = list(clock.CLOCKS[route])
    for i in range(WARMUPS+REPEATS):
        for direction in rng.sample(lanes, len(lanes)):
            yield {'round': i, 'phase': 'warmup' if i < WARMUPS else 'measured', 'direction': direction}


def _case(plan, item, row, entry):
    route = item['route']; scope = item['input']; e = row['evidence']
    frozen = plan['measurement']['gorilla']['bindings']['original' if route=='tv-batch' else 'repair']
    rows, cols = entry['rows'], entry['value_count']
    epoch = plan['measurement']['population'][item['work_item_id']]
    obj = item['canonical_object_id']
    blocks = list(clock._blocks(cols, rows)); is_state = route=='append-resume'
    require(item['selection'] == 7 and entry['canonical']['object_id'] == obj and
            scope['row_ranges'] == [{'object_id':obj,'partition':'full','start':0,'end':rows}] and
            scope['value_column_range'] == [0,cols] and scope['size_estimate']['input_units'] == len(blocks) == len(e['units']) and
            (e['rows'],e['columns'],e['input_bytes']) == (rows,cols,rows*cols*PAIR.size) and
            e['axis_coordinate'] == 'civil_label_ms_not_utc' and e['native_threads'] == 1 and e['backend'] == 'gorilla_c' and
            e['driver'] == 'gorilla-corpus-control/1' and all(e[k] == frozen[k] for k in ('implementation','executable','dependency')),
            'Gorilla functional route, build or input extent mismatch')
    facts, progress = sha256(), sha256()
    sizes = [0,0]
    for (c,start,n),unit in zip(blocks,e['units'],strict=True):
        require((unit['column'],unit['row_range']) == (c,[start,start+n]) and 2 <= unit['native_frame_bytes'] <= 16384,
                'Gorilla same-run block geometry differs')
        sizes[0] += unit['native_frame_bytes']; clock._commit(facts, clock._without_clocks(unit))
        if is_state:
            snap = unit['snapshot']; sizes[1] += snap['native_bytes']
            require(snap['rows'] == n//2 and 2 <= snap['native_bytes'] <= 16384 and
                    unit['batch_byte_parity_verified'] is True, 'Gorilla same-run checkpoint differs')
            clock._commit(progress,[c,start,n,unit['native_frame_bytes'],snap['rows'],snap['native_bytes'],
                                   snap['compressed_data_bits']+16,snap['bounded_workspace_bytes']])
    framing = HEADER.size + len(blocks)*LENGTH.size
    require(e['harness_framing_bytes'] == framing and e['native_frame_bytes'] == sizes[0] and
            e['artifact_bytes'] == framing+sizes[0] <= clock.launch.FILE_CEILING and
            e['snapshot_native_bytes'] == (sizes[1] if is_state else None) and
            e['snapshot_artifact_bytes'] == (framing+sizes[1] if is_state else None) and
            (not is_state or e['snapshot_artifact_bytes'] <= clock.launch.FILE_CEILING), 'Gorilla byte billing differs')
    return {**{k:item[k] for k in ('work_item_id','operation_config_id','canonical_object_id','dataset_id','route')},
            'case_id':epoch['case_id'],'rows':rows,'columns':cols,'units':len(blocks),'input_bytes':e['input_bytes'],
            'artifact_bytes':e['artifact_bytes'],'snapshot_bytes':e['snapshot_artifact_bytes'],
            'input_identity':e['input_identity'],'source_original':entry['file'],'implementation':frozen['implementation'],
            'state_progress_sha256':progress.hexdigest() if is_state else None,'block_facts_sha256':facts.hexdigest()}


def _identities(paths):
    return {p.name:{'bytes':p.stat().st_size,'sha256':digest(p)} for p in paths}


def _stage(root, entry, case, out):
    axis, paths, identity = stage(root, entry, out)
    require(entry['file'] == case['source_original'] and identity == case['input_identity'], 'Gorilla canonical identity differs')
    return _identities([axis,*paths])


def _check_anchor(path, case, row):
    expected = clock._archive_sizes(case)
    require(path.is_dir() and not path.is_symlink() and {p.name for p in path.iterdir()} == expected.keys(),
            'Gorilla fixed archive inventory differs')
    assets = [local_file(path,name) for name in expected]
    for file in assets:
        partial = file.name == 'snapshot.gtv1'
        require(file.stat().st_size == expected[file.name], 'Gorilla fixed archive extent differs')
        with file.open('rb') as f:
            _head(f,case['columns'],case['rows'])
            for (_,_,n),unit in zip(clock._blocks(case['columns'],case['rows']),row['evidence']['units'],strict=True):
                block = read_frame(f,n//2 if partial else n)
                want = unit['snapshot']['sha256'] if partial else unit['frame_sha256']
                require(sha256(block).hexdigest() == want, 'Gorilla frame differs from same-run functional identity')
            require(not f.read(1),'Gorilla fixed archive has trailing bytes')
    return _identities(assets)


def _outputs(case, row, canonical):
    """Recompute delivered TV by column from frozen originals, including every checkpoint prefix."""
    axis = np.fromfile(canonical/'axis.ms', dtype='<i8'); rows = case['rows']
    require(len(axis)==rows,'Gorilla canonical time extent differs')
    result = {d:{} for d in clock.CLOCKS[case['route']] if d!='encode'}
    pos = 0
    for col, name in enumerate(clock.launch.value_files(case['columns'])):
        digests = {d:sha256() for d in result}
        with (canonical/name).open('rb') as source:
            for _,start,n in clock._blocks(1,rows):
                buffer = np.empty(n,dtype=RECORD); buffer['t'] = axis[start:start+n]
                raw=source.read(n*8); require(len(raw)==n*8,'Gorilla short canonical value column')
                buffer['v']=np.frombuffer(raw,dtype='<u8')
                unit = row['evidence']['units'][pos]; pos += 1
                for d, checksum in digests.items():
                    snapshot = d=='snapshot_decode'; length = n//2 if snapshot else n
                    data = buffer[:length].tobytes()
                    want = unit['snapshot'] if snapshot else unit
                    require(sha256(data).hexdigest() == want['restored_tv_sha256'], 'Gorilla same-run source TV evidence differs')
                    checksum.update(data)
            require(not source.read(1),'Gorilla canonical value column has trailing bytes')
        name = f'column-{col:04d}.tv'
        for d, checksum in digests.items():
            result[d][name] = {'bytes':clock._decoded_sizes(case,d)[name],'sha256':checksum.hexdigest()}
    return result


def _slot_dir(case, slot):
    return f"{DIRECTORY}/{case['case_id']}/logs/{slot['round']:02d}-{slot['direction']}"


def _trial(root, run, work, scratch, binding, case, entry, slot, anchors):
    direction = slot['direction']; encode = direction=='encode'; base = run/DIRECTORY/case['case_id']
    start, cpu_start = monotonic_ns(), process_time_ns()
    source = work/'canonical'
    if encode:
        source = scratch/'canonical'
        _stage(root,entry,case,source)
    out, record, op = clock._invoke(work,binding,case,source,base/'fixed',scratch/direction,direction)
    if not encode:
        name = 'snapshot.gtv1' if direction=='snapshot_decode' else 'frame.gtv1'
        clock._verify_restored_direction(case,direction,source,base/'fixed'/name,out,record)
    products = _identities(out.iterdir())
    require(products == (anchors['fixed'] if encode else anchors['restored'][direction]), 'Gorilla timed products differ')
    _sync({p.name:p for p in out.iterdir()},run)
    observed = {**slot, **op, 'case_id':case['case_id'],'products':products,'status':'measured_as_declared',
                'verified_durable_wall_ns':monotonic_ns()-start,'verified_durable_controller_cpu_ns':process_time_ns()-cpu_start}
    logdir = run/_slot_dir(case,slot); logdir.mkdir(parents=True)
    observed['logs'] = []
    for suffix in ('stdout','stderr'):
        name = f'native.{suffix}'; path = logdir/name
        shutil.copyfile(scratch/direction/name,path)
        observed['logs'].append(clock._ref(run,path))
    return observed


def _check_trial(run, case, slot, trial, anchors, row, seen):
    direction = slot['direction']; encode=direction=='encode'; proc=trial['process']; session=proc['session_id']; usage=proc['child_usage']
    archive='snapshot.gtv1' if direction=='snapshot_decode' else 'frame.gtv1'
    mounts=anchors['canonical'] if encode else {'frame.gtv1':anchors['fixed'][archive]}
    products=anchors['fixed'] if encode else anchors['restored'][direction]
    require(trial['case_id']==case['case_id'] and all(trial[k]==v for k,v in slot.items()) and trial['products']==products and
            proc['status']=='completed' and proc['returncode']==0 and not proc['reason'] and proc['operation']=='native' and
            proc['input_mounts']==mounts and proc['pid']>0 and isinstance(session,str) and session and session not in seen and
            set(usage)=={'user_cpu_ns','system_cpu_ns','maxrss_bytes'} and all(type(v) is int and v>=0 for v in usage.values()) and
            usage['maxrss_bytes']>0 and
            0<proc['process_wall_ns']<=trial['durable_output_wall_ns']<=trial['verified_durable_wall_ns'] and
            0<trial['controller_cpu_ns']<=trial['verified_durable_controller_cpu_ns'], 'Gorilla timed process/scope differs')
    expected_logs = [f'{_slot_dir(case,slot)}/native.{s}' for s in ('stdout','stderr')]
    require([r['path'] for r in trial['logs']]==expected_logs and trial['logs'][1]['bytes']==0,'Gorilla native logs differ')
    stdout,_ = (clock._file(run,ref) for ref in trial['logs'])
    record=load_json(stdout)
    require(clock._metrics(case,direction,record)==trial['native_ns'] and
            sum(trial['native_ns'].values())<=proc['process_wall_ns'],'Gorilla original native clock does not recompute')
    if case['route']=='iterator' and direction=='decode':
        for entry,unit in zip(record['units'],row['evidence']['units'],strict=True):
            seek=unit['forward_seek']
            require(entry[-3:]==[seek['target_ms'],seek['timestamp_ms'],seek['value_bits']], 'Gorilla iterator seek differs')
    seen.add(session)


def _summary(case, trials):
    report={}
    for direction,spans in clock.CLOCKS[case['route']].items():
        rows=[t for t in trials if t['phase']=='measured' and t['direction']==direction]
        require(len(rows)==REPEATS,'missing Gorilla measured rounds')
        entry={'samples':len(rows),'byte_bill':clock._bill(case,direction),
               'native_wall_ns':{k:clock._series([r['native_ns'][k] for r in rows]) for k in spans},
               **{k:clock._series([r[k] for r in rows]) for k in ('durable_output_wall_ns','verified_durable_wall_ns',
                                                               'controller_cpu_ns','verified_durable_controller_cpu_ns')},
               'process_wall_ns':clock._series([r['process']['process_wall_ns'] for r in rows]),
               'child_usage':{k:clock._series([r['process']['child_usage'][k] for r in rows])
                              for k in ('user_cpu_ns','system_cpu_ns','maxrss_bytes')}}
        if case['route']=='append-resume' and direction=='encode':
            entry['checkpoint_byte_bill']=clock._bill(case,'snapshot_decode')
            entry['total_gtv1_bytes_written']=case['artifact_bytes']+case['snapshot_bytes']
        report[direction]=entry
    return {**case,'directions':report,'native_backend':'gorilla_c','native_threads':1}


def measure(root, plan, item, entry, work, run, row):
    frozen=plan['measurement']; prescribed=frozen['population'][item['work_item_id']]
    before=resource.observe(frozen['environment']['cpu']); base=run/DIRECTORY/prescribed['case_id']
    binding=frozen['gorilla']; lane='original' if item['route']=='tv-batch' else 'repair'
    anchors, reason, trials = None, None, []
    try:
        case=_case(plan,item,row,entry)
        stage_recovery(root,work,binding['bindings'][lane]['runtime'],directory=f'runtime-{lane}')
        canonical=_stage(root,entry,case,work/'canonical'); restored=_outputs(case,row,work/'canonical')
        fixed,_=clock._stash_anchors(work,binding,case,work/'canonical',work)
        archive=_check_anchor(fixed,case,row)
        base.mkdir(parents=True); fixed.rename(base/'fixed')
        anchors={'canonical':canonical,'fixed':archive,'restored':restored}
    except (OSError,ValueError) as exc:
        reason=f'Gorilla same-run anchor failed: {exc}'
    for slot in schedule(prescribed['case_id'],item['route']):
        if reason:
            trials.append({**slot,'case_id':prescribed['case_id'],'status':'not_run_after_measurement_failure','reason':reason})
            continue
        try:
            # Keep original canonical/ELF closure available, but release each trial's decoded/encoded bytes after verification.
            with TemporaryDirectory(prefix='trial-',dir=work) as tmp:
                trial=_trial(root,run,work,Path(tmp),binding,case,entry,slot,anchors)
            trials.append(trial)
        except (OSError,ValueError) as exc:
            reason=str(exc) or type(exc).__name__
            trials.append({**slot,'case_id':prescribed['case_id'],'status':'measurement_failed','reason':reason})
    doc={**prescribed,'status':'measurement_failed' if reason else 'measured_and_verified','reason':reason,
         'trials':trials,'anchors':anchors,'resource_before':before,'resource_after':resource.observe(frozen['environment']['cpu']),
         'timing_admitted':False}
    return {**doc,'summary':recompute(root,plan,item,row,entry,run,doc,set(),check_anchors=False)}


def recompute(root, plan, item, row, entry, run, doc, seen, *, check_anchors=True):
    prescribed=plan['measurement']['population'][item['work_item_id']]; anchors=doc['anchors']
    passed=doc['status']=='measured_and_verified'; base=run/DIRECTORY/prescribed['case_id']
    require(row['status']=='verified' and prescribed['adapter']==doc['adapter']==GORILLA and doc['case_id']==prescribed['case_id'] and
            doc['timing_admitted'] is False and doc['status'] in ('measured_and_verified','measurement_failed') and
            (doc['reason'] is None if passed else bool(doc['reason'])) and (anchors is not None or not passed),
            'invalid Gorilla measured decision identity or terminal')
    if anchors is not None:
        case=_case(plan,item,row,entry)
        if check_anchors:
            with TemporaryDirectory(prefix='gorilla-audit-') as tmp:
                source=Path(tmp)/'original'
                canonical=_stage(root,entry,case,source); restored=_outputs(case,row,source)
            require(anchors == {'canonical':canonical,'restored':restored,'fixed':_check_anchor(base/'fixed',case,row)},
                    'Gorilla retained anchor differs')
    else:
        require(not (base/'fixed').exists(),'unanchored Gorilla decision has a fixed archive')
    failed=anchors is None
    slots=list(schedule(prescribed['case_id'],item['route']))
    require(len(slots)==len(doc['trials']),'Gorilla direction coverage differs')
    expected_logs=set()
    for slot, trial in zip(slots,doc['trials'],strict=True):
        require(trial['case_id']==prescribed['case_id'] and all(trial[k]==v for k,v in slot.items()),'Gorilla timing slot differs')
        if not failed and trial['status']=='measured_as_declared':
            _check_trial(run,case,slot,trial,anchors,row,seen)
            expected_logs.update(r['path'] for r in trial['logs'])
        else:
            require(not passed and trial.get('reason')==doc['reason'] and
                    trial['status']==('not_run_after_measurement_failure' if failed else 'measurement_failed'),
                    'invalid Gorilla direction terminal')
            failed=True
    require(passed==(not failed),'Gorilla decision disagrees with direction terminals')
    if check_anchors and anchors is not None:
        actual={p.relative_to(run).as_posix() for p in (base/'logs').rglob('*') if p.is_file()}
        require(actual==expected_logs,'Gorilla retained log inventory differs')
    return _summary(case,doc['trials']) if passed else None


def observe(root, plan, item, entry, pbepla_pairs, run, row):
    """Extend the frozen v3 observer without rewriting its evidence contract."""
    from .m3_in_run_measurement import guard, unavailable
    from .m3_primary_measurement import observe as previous

    prescribed=plan['measurement']['population'][item['work_item_id']]
    if prescribed.get('adapter')!=GORILLA:
        return previous(root,plan,item,entry,pbepla_pairs,run,row)
    if row['status']!='verified':
        return unavailable(prescribed,row['status'])
    with guard(plan), TemporaryDirectory(prefix='m3-gorilla-timing-',dir=run) as work:
        return measure(root,plan,item,entry,Path(work),run,row)
