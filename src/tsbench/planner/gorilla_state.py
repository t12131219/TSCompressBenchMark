"""Freeze native snapshot/continuation and immutable forward iterator products."""
import struct
from pathlib import PurePosixPath

from ..assets import canonical_bytes, content_id, require
from .gorilla import CONFIG, DUPLICATE, LIMIT, PREFIX, TRAFFIC, max_payload, oracle, plan_gorilla, sha

TOOL, TARGET = 'gorilla-native-work', 'tsbench_gorilla_sealed_work_control'
PROTOCOL = 'gorilla-state-bound-v1'
APPEND, ITER = 'gorilla-append-resume', 'gorilla-iterator'
ROUTES = {(7,'append-resume'):APPEND,(7,'iterator'):ITER}
METHODS = {APPEND:{'mode':'native_snapshot_resume','format':'xorchunk','prefix_rows':PREFIX},
           ITER:{'mode':'immutable_native_forward_iterator','format':'xorchunk','requires_nondecreasing_time':True}}
SOURCES = (CONFIG,'plugins/codecs/gorilla-tv/state_control.c','plugins/codecs/gorilla-tv/CMakeLists.txt',
           'tests/native/gorilla_work_control.c','src/tsbench/planner/gorilla.py',
           'src/tsbench/planner/gorilla_state.py','src/tsbench/application/gorilla_state.py','src/tsbench/qualification/gorilla.py')
CAP = 16384


def work_path(build):
    return PurePosixPath(build['plugins']['gorilla-tv']['library']['path']).with_name(TARGET)


def is_state(slot):
    return slot.get('protocol')==PROTOCOL


def operations(slot):
    from .batch_execution import DIRECT_TOOL

    if slot['method']==ITER:
        return [('state-encode',DIRECT_TOOL),('iterator-drain',DIRECT_TOOL),('iterator-work',TOOL)]
    if slot['name']=='empty':
        return [('state-encode',DIRECT_TOOL),('empty-work',TOOL),('restore-backing',DIRECT_TOOL)]
    return [('state-append',DIRECT_TOOL),('state-resume',DIRECT_TOOL),('restore-snapshot',DIRECT_TOOL),
            ('restore-uninterrupted',DIRECT_TOOL),('restore-resumed',DIRECT_TOOL),
            ('prefix-work',TOOL),('full-work',TOOL),('trailing-work',TOOL)]


def _pairs_wire(rows):
    return b''.join(struct.pack('<qQ',t,v) for t,v in rows)


def state_inputs(root):
    from .batch_execution import BatchInput
    from .gorilla import columns

    bundle,pairs = plan_gorilla(root)
    fixtures = {f['name']:f for f in bundle['fixtures']}
    products,ids = {},{}
    for lane,(method,names) in {'append-resume':(APPEND,(TRAFFIC,'empty')),'iterator':(ITER,(TRAFFIC,DUPLICATE))}.items():
        for name in names:
            data = pairs[name]
            body = {'protocol':PROTOCOL,'method':method,'name':name,'original':oracle(data),'lineage':fixtures[name]['lineage'],
                    'parts':{'backing':max_payload(len(data))},'seek':None,'prefix':None,'tail':None}
            if method==APPEND and name==TRAFFIC:
                body.update(prefix=oracle(data[:PREFIX]),tail={'bytes':16*(LIMIT-PREFIX),'sha256':sha(_pairs_wire(data[PREFIX:]))},
                            parts={'snapshot':max_payload(PREFIX),'uninterrupted':max_payload(LIMIT),'resumed':max_payload(LIMIT)})
            if method==ITER:
                body['seek'] = bundle['seeks'][name]
            sid = ids[lane,name] = content_id(body)
            products[sid] = {**body,'product_slot':sid},BatchInput(b'',columns(data))
    binds = {c['case_id']:(bundle['bundle_id'],[ids[c['route'],f['name']] for f in c['criteria']['fixtures']])
             for c in bundle['cases'] if c['route'] in {'append-resume','iterator'}}
    require(len(products)==4 and len(binds)==8,'Gorilla lifecycle obligation denominator differs')
    return products,binds


def check_slots(plan):
    rows = [s for s in plan['slots'] if is_state(s)]
    require(len(rows)==4 and {(s['method'],s['name']) for s in rows}=={(APPEND,TRAFFIC),(APPEND,'empty'),(ITER,TRAFFIC),(ITER,DUPLICATE)},
            'Gorilla state product denominator differs')
    admission = plan['admission_definition']
    cases = {}
    for ob in admission['obligations']:
        if (ob['selection'],ob['route']) not in ROUTES:
            continue
        for c in ob['planned_case_inputs']:
            # Case criteria are locked by the native planning binding. Slot
            # checks below additionally pin executable/resource shape.
            cases[c['case_id']] = ob['route']
    require(len(cases)==8,'Gorilla state obligation denominator differs')
    for s in rows:
        name,n = s['name'],s['original']['rows']
        require(set(s)=={'protocol','method','name','original','lineage','parts','seek','prefix','tail','product_slot'} and
                set(s['original'])=={'rows','milliseconds_sha256','value_sha256'} and
                n=={TRAFFIC:LIMIT,'empty':0,DUPLICATE:5}[name], 'Gorilla state input shape differs')
        if s['method']==APPEND and name==TRAFFIC:
            require(s['seek'] is None and s['prefix']['rows']==PREFIX and s['tail']['bytes']==16*(LIMIT-PREFIX) and
                    s['parts']=={'snapshot':max_payload(PREFIX),'uninterrupted':max_payload(LIMIT),'resumed':max_payload(LIMIT)},
                    'Gorilla state resume retention or prefix differs')
        else:
            require(s['parts']=={'backing':max_payload(n)} and s['prefix'] is None and s['tail'] is None and
                    (s['seek'] is None if name=='empty' else len(s['seek'])==(4 if name==TRAFFIC else 8)),
                    'Gorilla iterator or empty product shape differs')
    a,b = [s for s in rows if s['name']==TRAFFIC]
    require(all(canonical_bytes(a[k])==canonical_bytes(b[k]) for k in ('original','lineage')),'Gorilla state traffic windows differ')
