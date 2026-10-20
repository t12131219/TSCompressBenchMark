"""Read native quality settings from checked artifacts, outside timing clocks."""
from __future__ import annotations

import hashlib
import ctypes
import math
from pathlib import Path
import struct

from .artifact import read_bundle_prefix, validate_descriptor
from .records import file_hash


ZFP_HEADER = struct.Struct('<4sBBBBHQddI')
ZFP_RECORD = struct.Struct('<BBHIQ')
MAX_ZFP_ELEMENTS = 16_777_216


def zfp_core_quality(payload, part, library_path):
    """Read the effective accuracy from the actual native ZFP full header.

    The same pinned ZFP library parses its native header, outside all benchmark
    clocks. No encoder context or task bound supplies the effective value.
    Successful native decode has already checked complete stream consumption.
    """
    if len(payload) < 12 or payload[:3] != b'zfp':
        raise ValueError('truncated or invalid native ZFP full header')
    lib = ctypes.CDLL(str(library_path))
    pointer = ctypes.c_void_p
    specifications = {
        'stream_open': ([pointer, ctypes.c_size_t], pointer),
        'stream_close': ([pointer], None),
        'zfp_stream_open': ([pointer], pointer),
        'zfp_stream_close': ([pointer], None),
        'zfp_field_alloc': ([], pointer),
        'zfp_field_free': ([pointer], None),
        'zfp_read_header': ([pointer, pointer, ctypes.c_uint], ctypes.c_size_t),
        'zfp_stream_compression_mode': ([pointer], ctypes.c_int),
        'zfp_stream_accuracy': ([pointer], ctypes.c_double),
        'zfp_field_type': ([pointer], ctypes.c_int),
        'zfp_field_dimensionality': ([pointer], ctypes.c_uint),
        'zfp_field_size': ([pointer, ctypes.POINTER(ctypes.c_size_t)], ctypes.c_size_t),
    }
    for name, (arguments, result) in specifications.items():
        function = getattr(lib, name)
        function.argtypes, function.restype = arguments, result
    # ZFP reads whole words. Padding supplies safe storage only, never data
    # claimed in the compressed stream or in the raw byte denominator.
    storage = ctypes.create_string_buffer(payload, len(payload) + 16)
    bits = stream = field = None
    try:
        bits = lib.stream_open(storage, len(storage))
        stream = lib.zfp_stream_open(bits) if bits else None
        field = lib.zfp_field_alloc()
        if not bits or not stream or not field:
            raise ValueError('native ZFP quality header parser allocation failed')
        header_bits = lib.zfp_read_header(stream, field, 7)  # ZFP_HEADER_FULL
        if not header_bits or header_bits > len(payload) * 8:
            raise ValueError('invalid native ZFP full header')
        sizes = (ctypes.c_size_t * 4)()
        count = lib.zfp_field_size(field, sizes)
        dtype = {3: '<f4', 4: '<f8'}.get(lib.zfp_field_type(field))
        if (dtype != part['dtype'] or lib.zfp_field_dimensionality(field) != 1
                or count != math.prod(part['shape']) or not 0 < count <= MAX_ZFP_ELEMENTS
                or lib.zfp_stream_compression_mode(stream) != 4):
            raise ValueError('native ZFP header mode or physical stream geometry differs from task')
        effective = lib.zfp_stream_accuracy(stream)
        requested = float(part['params']['error_bound'])
        if (not math.isfinite(effective) or not math.isfinite(requested)
                or not 0 < effective <= requested):
            raise ValueError('native ZFP effective accuracy exceeds configured request')
        return {'native_format': 'ZFP_HEADER_FULL',
                'codec_requested_absolute_tolerance': requested,
                'codec_requested_absolute_tolerance_hex': requested.hex(),
                'codec_request_source': 'resolved encoder configuration; not stored in native header',
                'codec_effective_absolute_tolerance': effective,
                'codec_effective_absolute_tolerance_hex': effective.hex(),
                'codec_effective_tolerance_source': 'zfp_read_header + zfp_stream_accuracy',
                'configured_error_bound': str(part['params']['error_bound']),
                'tolerance_scope': 'native ZFP fixed-accuracy parameter recovered from complete output',
                'zfp_header_bits': header_bits, 'physical_stream_count': count,
                'physical_stream_dtype': dtype, 'input_geometry': 'physical-contiguous-stream'}
    finally:
        if field:
            lib.zfp_field_free(field)
        if stream:
            lib.zfp_stream_close(stream)
        if bits:
            lib.stream_close(bits)


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
            if part['codec'] not in {'zfp-accuracy-1d','pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized'}:
                continue
            payload = body[part['offset']:part['offset'] + part['length']]
            settings = zfp_frame_quality(payload, part) if part['codec'] == 'zfp-accuracy-1d' else chimp_frame_quality(payload, part)
            parts.append({'component': component['name'], 'part_index': index,
                          'row_start': part['row_start'], 'row_stop': part['row_stop'],
                          'channel': part.get('channel'), 'payload_body_offset': part['offset'],
                          'payload_bytes': len(payload),
                          'payload_sha256': hashlib.sha256(payload).hexdigest(),
                          **settings})
    return {'schema': 'tsbench.codec-quality-metadata/1', 'parser_sha256': file_hash(Path(__file__)),
            'artifact_sha256': hashlib.sha256(wire).hexdigest(), 'parts': parts,
            'scope': 'native settings read from checked wire after completed decode; task target and actual error remain in verification'}


def chimp_frame_quality(payload, part):
    """Recover source f32 epsilon from complete CFP1 / CFS1 outputs, after decode.

    This is the configured source threshold, never a claim of a universal bound.
    quality_mode belongs to the encoder request and is not stored in CFP1.
    """
    import zlib
    method_ids = {'pmc-mr': 7, 'swing-filter': 8, 'swing-filter-disjoint': 9,
                  'swing-filter-disjoint-quantized': 10}
    method = method_ids[part['codec']]
    shape = part['shape']
    frames = []
    if payload[:4] == b'CFS1':
        if len(payload) < 16:
            raise ValueError('truncated CFS1 quality container')
        width, mid, columns, rows = struct.unpack_from('<BBHQ', payload, 4)
        if (width != 4 or mid != method or columns != (shape[1] if len(shape) == 2 else 1)
                or rows != shape[0]):
            raise ValueError('CFS1 quality geometry mismatch')
        at = 16
        for _ in range(columns):
            if len(payload) - at < 8:
                raise ValueError('truncated CFS1 column')
            size, = struct.unpack_from('<Q', payload, at); at += 8
            if size > len(payload) - at:
                raise ValueError('truncated CFS1 frame')
            frames.append((payload[at:at + size], rows)); at += size
        if at != len(payload):
            raise ValueError('trailing CFS1 quality bytes')
    else:
        frames = [(payload, math.prod(shape))]
    epsilons = []
    for frame, count in frames:
        if (len(frame) < 36 or frame[:4] != b'CFP1' or frame[4:8] != bytes([1, method, 0, 0])
                or struct.unpack_from('<Q', frame, 16)[0] != count
                or struct.unpack_from('<Q', frame, 24)[0] != len(frame) - 36
                or zlib.crc32(frame[:-4]) != struct.unpack_from('<I', frame, len(frame) - 4)[0]):
            raise ValueError('invalid CFP1 quality frame')
        eps, = struct.unpack_from('<f', frame, 12)
        configured = float(part['params']['epsilon'])
        if (not math.isfinite(eps) or eps < 0
                or struct.pack('<f', configured) != frame[12:16]):
            raise ValueError('CFP1 source epsilon differs from encoder configuration')
        epsilons.append(eps)
    return {'native_format': 'CFP1' if payload[:4] == b'CFP1' else 'CFS1/CFP1',
            'codec_configured_epsilon': epsilons[0],
            'codec_configured_epsilon_hex': epsilons[0].hex(),
            'codec_epsilon_source': 'CFP1 header f32LE, CRC validated',
            'codec_requested_epsilon': str(part['params']['epsilon']),
            'encoder_quality_mode': part['params']['quality_mode'],
            'quality_mode_source': 'encoder configuration; not encoded in CFP1',
            'tolerance_scope': 'source filter threshold; strict_abs checks actual input reconstruction and rejects failures; compatible has no guarantee',
            'input_grid': 'implicit unit indices per column', 'columns': len(frames)}
