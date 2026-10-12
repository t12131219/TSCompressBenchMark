"""One fresh traced release per existing codec, using already observed discovery."""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];BASE=Path(__file__).resolve().parent
DRIVER=BASE/'traced_rebuild_driver_v5b.py';ANALYZER=BASE/'analyze_trace_v5e.py'
def read(path):return json.loads(path.read_text())
def digest(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def seed_for(key):
 pilot=ROOT/'build/closure-formal-verification-20261011/traced-builds-r7/strict-pilots'/f'{key}--release/strict-trace-report.json'
 if pilot.is_file():return pilot
 if key=='abba':return BASE/'abba-release-pinned-r4b-trace.json'
 special=ROOT/'build/closure-formal-verification-20261011/traced-builds-r5/special-release/pinned-replay'/f'{key}--release/trace-report.json'
 if special.is_file():return special
 return ROOT/'build/closure-formal-verification-20261011/traced-builds-r2/ordinary-release/pinned-replay'/f'{key}--release/trace-report.json'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-root',type=Path,required=True);p.add_argument('--codecs',nargs='*');a=p.parse_args()
 if not a.codecs:a.codecs=[key for key in sorted(read(ROOT/'registry/algorithm_scope.json')['registered_codecs']) if key not in {'lz4-frame','abba','alp','alp-rd'}]
 out=a.output_root.resolve();out.mkdir(parents=True,exist_ok=False);rows=[]
 env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
 for key in a.codecs:
  seed=seed_for(key);discovered=read(seed);directory=out/(key+'--release');trace=directory/'trace';trace.mkdir(parents=True)
  checkpoint=read(BASE/'supplemental_exec_checkpoint_before_v1.json');paths={DRIVER,ANALYZER,BASE/'preserve_build_reads_v3.c',seed,Path(sys.executable).resolve()}
  instrumentation_seed=read(ROOT/'build/closure-formal-verification-20261011/traced-builds-r8/strict-pilots/lz4-frame--release/strict-trace-report.json')
  for item in instrumentation_seed['successful_read_file_inputs']:
   selected=Path(item['path'])
   if selected.is_file() and not selected.is_relative_to(Path(instrumentation_seed['output_root'])) and not item.get('generated_in_audit_output'):paths.add(selected.resolve())
  for field in ('successful_read_file_inputs','successful_execve_observations','executed_kernel_interpreters'):
   for item in discovered[field]:
    selected=Path(item['path'])
    if selected.is_file() and not selected.is_relative_to(Path(discovered['output_root'])) and not item.get('generated_in_audit_output'):paths.add(selected.resolve())
  for selected in sorted(paths):checkpoint['entries'].append({'path':str(selected),'sha256':digest(selected),'size_bytes':selected.stat().st_size,'epoch_sha_read_finished':time.time()})
  prelaunch=directory/'prelaunch.json';prelaunch.write_text(json.dumps(checkpoint,indent=2)+'\n')
  command=['strace','-ff','-qq','-ttt','-s','1048576','-yy','-e','trace=process,file','-o',str(trace/'process'),sys.executable,str(DRIVER),key,'--profile','release','--output-root',str(directory),'--discovered-inputs',str(seed)]
  started=time.monotonic()
  with (trace/'stdout.log').open('x') as stdout,(trace/'stderr.log').open('x') as stderr:built=subprocess.run(command,cwd=ROOT,env=env,stdout=stdout,stderr=stderr)
  report=directory/'strict-trace-report.json';analysis=None;result=None
  if built.returncode==0:
   analysis=[sys.executable,str(ANALYZER),'--output-root',str(directory),'--codec',key,'--profile','release','--trace-directory',str(trace),'--prelaunch-receipt',str(prelaunch),'--report',str(report)]
   analyzed=subprocess.run(analysis,cwd=ROOT,env=env,capture_output=True,text=True);(trace/'analyzer-output.log').write_text(analyzed.stdout+analyzed.stderr)
   if report.is_file():result=read(report)
  row={'codec':key,'profile':'release','actual_command':command,'analysis_command':analysis,'build_returncode':built.returncode,'elapsed_seconds':time.monotonic()-started,'report':str(report) if report.is_file() else None,
       'status':'PASS' if result and result['strict_observed_build_closure_status']=='PASS' and result['status']=='PASS' else 'GAPS_REMAIN'}
  if result:row.update({name:result[name] for name in ('strict_observed_build_closure_status','exec_and_kernel_interpreter_pre_post_sha_gate','read_capable_open_version_binding_complete','old_new_artifact_bytes_equal','old_new_object_byte_equality_by_name','old_new_normalized_declared_source_byte_closures_equal')})
  rows.append(row);(out/'progress.json').write_text(json.dumps({'status':'RUNNING','rows':rows},indent=2)+'\n');print(json.dumps(row),flush=True)
 summary={'scope':'FRESH_RELEASE_EXEC_PRE_POST_SHA_READ_CAPABLE_OPEN_INITIAL_VERSION_BINDING_NOT_HISTORICAL_FULL_N1','planned_codecs':a.codecs,'rows':rows,'all_strict_gates_PASS':all(row['status']=='PASS' for row in rows)}
 with (out/'summary.json').open('x') as f:f.write(json.dumps(summary,indent=2)+'\n')
 if not summary['all_strict_gates_PASS']:raise SystemExit(1)
if __name__=='__main__':main()
