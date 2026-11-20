"""Execute and independently audit named native sessions in the main M3 ledger."""
from collections import Counter

from ..assets import ContractError, require
from ..planner.lzbench_session import ROUTES, execution_inputs
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import lzbench_session as native
from .batch_execution import _files


def _scope(binding, rows):
    mapping = binding['obligation_slots']
    require(all((r['selection'],r['route']) in ROUTES and r['obligation_id'] in mapping for r in rows),
            'lzbench specialist scope differs')
    return sorted({p for r in rows for p in mapping[r['obligation_id']]})


def run_specialized(root, run, binding, rows, append):
    folder = run/'lzbench-session-specialized'; folder.mkdir()
    fixtures,_ = execution_inputs(root)
    require(binding['slots']=={p:s for p,(s,_) in fixtures.items()},'lzbench session fixture drift')
    ids = _scope(binding,rows)
    products = {}
    try:
        require(launcher_lock()==binding['launchers'],'lzbench session isolation launcher identity changed')
        stage_recovery(root,folder,binding['decoder'])
    except (ContractError,OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed',reason=str(exc))
    else:
        for name in ('logs','products'):
            (folder/name).mkdir()
        for p in ids:
            slot,data = fixtures[p]
            products[p] = native.run_slot(folder,binding,slot,data,lambda:False)
            append({'entry_kind':'specialized_product','selection':39 if slot['method']=='xz-session' else 40,**products[p]})
        for row in rows:
            required = binding['obligation_slots'][row['obligation_id']]
            bad = [products[p] for p in required if products[p]['status']!='verified']
            row.update(status='failed' if bad else 'verified',reason='; '.join(r['reason'] for r in bad),
                       evidence={'driver':binding['driver'],'fixture_slots':required})
    return {'driver':binding['driver'],'recovery_id':binding['decoder']['recovery_id'],'fixtures':products,
            'statuses':dict(Counter(r['status'] for r in products.values())),'files':_files(folder)}


def audit_specialized(run,binding,rows,evidence,*,replay=False):
    folder = run/'lzbench-session-specialized'
    products, files = evidence['fixtures'], evidence['files']
    closure = {f'{DIRECTORY}/{k}':{'path':f'{DIRECTORY}/{k}','bytes':v['bytes'],'sha256':v['sha256']}
               for k,v in binding['decoder']['files'].items()}
    require(evidence['driver']==binding['driver'] and evidence['recovery_id']==binding['decoder']['recovery_id'] and
            list(products)==_scope(binding,rows) and files==_files(folder) and
            evidence['statuses']==dict(Counter(p['status'] for p in products.values())) and
            {k:v for k,v in files.items() if k.startswith(DIRECTORY+'/')}==closure,'lzbench specialist closure differs')
    if replay:
        require(launcher_lock()==binding['launchers'],'lzbench session audit isolation launcher identity changed')
    allowed,replayed = set(closure),[]
    for key,product in products.items():
        slot = binding['slots'][key]
        require(product['product_slot']==key and native.inspect_evidence(folder,binding,slot,product,files,allowed),
                'lzbench specialist did not validate')
        if replay:
            replayed.append(native.audit_slot(folder,binding,slot,product))
    require(set(files)==allowed,'lzbench specialist has undeclared evidence')
    for row in rows:
        require(row['status']=='verified' and not row['reason'] and row['evidence']=={'driver':binding['driver'],
                'fixture_slots':binding['obligation_slots'][row['obligation_id']]},'lzbench obligation did not verify')
    return {'verified_obligations':len(rows),'fixture_statuses':evidence['statuses'],'replayed':replayed}
