"""Resource guard and evidence rules for the bounded serial candidate worker."""
import os
from pathlib import Path
import re

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract

POLICY = 'configs/profiles/resource_policy_v1.json'
SCHEMA = 'resource-candidate-policy'
SNAPSHOT = SCHEMA + '.schema.json'
FILES = ('original.bin','original.json','restored.bin','restored.json')


def resource_binding(root):
    schema = load_contract(root,SCHEMA)
    doc = load_json(local_file(root,POLICY))
    schema.validate(doc,POLICY)
    return {'policy':doc,'policy_id':content_id(doc),'schema_id':schema.document_id,
            'guard_sha256':digest(Path(__file__))}


def _memavailable():
    try:
        text = Path('/proc/meminfo').read_text()
    except OSError:
        return None
    match = re.search(r'^MemAvailable:\s+([0-9]+) kB$',text,re.M)
    return int(match.group(1))*1024 if match else None


def sample(run):
    """Measure actual output filesystem; host memory is an advisory signal."""
    try:
        fs = os.statvfs(run)
        disk = {'device':run.stat().st_dev,'available_bytes':fs.f_bavail*fs.f_frsize,
                'available_inodes':fs.f_favail if fs.f_files else None}
    except OSError:
        disk = None
    return {'disk':disk,'host_memavailable_bytes':_memavailable()}


def admission(plan, slot, reading, *, recovery_pending=False):
    policy = plan['contract_bindings']['resource']['policy']
    original = plan['inputs'][slot['input_id']]['bytes']
    required_bytes = policy['disk_free_floor_bytes'] + original + plan['suite']['max_serialized_bytes_per_slot']
    required_inodes = policy['disk_free_inodes_floor']
    if recovery_pending:
        files = plan['contract_bindings']['recovery']['files']
        required_bytes += sum(row['bytes'] for row in files.values())
        required_inodes += len(files) + 3  # bundle root, bin and lib
    required_mem = policy['host_available_memory_floor_bytes'] + original
    disk = reading['disk']
    reasons = []
    if disk is None or disk['available_inodes'] is None:
        reasons.append('results_mount_capacity_unavailable')
    else:
        if disk['available_bytes'] < required_bytes:
            reasons.append('results_mount_free_bytes_below_floor')
        if disk['available_inodes'] < required_inodes:
            reasons.append('results_mount_free_inodes_below_floor')
    if reading['host_memavailable_bytes'] is None:
        reasons.append('host_memavailable_unavailable')
    elif reading['host_memavailable_bytes'] < required_mem:
        reasons.append('host_memavailable_below_advisory_floor')
    return {'sample':reading,'minimum':{'available_bytes':required_bytes,'available_inodes':required_inodes,
                                        'host_memavailable_bytes':required_mem},'reasons':reasons}


def workspace_inventory(tmp):
    paths = sorted(tmp.iterdir())
    require(all(not p.is_symlink() and p.is_file() and p.name in FILES for p in paths),
            'worker temporary workspace contains an undeclared output')
    return [{'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in paths]


def verify_resources(plan,slot,row,event,validation,sealed, *, recovery_pending=False, keep_verified=False):
    guard = row['resource_guard']
    require(admission(plan,slot,guard['sample'],recovery_pending=recovery_pending)==guard, 'resource guard decision differs from the frozen policy')
    require(bool(guard['reasons'])==(row['status']=='resource_blocked'), 'resource terminal state differs from capacity reading')
    if guard['reasons']:
        require(row['reason']=='; '.join(guard['reasons']) and not row['operations'] and row['artifact'] is None and
                not row['workspace'], 'blocked slot cannot have launched work')
    files = row['workspace']
    names = [f['name'] for f in files]
    require(names==sorted(set(names)), 'workspace evidence must list each file once')
    expected = {p:r for p,r in sealed.items() if p.startswith(f"failures/{row['slot_id']}/")}
    kept = {p:r for p,r in sealed.items() if p.startswith(f"retained/{row['slot_id']}/")}
    require(not kept or (row['status']=='verified' and keep_verified), 'unexpected retained verified workspace')
    if row['status']=='verified':
        require(not expected and names==['restored.bin','restored.json'] and validation is not None,
                'invalid verified workspace')
        require(files[0]['bytes']==plan['inputs'][slot['input_id']]['bytes'] and
                [f['sha256'] for f in files]==[validation['decoded']['values_sha256'],validation['decoded']['schema_sha256']],
                'reclaimed output differs from the verified restoration')
        if keep_verified:
            require(kept=={path:{'path':path,'bytes':f['bytes'],'sha256':f['sha256']} for f in files
                          for path in [f"retained/{row['slot_id']}/{f['name']}"]},
                    'verified workspace must be retained when recovery is unavailable')
        action = 'verified_retained' if keep_verified else 'verified_released'
    elif files:
        require(expected=={path:{'path':path,'bytes':f['bytes'],'sha256':f['sha256']} for f in files
                          for path in [f"failures/{row['slot_id']}/{f['name']}"]},
                'failed workspace evidence was not retained')
        action = 'failure_retained'
    else:
        require(not expected,'undeclared retained workspace')
        action = 'no_files'
    require(event['workspace_action']==action, 'workspace disposition is inconsistent with the run ledger')
