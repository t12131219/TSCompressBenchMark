import os
from pathlib import Path
import random
import struct

import pytest

from tsbench.application.m3_pbepla import _quality_layers, quality, run_group
from tsbench.qualification.pbepla_progressive import quality as full_oracle


def test_fast_prefix_error_preserves_exact_maximum_in_rounding_ties_and_overflow():
    def pack(values):
        return struct.pack(f'<{len(values)}d', *values)
    top = float.fromhex('0x1.fffffffffffffp1023')
    subnormal = float.fromhex('0x0.0000000000001p-1022')
    pairs = [([1.0,1.0], [-2**-55,-2**-54]), ([top,top], [-top,-top/2]),
             ([subnormal,-0.0], [0.0,0.0])]
    rnd = random.Random(3261)
    pairs.append(([rnd.random()*2**rnd.randint(-1020,1020) for _ in range(4096)],
                  [rnd.random()*2**rnd.randint(-1020,1020) for _ in range(4096)]))
    for a,b in pairs:
        src, dst = pack(a),pack(b)
        assert quality(src,dst) == full_oracle(src,dst)


@pytest.fixture
def control():
    path = os.environ.get('TSBENCH_PBEPLA_CORPUS_CONTROL')
    if not path:
        pytest.skip('set TSBENCH_PBEPLA_CORPUS_CONTROL to the built real-corpus control')
    return Path(path).resolve(strict=True)


def test_real_prefixes_callback_accounting_and_independent_nonpass(control, tmp_path):
    singleton = struct.pack('<d',1.5)
    bad = struct.pack('<d', float('nan'))
    raw = struct.pack('<137d',*(i/10 for i in range(137)))
    expected = [singleton,bad,raw]
    a = list(run_group(control,tmp_path,expected,False))
    b = list(run_group(control,tmp_path,expected,True))
    assert [row[0]['status'] for row in a] == [row[0]['status'] for row in b] == ['verified','failed','verified']
    assert a[1][1] is b[1][1] is None
    for i in [0,2]:
        prog, frames = a[i]
        replay, same = b[i]
        n = len(expected[i])//8
        assert len(frames) == 3 and frames == same and prog['layers'] == replay['layers']
        assert replay['replay']['source_bytes_read'] == 3*8*n and replay['replay']['temp_seeks'] == 9
        assert all(p['quality_passed'] for p in prog['layers'])
        intentionally_bad_restore = struct.pack(f'<{n}d', *[100_000.0]*n)
        nonpass = _quality_layers(expected[i], frames, [intentionally_bad_restore]*3,
                                  {'rows': n,'native_full_bytes': len(frames[-1]),'replay': None}, False)
        assert not nonpass['quality_passed'] and all(not x['quality_passed'] for x in nonpass['layers'])
