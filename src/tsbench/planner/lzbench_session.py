"""Freeze the two non-dictionary native byte sessions and their recovery inputs."""
from pathlib import PurePosixPath

from ..assets import content_id, require
from .lzbench import SPAN_LIMITS, byte_identity, plan_lzbench, sample, source

TOOL, TARGET = 'lzbench-native-session', 'tsbench_lzbench_session_control'
PROTOCOL = 'lzbench-session-bound-v1'
ROUTES = {(40,'zstd-session'):'zstd-session',(39,'xz-session'):'xz-session'}
METHODS = {method:{'entry':'lzbench_native::session::process','codec':codec,'format':wire}
           for method,codec,wire in (('zstd-session','zstd','zstd-frame'),('xz-session','xz','xz-stream'))}
SOURCES = ('plugins/codecs/zstd/CMakeLists.txt','plugins/codecs/zstd/session_control.cpp',
           'src/tsbench/planner/lzbench_session.py','src/tsbench/application/lzbench_session.py',
           'src/tsbench/qualification/lzbench_session.py')
PARTS = ('first','second')
SLACK = 65536
CALL_LIMIT = 4096
RESTORE_SPANS = (17,127)
# One-byte XZ control with LZMA2 dictionary property 33 (384 MiB) and correct
# header CRC. No runtime-generated training data or old verdict is required.
BUDGET_FRAME = bytes.fromhex('fd377a585a000000ff12d94104c00501210121000000000000000000451b4607'
                            '010000000000000000011901a52c81cc06729e7a010000000000595a')


def tool_path(build):
    paths = {PurePosixPath(build['plugins'][name]['library']['path']).with_name(TARGET)
             for name in ('zstd','xz-baseline')}
    require(len(paths)==1,'lzbench session and baseline plugins must share a build directory')
    return paths.pop()


def is_session(slot):
    return slot.get('protocol')==PROTOCOL


def operations(slot):
    return [(label,TOOL) for label in ('session-exercise','restore-first','restore-second')]


def input_bytes(slot):
    return sum(x['bytes'] for x in slot['inputs'].values()) + (slot['budget_frame'] or {'bytes':0})['bytes']


def _slot(method):
    xz = method=='xz-session'
    inputs = dict(zip(PARTS,(source(136013,9),source(7919,13)),strict=True))
    body = {'protocol':PROTOCOL,'method':method,'inputs':inputs,'parts':{k:v['bytes']+SLACK for k,v in inputs.items()},
            'level':1 if xz else -1,'parameters':{'block_size':32768,'check':4,'filter0':3,'filter0_distance':4,
                      'memory_limit':64<<20,'threads':1} if xz else {'workers':0,'checksum':1},
            'span_limits':{key:list(values) for key,values in SPAN_LIMITS.items()},'restore_spans':list(RESTORE_SPANS),
            'call_limit':CALL_LIMIT,'budget_frame':byte_identity(BUDGET_FRAME) if xz else None,
            'dictionary_property':16 if xz else None}
    return {**body,'product_slot':content_id(body)}


def execution_inputs(root):
    from .batch_execution import BatchInput

    bundle = plan_lzbench(root)
    products, bindings = {}, {}
    for (selection,route),method in ROUTES.items():
        slot = _slot(method)
        spec = bundle['sessions'][METHODS[method]['codec']]
        require(all(slot[k]==spec[k] for k in ('inputs','level','parameters','span_limits')) and
                slot['dictionary_property']==spec.get('dictionary_property'),'lzbench session inputs diverge from native plan')
        sid = slot['product_slot']
        products[sid] = slot,BatchInput(b'',tuple(sample(row['bytes'],row['salt']) for row in slot['inputs'].values()))
        for case in bundle['cases']:
            if (case['selection'],case['route'])==(selection,route):
                bindings[case['case_id']] = bundle['bundle_id'],[sid]
    require(len(products)==2 and len(bindings)==10,'lzbench session obligation denominator differs')
    return products,bindings


def check_slots(plan):
    slots = {s['method']:s for s in plan['slots'] if is_session(s)}
    require(sum(is_session(s) for s in plan['slots'])==2 and slots=={method:_slot(method) for method in METHODS},
            'lzbench session fixture, spans or retained budget differs')
