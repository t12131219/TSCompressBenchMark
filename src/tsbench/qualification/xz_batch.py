"""Independent header/Index oracle for the frozen legacy XZ profile."""
from ..assets import require
from .lzbench import _xz_index, xz_advertise_dictionary, xz_blocks

MAGIC = b'BMKXZ\0\1\0'


def inspect_xz(slot, payload):
    expected = slot['original']['column_bytes'][0]
    check, _ = _xz_index(payload)
    require(check == 0, 'XZ baseline frame does not use Check=None')
    blocks = xz_blocks(payload)
    require(len(blocks) == int(expected != 0) and (not blocks or
            (blocks[0]['raw'] == expected and blocks[0]['filters'] == [(0x21, bytes([22]))])),
            'XZ baseline Index length, block count or preset-6 LZMA2 property differs')
    return {'check':check, 'blocks':len(blocks), 'uncompressed_bytes':expected,
            'lzma2_dictionary_property':22 if blocks else None}


def reject_xz(slot, payload, pack):
    n = slot['original']['column_bytes'][0]
    result = {'wrong_output_count': pack(payload,count=(n-1 if n else 1)),
              'truncated_payload': pack(payload[:-1])}
    if 'oversize_dictionary' in slot['reject_decodes']:
        result['oversize_dictionary'] = pack(xz_advertise_dictionary(payload,33))
    return result


def verify_xz_info(layout, encode, decode):
    info = {'backend':'ln-xz-baseline','mode':'batch','threads':1,'fallback':False,
            'blocks':layout['blocks'],'check':'none'}
    require(encode == {**info,'operation':'encode','preset':6} and decode == {**info,'operation':'decode'} and
            type(encode['threads']) is type(decode['threads']) is int, 'XZ worker effective method differs')


def direct_observation(slot):
    n = slot['original']['column_bytes'][0]
    jobs = int(n != 0)
    return {'bytes':n, 'encode_jobs':jobs, 'background_workers':jobs, 'caller_jobs':0,
            'encode_short_capacity':2, 'decode_short_capacity':2 if n else None,
            'wrong_length':1 if n == 65536 else 4, 'truncated':4,
            'lzma_budget_error':6 if 'oversize_dictionary' in slot['reject_decodes'] else None}
