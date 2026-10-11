"""Independent file-only review of completed qualification; no ldd/CTest/codec."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import shlex
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
cache={}
errors=[]
def local(root,value):
    path=Path(value)
    return path if path.is_absolute() else root/path
def sha(path):
    path=path.resolve()
    if path not in cache:cache[path]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return cache[path]
def check(condition,label):
    if not condition:errors.append(label)
def verify(path,expected,label):check(sha(path)==expected,label+': '+str(path))
def entries(items,label):
    check(bool(items),label+' nonempty')
    paths=[]
    for entry in items:
        path=local(ROOT,entry['path']).resolve()
        verify(path,entry['sha256'],label)
        paths.append(path)
    check(len(paths)==len(set(paths)),label+' duplicate-free')
    return set(paths)

summary=json.loads((OUT.parent/'completed_native_r1-summary/report.json').read_text())
lock_path=ROOT/'adapters/completed_rewrites/FROZEN_SOURCES.json'
lock=json.loads(lock_path.read_text())
rows=[]
for component in summary['component_reports']:
    report_path=ROOT/component['path']
    verify(report_path,component['sha256'],'summary component report')
    report=json.loads(report_path.read_text())
    check(report['status']=='PASS','component PASS')
    verify(ROOT/'tools/qualify_completed_rewrites_native.py',report['driver_sha256'],'qualification driver')
    for case in report['cases']:
        name,profile=case['algorithm'],case['profile']
        folder=Path(case['build_directory'])
        build_path=folder/'build-record.json'
        record=json.loads(build_path.read_text())
        check(record['algorithm']==name and record['profile']==profile,name+'/'+profile+' identity')
        check(case['status']=='PASS' and case['exit_code']==0,name+'/'+profile+' case PASS')
        check(case['full_native_capability_parity']=='NOT_CLAIMED' and case['standalone_rewrite_done']=='NOT_GRANTED_BY_THIS_QUALIFICATION',name+'/'+profile+' scope')
        verify(build_path,case['closure']['build_record_sha256'],'qualified build record')
        verify(lock_path,record['frozen_sources_sha256'],'frozen lock')
        entries(lock['packages'][name]['files'],'frozen sources')
        verify(folder/'recipe/CMakeLists.txt',record['build_recipe_sha256'],'build recipe')
        verify(ROOT/'tools/build_completed_rewrite.py',record['build_driver_sha256'],'build driver')
        verify(ROOT/'adapters/completed_rewrites/tests/qualification.cpp',record['qualification_source_sha256'],'qualification source')
        artifact=local(ROOT,record['artifact'])
        verify(artifact,record['artifact_sha256'],'codec artifact')
        check(record['artifact_sha256']==case['closure']['artifact_sha256'],'qualified artifact equality')
        for field in ['binding_sources','runtime_dependencies','test_artifacts']:
            paths=entries(record[field],field)
            if field!='binding_sources':check(record[field]==case['closure'][field],'qualified '+field+' equality')
            if field=='test_artifacts':check(paths=={Path(t['command'][0]).resolve() for t in record['ctest_tests']},'test command executable universe')
        if record['pinned_native_dependencies']:entries(record['pinned_native_dependencies'],'pinned dependencies')
        closure=entries(record['compiled_source_closure'],'compiler closure')
        depfiles=list((folder/'cmake').rglob('*.o.d'))
        actual=set()
        for path in depfiles:
            content=path.read_text().replace('\\\n',' ')
            for value in shlex.split(content.split(':',1)[1]):actual.add(local(folder/'cmake',value).resolve())
        check(closure==actual,name+'/'+profile+' actual dependency universe')
        commands_path=folder/'cmake/compile_commands.json'
        verify(commands_path,record['compile_commands_sha256'],'compile commands')
        commands=json.loads(commands_path.read_text())
        optimizations=Counter()
        for command in commands:
            flags=command.get('arguments') or shlex.split(command['command'])
            path=local(Path(command['directory']),flags[flags.index('-o')+1]+'.d')
            check(path.is_file(),'TU depfile exists')
            source=local(Path(command['directory']),command['file']).resolve()
            check(source in closure,'compiled TU in closure')
            check('-ffast-math' not in flags and '-Ofast' not in flags,'safe floating compiler flags')
            if profile=='sanitizer':check('-fsanitize=address,undefined' in flags,'sanitizer instrumentation')
            optimizations[' '.join(flag for flag in flags if flag.startswith('-O'))]+=1
        check(record['ctest_tests']==case['closure']['ctest_tests'],'qualified CTest plan')
        junit=Path(case['command'][-1])
        verify(junit,case['junit_sha256'],'JUnit')
        verify(Path(case['log']),case['log_sha256'],'qualification log')
        cases=list(ET.parse(junit).getroot().iter('testcase'))
        check(Counter(c.get('name') for c in cases)==Counter(t['name'] for t in record['ctest_tests']),'JUnit exact nonempty universe')
        check(len(cases)==case['test_count'] and bool(cases),'case count')
        check(all(not list(c.iter('failure')) and not list(c.iter('error')) and not list(c.iter('skipped')) and c.get('status','run').lower() not in ['notrun','skipped','disabled'] for c in cases),'no failure/error/skipped')
        rows.append({'algorithm':name,'profile':profile,'actual_tu_count':len(commands),'depfile_count':len(depfiles),'compiler_dependency_file_count':len(closure),'ctest_count':len(cases),'optimization_flags_in_order':dict(optimizations),'sanitizer_scope':record['sanitizer_scope']})

check(len(rows)==8 and sum(row['ctest_count'] for row in rows)==32,'summary 8 profiles/32 tests')
result={'schema_version':'tscb.completed-independent-file-review.v1','status':'PASS_CURRENT_SAVED_COMPLETED_RECORDS' if not errors else 'FAIL','scope':'PURE_FILE_REVIEW_NO_BUILD_CTEST_LDD_OR_CODEC_EXECUTION','full_parity_granted':False,'complete_n1_granted':False,'new_formal_granted':False,'unique_files_hashed':len(cache),'profile_count':len(rows),'test_count':sum(row['ctest_count'] for row in rows),'rows':rows,'errors':errors}
(OUT/'completed_file_review.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
