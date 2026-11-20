"""Bind the named Zstd/XZ session obligations to existing native fixture tools."""
from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import lzbench_session as session
from .lzbench import plan_lzbench

DRIVER = 'lzbench-session-specialized/1'
LIMITS = {'file_bytes': 1 << 20, 'address_space_bytes': 256 << 20, 'wall_seconds': 30}
SOURCES = (*session.SOURCES,'src/tsbench/planner/m3_lzbench_specialized.py',
           'src/tsbench/application/m3_lzbench_specialized.py','src/tsbench/planner/lzbench.py',
           'src/tsbench/supervisor/isolated_worker.py','src/tsbench/supervisor/process.py','src/tsbench/recovery.py')


def bind(root, build, obligations, corpus):
    if corpus is None:
        return None
    tool = session.tool_path(build).as_posix()
    if not (root/tool).is_file():
        return None
    products, cases = session.execution_inputs(root)
    slots = {p:s for p,(s,_) in products.items()}
    session.check_slots({'slots':list(slots.values())})
    bundle = plan_lzbench(root)
    declared = {c['case_id']:c for c in bundle['cases'] if (c['selection'],c['route']) in session.ROUTES}
    wanted = [o for o in obligations if (o['selection'],o['route']) in session.ROUTES]
    require(len(wanted)==len(cases)==10 and all(o['kind']=='required' and len(o['planned_case_inputs'])==1 for o in wanted),
            'lzbench session obligation scope differs')
    mapping, seen = {}, set()
    for row in wanted:
        frozen, = row['planned_case_inputs']; cid = frozen['case_id']
        require(cid in declared and cid not in seen and frozen['bundle_key']=='lzbench_cases' and
                frozen['bundle_id']==bundle['bundle_id']==cases[cid][0] and
                (frozen['case_name'],row['check'],row['selection'],row['route']) ==
                tuple(declared[cid][k] for k in ('name','check','selection','route')),
                'lzbench session named case differs from the accepted definition')
        ids = cases[cid][1]
        require(len(ids)==1 and slots[ids[0]]['method']==row['route'],'lzbench session case bound to the wrong tool lane')
        mapping[row['obligation_id']] = ids
        seen.add(cid)
    require(seen==declared.keys() and len(mapping)==10 and set().union(*mapping.values())==slots.keys(),
            'lzbench session fixture coverage differs')
    validate_limits(LIMITS)
    methods = {name:{'plugin':name,'options':{}} for name in ('zstd','xz-baseline')}
    closure = plan_recovery(root,build,methods,tools={session.TOOL:{'path':tool,'sha256':digest(local_file(root,tool))}})
    require(closure['files']['lib/liblzbench_native.so']['sha256']==corpus['dependency']['sha256'] and
            'liblzbench_native.so' in closure['files'][closure['tools'][session.TOOL]]['needed'],
            'lzbench session specialist does not share the corpus native library')
    return {'driver':DRIVER,'decoder':closure,'limits':dict(LIMITS),'launchers':launcher_lock(),
            'slots':slots,'obligation_slots':mapping,'code':{p:digest(local_file(root,p)) for p in SOURCES}}
