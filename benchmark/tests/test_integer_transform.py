"""Original-domain recovery, overflow rejection and self-contained wire metadata."""
import numpy as np
import pytest

from tsbench.artifact import EncodedObject, pack_bundle, read_bundle_prefix
from tsbench.data import TimeSeriesObject
from tsbench.errors import Unsupported
from tsbench.schemes import ObjectScheme, decode_once
from tsbench.transforms import forward, inverse


@pytest.mark.parametrize('values', [[], [17, 17], [0, 60_000_000_000, 60_000_000_000, 180_000_000_000],
                                  [-(2**63), 2**63-1]])
def test_integer_normalization_restores_exact_original_domain(values):
    original = np.array(values, dtype='<i8')
    obj = TimeSeriesObject({'T': original}, {'roles': {'T': 'T'}})
    artifact = ObjectScheme({'codec': 'raw-store', 'transform': 'integer_affine_gcd'}).encode_once(obj)
    recovered = decode_once(artifact)
    assert recovered.components['T'].tobytes() == original.tobytes()
    assert artifact.descriptor['transform_id'] != 'identity'
    descriptor = artifact.descriptor['components'][0]['parts'][0]['transform']
    assert descriptor['scale'] >= 1
    if values == [-(2**63), 2**63-1]:
        assert descriptor['scale'] == 2**64-1


def test_full_integer_spread_with_gcd_one_is_explicitly_rejected():
    values = np.array([-(2**63), -(2**63)+1, 2**63-1], dtype='<i8')
    with pytest.raises(Unsupported, match='exceed'):
        forward(values, 'integer_affine_gcd')
    with pytest.raises(Unsupported, match='integer component'):
        forward(values.astype('<f8'), 'integer_affine_gcd')


def test_inverse_rejects_overflow_and_untrusted_transform_metadata():
    q = np.array([2], dtype='<i8')
    good = {'kind': 'integer_affine_gcd', 'version': 1, 'bias': 0, 'scale': 1}
    for changes in ({'scale': 2**63}, {'bias': True}, {'version': 2}, {'scale': 0}):
        with pytest.raises(ValueError):
            inverse(q, {**good, **changes})
    obj = TimeSeriesObject({'T': np.array([0, 2], dtype='<i8')}, {'roles': {'T': 'T'}})
    artifact = ObjectScheme({'codec': 'raw-store', 'transform': 'integer_affine_gcd'}).encode_once(obj)
    descriptor, body = read_bundle_prefix(artifact.wire)
    descriptor['components'][0]['parts'][0]['transform']['bias'] = 2**63-1
    with pytest.raises(ValueError, match='overflows'):
        decode_once(EncodedObject(pack_bundle(descriptor, body)))
