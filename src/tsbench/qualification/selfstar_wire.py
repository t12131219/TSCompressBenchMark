"""Read BMKSEL envelopes and bounded, MSB-first SElf* native records."""
from ..assets import require
from ..planner.selfstar import BITLEN, BLOCK, DTYPE_ID, HEADER, MAGIC


def read_record(wire, at, count, width):
    require(at+BITLEN.size<=len(wire),'truncated SElf* bit length')
    bits, = BITLEN.unpack_from(wire,at)
    to = at + BITLEN.size + (bits+7)//8
    require(0<bits<=(count+1)*(width+28)+395 and to<=len(wire),'invalid SElf* native bit extent')
    payload = wire[at+BITLEN.size:to]
    require(bits%8 == 0 or not payload[-1]&((1<<(8-bits%8))-1),'nonzero SElf* native block padding')
    return to,(count,bits,payload)


def read_frame(wire, width, total, schema):
    at = HEADER.size+len(schema)
    require(width in DTYPE_ID and total>0 and len(wire)>=at and
            HEADER.unpack_from(wire)==(MAGIC,DTYPE_ID[width],total,len(schema),len(wire)-at) and
            wire[HEADER.size:at]==schema,'invalid SElf* envelope')
    records = []
    for off in range(0,total,BLOCK):
        at,record = read_record(wire,at,min(total-off,BLOCK),width)
        records.append(record)
    require(at==len(wire),'trailing SElf* payload')
    return records


def leading_bits(payload, n):
    """Mask low pad bits so a final block and an unfinished prefix can be compared."""
    require(0 < n <= 8*len(payload),'invalid SElf* prefix extent')
    end = (n+7)//8
    return payload[:end] if n%8==0 else payload[:end-1]+bytes([payload[end-1] & (0xff << (8-n%8))])
