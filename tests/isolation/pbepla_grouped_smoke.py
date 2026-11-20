"""Same-r40 PBEP timings with one verified window and one unchanged native rejection."""
import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.m3_column_batch_timing import _pin
from tsbench.application.m3_pbepla import _quality_layers, staged_windows
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.m3_sprintz_timing import check, ref, relative
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, digest, load_json, parse_json, require
from tsbench.planner.m3_pbepla import PROGRESSIVE, REPLAY
from tsbench.recovery import plan_recovery, stage_recovery
from tsbench.supervisor import timing_resource as resource
from tsbench.supervisor.isolated_worker import invoke_isolated_tool

DATASETS = ('etth1','bitcoin-dataset-without-missing-values-1')
OPERATIONS = (PROGRESSIVE,REPLAY)
TOOL = 'pbepla-grouped'
LIMITS = {'address_space_bytes':512<<20, 'file_bytes':1<<20, 'wall_seconds':60}


def call(run, binding, work, cpu, mode, inputs, indexes, layer=None):
    work.mkdir()
    argv = [mode, *([str(layer)] if layer else []), *map(str,indexes)]
    out, p = invoke_isolated_tool(run/'runtime',binding,TOOL,LIMITS,work,work,mode,inputs,argv,lambda:False,
                                 observe=True, private_tmp=True)
    require(p['status']=='completed' and p['returncode']==0 and p['input_mounts']=={n:ref(f) for n,f in inputs.items()} and
            (work/(mode+'.stderr')).stat().st_size==0,
            'isolated PBEPLA phase failed: '+(work/(mode+'.stderr')).read_text()[:300])
    parsed = [parse_json(x,'PBEP grouped stdout') for x in (work/(mode+'.stdout')).read_text().splitlines()]
    require(len(parsed)==2*len(indexes)+1 and parsed[-1]=={'units':len(indexes),'cpu_endpoints':[cpu,cpu]},'PBEP phase scope differs')
    pair = {}
    for ix, observation, clock in zip(indexes,parsed[:-1:2],parsed[1:-1:2],strict=True):
        require(ix==observation['index']==clock['index'] and bool(clock['native_calls']) and
                all(type(k['wall_ns']) is int and k['wall_ns']>0 and type(k['result']) is int for k in clock['native_calls']),
                'PBEPLA native call census differs')
        pair[ix] = observation, clock['native_calls']
    require(sum(k['wall_ns'] for _,calls in pair.values() for k in calls)<=p['process_wall_ns'], 'PBEP clocks overlap or exceed process')
    return out,pair,p


def cert_clock(calls, expected, failure=False):
    require([(r['part'],r['layer']) for r in calls]==expected and
            all((r['result']!=0)==failure for r in calls),'PBEPLA did not execute the declared native operations')


def smoke(plan_path, src_run, tool, cpu):
    source = load_json(plan_path)
    ledger, seal = full_run_source(source,src_run)
    entries = _entry_map(ROOT,load_json(check(ROOT,source['definition']['plan'])))
    paired = {ds:{} for ds in DATASETS}
    for row,item in full_run_rows(source,ledger):
        if 'entry_kind' not in row and row['dataset_id'] in paired and row['route'] in OPERATIONS:
            paired[row['dataset_id']][row['route']] = item,row['evidence']['units'][0]
    exe = relative(ROOT,tool)
    runtime = plan_recovery(ROOT,{},(),tools={TOOL:{k:exe[k] for k in ('path','sha256')}},
                            libraries=[source['build']['pbepla_corpus']['dependency']])
    checks,sessions = {},set()
    with resource.reserve(),_pin(cpu),TemporaryDirectory(prefix='tsbench-pbep-smoke-') as tmp:
        run = Path(tmp)
        stage_recovery(ROOT,run,runtime,directory='runtime')
        inputs, want = {}, {}
        for i,(ds,status) in enumerate(zip(DATASETS,('verified','failed'),strict=True)):
            mapping = paired[ds]
            require(set(mapping)==set(OPERATIONS),'PBEPLA smoke source decision missing')
            base = run/ds
            base.mkdir()
            with staged_windows(ROOT,entries[ds],mapping[PROGRESSIVE][0],mapping[REPLAY][0],base) as iterator:
                win,raw = next(iterator)
            f = run/str(i)
            f.write_bytes(raw)
            for route,(_,expected) in mapping.items():
                require((expected['column'],expected['row_range'],expected['input_sha256'],expected['status'])==
                        (win.column,[win.start,win.end],digest(f),status),'PBEPLA smoke source or frozen status changed')
                want[route,i] = expected
            inputs[f.name] = f
        for route,mode in zip(OPERATIONS,('progressive','replay'),strict=True):
            replay = route==REPLAY
            out,pairs,proc = call(run,runtime,run/mode,cpu,mode,inputs,(0,1))
            sessions.add(proc['session_id'])
            reject,bad_calls = pairs[1]
            require(reject=={'index':1,'status':'failed','reason':want[route,1]['reason']},'PBEPLA native failure no longer matches evidence')
            first_call = 'replay_encode' if replay else 'batch_encode'
            cert_clock(bad_calls,[(first_call,0)],failure=True)
            obs,calls = pairs[0]
            prefix = ([('replay_encode',0)] if replay else [])+[('batch_encode',0)]
            cert_clock(calls,prefix+[('prefix_materialize',l) for l in range(1,4)])
            require(obs['status']=='encoded' and {p.name for p in out.iterdir()}=={'0-1','0-2','0-3'},'PBEP prefix population differs')
            frames = [out/f'0-{l}' for l in range(1,4)]
            restored = []
            restore_mode = 'restore-callback' if replay else 'restore-batch'
            for layer,frame in enumerate(frames,1):
                decoded,results,proc = call(run,runtime,run/f'{mode}-L{layer}',cpu,restore_mode,{frame.name:frame},(0,),layer)
                require(proc['session_id'] not in sessions and {p.name for p in decoded.iterdir()}=={frame.name},'PBEP decode was not detached')
                sessions.add(proc['session_id'])
                decoded_obs,dec_calls = results[0]
                require(decoded_obs=={'index':0,'status':'restored','layer':layer},'PBEPLA detached layer differs')
                cert_clock(dec_calls,[('detached_prefix_inspect',0),('callback_restore' if replay else 'batch_restore',layer)])
                restored.append((decoded/frame.name).read_bytes())
            quality = _quality_layers(inputs['0'].read_bytes(),[f.read_bytes() for f in frames],restored,obs,replay)
            expected = want[route,0]
            require(quality['quality_passed'] and quality['layers']==expected['layers'] and
                    all(quality[k]==expected[k] for k in ('full_frame_bytes','full_frame_sha256')),'PBEP quality or bytes changed in harness')
            checks[route] = {'complete_prefixes':3,'native_failure':reject['reason'],
                             'positive_call_parts':[r['part'] for r in calls],'full_frame_sha256':quality['full_frame_sha256']}
    require(len(sessions)==8 and len({r['full_frame_sha256'] for r in checks.values()})==1,'PBEP smoke route/session cross-check failed')
    body = {'schema':'bmk.m3-pbepla-grouped-smoke/1','source_plan':relative(ROOT,plan_path),'source_seal':seal,'tool':exe,
            'cpu':cpu,'verified_direction_operations':len(sessions),'checks':checks,
            'timing_admitted':False,'stage_accepted':False,'qualification_granted':False}
    return {**body,'smoke_id':content_id(body)}


if __name__=='__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('source-plan','source-run','tool','out'):
        p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--cpu',required=True,type=int)
    a = p.parse_args()
    try:
        report = smoke(*(x.resolve(strict=True) for x in (a.source_plan,a.source_run,a.tool)),a.cpu)
        a.out.parent.mkdir(parents=True,exist_ok=True)
        write_new(a.out,report)
        print(report['smoke_id'],report['verified_direction_operations'])
    except (ContractError,OSError) as e:
        p.exit(1,f'{e}\n')
