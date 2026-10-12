"""Index successful and failed fresh trial receipts without rebuilding anything."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];BASE=Path(__file__).resolve().parent;BUILD=ROOT/'build/closure-formal-verification-20261011'
def identity(path):
 with path.open('rb') as f:s=hashlib.file_digest(f,'sha256').hexdigest()
 return {'path':str(path),'sha256':s,'size_bytes':path.stat().st_size}
def main():
 p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);a=p.parse_args();rows=[]
 reports=sorted(set([*BASE.glob('*trace.json'),*BUILD.rglob('trace-report.json'),*BUILD.rglob('strict-trace-report.json')]))
 for path in reports:
  x=json.loads(path.read_text());rows.append({'report':identity(path),'status':x['status'],'strict_status':x.get('strict_observed_build_closure_status'),
    'codec':x['codec'],'profile':x['profile'],'output_root':x['output_root'],'scope':x['scope'],
    'full_N1_granted':x.get('full_N1_granted',False),'old_new_artifact_bytes_equal':x.get('old_new_artifact_bytes_equal'),
    'unavailable_observed_file_count':len(x['unavailable_observed_files'])})
 failed_or_incomplete=[]
 for path in sorted(BUILD.rglob('stderr.log')):
  directory=path.parent.parent
  related=[x for x in rows if x['output_root']==str(directory)]
  if not related or any(x['status']!='PASS' or x['strict_status']=='GAPS_REMAIN' for x in related):
   failed_or_incomplete.append({'stderr':identity(path),'stdout':identity(path.with_name('stdout.log')) if path.with_name('stdout.log').is_file() else None,
      'reason':'NO_SUCCESSFUL_FINAL_ANALYSIS_OR_GAPS_PRESERVED','output_root':str(directory)})
 interrupted=[identity(BASE/'strict-release-r9-progress.log')]
 result={'schema_version':'tscb.all-fresh-build-trial-receipts.v1','scope':'ALL_TRIALS_PRESERVED_NO_HISTORICAL_OVERWRITE',
  'analysis_receipt_count':len(rows),'analysis_PASS_count':sum(row['status']=='PASS' for row in rows),
  'analysis_FAIL_count':sum(row['status']=='FAIL' for row in rows),'analysis_GAPS_REMAIN_count':sum(row['strict_status']=='GAPS_REMAIN' for row in rows),
  'rows':rows,'unsuccessful_or_incomplete_build_analysis_log_receipts':failed_or_incomplete,
  'interrupted_batch_log_receipts':interrupted,'audit_scripts':[identity(path) for path in sorted(BASE.glob('*.py'))]+[identity(path) for path in sorted(BASE.glob('*.c'))],
  'failure_policy':'FAILURES_ARE_RETAINED; LATER_DIFFERENT_ISOLATED_RUNS_DO_NOT_REWRITE_EARLIER_RECEIPTS; UNIQUE_67_AND_33_SCOPE_SUMMARIES_SEPARATE',
  'full_N1_granted':False,'driver':identity(Path(__file__))}
 with a.report.open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
 print('trial receipts',len(rows),'failed/incomplete logs',len(failed_or_incomplete))
if __name__=='__main__':main()
