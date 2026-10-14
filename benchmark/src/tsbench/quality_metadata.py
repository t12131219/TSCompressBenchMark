"""Read native quality settings from checked artifacts, outside timing clocks."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import struct

from .artifact import read_bundle_prefix, validate_descriptor
from .records import file_hash


ZFP_HEADER = struct.Struct('<4sBBBBHQddI')
ZFP_RECORD = struct.Struct('<BBHIQ')
MAX_ZFP_ELEMENTS = 16_777_216


def _zfp_checksum(data):
    # Exact uint64 algorithm in adapters/zfp/native/tscb_zfp.c:checksum64.
    checksum = 1_469_598_103_934_665_603
    for byte in data:
        checksum = ((checksum ^ byte) * 1_099_511_628_211) & 0xffffffffffffffff
    return checksum


def zfp_frame_quality(payload, part):
    """Check frame/checksum/record geometry; native decode checks zfp streams."""
    if len(payload) < ZFP_HEADER.size + 8:
        raise ValueError('truncated zfp quality frame')
    if _zfp_checksum(payload[:-8]) != struct.unpack_from('<Q', payload, len(payload) - 8)[0]:
        raise ValueError('zfp quality frame checksum mismatch')
    magic, version, width, mode, policy, columns, rows, requested, effective, records = ZFP_HEADER.unpack_from(payload)
    if (magic != b'ZFA1' or version != 1 or width not in (4, 8) or mode != 4 or policy != 7
            or not columns or records != columns or rows > MAX_ZFP_ELEMENTS
            or rows * columns > MAX_ZFP_ELEMENTS or not math.isfinite(requested)
            or requested <= 0 or not math.isfinite(effective) or not 0 < effective <= requested):
        raise ValueError('invalid zfp quality frame header')
    shape = part['shape']
    expected_columns = shape[1] if len(shape) == 2 else 1
    if (part['dtype'] != ('<f4' if width == 4 else '<f8') or len(shape) not in (1, 2)
            or rows != shape[0] or columns != expected_columns):
        raise ValueError('zfp quality frame shape/dtype differs from object descriptor')
    configured = float(part['params']['error_bound'])
    if struct.pack('<d', requested) != struct.pack('<d', configured):
        raise ValueError('zfp quality frame requested tolerance differs from configured parameter')
    offset = ZFP_HEADER.size
    column_modes = []
    end = len(payload) - 8
    for column in range(columns):
        if offset + ZFP_RECORD.size > end:
            raise ValueError('truncated zfp quality column record')
        kind, reserved, header_bits, count, size = ZFP_RECORD.unpack_from(payload, offset)
        record_offset = offset
        offset += ZFP_RECORD.size
        if (reserved != 0 or count != rows or offset + size > end
                or kind not in (0, 1)
                or kind == 1 and (header_bits != 0 or size != rows * width)
                or kind == 0 and (rows == 0 or header_bits == 0 or size == 0)):
            raise ValueError('invalid zfp quality column record')
        column_modes.append({'column': column, 'mode': 'raw_exception' if kind == 1 else 'zfp_fixed_accuracy',
                             'logical_count': count, 'record_offset': record_offset,
                             'payload_offset': offset, 'payload_bytes': size, 'zfp_header_bits': header_bits})
        offset += size
    if offset != end:
        raise ValueError('zfp quality frame has unclaimed trailing bytes')
    return {'native_format': 'TSCB_ZFP_FIXED_ACCURACY_1D_CONTAINER_V1',
            'codec_requested_absolute_tolerance': requested,
            'codec_requested_absolute_tolerance_hex': requested.hex(),
            'codec_effective_absolute_tolerance': effective,
            'codec_effective_absolute_tolerance_hex': effective.hex(),
            'configured_error_bound': str(part['params']['error_bound']),
            'tolerance_scope': 'native zfp fixed-accuracy stream parameter; raw exception columns retain exact bits',
            'native_checksum': 'uint64 checksum64 validated', 'columns': column_modes}


def extract(wire):
    descriptor, body = read_bundle_prefix(wire)
    components = validate_descriptor(descriptor, body)
    parts = []
    for component in components:
        for index, part in enumerate(component['parts']):
            if part['codec'] != 'zfp-accuracy-1d':
                continue
            payload = body[part['offset']:part['offset'] + part['length']]
            settings = zfp_frame_quality(payload, part)
            parts.append({'component': component['name'], 'part_index': index,
                          'row_start': part['row_start'], 'row_stop': part['row_stop'],
                          'channel': part.get('channel'), 'payload_body_offset': part['offset'],
                          'payload_bytes': len(payload),
                          'payload_sha256': hashlib.sha256(payload).hexdigest(),
                          **settings})
    return {'schema': 'tsbench.codec-quality-metadata/1', 'parser_sha256': file_hash(Path(__file__)),
            'artifact_sha256': hashlib.sha256(wire).hexdigest(), 'parts': parts,
            'scope': 'native settings read from checked wire after completed decode; task target and actual error remain in verification'}
