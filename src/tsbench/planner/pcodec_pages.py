"""Freeze multi-asset product slots for both pcodec wrapped-page APIs."""
from ..assets import content_id, require
from .pcodec import PAGE_CHECKS, TRAFFIC, identity, page_spans, plan_pcodec

TOOL = 'pcodec-wrapped-driver'
TARGET = 'tsbench_pcodec_pages_control'
POLICY = 'configs/suites/m3_first_batch_native_v2/pcodec-wrapped-execution.json'
PROTOCOL = 'pcodec-wrapped-pages/1'
ROUTES = {(11,route):f'pcodec-{route}' for route in PAGE_CHECKS}
METHODS = {method:{'protocol':PROTOCOL,'tool':TOOL,'native_prefix':'pcn' if route=='native-pages' else 'pcs'}
           for (_,route),method in ROUTES.items()}
SOURCES = ('plugins/codecs/pcodec/pages_control.cpp', 'src/tsbench/planner/pcodec_pages.py',
           'src/tsbench/application/pcodec_pages.py','src/tsbench/qualification/pcodec_pages.py')
CAPACITY = 256
COUNTS = (513,260)
DTYPE, WIDTH = 6, 8  # native PC_F64
PARTS = {'meta':65536,'page-0':65536+COUNTS[0]*WIDTH,'page-1':65536+COUNTS[1]*WIDTH,'geometry.json':4096}
OPERATIONS = ('wrapped-encode','detached-page-1','detached-page-0','missing-meta','wrapped-diagnose')


def pcodec_page_inputs(root):
    from .batch_execution import BatchInput

    plan, originals = plan_pcodec(root)
    original, = [data for name,dtype,data in originals if name == TRAFFIC and dtype == 'f64']
    products, binds = {}, {}
    for route,bundle in plan['page'].items():
        method = ROUTES[(11,route)]
        require(bundle['dtype'] == DTYPE and bundle['capacity'] == CAPACITY and
                [p['count'] for p in bundle['pages']] == list(COUNTS) and identity(original) == bundle['input'],
                'pcodec wrapped input definition differs')
        cursor = 0
        for count,page in zip(COUNTS,bundle['pages'],strict=True):
            end = cursor+count*WIDTH
            require(identity(original[cursor:end]) == page['plain'] and page['spans'] == page_spans(count,CAPACITY),
                    'pcodec wrapped page slice differs')
            cursor = end
        require(cursor == len(original), 'pcodec wrapped original extent differs')
        body = {'method':method,'protocol':PROTOCOL,'name':'traffic-test-wrapped-pages','lineage':plan['window'],
                'original':bundle['input'],'page_originals':[p['plain'] for p in bundle['pages']],
                'parts':PARTS,'operations':list(OPERATIONS), 'read_capacity':CAPACITY,'counts':list(COUNTS),'native_dtype':DTYPE}
        slot = {**body,'product_slot':content_id(body)}
        products[slot['product_slot']] = slot,BatchInput(b'',(original,))
        cases = [c for c in plan['cases'] if c['route'] == route]
        require({c['check'] for c in cases} == set(PAGE_CHECKS[route]), 'pcodec wrapped obligation scope differs')
        for case in cases:
            binds[case['case_id']] = plan['bundle_id'], [slot['product_slot']]
    require(len(products) == len(METHODS) and len(binds) == sum(map(len,PAGE_CHECKS.values())), 'pcodec wrapped scope differs')
    return products, binds


def check_wrapped_slots(plan):
    """Require the exact methods, obligation keys and slot memberships at replay."""
    from ..qualification.pcodec_pages import check_slot

    wrapped = [s for s in plan['slots'] if s.get('protocol')==PROTOCOL]
    require(len(wrapped) == len(METHODS) and {s['method'] for s in wrapped} == METHODS.keys(), 'wrapped method coverage differs')
    for slot in wrapped:
        check_slot(slot)
    require(all(s['method'] in plan['methods'] for s in plan['slots'] if 'protocol' not in s), 'unknown framed method')
    ids = {s['method']:s['product_slot'] for s in wrapped}
    obligations, route_ids = {}, set()
    for key, method in ROUTES.items():
        rid, = [rid for rid,row in plan['route_contracts'].items() if (row['selection'],row['route']) == key]
        route_ids.add(rid)
        for check in PAGE_CHECKS[key[1]]:
            obligations[f'{key[0]}/{key[1]}/{check}'] = (rid,[ids[method]])
    actual = {key:(v['route_contract_id'],v['product_slots']) for key,v in plan['obligation_bindings'].items()
              if v['route_contract_id'] in route_ids or set(v['product_slots']) & set(ids.values()) or key in obligations}
    require(actual == obligations, 'wrapped obligation coverage or product membership differs')
