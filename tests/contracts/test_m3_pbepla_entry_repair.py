"""The explicit wide-grid route accepts only canonical, nested PBEP prefixes."""
from struct import pack
from zlib import crc32

import pytest

from tsbench.application.m3_pbepla_repair import assess
from tsbench.assets import ContractError
from tsbench.qualification.pbep_wide import EPS, HEADER, parse_prefix


def make(layer, *, version=2, width=32, payload=None):
    # Span / (2 * eps[0]) is 2**32. The residual grids need 3 bits each.
    body = b'abc'[:layer] if payload is None else payload
    h = (HEADER.pack(b'PBEP',version,1,3,layer,1,64,0,32*2**32) + pack('<3d',*EPS) + bytes([width,3,3]) +
         pack(f'<{layer}Q',*[8]*layer) + pack('<I',crc32(body)))
    return h + pack('<I',crc32(h)) + body


def test_wide_grid_has_canonical_version_and_rejects_crc_or_resolution_changes():
    prefix = make(2)
    meta,bits,sizes,payload = parse_prefix(prefix,1,2)
    assert meta == (2,0,32*2**32,EPS,(32,3,3)) and bits == (8,8) and sizes == (1,1) and payload == b'ab'
    for broken in (make(2,version=1),make(2,width=53),make(2,width=33),prefix[:-1]+b'!'):
        with pytest.raises(ContractError):
            parse_prefix(broken,1,2)


def test_wide_grid_still_requires_nested_prefixes_and_original_domain_quality():
    raw = pack('<d',1.0)
    frames = [make(k) for k in (1,2,3)]
    row = {'rows':1,'native_full_bytes':len(frames[-1]),'replay':None}
    proof = assess(raw,frames,[raw]*3,row,False)
    assert proof['quality_passed'] and all(x['pbep_version']==2 for x in proof['layers'])
    assert not assess(raw,frames,[raw,raw,pack('<d',3)],row,False)['quality_passed']
    with pytest.raises(ContractError,match='nested'):
        assess(raw,[make(1,payload=b'!'),*frames[1:]],[raw]*3,row,False)
