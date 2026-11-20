"""The diagnostic parser cannot mislabel wide grids as legacy frames."""
from ctypes import CDLL, c_bool, c_double
from fractions import Fraction
from math import inf, isfinite, nextafter
from pathlib import Path
from random import Random
from shutil import which
from struct import pack, unpack
import subprocess
import sys
from zlib import crc32

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from m3_pbepla_wide_grid import HEADER, frame
from tsbench.assets import ContractError


def wire(version, resolution):
    # Framing-only: the real native pilot also verifies bitstream restoration.
    payload = b'\xa5'
    head = HEADER.pack(b'PBEP',version,1,3,1,1,64,0,32.0*2.0**resolution)
    head += pack('<dddBBBQI',16.0,4.0,1.0,resolution,3,3,8,crc32(payload))
    return head + pack('<I',crc32(head)) + payload


@pytest.mark.parametrize(('version','resolution'), ((1,30),(2,31),(2,52)))
def test_wire_versions_preserve_precision_boundary(version,resolution):
    fields, payload = frame(wire(version,resolution),1,1)
    assert (fields['version'],fields['resolutions'][0],payload)==(version,resolution,b'\xa5')


@pytest.mark.parametrize(('version','resolution'), ((1,31),(2,30),(2,53),(3,31)))
def test_wrong_version_or_grid_cap_is_rejected_even_with_valid_crc(version,resolution):
    with pytest.raises(ContractError,match='version or grid limit'):
        frame(wire(version,resolution),1,1)


def test_payload_corruption_is_not_a_quality_result():
    data = wire(2,40)
    with pytest.raises(ContractError,match='payload length or CRC'):
        frame(data[:-1]+b'\xa4',1,1)


def test_native_exact_error_comparison_against_rational_oracle(tmp_path):
    compiler = which('c++')
    if compiler is None:
        pytest.skip('a C++ compiler is required to exercise the candidate kernel')
    patch = ROOT/'third_party/patches/pbepla-rr-wide-grid-exact-bound.candidate.patch'
    revised = '\n'.join(l[1:] for l in patch.read_text().splitlines() if l.startswith(('+',' ')) and not l.startswith('+++'))
    function = revised[revised.index('bool within_exact_error('):]
    function = function[:function.index('\n}')+2]
    source = tmp_path/'candidate.cpp'
    library = tmp_path/'candidate.so'
    source.write_text('#include <cmath>\n#include <algorithm>\nextern "C" '+function+'\n')
    subprocess.run([compiler,'-std=c++17','-O3','-fno-fast-math','-ffp-contract=off','-shared','-fPIC',
                    str(source),'-o',str(library)],check=True)
    compare = CDLL(str(library)).within_exact_error
    compare.argtypes, compare.restype = [c_double]*3, c_bool
    tiny, highest = float.fromhex('0x0.0000000000001p-1022'), sys.float_info.max
    pairs = [(16., -2.0**-50),(16., 2.0**-50),(-16., 2.0**-50),(-16., -2.0**-50),
             (16.,0.), (0.,tiny), (tiny,-tiny), (highest,-tiny), (highest,tiny), (highest,-highest)]
    rng = Random(8701)
    for _ in range(4000):
        x,y = unpack('<dd',pack('<QQ',rng.getrandbits(64),rng.getrandbits(64)))
        if isfinite(x) and isfinite(y):
            pairs.append((x,y))
    for x,y in pairs:
        rounded = abs(x-y)
        exact = abs(Fraction(x)-Fraction(y))
        for bound in {rounded,nextafter(rounded,inf),nextafter(rounded,0.0)}:
            if isfinite(bound) and bound>0:
                assert compare(x,y,bound) is (exact<=Fraction(bound)), (x,y,bound)
