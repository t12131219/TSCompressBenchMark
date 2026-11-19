"""Recompute session evidence from the complete span transcript and raw streams."""
from ..assets import canonical_bytes, require
from ..planner.lzbench import byte_identity
from ..planner.lzbench_session import BUDGET_FRAME, PARTS
from .lzbench import _xz_restore, verify_spans, xz_blocks, zstd_frame

COMMON_GUARDS = {'unknown':'unsupported parameter: tsbench_invalid',
    'overlap':'stream spans/capacity/overlap','zero-capacity':'stream spans/capacity/overlap',
    'batch-encode':'use process for native stream/frame','batch-decode':'use process for stream/frame',
    'after-finish':'reset required after stream end','truncated':'truncated stream','after-failure':'reset required after failure'}
XZ_GUARDS = {'dictionary':'backend has no external dictionary in selected format','filter':'XZ BCJ filter id',
             'encode-budget':'XZ encoder memory/configuration limit','decode-budget':'XZ code: 6'}


def match(actual,expected,message):
    require(canonical_bytes(actual)==canonical_bytes(expected),message)


def _span(slot,calls,length,output,incap,outcap):
    require(isinstance(calls,list) and len(calls)<=slot['call_limit'],'lzbench session transcript exceeds call limit')
    first,finish,drain = verify_spans(calls,length,output,incap,outcap)
    return {'calls':len(calls),'first_output_call':first,'finish_calls':finish,'zero_input_finish_output':drain,
            'input_bytes':length,'output_bytes':output}


def verify_restore(slot,key,wire,calls):
    return _span(slot,calls,len(wire),slot['inputs'][key]['bytes'],*slot['restore_spans'])


def verify_exercise(slot,wires,evidence):
    xz = slot['method']=='xz-session'
    require(isinstance(evidence,dict) and set(evidence)=={'level','parameters','guards','calls'},'lzbench session report shape differs')
    match({k:evidence[k] for k in ('level','parameters')},{k:slot[k] for k in ('level','parameters')},'lzbench session config differs')
    guards = {**COMMON_GUARDS,**(XZ_GUARDS if xz else {'pledged-size':'pledged size'})}
    match(evidence['guards'],guards,'lzbench session rejection census differs')
    if xz:
        require(byte_identity(BUDGET_FRAME)==slot['budget_frame'] and
                xz_blocks(BUDGET_FRAME)[0]['filters']==[(0x21,b'\x21')], 'XZ decoder budget fixture differs')
    layout = {}
    for k in PARTS:
        wire = wires[k]
        raw = slot['inputs'][k]['bytes']
        require(0<len(wire)<=slot['parts'][k],'lzbench session stream outside retained bound')
        if xz:
            blocks = xz_blocks(wire)
            block = slot['parameters']['block_size']
            require(wire[7]==slot['parameters']['check'] and [b['raw'] for b in blocks]==[min(block,raw-at) for at in range(0,raw,block)]
                    and all(b['filters']==[(3,b'\x03'),(0x21,bytes([slot['dictionary_property']]))] for b in blocks),
                    'XZ session CRC64, Delta or LZMA2 block layout differs')
            _xz_restore(wire,slot['inputs'][k],slot['parameters']['check'],slot['parameters']['memory_limit'])
            layout[k] = {'check':'crc64','raw_block_bytes':[b['raw'] for b in blocks],
                         'delta_distance':4,'lzma2_dictionary_property':slot['dictionary_property']}
        else:
            flags = zstd_frame(wire)
            require(flags['checksum'] and not flags['dictionary_id'] and flags['content_size'] in (None,raw) and
                    0 < flags['window'] <= 1<<20,
                    'Zstd session frame flags differ')
            layout[k] = flags
    spans = {}
    calls = evidence['calls']
    require(isinstance(calls,dict) and calls.keys()==slot['span_limits'].keys(),'lzbench session spans incomplete')
    for label,(key,incap,outcap) in slot['span_limits'].items():
        raw,frame = slot['inputs'][key]['bytes'],len(wires[key])
        length,output = (raw,frame) if label.startswith('encode-') else (frame,raw)
        spans[label] = _span(slot,calls[label],length,output,incap,outcap)
    finish = spans['encode-first']
    require(finish['finish_calls']>1 and finish['zero_input_finish_output'],'lzbench session did not exercise finish drain')
    return {'layout':layout,'spans':spans,'guards':guards}
