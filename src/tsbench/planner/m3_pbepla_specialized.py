"""Bind all nine accepted PBEPLA obligations to their 33 named cases."""
from . import pbepla_execution as native
from .pbepla_progressive import plan_pbepla_progressive
from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits

DRIVER = 'pbepla-specialized/1'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 20}
SOURCES = (*native.SOURCES,'src/tsbench/planner/m3_pbepla_specialized.py','src/tsbench/application/m3_pbepla_specialized.py',
           'src/tsbench/recovery.py','src/tsbench/supervisor/process.py')


def bind(root, build, obligations, corpus):
    if corpus is None:
        return None
    targets = native.tool_paths(build)
    if not all((root / p).is_file() for p in targets.values()):
        return None
    products, fixture_cases = native.plan_slots(root)
    native.check_slots({'slots':[s for s,_ in products.values()],'limits':LIMITS})
    bundle, _, _ = plan_pbepla_progressive(root)
    expected = {c['case_id']: c for c in bundle['cases']}
    mapping, seen = {}, set()
    selected = [o for o in obligations if o['selection']==87]
    require(len(selected)==9 and all(o['kind']=='required' for o in selected),'PBEPLA specialist obligations differ')
    for ob in selected:
        route, check = ob['route'], ob['check']
        ids = []
        for frozen in ob['planned_case_inputs']:
            cid = frozen['case_id']
            case = expected.get(cid)
            require(case is not None and cid not in seen and frozen['bundle_key']=='pbepla_cases' and
                    (case['name'],case['route'],case['check'],bundle['bundle_id']) ==
                    (frozen['case_name'],route,check,frozen['bundle_id']) and fixture_cases[cid][0]==bundle['bundle_id'],
                    'PBEPLA named case differs from the accepted definition')
            ids += fixture_cases[cid][1]
            seen.add(cid)
        distinct = list(dict.fromkeys(ids))
        require(distinct and all(products[p][0]['method']==route for p in distinct),'PBEPLA named case landed on the wrong route')
        mapping[ob['obligation_id']] = distinct
    require(len(seen)==33 and seen==fixture_cases.keys() and len(mapping)==9 and len(products)==13 and
            set().union(*mapping.values())==products.keys(),'PBEPLA coverage differs')
    validate_limits(LIMITS)
    tools = {n:{'path':p.as_posix(),'sha256':digest(local_file(root,p.as_posix()))} for n,p in targets.items()}
    closure = plan_recovery(root,build,{native.PLUG:native.DEFAULT_METHOD},tools=tools)
    require(closure['files']['lib/libtba_native.so']['sha256']==corpus['dependency']['sha256'] and
            all('libtba_native.so' in closure['files'][v]['needed'] for v in closure['tools'].values()),
            'PBEPLA specialists and corpus must share the same Unique C ABI library')
    return {'driver':DRIVER,'decoder':closure,'limits':dict(LIMITS),'launchers':launcher_lock(),
            'obligation_slots':mapping,'slots':{p:s for p,(s,_) in products.items()},
            'code':{p:digest(local_file(root,p)) for p in SOURCES}}
