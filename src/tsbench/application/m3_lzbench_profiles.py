"""Execute the three lzbench profile products within the main M3 ledger."""
from collections import Counter

from ..assets import ContractError, require
from ..planner.lzbench_profiles import ROUTES, XZ, plan_slots
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import lzbench_profiles as native
from .batch_execution import _files


def selection(slot):
    return 39 if slot['method']==XZ else 40


def _scope(binding,rows):
    mapping=binding['obligation_slots']
    require(all((r['selection'],r['route']) in ROUTES and r['obligation_id'] in mapping for r in rows),
            'lzbench profile obligation scope differs')
    return sorted({p for r in rows for p in mapping[r['obligation_id']]})


def run_specialized(root,run,binding,rows,append):
    folder=run/'lzbench-profile-specialized'; folder.mkdir()
    fixtures,_=plan_slots(root)
    require(binding['slots']=={p:s for p,(s,_) in fixtures.items()},'lzbench profile fixtures drifted')
    ids=_scope(binding,rows); products={}
    try:
        require(launcher_lock()==binding['launchers'],'lzbench profile isolation launchers drifted')
        stage_recovery(root,folder,binding['decoder'])
    except (ContractError,OSError) as exc:
        for r in rows:
            r.update(status='dependency_failed',reason=str(exc))
    else:
        for k in ('logs','products'):
            (folder/k).mkdir()
        for p in ids:
            slot,raw=fixtures[p]
            products[p]=native.run_slot(folder,binding,slot,raw,lambda:False)
            append({'entry_kind':'specialized_product','selection':selection(slot),**products[p]})
        for r in rows:
            members=binding['obligation_slots'][r['obligation_id']]
            bad=[products[p]['reason'] for p in members if products[p]['status']!='verified']
            r.update(status='failed' if bad else 'verified',reason='; '.join(bad),
                     evidence={'driver':binding['driver'],'fixture_slots':members})
    return {'driver':binding['driver'],'recovery_id':binding['decoder']['recovery_id'],'fixtures':products,
            'statuses':dict(Counter(p['status'] for p in products.values())),'files':_files(folder)}


def audit_specialized(run,binding,rows,evidence,*,replay=False):
    folder=run/'lzbench-profile-specialized'
    products,files=evidence['fixtures'],evidence['files']
    closure={f'{DIRECTORY}/{k}':{'path':f'{DIRECTORY}/{k}','bytes':v['bytes'],'sha256':v['sha256']}
             for k,v in binding['decoder']['files'].items()}
    require(evidence['driver']==binding['driver'] and evidence['recovery_id']==binding['decoder']['recovery_id'] and
            list(products)==_scope(binding,rows) and files==_files(folder) and
            evidence['statuses']==dict(Counter(p['status'] for p in products.values())) and
            {k:v for k,v in files.items() if k.startswith(DIRECTORY+'/')}==closure,'lzbench profile closure differs from plan')
    if replay:
        require(launcher_lock()==binding['launchers'],'lzbench profile replay launchers drifted')
    allowed,samples=set(closure),[]
    for key,prod in products.items():
        slot=binding['slots'][key]
        require(prod['product_slot']==key and native.inspect_evidence(folder,binding,slot,prod,files,allowed),
                'lzbench profile product failed verification')
        if replay:
            samples.append(native.audit_slot(folder,binding,slot,prod))
    require(set(files)==allowed,'lzbench profile contains undeclared evidence')
    for row in rows:
        require(row['status']=='verified' and not row['reason'] and row['evidence']=={'driver':binding['driver'],
                'fixture_slots':binding['obligation_slots'][row['obligation_id']]},'lzbench profile obligation lacks evidence')
    return {'verified_obligations':len(rows),'statuses':evidence['statuses'],'replayed':samples}
