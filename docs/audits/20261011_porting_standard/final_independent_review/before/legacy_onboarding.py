"""Call the real legacy onboarding main against an isolated temporary tree.

No native codec, build, test, or benchmark is executed. Main writes only tmp.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import tempfile

ROOT = Path('/home/fzg/PycharmProjects/TSDataCompressBenchMark')
OUT = Path('/tmp/tscb-final-gap-counterexamples')
temp = Path(tempfile.mkdtemp(prefix='onboarding-', dir=OUT))

def copy(relative):
    source = ROOT/relative
    dest = temp/relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)

shutil.copytree(ROOT/'registry/sources', temp/'registry/sources')
shutil.copytree(ROOT/'registry/codecs', temp/'registry/codecs')
(temp/'registry/onboarding').mkdir()
(temp/'docs').mkdir()
copy('adapters/rewrite_lossless/FROZEN_APIS.json')
lock = json.loads((temp/'adapters/rewrite_lossless/FROZEN_APIS.json').read_text())
copy('build/rewrite_review/native-abi/report.json')
for name, entry in lock['algorithms'].items():
    package = entry['package']
    copy('adapters/rewrite_lossless/vendor/'+package+'/UPSTREAM_PROVENANCE.json')
    copy('Compression_Rewrite/ReWrite/'+package+'/validation/differential/report.json')
    copy('build/rewrite_review/native-abi/'+name+'/run.log')
    for profile in ['release','sanitizer']:
        folder = 'build/adapters/'+name.replace('-','_')+'/'+profile
        copy(folder+'/build-record.json')
        copy(folder+'/compile-command.json')
        record = json.loads((temp/folder/'build-record.json').read_text())
        copy(record['artifact'])

path = temp/'build/rewrite_review/native-abi/report.json'
report = json.loads(path.read_text())
report['cases'] = []
report['driver_sha256'] = '0'*64
path.write_text(json.dumps(report)+'\n')
for name in lock['algorithms']:
    (temp/'build/rewrite_review/native-abi'/name/'run.log').write_text('ISOLATED UNQUALIFIED REPLACEMENT LOG\n')
spec = importlib.util.spec_from_file_location('isolated_legacy_onboard', ROOT/'tools/onboard_requested_lossless.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ROOT = temp
module.main()
result = {
    'status':'DEMONSTRATED',
    'scope':'REAL_LEGACY_ONBOARDING_MAIN_ISOLATED_NO_CODEC_EXECUTION',
    'main_repository_modified':False,
    'temporary_project_root':str(temp),
    'qualification_cases_empty':report['cases']==[],
    'qualification_driver_sha256':'0'*64,
    'qualification_run_logs_replaced':True,
    'onboarding_cards_written':sorted(p.name for p in (temp/'registry/onboarding').glob('*.json')),
    'source':'tools/onboard_requested_lossless.py',
    'source_sha256':hashlib.sha256((ROOT/'tools/onboard_requested_lossless.py').read_bytes()).hexdigest(),
}
(OUT/'legacy_onboarding_report.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
