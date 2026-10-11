"""Isolated factory/resolution identity test: no codec/native execution."""
from pathlib import Path
from types import SimpleNamespace
import ast
import hashlib
import json
import shutil
import tempfile

from tscompbench.adapters.factory import adapter_artifacts
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import CapabilityStatus
from tscompbench.ids import canonical_json_bytes
from tscompbench.planning.resolution import resolve_execution

ROOT = Path('/home/fzg/PycharmProjects/TSDataCompressBenchMark')
OUT = Path('/tmp/tscb-final-gap-counterexamples-fixed')
OUT.mkdir(exist_ok=True)
registry = CodecRegistry(ROOT/'registry/codecs', SourceRegistry(ROOT/'registry/sources'))
routes = json.loads((ROOT/'docs/audits/20261011_porting_standard/rewrite_routes.json').read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def local_imports(path):
    result = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            candidate = path.parent/(node.module.replace('.', '/')+'.py')
            if candidate.is_file():
                result.add(candidate)
    return result

mapping = {}
pending_factory_errors = {}
for entry in routes['entries']:
    name = entry['codec']
    manifest = registry.get(name)
    try:
        _, support = adapter_artifacts(ROOT, manifest)
    except Exception as error:
        pending_factory_errors[name] = str(error)
        continue
    support = {p.resolve() for p in support}
    adapter_files = [p for p in support if p.parent == ROOT/'src/tscompbench/adapters' and p.name != 'factory.py']
    missing = set()
    seen = set(adapter_files)
    queue = list(adapter_files)
    while queue:
        path = queue.pop()
        for imported in local_imports(path):
            if imported not in support:
                missing.add(imported)
            if imported not in seen:
                seen.add(imported)
                queue.append(imported)
    if missing:
        mapping[name] = [str(p.relative_to(ROOT)) for p in sorted(missing)]

results = []
cases = [(name, 'lzsse8_raw.py') for name in ['alp','alp-rd','leats-lossless-i64','neats-lossless-i64','sprintz-delta','sprintz-fire','sprintz-fire-huff0','sprintz-delta-u8','sprintz-fire-u8']]
cases += [(name, 'deflate_zlib.py') for name in ['fse','huff0']]
cases += [('lzss-raw', 'lzss_common.py'), ('lzss-dipperstein-c', 'lzss_common.py')]
cases += [('alp', 'source_reject_fallback.py')]
for name, changed in cases:
    temp = Path(tempfile.mkdtemp(prefix='identity-', dir=OUT))
    module_dir = temp/'src/tscompbench/adapters'
    module_dir.parent.mkdir(parents=True)
    shutil.copytree(ROOT/'src/tscompbench/adapters', module_dir, ignore=shutil.ignore_patterns('__pycache__'))
    manifest = registry.get(name)
    document = json.loads(json.dumps(manifest.document))
    artifact = temp/'build/adapters'/name/'release/libfixture.so'
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'not executable; never loaded')
    document['adapter']['artifact_path'] = str(artifact.relative_to(temp))
    document['adapter'].pop('models', None)
    document['adapter'].pop('python_source_closure', None)
    # The inert fixture is never loaded. Production runtime selection is
    # independently exercised by runtime_fixed_recheck.py with real toy DSOs.
    document['adapter'].pop('runtime_profile', None)
    command = {'schema_version':'tscb.compile-command.v1','profile':'release','command':['cc','-shared','never-executed.c','-o','never-executed.so']}
    (artifact.parent/'compile-command.json').write_text(json.dumps(command))
    record = {'schema_version':'tscb.build-artifact.v1','algorithm':name,'profile':'release','artifact':str(artifact.relative_to(temp)),'artifact_sha256':digest(artifact),'compile_commands_sha256':hashlib.sha256(canonical_json_bytes(command)).hexdigest()}
    (artifact.parent/'build-record.json').write_text(json.dumps(record))
    fake = SimpleNamespace(key=name, document=document, algorithm_id=manifest.algorithm_id, source_artifact_id=manifest.source_artifact_id)
    config = SimpleNamespace(parameters={'isa':document['execution']['isa'][0]})
    compatibility = SimpleNamespace(status=CapabilityStatus.DIRECT_SUPPORTED, output_descriptor=None, input_descriptor=SimpleNamespace(alignment_bytes=64))
    environment = {'cpu':{'flags':['avx','avx2','bmi2','abm','lzcnt','sse4_1'],'affinity':[0]},'python':{},'tools':{},'environment_id':'fixture-environment'}
    profile = {'threads':3,'runner_version':'fixture','allocation_policy':'fixture','cache_policy':'fixture','state_policy':'fixture','gc_policy':'fixture','jit_policy':'fixture'}
    def resolve():
        primary, support = adapter_artifacts(temp, fake)
        return support, resolve_execution(fake,config,compatibility,environment,artifact_path=primary,profile=profile,supporting_artifact_paths=support)
    before_support, before = resolve()
    changed_path = module_dir/changed
    old = changed_path.read_text()
    if '_MAX_RANK = 8' in old:
        changed_path.write_text(old.replace('_MAX_RANK = 8','_MAX_RANK = 7',1))
    else:
        changed_path.write_text(old+'\n# isolated mutation used only for identity detection\n')
    after_support, after = resolve()
    results.append({'codec':name,'changed':changed,'changed_file_in_support':changed_path in before_support,'support_paths_unchanged':before_support==after_support,'artifact_identity_unchanged':before.artifact_sha256==after.artifact_sha256,'execution_path_unchanged':before.execution_path_hash==after.execution_path_hash,'before_artifact_sha256':before.artifact_sha256,'after_artifact_sha256':after.artifact_sha256,'temp_directory':str(temp)})

expected = [case for case in results if not case['artifact_identity_unchanged'] and not case['execution_path_unchanged'] and case['changed_file_in_support']]
assert len(expected) == len(results), results
assert not mapping, mapping
report = {'status':'PASS_FIXED_TRANSITIVE_IDENTITY_BINDING','scope':'NO_CODEC_OR_NATIVE_EXECUTION_FACTORY_RESOLUTION_ONLY','main_repository_modified':False,'adapter_local_transitive_missing_by_current_factory':mapping,'pending_factory_errors':pending_factory_errors,'cases':results,'conditional_alp_source_reject_fallback_in_factory':True}
(OUT/'python_closure_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
