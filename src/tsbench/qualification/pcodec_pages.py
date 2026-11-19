"""Replay wrapped-page geometry and operation evidence without native code."""
from ..assets import canonical_bytes, content_id, require
from ..planner.pcodec import page_spans
from ..planner.pcodec_pages import CAPACITY, COUNTS, DTYPE, METHODS, OPERATIONS, PARTS, PROTOCOL, WIDTH


def is_wrapped(slot):
    return slot.get('protocol') == PROTOCOL


def _identity_shape(row, n):
    return (isinstance(row,dict) and set(row)=={'bytes','sha256'} and type(row['bytes']) is int and row['bytes']==n and
            isinstance(row['sha256'],str) and len(row['sha256'])==64 and all(c in '0123456789abcdef' for c in row['sha256']))


def check_slot(slot):
    body = {k:v for k,v in slot.items() if k!='product_slot'}
    require(slot['method'] in METHODS and is_wrapped(slot) and
            slot['product_slot'] == content_id(body) and canonical_bytes(slot['parts']) == canonical_bytes(PARTS) and
            slot['operations'] == list(OPERATIONS) and canonical_bytes(slot['counts']) == canonical_bytes(list(COUNTS)) and
            slot['read_capacity'] == CAPACITY and slot['native_dtype'] == DTYPE and
            _identity_shape(slot['original'],sum(COUNTS)*WIDTH) and len(slot['page_originals']) == 2 and
            all(_identity_shape(r,n*WIDTH) for r,n in zip(slot['page_originals'],COUNTS,strict=True)),
            'invalid wrapped page product definition')


def native_method(slot):
    return METHODS[slot['method']]['native_prefix'] == 'pcn'


def geometry(slot, parts):
    return {'dtype':slot['native_dtype'],'counts':slot['counts'],'capacity':slot['read_capacity'],
            'meta_bytes':parts['meta']['bytes'],'lengths':[parts[f'page-{i}']['bytes'] for i in range(2)]}


def read_geometry(slot, path, parts):
    expected = geometry(slot,parts)
    require(path.read_bytes() == canonical_bytes(expected), 'retained wrapped geometry differs')
    return expected


def expect_encode(slot, sizes, row):
    state = row.get('state')
    native = native_method(slot)
    require(isinstance(state,dict) and state.get('backend') == ('native-c11' if native else 'source-rust-repaired') and
            (not native or state.get('auto_policy') == 'NativeAuto') and
            all(type(state.get(k)) is int for k in ('mode','delta')), 'wrapped native encoder state differs')
    expected = {'counts':slot['counts'],'generation_order':[1,0],'dtype':slot['native_dtype'],'level':8,
                'requested_mode':-1,'requested_delta':-1,'meta_bytes':sizes['meta_bytes'],
                'page_bytes':sizes['lengths'],'state':state}
    require(canonical_bytes(row) == canonical_bytes(expected), 'wrapped native geometry or encoder options differ')
    return state


def expect_decode(slot, sizes, state, index, row):
    expected = {'index':index,'rows':slot['counts'][index],'meta_bytes':sizes['meta_bytes'],
                'page_bytes':sizes['lengths'][index],'spans':page_spans(slot['counts'][index],slot['read_capacity']),
                'finished':True,'state':state}
    require(canonical_bytes(row) == canonical_bytes(expected), 'wrapped detached decoder did not match geometry or drain terminal')
    return {**expected,'restored':slot['page_originals'][index],
            'native_input_bytes':sizes['meta_bytes']+sizes['lengths'][index]}


def expect_missing(slot, sizes, row):
    want = {'metadata_bytes':0,'available_page_bytes':sizes['lengths'][0],
            'status':1 if native_method(slot) else 3,'decoder_null':True}
    require(canonical_bytes(row)==canonical_bytes(want), 'detached page missing metadata did not reject')
    return want


def expect_diagnosis(slot, row):
    native = native_method(slot)
    want = {'first_page_small_quota':6,'early_next_page':1,'read_capacity_255':1,
            'after_first_with_second_quota':6 if native else 0,'trailing_at_drain':4,'read_after_error':1,
            'truncated_page':{'stage':'drain','status':3,'prefix_rows':256},'overwrote_caller_buffer':native}
    require(canonical_bytes(row)==canonical_bytes(want), 'wrapped page control or quota scope differs')
    return {**want,'session_restored':slot['page_originals'],
            'ownership_restored':slot['page_originals'][0] if native else None}
