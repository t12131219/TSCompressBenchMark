#!/usr/bin/env python3
"""Exercise the public registry, suite and native execution without editing core files."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.api import plan_tv
from tsbench.assets import canonical_bytes, digest, load_json, require, verify_asset
from tsbench.ingress import load_typed_source, sha

LOADER = 'test-rowpack'
GROUP = 'edge-bits'
LOCK = 'build/build-lock.json'
FIXTURES = 'datasets/fixtures/m3-ingress'
REGISTRY = 'catalog/source-loaders.json'
FORMAT = 'plugins/loaders/rowpack_source.py'
OPTIONS = 'plugins/loaders/rowpack.schema.json'
ORIGINAL = 'configs/suites/dev_tv_cross_format_v2/suite.json'


def write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canonical_bytes(data)+b'\n')


def stage_assets(stage, source_root):
    def copy(relative):
        dest = stage/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():
            shutil.copy2(source_root/relative,dest)

    for tree in ('src', 'schemas'):
        shutil.copytree(source_root/tree,stage/tree,ignore=shutil.ignore_patterns('__pycache__'))
    for f in ('bmk','catalog/plugins.toml',REGISTRY,LOCK):
        copy(f)
    locked = load_json(source_root/LOCK)
    refs = [locked['worker']]
    for row in locked['plugins'].values():
        refs.extend([row['library'],*row['dependencies']])
    for ref in refs:
        verify_asset(source_root,ref)
        copy(ref['path'])
        verify_asset(stage,ref)
    catalog = tomllib.loads((stage/'catalog/plugins.toml').read_text())['plugins']
    for name in locked['plugins']:
        path = catalog[name]['manifest']
        copy(path)
        manifest = load_json(stage/path)
        for f in [manifest['options_schema'],*manifest['source_files']]:
            copy(f)
    registry = load_json(stage/REGISTRY)
    registry['plugins'] = {k:v for k,v in registry['plugins'].items() if k in ('csv','npy')}
    for row in registry['plugins'].values():
        copy(row['implementation'])
        copy(row['options_schema'])
    for fmt in ('csv','npy'):
        f = f'{FIXTURES}/exact-bits-tail-{fmt}.json'
        copy(f)
        for ref in load_json(stage/f)['files']:
            copy(ref['path'])
    write(stage/REGISTRY,registry)
    return registry


def install(stage, registry, version, source_spec, columns):
    loader = (ROOT/'tests/fixtures/loaders/rowpack_source.py').read_text()
    if version==2:
        loader = loader.replace("b'TSBROW01'","b'TSBROW02'")
    (stage/FORMAT).write_text(loader)
    properties = {'byte_order':{'const':'big'}} if version==2 else {}
    write(stage/OPTIONS,{'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object',
                         'additionalProperties':False,'required':list(properties),'properties':properties})
    index = deepcopy(registry)
    index['plugins'][LOADER] = {'implementation':FORMAT,'options_schema':OPTIONS,'version':version}
    write(stage/REGISTRY,index)
    suffix = f'v{version}'
    path = f'{FIXTURES}/rowpack-{suffix}.bin'
    rows = source_spec['rows']
    words = (col[8*r:8*r+8] for r in range(rows) for col in columns)
    raw = f'TSBROW0{version}'.encode()+b''.join(word[::-1] if version==2 else word for word in words)
    (stage/path).write_bytes(raw)
    mf = f'{FIXTURES}/rowpack-{suffix}.json'
    write(stage/mf,{'schema':'bmk.typed-tv-source/1','plugin':LOADER,'object':source_spec,
                    'options':{'byte_order':'big'} if version==2 else {},
                    'files':[{'role':'records','path':path,'bytes':len(raw),'sha256':sha(raw)}]})
    return mf


def suite_doc(base, manifest=None):
    d = deepcopy(base)
    d['schema'] = 'bmk.dev-tv-suite/3'
    d['cases'] = {fmt:{'ingress':{'group':GROUP,'manifest':f'{FIXTURES}/exact-bits-tail-{fmt}.json'}} for fmt in ('csv','npy')}
    d['source_groups'] = {GROUP:['csv','npy']}
    if manifest:
        d['cases']['rowpack'] = {'ingress':{'group':GROUP,'manifest':manifest}}
        d['source_groups'][GROUP].append(LOADER)
    [c] = d['comparisons'].values()
    c['cases'] = list(d['cases'])
    return d


def main(out):
    stage = out/'relocated project'
    stage.mkdir()
    logs = out/'logs'; logs.mkdir()
    base_suite = load_json(ROOT/ORIGINAL)
    registry = stage_assets(stage,ROOT)
    core = {p:digest(p) for p in [stage/'bmk',*sorted((stage/'src').rglob('*.py')),*sorted((stage/'schemas').glob('*.json'))]}
    original, columns = load_typed_source(stage,f'{FIXTURES}/exact-bits-tail-npy.json')
    spec = original['ingestion']['object']

    def bmk(name,*args,rc=0,reason=None):
        proc = subprocess.run([sys.executable,'-I','-B','bmk',*args],cwd=stage,capture_output=True,timeout=120,check=False)
        (logs/f'{name}.stdout').write_bytes(proc.stdout)
        (logs/f'{name}.stderr').write_bytes(proc.stderr)
        require(proc.returncode==rc and (not reason or reason in proc.stderr.decode()),f'{name} unexpected exit: {proc.returncode} {proc.stderr[:900]}')
        return json.loads(proc.stdout) if not rc else None

    def mk_suite(tag, manifest=None):
        ref = f'configs/{tag}.json'
        write(stage/ref,suite_doc(base_suite,manifest))
        return ref

    def freeze(tag,suite,reason=None):
        plan_file = f'configs/plan-{tag}.json'
        bmk(f'plan-{tag}','tv-plan','--build-lock',LOCK,'--suite',suite,'--out',plan_file,rc=2 if reason else 0,reason=reason)
        if reason:
            require(not (stage/plan_file).exists(), f'{tag}: rejected plan published')
            return None
        plan = load_json(stage/plan_file)
        require(plan==plan_tv(stage,LOCK,suite),'CLI/API provider plan mismatch')
        return plan_file, plan

    def run(tag,frozen,expected_providers):
        ref, plan = frozen
        report = bmk(f'run-{tag}','tv-run','--plan',ref)
        eq = report['source_equivalence']
        g = eq['groups'][GROUP]
        require(report['schema']=='bmk.dev-tv-report/3' and report['verified'] and
                report['statuses']=={'verified':2*len(expected_providers)} and
                report['plan_content_id']==plan['plan_content_id'] and not report['qualification_granted'],
                'provider run did not really restore all planned slots')
        require(eq['logical_dataset_weights']==1 and set(g['providers'])==expected_providers and
                g['canonical_dataset_hash']==original['canonical_dataset_hash'] and
                all(m['byte_identical_bundle'] and m['verified_all_formats'] for m in g['methods'].values()),
                'provider variants changed canonical identity, weights or bundle')
        require(len({o['session_id'] for s in report['slots'] for o in s['operations']})==4*len(expected_providers),
                'provider test reused operation records')
        run_dir = stage/'results'/report['run_id']
        require(all(s['restored']['canonical_dataset_hash']==original['canonical_dataset_hash'] for s in report['slots']),
                'lost original-domain restoration')
        return { 'run_id':report['run_id'],'plan_content_id':plan['plan_content_id'],
                 'slots':len(report['slots']),'report_sha256':digest(run_dir/'report.json') }

    # A new provider + versioned public composition. No core patch, rebuild or algorithm substitution.
    m1 = install(stage,registry,1,spec,columns)
    suite1 = mk_suite('added',m1)
    v1 = freeze('added',suite1)
    before = v1[1]['cases']['rowpack']['lineage']
    require(before['ingestion']['version']==1 and before['canonical_dataset_hash']==original['canonical_dataset_hash'], 'new v1 provider resolved incorrectly')
    report1 = run('added',v1,{'csv','npy',LOADER})

    broken = suite_doc(base_suite,m1)
    broken['source_groups'][GROUP].remove(LOADER)
    write(stage/'configs/wrong-group.json',broken)
    freeze('wrong-group','configs/wrong-group.json','must match declared providers')
    broken = suite_doc(base_suite,m1)
    broken['comparisons'][next(iter(broken['comparisons']))]['cases'].remove('rowpack')
    write(stage/'configs/incomplete-comparison.json',broken)
    freeze('incomplete-comparison','configs/incomplete-comparison.json','must exercise all formats')

    # Unregister with the file still present: never substitute another decoder or an identically named file.
    write(stage/REGISTRY,registry)
    require((stage/FORMAT).is_file(),'disable test must still have the provider implementation')
    freeze('disabled',suite1,'source loader is not registered')
    bmk('submit-disabled','tv-run','--plan',v1[0],rc=2,reason='source loader is not registered')
    require(len(list((stage/'results').iterdir()))==1,'rejected submission published a runtime ledger')

    # Update under the same registry ID. The new loader only understands the new binary prefix.
    m2 = install(stage,registry,2,spec,columns)
    freeze('old-options-with-new-provider',suite1,f'{LOADER} options')
    incompatible = load_json(stage/m1)
    incompatible['options'] = {'byte_order':'big'}
    stale_source = f'{FIXTURES}/rowpack-old-with-new-options.json'
    write(stage/stale_source,incompatible)
    freeze('old-source-with-new-provider',mk_suite('stale-source',stale_source),'source format version differs')
    invalid = load_json(stage/m2); invalid['options']['byte_order']='little'
    wrong_manifest = f'{FIXTURES}/rowpack-invalid-option.json'
    write(stage/wrong_manifest,invalid)
    freeze('plugin-option-rejected',mk_suite('invalid-options',wrong_manifest),f'{LOADER} options')
    v2 = freeze('upgraded',mk_suite('upgraded',m2))
    after = v2[1]['cases']['rowpack']['lineage']
    require(after['ingestion']['version']==2 and after['ingestion']['options']=={'byte_order':'big'} and
            all(before[k]!=after[k] for k in ('ingestion_id','source_file_hash','manifest_id')) and
            before['ingestion']['implementation_sha256']!=after['ingestion']['implementation_sha256'] and
            after['canonical_dataset_hash']==before['canonical_dataset_hash'] and v1[1]['methods']==v2[1]['methods'],
            'provider upgrade did not bind version/format/options with stable canonical task/methods')
    report2 = run('upgraded',v2,{'csv','npy',LOADER})
    pair = lambda run: {item['method']:item['artifact']['sha256'] for item in
                        load_json(stage/'results'/run['run_id']/'report.json')['slots'] if item['case']=='rowpack'}
    require(pair(report1)==pair(report2), 'upgraded provider changed codec artifact bytes')

    # Remove package/config assets from the execution root; independent selected providers still run.
    write(stage/REGISTRY,registry)
    retired = out/'removed-package'; retired.mkdir()
    for relative in (FORMAT,OPTIONS,m1,m2,*[f'{FIXTURES}/rowpack-v{i}.bin' for i in (1,2)]):
        (stage/relative).rename(retired/Path(relative).name)
    report3 = run('after-removal',freeze('after-removal',mk_suite('remaining')),{'csv','npy'})
    require(all(digest(path)==value for path,value in core.items()),'provider authoring modified shared core')
    require(not (stage/'.git').exists() and not (stage/'Unique_Selected_Compression_Rewrite').exists(), 'not a reduced checkout')
    write(out/'audit.json',{'schema':'bmk.source-loader-authoring/1','runs':{'added':report1,'upgraded':report2,'remaining':report3},
                           'namespace':os.readlink('/proc/self/ns/net'),'logical_dataset_weights':1,
                           'aborted_before_publish':['wrong_provider_group','incomplete_comparison','disabled_plan',
                                                      'disabled_submit','incompatible_source_config','incompatible_source_format','plugin_specific_option'],
                           'core_file_hashes_preserved':len(core),'cli_api_parity':True,
                           'byte_identical_bundles_across_providers':True,'qualification_granted':False})


if __name__=='__main__':
    main(Path(sys.argv[1]).resolve(strict=True))
