"""Unique 33 current release scopes; truthful gates and no historical resigning."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];BASE=Path(__file__).resolve().parent;BUILD=ROOT/'build/closure-formal-verification-20261011'
def read(p):return json.loads(p.read_text())
def identity(p):
 with p.open('rb') as f:s=hashlib.file_digest(f,'sha256').hexdigest()
 return {'path':str(p),'sha256':s,'size_bytes':p.stat().st_size}
def main():
 p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 batches=[BUILD/'traced-builds-r8/strict-pilots/summary.json',BUILD/'traced-builds-r9/strict-release/progress.json',BUILD/'traced-builds-r9a/strict-release/summary.json']
 actual={};batch_records=[]
 for path in batches:
  x=read(path);batch_records.append(identity(path))
  for row in x['rows']:
   if row['codec'] in actual:raise RuntimeError('duplicate current unique strict codec')
   actual[row['codec']]=row
 expected=set(read(ROOT/'registry/algorithm_scope.json')['registered_codecs'])
 if set(actual)!=expected:raise RuntimeError('codec universe mismatch')
 rows=[]
 for key in sorted(actual):
  row=actual[key];report=read(Path(row['report'])) if row['report'] else None
  driver=read(Path(report['driver_report']['path'])) if report else None
  detail={'codec':key,'profile':'release','build_returncode':row['build_returncode'],'status':row['status'],
   'report':identity(Path(row['report'])) if row['report'] else None,
   'driver_identity':driver['diagnostic_wrapper'] if driver else None,'analyzer_identity':report['analyzer'] if report else None,
   'actual_command':row['actual_command'],'analysis_command':row['analysis_command'],
   'strict_scope':report['strict_scope'] if report else None,'full_N1_granted':False,
   'historical_execution_claimed':False,'full_qualification_or_source_parity_granted':False,
   'old_artifact_content_association':'CURRENT_SHARED_ARTIFACT_CONTENTS_ONLY' if report and report['old_new_artifact_bytes_equal'] else 'NOT_ALLOWED_BYTE_DIFFERENT'}
  if report:
   for field in ['strict_observed_build_closure_status','strict_nonzero_denominator_and_object_count_gate','exec_and_kernel_interpreter_pre_post_sha_gate','read_capable_open_version_binding_complete','audit_capture_error_logs','unavailable_observed_files','baseline_and_checkpoint_input_sha_drift','old_new_artifact_bytes_equal','old_new_object_byte_equality_by_name','old_new_normalized_declared_source_byte_closures_equal']:
    detail[field]=report[field]
   detail['successful_execve_count']=len(report['successful_execve_observations']);detail['executed_unique_file_count']=report['executed_unique_file_count']
   detail['read_capable_open_count']=len(report['actual_read_capable_open_events_with_version_binding']);detail['unbound_open_version_count']=len(report['read_capable_open_version_binding_gaps'])
   detail['link_map_count']=len(report['link_maps']);detail['archive_member_contribution_count']=len(report['observed_archive_member_contributions'])
  rows.append(detail)
 result={'schema_version':'tscb.release-observed-exec-open-initial-version-closure.v1','current_registered_release_codec_count':len(expected),'unique_actual_release_builds':len(rows),
  'status':'PASS_IN_DECLARED_LIMITED_SCOPE' if all(row['status']=='PASS' for row in rows) else 'GAPS_REMAIN',
  'strict_gate_PASS_count':sum(row['status']=='PASS' for row in rows),'strict_gate_gaps':[row['codec'] for row in rows if row['status']!='PASS'],
  'scope':'ACTUAL_FRESH_EXEC_PRE_POST_SHA_AND_READ_CAPABLE_OPEN_INITIAL_VERSION_OBSERVATION_ONLY',
  'limits':['SAME_DESCRIPTOR_READ_AFTER_IN_PLACE_WRITE_NOT_TRACED','PREWRAPPER_CAPTURE_INVALIDATED_ONLY_BY_OBSERVED_WRITE_OPEN_RENAME_UNLINK',
            'AUDIT_BOOTSTRAP_OUTPUT_HASH_MEASUREMENTS_AND_EVIDENCE_COPY_READS_ARE_INSTRUMENTATION_EXCEPTIONS',
            'HISTORICAL_BUILD_PROCESS_NOT_TRACED_AND_NO_OLD_ID_RESIGNING','SHARED_ARTIFACT_BYTE_EQUAL_DOES_NOT_IMPLY_OBJECTS_SOURCE_TREE_OR_TEST_EXECUTABLE_BYTE_EQUAL',
            'FULL_N1_AND_SOURCE_PARITY_AND_OTHER_N_G_CAP_GATES_NOT_GRANTED'],
  'batch_receipts':batch_records,'interrupted_batch_preserved':identity(BASE/'strict-release-r9-progress.log'),'rows':rows,
  'dzip_generated_header_difference':identity(BASE/'dzip-release-generated-header-difference-r1.json'),'driver':identity(Path(__file__))}
 with a.report.open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
 print(json.dumps({key:result[key] for key in ['status','current_registered_release_codec_count','unique_actual_release_builds','strict_gate_PASS_count','strict_gate_gaps']},indent=2))
if __name__=='__main__':main()
