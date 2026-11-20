"""Independent wire checks for the opt-in native PBEP v1/v2 wide-grid profile."""
from math import isfinite, ldexp
from struct import Struct, unpack_from
from zlib import crc32

from ..assets import require

EPS = (16, 4, 1)
LAYERS = (1, 2, 3)
HEADER = Struct('<4sBBBBQIdd')
CAP = 131072


def parse_prefix(wire, rows, layer):
    require(layer in LAYERS and 0 < rows <= 4096, 'PBEP prefix input exceeds the frozen corpus domain')
    header_bytes = HEADER.size + 9 * len(EPS) + 8 * layer + 8
    require(header_bytes <= len(wire) <= CAP, 'PBEP prefix extent differs')
    magic, version, flags, declared, stored, count, delay, lo, hi = HEADER.unpack_from(wire)
    require((magic, flags, declared, stored, count, delay) == (b'PBEP', 1, 3, layer, rows, 64) and
            isfinite(lo) and isfinite(hi) and isfinite(hi-lo) and lo < hi, 'PBEP prefix geometry differs')
    eps = unpack_from('<3d', wire, HEADER.size)
    require(all(isfinite(e) and 0 < e <= r for e,r in zip(eps,EPS,strict=True)) and eps[0] > eps[1] > eps[2],
            'PBEP effective error exceeds the frozen request')
    offset = HEADER.size + 8 * declared
    resolutions = tuple(wire[offset:offset+declared])
    maximum = max(resolutions)
    require(maximum <= 52 and version == (1 if maximum <= 30 else 2), 'PBEP version or grid limit differs')
    spans = hi-lo, 2*eps[0]+2*eps[1], 2*eps[1]+2*eps[2]
    require(all(0 < ldexp(s,-r) <= 2*e and (r == 0 or ldexp(s,1-r) > 2*e)
                for s,r,e in zip(spans,resolutions,eps,strict=True)), 'PBEP did not use the minimum fitting resolution')
    bits = unpack_from(f'<{stored}Q', wire, offset+declared)
    body = wire[header_bytes:]
    sizes = tuple((n+7)//8 for n in bits)
    require(all(bits) and sum(sizes)==len(body) and (crc32(body),crc32(wire[:header_bytes-4]))==
            unpack_from('<II',wire,header_bytes-8), 'PBEP prefix lengths or CRC differ')
    return (version,lo,hi,eps,resolutions), bits, sizes, body
