"""Record PBEPLA's sealed specialized products in the main M3 ledger."""
from collections import Counter

from ..assets import ContractError, require
from ..planner.pbepla_execution import PROGRESSIVE, REPLAY, plan_slots
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import pbepla_execution as native
from .batch_execution import _files


def _scope(binding, rows):
    slots = binding['slots']; mapping = binding['obligation_slots']
    require(all(r['selection']==87 and r['obligation_id'] in mapping for r in rows),'PBEPLA specialist rows differ from plan')
    selected = {p for r in rows for p in mapping[r['obligation_id']]}
    pairs = {s['spec']['input_id']:p for p,s in slots.items() if s['method']==PROGRESSIVE and s['variant']=='prefixes'}
    weather, = (p for p in pairs.values() if slots[p]['spec']['name']=='weather')
    for p in tuple(selected):
        s = slots[p]
        if s['method']==REPLAY:
            selected.add(pairs[s['spec']['input_id']])
        elif s['variant']=='input-negatives':
            selected.add(weather)
    return sorted(selected)


def _status(binding, products, ids):
    good = {p for p in ids if products[p]['status']==native._terminal(binding['slots'][p])}
    plan = {**binding,'slots':[binding['slots'][p] for p in ids]}
    # A mismatch must leave the replay result nonpassing, not discard the
    # independent batch evidence or omit the remaining replay cases.
    for p in ids:
        s = binding['slots'][p]
        if p not in good or s['method']!=REPLAY:
            continue
        entry = products[p]['pbepla']
        reference = [products[a]['pbepla'] for a in good if binding['slots'][a]['method']==PROGRESSIVE and
                     binding['slots'][a]['variant']=='prefixes' and binding['slots'][a]['spec']['input_id']==s['spec']['input_id']]
        if len(reference)!=1 or any(entry[k]!=reference[0][k] for k in ('native_sha256','layers','wire')):
            good.remove(p)
    return good, plan


def run_specialized(root, run, binding, rows, append):
    folder = run/'pbepla-specialized'; folder.mkdir()
    fixtures, _ = plan_slots(root)
    require(binding['slots']=={p:s for p,(s,_) in fixtures.items()},'PBEPLA specialist input drift')
    ids = _scope(binding,rows); actual = {}
    try:
        require(launcher_lock()==binding['launchers'],'PBEPLA isolation launchers changed')
        stage_recovery(root,folder,binding['decoder'])
    except (ContractError,OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed',reason=str(exc))
    else:
        for name in ('logs','products'):
            (folder/name).mkdir()
        for p in ids:
            slot, sample = fixtures[p]
            actual[p] = native.run_slot(folder,binding,slot,sample,lambda:False)
            append({'entry_kind':'specialized_product','selection':87,**actual[p]})
        good,_ = _status(binding,actual,ids)
        for row in rows:
            required = binding['obligation_slots'][row['obligation_id']]
            bad = [f"{p}: {actual[p]['status']} ({actual[p]['reason'] or 'batch/replay parity not verified'})"
                   for p in required if p not in good]
            row.update(status='failed' if bad else 'verified',reason='; '.join(bad),
                       evidence={'driver':binding['driver'],'fixture_slots':required})
    return {'driver':binding['driver'],'recovery_id':binding['decoder']['recovery_id'],'fixtures':actual,
            'statuses':dict(Counter(r['status'] for r in actual.values())),'files':_files(folder)}


def audit_specialized(run, binding, rows, evidence, *, replay=False):
    folder = run/'pbepla-specialized'; ids = _scope(binding,rows)
    products, files = evidence['fixtures'], evidence['files']
    closure = {f'{DIRECTORY}/{k}':{'path':f'{DIRECTORY}/{k}','bytes':v['bytes'],'sha256':v['sha256']}
               for k,v in binding['decoder']['files'].items()}
    require(evidence['driver']==binding['driver'] and evidence['recovery_id']==binding['decoder']['recovery_id'] and
            list(products)==ids and files==_files(folder) and evidence['statuses']==dict(Counter(r['status'] for r in products.values())) and
            {k:v for k,v in files.items() if k.startswith(DIRECTORY+'/')}==closure,'PBEPLA specialist closure differs')
    if replay:
        require(launcher_lock()==binding['launchers'],'PBEPLA audit isolation launchers changed')
    allowed, replayed = set(closure), []
    good,plan = _status(binding,products,ids)
    for p in ids:
        slot, row = binding['slots'][p], products[p]
        require(p in good and row['product_slot']==p and native.inspect_evidence(folder,plan,slot,row,files,allowed),
                'PBEPLA specialist did not validate')
        if replay:
            replayed.append(native.audit_slot(folder,plan,slot,row))
    require(files.keys()==allowed,'PBEPLA specialist has undeclared retained evidence')
    for row in rows:
        require(row['status']=='verified' and not row['reason'] and row['evidence']=={'driver':binding['driver'],
                'fixture_slots':binding['obligation_slots'][row['obligation_id']]},'PBEPLA obligation not verified')
    return {'verified_obligations':len(rows),'fixture_statuses':evidence['statuses'],'replayed':replayed}
