"""Bounded candidate schedule for steady/cold same-ABI frame batches."""
from hashlib import sha256
import random
import re
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require

CONFIG = 'configs/experiments/measurement_controls/frame_batches_v1.json'
TEST = 'tsbench.control.frame-batches'
METHODS = ('raw-store','zstd','alp-auto')
LANES = ('dlopen','linked_entry')
EXTENTS = ('steady','cold')


def reference_path(case, method):
    return f'ref-{case}.{method}.bmk'


def retained_paths(plan):
    return sorted({reference_path(g['case'], g['method']) for g in plan['groups']})


def materialize(case):
    schema = canonical_bytes({'dtype':'f64le','column':'v','case':case['id']})
    src = b''.join(struct.pack('<d',(i%161-80)/10) for i in range(case['rows']))
    return src, schema


def plan_frame_batches(root):
    return compile_frame_batches(load_json(local_file(root,CONFIG)))


def compile_frame_batches(cfg):
    fixed = {'schema':'bmk.frame-batches/1','scope':'frame','lifecycles':list(EXTENTS),'lanes':list(LANES),
             'completion':'result_ready','verification':'artifact_each','cache':'natural_repeated_input'}
    bounds = {'warmups':(1,8),'matched_rounds':(2,5),'seed':(0,2**32-1),'target_batch_ns':(1,10_000_000),
              'max_loops':(1,256),'retention_budget_bytes':(2**20,2**27)}
    require(isinstance(cfg,dict) and cfg.keys() == fixed.keys() | bounds.keys() | {'cases'} and
            all(cfg[k]==v for k,v in fixed.items()) and
            all(type(cfg[k]) is int and lo<=cfg[k]<=hi for k,(lo,hi) in bounds.items()), 'invalid frame batch config')
    cases, seen = [], set()
    require(isinstance(cfg['cases'],list) and 1<=len(cfg['cases'])<=8,'invalid frame batch case count')
    for c in cfg['cases']:
        require(isinstance(c,dict) and c.keys()=={'id','rows','methods'} and isinstance(c['id'],str) and
                re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}',c['id']) and c['id'] not in seen and
                type(c['rows']) is int and 1<=c['rows']<=4194304 and isinstance(c['methods'],list) and
                bool(c['methods']) and all(m in METHODS for m in c['methods']) and len(set(c['methods']))==len(c['methods']) and
                ('zstd' not in c['methods'] or c['rows']<=8192),'invalid frame batch case')
        seen.add(c['id'])
        data, schema = materialize(c)
        cases.append({**c,'bytes':len(data),'schema_bytes':len(schema),'input_sha256':sha256(data).hexdigest(),
                      'schema_sha256':sha256(schema).hexdigest()})
    rng = random.Random(cfg['seed'])
    groups = []
    for case in cases:
        for method in case['methods']:
            for lifecycle in EXTENTS:
                orders = [rng.sample(LANES,len(LANES)) for _ in range(cfg['matched_rounds'])]
                options = {'decode_backend':'falp-scalar'} if method=='alp-auto' else {}
                row = {'case':case['id'],'method':method,'lifecycle':lifecycle,'options':options,'round_lane_order':orders}
                groups.append({**row,'group_id':content_id(row)})
    body = {'config':cfg,'test':TEST,'evidence_path':'frame-batches/frame-batches.json','cases':cases,'groups':groups,
            'status':'development_timing_only_no_ranking'}
    return {**body,'plan_id':content_id(body)}


def choose_loops(config, logical_each, calibration):
    """Give both lanes the same loops, from two single-loop pilots and a shared cap."""
    largest_cap = max(p['frame_capacity_total'] for p in calibration)
    largest_frame = max(p['frame_bytes_each'] for p in calibration)
    faster = min(p[k] for p in calibration for k in ('encode_batch_ns','decode_batch_ns'))
    budget_loops = (config['retention_budget_bytes']-largest_frame)//(largest_cap+logical_each)
    require(budget_loops>=1 and faster>0,'frame batch calibration cannot fit one retained operation')
    desired = (config['target_batch_ns']+faster-1)//faster
    return min(desired,budget_loops,config['max_loops'])
