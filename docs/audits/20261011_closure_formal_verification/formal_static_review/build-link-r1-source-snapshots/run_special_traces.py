"""Run only new self-child traced builds; no registration or codec measurement."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[4]
BASE=Path(__file__).resolve().parent
PILOT=BASE/'abba-release-pinned-r4b-trace.json'
DRIVER=BASE/'traced_rebuild_driver_v4b.py'
ANALYZER=BASE/'analyze_trace_v4.py'

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--profile',required=True,choices=['release','sanitizer','debug'])
    p.add_argument('--output-root',type=Path,required=True)
    p.add_argument('--codecs',nargs='+')
    a=p.parse_args(); output=a.output_root.resolve(); output.mkdir(exist_ok=False,parents=True)
    scope=json.loads((ROOT/'registry/algorithm_scope.json').read_text())
    codecs=[]
    for key in sorted(scope['registered_codecs']):
        doc=json.loads((ROOT/'registry/codecs'/f'{key}.json').read_text())
        if doc['adapter']['factory'] in {'COMPLETED_REWRITE_CTYPES_V1','SIMDCOMP_CTYPES_V1'} or key == 'xz-stream':
            if not a.codecs or key in a.codecs: codecs.append(key)
    rows=[]
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
    for key in codecs:
        discovered=PILOT
        for phase in ('discovery','pinned-replay'):
            directory=output/phase/(key+'--'+a.profile)
            trace=directory/'trace'; trace.mkdir(parents=True)
            command=['strace','-ff','-qq','-ttt','-s','1048576','-yy','-e','trace=process,file','-o',str(trace/'process'),
                     sys.executable,str(DRIVER),key,'--profile',a.profile,'--output-root',str(directory),'--discovered-inputs',str(discovered)]
            started=time.monotonic()
            with (trace/'stdout.log').open('x') as stdout, (trace/'stderr.log').open('x') as stderr:
                built=subprocess.run(command,cwd=ROOT,env=env,stdout=stdout,stderr=stderr)
            report=directory/'trace-report.json'
            analysis=['not run after build failed']
            if built.returncode==0:
                analysis=[sys.executable,str(ANALYZER),'--output-root',str(directory),'--codec',key,'--profile',a.profile,'--trace-directory',str(trace),'--report',str(report)]
                analyzed=subprocess.run(analysis,cwd=ROOT,env=env,capture_output=True,text=True)
                (trace/'analyzer-output.log').write_text(analyzed.stdout+analyzed.stderr)
                successful=analyzed.returncode==0
            else:
                successful=False
            row={'codec':key,'profile':a.profile,'phase':phase,'elapsed_seconds':time.monotonic()-started,'build_returncode':built.returncode,
                 'status':'PASS' if successful else 'FAIL','actual_command':command,'analyze_command':analysis,'report':str(report) if report.exists() else None}
            if report.exists():
                result=json.loads(report.read_text())
                row.update({name:result[name] for name in ('pre_read_scope_complete','old_new_artifact_bytes_equal','old_new_object_byte_equality_by_name','old_new_normalized_declared_source_byte_closures_equal','successful_read_file_count','executed_unique_file_count')})
            rows.append(row)
            (output/'progress.json').write_text(json.dumps({'status':'RUNNING','planned_codecs':len(codecs),'rows':rows},indent=2)+'\n')
            print(json.dumps(row,ensure_ascii=False),flush=True)
            if not successful:
                break
            discovered=report
        # Preserve failures; continue independent objects rather than abort all.
    summary={'scope':'FRESH_SELF_CHILD_TRACED_SPECIAL_CMAKE_SIMD_BUILDS_NOT_REGISTERED_PRODUCTION','profile':a.profile,'planned_codecs':len(codecs),'rows':rows,
             'all_two_pass_successful':len(rows)==len(codecs)*2 and all(row['status']=='PASS' for row in rows),
             'all_pinned_external_inputs_complete':all(row.get('pre_read_scope_complete') for row in rows if row['phase']=='pinned-replay')}
    with (output/'summary.json').open('x') as stream:stream.write(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({name:summary[name] for name in ('profile','planned_codecs','all_two_pass_successful','all_pinned_external_inputs_complete')},indent=2),flush=True)
    if not summary['all_two_pass_successful'] or not summary['all_pinned_external_inputs_complete']:raise SystemExit(1)

if __name__=='__main__':main()
