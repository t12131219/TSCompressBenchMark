"""True full-build TryIntMult, with requested and emitted integer modes kept separate."""
import struct

from ..assets import canonical_bytes, content_id, require
from .pcodec import CONFIG, INTMULT_CHECKS, INTMULT_CONFIG, TYPES, identity, intmult_inputs, plan_pcodec
from .pcodec_pages import TOOL

PROTOCOL, METHOD = 'pcodec-intmult-bound-v1', 'pcodec-intmult'
ROUTES = {(11,'intmult'):METHOD}
METHODS = {METHOD:{'encode_entry':'pc_compress_intmult','encode_policy':'Source-TryIntMult',
                   'decode_entry':'pcs_file_open/pcs_read','wire':'standalone v3 / wrapped v4.1'}}
SOURCES = (CONFIG,'plugins/codecs/pcodec/CMakeLists.txt','plugins/codecs/pcodec/intmult_control.cpp',
           'plugins/codecs/pcodec/pages_control.cpp','src/tsbench/planner/pcodec.py',
           'src/tsbench/planner/pcodec_intmult.py','src/tsbench/application/pcodec_intmult.py',
           'src/tsbench/qualification/pcodec.py')
FILE_LIMIT = 8192 + 65536


def is_intmult(slot):
    return slot.get('protocol')==PROTOCOL


def operations(slot):
    return [('intmult-encode',TOOL)] if slot['expected_status'] else [('intmult-encode',TOOL),('intmult-decode',TOOL)]


def negative_input(slot):
    require(slot['expected_status']==1 and slot['count']==1,'IntMult rejection not a frozen single zero')
    return bytes(struct.calcsize(TYPES[slot['dtype']][2]))


def _slots(spec, originals):
    for rejected, jobs in ((False,spec['frames']),(True,spec['rejected'])):
        for job in jobs:
            body = {'protocol':PROTOCOL,'method':METHOD,'name':job['case'],'dtype':job['dtype'],
                    'count':job.get('count',1),'base':job['base'],'wire':None if rejected else {
                        'mode':job['wire_mode'],'base':job['wire_base']},'parameters':spec['parameters'],
                    'expected_status':int(rejected),'original':job['plain'],
                    'parts':{} if rejected else {'frame':job['plain']['bytes']+65536}}
            data = negative_input(body) if rejected else originals[job['case']]
            require(identity(data)==body['original'],'IntMult source differs')
            yield {**body,'product_slot':content_id(body)},data


def execution_inputs(root):
    from .batch_execution import BatchInput

    bundle,_ = plan_pcodec(root)
    spec, originals = intmult_inputs(INTMULT_CONFIG)
    require(spec==bundle['intmult'],'IntMult bundle diverges from the frozen policy')
    products = {s['product_slot']:(s,BatchInput(b'',(d,))) for s,d in _slots(spec,originals)}
    ids = {s['name']:sid for sid,(s,_) in products.items()}
    binds = {}
    for case in bundle['cases']:
        if case['route']!='intmult':
            continue
        name = INTMULT_CHECKS[case['check']]
        names = [name] if name else [j['case'] for j in spec['rejected']]
        binds[case['case_id']] = bundle['bundle_id'],[ids[n] for n in names]
    require(len(binds)==4 and len(ids)==6,'IntMult obligation denominator differs')
    return products,binds


def check_slots(plan):
    actual = [s for s in plan['slots'] if is_intmult(s)]
    expected = [s for s,_ in _slots(*intmult_inputs(INTMULT_CONFIG))]
    require(canonical_bytes(actual)==canonical_bytes(expected),'pcodec IntMult fixture or parameter contract differs')
