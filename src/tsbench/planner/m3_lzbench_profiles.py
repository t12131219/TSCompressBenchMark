"""Bind the accepted dictionary and worker obligations to the existing native fixtures."""
from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import lzbench_profiles as native
from .lzbench import plan_lzbench

DRIVER='lzbench-profiles-specialized/1'
SOURCES=(*native.SOURCES,'src/tsbench/planner/m3_lzbench_profiles.py','src/tsbench/application/m3_lzbench_profiles.py',
         'src/tsbench/planner/lzbench.py','src/tsbench/planner/native_conditions.py','src/tsbench/qualification/lzbench.py',
         'src/tsbench/recovery.py','src/tsbench/supervisor/process.py')


def bind(root,build,obligations,dictionary,workers):
    if dictionary is None or workers is None:
        return None
    paths=native.tool_paths(build)
    if not all((root/p).is_file() for p in paths.values()):
        return None
    fixtures,cases=native.plan_slots(root)
    slots={p:s for p,(s,_) in fixtures.items()}
    native.check_slots({'slots':list(slots.values())})
    bundle=plan_lzbench(root)
    declared={c['case_id']:c for c in bundle['cases'] if (c['selection'],c['route']) in native.ROUTES}
    mapping={}; seen=set(); n_cond=0
    for ob in obligations:
        if (ob['selection'],ob['route']) not in native.ROUTES:
            continue
        if native.supports_condition(ob):
            require(ob['condition_case']['bundle_id']==bundle['bundle_id'] and not ob.get('planned_case_inputs'),
                    'lzbench feature conditional case identity differs')
            ids=native.condition_slots(ob,list(slots.values())); n_cond+=1
        else:
            require(ob['kind']=='required' and len(ob['planned_case_inputs'])==1,'lzbench named case scope differs')
            c,=ob['planned_case_inputs']; cid=c['case_id']
            require(cid in declared and cid not in seen and c['bundle_key']=='lzbench_cases' and
                    c['bundle_id']==bundle['bundle_id']==cases[cid][0] and
                    (c['case_name'],ob['check'],ob['selection'],ob['route'])==
                    tuple(declared[cid][k] for k in ('name','check','selection','route')),
                    'lzbench profile named case differs from accepted definition')
            seen.add(cid); ids=cases[cid][1]
        require(len(ids)==1 and slots[ids[0]]['method']==ob['route'],'lzbench profile obligation bound to the wrong lane')
        mapping[ob['obligation_id']]=ids
    require(len(seen)==11 and seen==declared.keys() and n_cond==2 and len(mapping)==13 and
            set().union(*mapping.values())==slots.keys(),'lzbench feature coverage differs')
    for s in slots.values():
        validate_limits(s['limits'],file_ceiling=native.FILE_CEILING)
    tools={k:{'path':p.as_posix(),'sha256':digest(local_file(root,p.as_posix()))} for k,p in paths.items()}
    methods={p:{'plugin':p,'options':{}} for p in ('zstd','xz-baseline')}
    closure=plan_recovery(root,build,methods,tools=tools)
    require(closure['files']['lib/liblzbench_native.so']['sha256']==dictionary['dependency']['sha256']==workers['dependency']['sha256'] and
            all('liblzbench_native.so' in closure['files'][p]['needed'] for p in closure['tools'].values()) and
            tools[native.TOOL]['sha256']==dictionary['executable']['sha256'],'lzbench profile and corpus tool binding differ')
    return {'driver':DRIVER,'decoder':closure,'launchers':launcher_lock(),'slots':slots,'obligation_slots':mapping,
            'code':{p:digest(local_file(root,p)) for p in SOURCES}}
