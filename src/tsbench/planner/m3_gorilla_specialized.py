"""Register an explicit, opt-in Gorilla state derivative and frozen specialist slots."""
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require, verify_asset
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from .batch_execution import DIRECT_TARGET, DIRECT_TOOL, compile_batch_execution
from .gorilla_state import SOURCES, TARGET, TOOL, state_inputs

PROFILE = 'catalog/selections/gorilla-state-repair-v1.json'
PROGRAMS = ('tsbench_gorilla_corpus_control', DIRECT_TARGET, TARGET)
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 16384, 'wall_seconds': 15}
STATE_ROUTES = {'append-resume', 'iterator'}


def ref(root, path):
    path = Path(path).relative_to(root).as_posix() if Path(path).is_absolute() else str(path)
    f = local_file(root, path)
    return {'path': path, 'bytes':f.stat().st_size, 'sha256':digest(f)}


def load_repair(root, build, path):
    lock_ref = ref(root, path)
    lock = load_json(local_file(root, lock_ref['path']))
    profile = load_json(local_file(root, PROFILE))
    source = load_json(local_file(root,'third_party/sources.lock.json'))['sources'][profile['base_source']]
    original, = build['plugins']['gorilla-tv']['dependencies']
    require(lock['schema'] == 'bmk.gorilla-state-repair-build/1' and lock['base_build_id'] == build['build_id'] and
            lock['base_dependency'] == original and lock['source_profile'] == ref(root, PROFILE) and
            lock['repair_build_id'] == content_id({k:v for k,v in lock.items() if k!='repair_build_id'}), 'Gorilla repair lock identity differs')
    require(profile['schema'] == 'bmk.native-route-repair/1' and profile['selection'] == 7 and set(profile['routes']) == STATE_ROUTES and
            profile['preserved_unmodified_route'] == 'tv-batch' and profile['base_archive_sha256'] == source['archive']['sha256'],
            'Gorilla repair scope or parent source differs')
    verify_asset(root, source['archive']); verify_asset(root, profile['patch']); verify_asset(root, original)
    native = Path(lock['dependency']['path']).parent
    source_dir = native.parent / 'source'
    manifest = load_json(verify_asset(root,source['source_manifest']))
    expected = {m['path']: m['sha256'] for m in manifest['files']}
    member = profile['patched_member']
    require(expected[member] == profile['before_sha256'] and lock['patched_source']['path'] == (source_dir / member).as_posix() and
            lock['patched_source']['sha256'] == profile['after_sha256'] and lock['patched_source'] == ref(root, lock['patched_source']['path']),
            'Gorilla repair member does not match its frozen input and output')
    expected[member] = profile['after_sha256']
    tree = root / source_dir
    files = [p for p in tree.rglob('*') if not p.is_dir()]
    require(all(p.is_file() and not p.is_symlink() for p in files) and
            {p.relative_to(tree).as_posix():digest(p) for p in files} == expected, 'Gorilla repair tree differs from frozen archive plus patch')
    require(native.name == 'native' and native.is_relative_to(Path('build')) and
            lock['dependency'] == ref(root, native / 'libgorilla_c.so') and lock['dependency']['sha256'] != original['sha256'] and
            set(lock['programs']) == set(PROGRAMS), 'Gorilla repair build assets differ')
    for name, item in lock['programs'].items():
        require(item == ref(root, native / name) and item['sha256'] == ref(root, Path(original['path']).parent / name)['sha256'],
                'Gorilla derivative silently changed the original operation harness')
    return {'lock':lock_ref,'repair_build':lock,'implementation':profile['implementation'],'routes':profile['routes']}


def bind_specialized(root, obligations, build, repair):
    base = {**{k:build[k] for k in ('schema','worker')},'plugins':{'gorilla-tv':build['plugins']['gorilla-tv']}}
    direct = Path(base['plugins']['gorilla-tv']['library']['path']).with_name(DIRECT_TARGET).as_posix()
    batch, _ = compile_batch_execution(root, {**base,'build_id':content_id(base)}, direct)
    products, cases = state_inputs(root)
    tools = {key:{k:repair['repair_build']['programs'][name][k] for k in ('path','sha256')}
             for key,name in ((DIRECT_TOOL,DIRECT_TARGET),(TOOL,TARGET))}
    decoder = plan_recovery(root, {}, (), tools=tools, libraries=[repair['repair_build']['dependency']])
    validate_limits(LIMITS)
    ids = {'tv-batch':{},'state':{}}
    for o in (r for r in obligations if r['selection'] == 7):
        if o['route'] == 'tv-batch':
            bound = batch['obligation_bindings'][o['check']]
            require(bound['obligation_id'] == o['obligation_id'], 'Gorilla batch obligation identity differs')
            ids['tv-batch'][o['obligation_id']] = bound['product_slots']
        else:
            require(o['route'] in STATE_ROUTES and len(o['planned_case_inputs']) == 1,'Gorilla state obligation shape differs')
            case = o['planned_case_inputs'][0]
            bundle, slots = cases[case['case_id']]
            require(bundle == case['bundle_id'] and case['bundle_key'] == 'gorilla_cases','Gorilla state case origin differs')
            ids['state'][o['obligation_id']] = slots
    require(len(ids['tv-batch']) == 4 and len(ids['state']) == 8 and
            set().union(*ids['state'].values()) == products.keys(), 'Gorilla specialist denominator differs')
    state = {'limits':dict(LIMITS),'decoder':decoder,'direct_control':{'tool_refs':tools},
             'slots':{sid:slot for sid,(slot,_) in products.items()},'launchers':launcher_lock()}
    code = (*SOURCES, 'src/tsbench/planner/m3_gorilla_specialized.py', 'src/tsbench/application/m3_gorilla_specialized.py',
            'tools/build_m3_gorilla_repair.py','tools/prepare_plugin_source.py')
    return {'driver':'gorilla-specialized/1','state':state,'tv_batch':batch,'obligation_slots':ids,
            'code':{p:digest(local_file(root,p)) for p in code}}
