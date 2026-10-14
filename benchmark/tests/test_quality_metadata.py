"""Native settings come from checked frame bytes, with exact part provenance."""
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
import pytest

from tsbench.artifact import pack_bundle
from tsbench.quality_metadata import extract, zfp_frame_quality


def checksum(data):
    # Test fixture writer implements the native checksum independently.
    value = 1469598103934665603
    for byte in data:
        value ^= byte
        value *= 1099511628211
        value %= 2 ** 64
    return value


def frame(*, requested=0.1, effective=0.0625, count=2, logical_count=2, trailing=b''):
    values = struct.pack('<dd', 1., 2.)
    data = struct.pack('<4sBBBBHQddI', b'ZFA1', 1, 8, 4, 7, 1, count, requested, effective, 1)
    data += struct.pack('<BBHIQ', 1, 0, 0, logical_count, len(values)) + values + trailing
    return data + struct.pack('<Q', checksum(data))


def part(payload):
    return {'codec': 'zfp-accuracy-1d', 'params': {'error_bound': '0.1'},
            'dtype': '<f8', 'shape': [2], 'order': 'C', 'row_start': 0, 'row_stop': 2,
            'offset': 0, 'length': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}


def bundle(payload, entry=None):
    descriptor = {'schema_version': 'tsbench.object/1', 'schema': {'roles': {'V': 'V'}},
                  'components': [{'name': 'V', 'dtype': '<f8', 'shape': [2], 'order': 'C',
                                  'parts': [entry or part(payload)]}]}
    return pack_bundle(descriptor, payload)


def test_checked_native_settings_keep_requested_effective_and_raw_mode_distinct():
    payload = frame()
    wire = bundle(payload)
    metadata = extract(wire)
    actual = metadata['parts'][0]
    assert actual['codec_requested_absolute_tolerance'] == 0.1
    assert actual['codec_effective_absolute_tolerance'] == 0.0625
    assert actual['codec_requested_absolute_tolerance_hex'] == float(0.1).hex()
    assert actual['codec_effective_absolute_tolerance_hex'] == float(0.0625).hex()
    assert actual['payload_sha256'] == hashlib.sha256(payload).hexdigest()
    assert actual['columns'][0]['mode'] == 'raw_exception'
    assert metadata['artifact_sha256'] == hashlib.sha256(wire).hexdigest()
    json.dumps(metadata, allow_nan=False)


@pytest.mark.parametrize('payload, reason', [
    (frame()[:-1], 'checksum'),
    (frame(effective=0.2), 'header'),
    (frame(logical_count=1), 'column record'),
    (frame(trailing=b'x'), 'trailing'),
    (frame(requested=0.2), 'configured parameter'),
])
def test_outer_checksum_does_not_make_bad_native_metadata_valid(payload, reason):
    # Repack a correct outer envelope; the native defect must still be rejected.
    with pytest.raises(ValueError, match=reason):
        extract(bundle(payload))


def test_native_quality_shape_is_checked_against_actual_part():
    payload = frame()
    entry = part(payload)
    entry['shape'] = [1, 2]
    with pytest.raises(ValueError, match='shape/dtype'):
        zfp_frame_quality(payload, entry)


def test_real_zfp_frame_exposes_library_effective_tolerance_after_completed_decode():
    from tsbench.build import artifact_path
    from tsbench.data import TimeSeriesObject
    from tsbench.executors.cpu import measure_object
    from tsbench.schemes import ObjectScheme

    root = Path(__file__).resolve().parents[2]
    if not artifact_path(root, 'zfp-accuracy-1d').is_file():
        pytest.skip('real zfp build is required; test never compiles it')
    values = np.array([[1., -0.], [2., 3.], [4., 5.], [6., 7.], [8., 9.]])
    obj = TimeSeriesObject({'V': values}, {'roles': {'V': 'V'}})
    scheme = ObjectScheme({'codec': 'zfp-accuracy-1d', 'params': {'error_bound': '0.1'}}, asset_root=root)
    scheme.prepare(obj)
    row, wire = measure_object(scheme, obj, {'fidelity': 'bounded_abs', 'error_bound': '0.1'}, asset_root=root)
    assert row['status'] == 'ok' and row['verification']['task_absolute_bound'] == 0.1
    settings = row['codec_quality_metadata']['parts'][0]
    assert settings['codec_requested_absolute_tolerance'] == 0.1
    assert settings['codec_effective_absolute_tolerance'] == 0.0625
    assert [column['mode'] for column in settings['columns']] == ['zfp_fixed_accuracy', 'raw_exception']
    assert row['codec_quality_metadata']['artifact_sha256'] == hashlib.sha256(wire).hexdigest()
