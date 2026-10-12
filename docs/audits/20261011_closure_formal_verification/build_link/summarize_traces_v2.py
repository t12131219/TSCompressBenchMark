"""Reconcile 67 frozen profiles with newly observed traced builds, no codec load."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
BASE=Path(__file__).resolve().parent
BUILD=ROOT/'build/closure-formal-verification-20261011'
def digest(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def resolve(path):
 p=Path(path);return p if p.is_absolute() else ROOT/p
def identity(path):return {'path':str(path),'sha256':digest(path),'size_bytes':path.stat().st_size}
def read(path):return json.loads(path.read_text())
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 old=read(BASE/'inventory_v1.json');frozen_drift=[];rows=[]
 candidates={}
 for directory in [BUILD/'traced-builds-r2/ordinary-release',BUILD/'traced-builds-r2/ordinary-sanitizer',BUILD/'traced-builds-r5/special-release',BUILD/'traced-builds-r5/special-sanitizer',BUILD/'traced-builds-r5/simd-debug']:
  summary=directory/'summary.json'
  if not summary.is_file():raise RuntimeError('batch not finished: '+str(directory))
  doc=read(summary)
  for row in doc['rows']:
   if row['phase']=='pinned-replay' and row['status']=='PASS':candidates[(row['codec'],row['profile'])]=Path(row['report'])
 candidates[('abba','release')]=BASE/'abba-release-pinned-r4b-trace.json'
 for saved in old['profiles']:
  key=(saved['codec'],saved['profile'])
  if key not in candidates:raise RuntimeError('no completed candidate for '+str(key))
  path=candidates[key];report=read(path)
  if report['status']!='PASS' or not report['pre_read_scope_complete']:raise RuntimeError('incomplete traced report '+str(path))
  initial=read(BASE/'profiles'/('%s--%s.json'%key))
  for item in [saved['record'],saved['artifact'],*initial['explicit_link_inputs_current_static_inventory'],*initial['metadata_files'],*initial['dependency_files']]:
   selected=resolve(item['path'])
   if not selected.is_file() or digest(selected)!=item['sha256']:frozen_drift.append(str(selected))
  prior=read(resolve(saved['record']['path']));newdriver=read(Path(report['driver_report']['path']));new=newdriver['new_recipe_record']
  prior_folder=resolve(saved['record']['path']).parent;new_folder=resolve(new['artifact']).parent
  test_old={str(resolve(x['path']).relative_to(prior_folder)):x['sha256'] for x in prior.get('test_artifacts',[])}
  test_new={str(resolve(x['path']).relative_to(new_folder)):x['sha256'] for x in new.get('test_artifacts',[])}
  test_drift=[x['path'] for record in [prior,new] for x in record.get('test_artifacts',[]) if digest(resolve(x['path']))!=x['sha256']]
  frozen_drift+=test_drift
  rows.append({'codec':key[0],'profile':key[1],'fresh_build_closure_status':report['status'],
   'traced_report':identity(path),'new_artifact':newdriver['new_artifact'],'old_artifact':saved['artifact'],
   'actual_successful_execve_count':len(report['successful_execve_observations']),
   'executed_unique_file_count':report['executed_unique_file_count'],'read_input_record_count':report['successful_read_file_count'],
   'link_map_count':len(report['link_maps']),'archive_member_contribution_count':len(report['observed_archive_member_contributions']),
   'pre_existing_external_input_pre_post_sha_complete':report['pre_read_scope_complete'],
   'unavailable_observed_file_count':len(report['unavailable_observed_files']),
   'old_new_artifact_bytes_equal':report['old_new_artifact_bytes_equal'],
   'old_new_objects':report['old_new_object_byte_equality_by_name'],
   'old_new_normalized_declared_source_byte_closures_equal':report['old_new_normalized_declared_source_byte_closures_equal'],
   'old_new_native_test_executable_comparison':{'old_count':len(test_old),'new_count':len(test_new),'byte_equal':test_old==test_new,'current_hash_drift':test_drift},
   'old_artifact_content_association_allowed':report['old_new_artifact_bytes_equal'],
   'historical_actual_execution_claimed':False,'old_N1_retroactive_grant':False})
 for item in old['registration_snapshots']:
  selected=resolve(item['path'])
  if digest(selected)!=item['sha256']:frozen_drift.append(str(selected))
 result={'schema_version':'tscb.fresh-observed-toolchain-link-closure.v1','status':'PASS' if not frozen_drift else 'FAIL',
  'active_codecs':old['active_codec_count'],'current_profiles':len(rows),'fresh_observed_profiles_PASS':sum(row['fresh_build_closure_status']=='PASS' for row in rows),
  'current_registered_artifacts_records_and_registration_frozen':not frozen_drift,'frozen_sha_drift':sorted(set(frozen_drift)),
  'byte_equal_current_old_artifacts':sum(r['old_new_artifact_bytes_equal'] for r in rows),
  'byte_different_current_old_artifacts':sum(not r['old_new_artifact_bytes_equal'] for r in rows),
  'normalized_source_closure_byte_equal_count':sum(r['old_new_normalized_declared_source_byte_closures_equal'] for r in rows),
  'normalized_source_closure_byte_differences':[{'codec':r['codec'],'profile':r['profile']} for r in rows if not r['old_new_normalized_declared_source_byte_closures_equal']],
  'scope':'ACTUAL_FRESH_SELF_CHILD_TRACED_BUILD_ONLY_FULL_HISTORICAL_EXECUTION_NOT_RECONSTRUCTED',
  'original_67_profile_scope_limit':'PASS_DENOTES_RECORDED_EXECVE_READ_OPENS_MAP_AND_EXTERNAL_CHECKPOINT_INSTRUMENT_SCOPE_ONLY; EXEC_INTERPRETER_PRE_SHA_AND_PID_VERSION_BINDING_GAPS_NOT_REPAIRED_RETROACTIVELY; FULL_N1_FALSE',
  'instrumentation':'B frontend/as/ld wrappers plus audit-only read preservation LD_PRELOAD for CMake; saved production source and artifacts unchanged; new ldd clean env',
  'association_rule':'BYTE_EQUAL_FRESH_ARTIFACT_ASSOCIATES_CURRENT_OLD_CONTENTS_ONLY; BYTE_DIFFERENT_ARTIFACT_CANNOT_TRANSFER_FRESH_CLOSURE_TO_OLD_ARTIFACT',
  'rows':rows,'driver':identity(Path(__file__)), 'static_before_inventory':identity(BASE/'inventory_v1.json')}
 with a.report.open('x') as stream:stream.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({key:result[key] for key in ['status','current_profiles','fresh_observed_profiles_PASS','byte_equal_current_old_artifacts','byte_different_current_old_artifacts','frozen_sha_drift']},indent=2))
if __name__=='__main__':main()
