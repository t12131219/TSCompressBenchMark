"""Bounded standalone-header oracle; complete entropy validation is native."""
from ..assets import canonical_bytes, require
from ..planner.pcodec import C_NATIVE, MAGIC, SOURCE, TYPES


def inspect_pcodec(slot, payload):
    col, = slot['original']['columns']
    t = next(native for abi,native,_ in TYPES.values() if abi == col['dtype'])
    count = col['count']
    require(10 <= len(payload) and payload[:5] == b'pco!\x03' and payload[5] in (0,t) and payload[-1] == 0 and
            t == slot['wire_checks']['native_type'], 'pcodec standalone prefix, type or footer marker differs')
    width = (payload[6] & 63) + 1
    end = 6 + (6 + width + 7) // 8
    require(end + 2 < len(payload), 'pcodec count header truncated')
    hint = int.from_bytes(payload[6:end],'little') >> 6
    require(width == max(1,count.bit_length()) and hint == count and payload[end:end+2] == b'\x04\x01',
            'pcodec standalone count or wrapped version differs')
    chunk = payload[end+2:]
    if count:
        require(len(chunk) >= 6 and chunk[0] == t and int.from_bytes(chunk[1:4],'little') + 1 == count,
                'pcodec first chunk type or count differs')
    else:
        require(chunk == b'\0', 'unexpected content in empty pcodec payload')
    return {'standalone_version':3,'wrapped_version':[4,1],'native_type':t,'count_hint':hint,
            'first_chunk_count':count if count else None}


def reject_pcodec(wire, slot, payload, pack):
    n = slot['original']['columns'][0]['count']
    other = C_NATIVE if slot['method'] == SOURCE else SOURCE
    bad = {'envelope_trailing':wire+b'\0','payload_trailing':pack(payload+b'\0'),
           'payload_truncated':pack(payload[:-1]),'missing_payload_metadata':pack(b''),
           'count_too_large':pack(payload,count=n+1),'other_format':MAGIC[other]+wire[8:]}
    if n:
        bad['count_too_small'] = pack(payload,count=n-1)
    return bad


def verify_pcodec_info(slot, encode, decode):
    source = slot['method'] == SOURCE
    common = {'mode':'batch','threads':1}
    require(canonical_bytes(encode) == canonical_bytes({**common, 'backend':'rust-source-auto' if source else 'c-native-auto',
        'entry':'pc_compress' if source else 'pc_compress_native','operation':'encode','selected_modes':None,'fallback':None}) and
        canonical_bytes(decode) == canonical_bytes({**common,'backend':'rust-source','entry':'pc_decompress_bounded','operation':'decode'}),
        'pcodec effective native entry differs')


def direct_observation(slot, payload_bytes):
    count = slot['original']['columns'][0]['count']
    t = slot['wire_checks']['native_type']
    if slot['expected_status']:
        require(slot['method'] == C_NATIVE and t == 9 and count > 0 and payload_bytes is None,
                'pcodec direct rejection supports only the frozen C f16 input')
        return {'native_type':t,'rows':count,'entry':'pc_compress_native','status':5,'output_bytes':0,'output_pointer_null':True}
    require(payload_bytes is not None, 'pcodec direct control requires a payload')
    return {'native_type':t,'rows':count,'payload_bytes':payload_bytes,
            'direct_encode':'pcs_compress' if slot['method'] == SOURCE else 'pc_compress_native',
            'direct_decode':'pcs_decompress','native_output_count_limit_status':6 if count else None}
