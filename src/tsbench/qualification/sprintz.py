"""Verify sealed Sprintz development evidence without a native build or dataset."""
import struct
from zlib import crc32

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..planner.sprintz import plain, ref, retained_paths

GROUP_HEADER = struct.Struct('<8sIQIQ')


def inspect_u16_group(payload, rows, dims, schema, expected_crc):
    head = GROUP_HEADER.size
    require(len(payload)>=head, 'truncated grouped V envelope')
    marker, dtype, count, scope, length = GROUP_HEADER.unpack_from(payload)
    start = head+scope
    require((marker,dtype,count,scope)==(b'BMKSPG\x01\x00',4,rows*dims,len(schema)) and
            length==len(payload)-start and payload[head:start]==schema, 'grouped V envelope shape or schema differs')
    native = inspect_sfb1(payload[start:],{'width':16,'dims':dims,'count':count,'message_limit_bytes':65536,
                                           'algorithm':1,'path':0},expected_crc)
    return {'physical_envelope_bytes':start,**native}


def check_group_execution(fact, direction, dims):
    require(fact=={'operation':direction,'threads':1,'mode':'batch','algorithm':'fire','path':'generic_rle',
                   'required_isa':['avx2','bmi1','bmi2','lzcnt','popcnt'],'lanes':dims},
            'unbound grouped V execution profile')


def _exact(actual, expected, message):
    require(canonical_bytes(actual) == canonical_bytes(expected), message)


def reductions(original, width, dims):
    count, sums, maxima = [0] * dims, [0] * dims, [0] * dims
    for i, (value,) in enumerate(struct.iter_unpack('<B' if width == 8 else '<H', original)):
        lane = i % dims
        count[lane] += 1
        sums[lane] += value
        maxima[lane] = max(maxima[lane], value)
    return {'count': count, 'sum': sums, 'max': maxima}


def check_sfb1(wire, spec, original):
    layout = inspect_sfb1(wire, spec, crc32(original))
    literal_bytes = layout['literal_values'] * (spec['width'] // 8)
    require(len(original)==layout['raw_bytes'] and
            (not literal_bytes or wire[-literal_bytes:]==original[-literal_bytes:]),
            'Sprintz RLE length or literal-tail bytes differ')


def inspect_sfb1(wire, spec, expected_raw_crc):
    width, dims, count, limit = (spec[k] for k in ('width', 'dims', 'count', 'message_limit_bytes'))
    require(40 <= len(wire) <= 32 + 4 * limit, 'Sprintz SFB1 length outside bounds')
    magic, algorithm, bits, path, reserved, lanes, raw, z, raw_crc, payload_crc, reserved2 = struct.unpack_from(
        '<4s4B6I', wire)
    payload = wire[32:]
    require((magic, algorithm, bits, path, reserved, lanes, reserved2) ==
            (b'SFB1', spec['algorithm'], width, spec['path'], 0, dims, 0), 'Sprintz frame configuration differs')
    require(raw == count * (width // 8) <= limit and z == len(payload) and
            (raw_crc, payload_crc) == (expected_raw_crc, crc32(payload)), 'Sprintz frame lengths or CRC differ')

    # Walk the selected FIRE RLE grammar independently of the native codec.
    # This is structural verification plus literal-tail verification, not a
    # second predictor decoder. Full recovery is executed by the detached probe.
    groups, tail, inner_lanes = struct.unpack_from('<IHH', payload)
    step = 8 * dims
    require(inner_lanes == dims and tail <= count and groups <= count // step + 1,
            'Sprintz RLE shape differs')
    pos, values, elem = 8, 0, width // 8
    hbits = 3 if width == 8 else 4
    mask = (1 << hbits) - 1
    hbytes = (2 * dims * hbits + 7) // 8
    lowdim = dims <= (4 if width == 8 else 2)
    if count >= step * 3:
        require(groups > 0, 'Sprintz case did not exercise packed groups')
    packed_blocks = 0
    for _ in range(groups):
        require(pos + hbytes <= z, 'Sprintz RLE header truncated')
        headers = int.from_bytes(payload[pos:pos+hbytes], 'little')
        pos += hbytes
        for _block in range(2):
            codes = [(headers >> (lane * hbits)) & mask for lane in range(dims)]
            headers >>= dims * hbits
            total = sum(code + (code == mask) for code in codes)
            if total:
                packed_blocks += 1
                pos += total if lowdim else ((total + 7) // 8) * 8
                values += step
            else:
                require(pos < z, 'Sprintz RLE run truncated')
                run = payload[pos]
                pos += 1
                if run >= 128:
                    require(pos < z, 'Sprintz RLE run extension truncated')
                    run = (run & 127) | (payload[pos] << 7)
                    pos += 1
                values += run * step
            require(pos <= z and values <= count, 'Sprintz RLE spans exceed bounds')
    require(values + tail == count and pos + tail * elem == z,
            'Sprintz RLE length or literal-tail bytes differ')
    return {'groups':groups,'packed_blocks':packed_blocks,'literal_values':tail,
            'raw_bytes':raw,'raw_crc32':raw_crc,'sfb1_bytes':len(wire)}


def _read(out, name, maximum):
    file = local_file(out, name)
    require(file.stat().st_size <= maximum, 'Sprintz retained frame exceeds bound')
    return file.read_bytes()


def verify_sprintz(bundle, build, driver, out, *, sealed_paths=None):
    require(bundle['bundle_id'] == content_id({k: v for k, v in bundle.items() if k != 'bundle_id'}),
            'Sprintz bundle identity differs')
    if sealed_paths is not None:
        require(retained_paths(bundle) | {bundle['evidence_path']} <= sealed_paths, 'Sprintz evidence not sealed')
    report = load_json(local_file(out, bundle['evidence_path']))
    require(isinstance(report, dict) and {'native', 'worker'} <= report.keys(), 'missing Sprintz evidence')
    _exact({k: v for k, v in report.items() if k not in {'native', 'worker'}}, {
        'schema': 'bmk.m0-sprintz-control/2', 'bundle_id': bundle['bundle_id'],
        'build_sha256': build, 'driver_sha256': driver, 'formal_qualification': False, 'formal_performance': False,
        'native_rejected': bundle['native_rejections'], 'worker_rejected': bundle['worker_rejections'],
    }, 'Sprintz build, policy or rejection evidence differs')
    native, worker = report['native'], report['worker']
    require(isinstance(native, dict) and native.keys() == {s['name'] for s in bundle['shapes']} and
            isinstance(worker, dict) and worker.keys() == {s['name'] for s in bundle['shapes'] if s['worker_frame']},
            'Sprintz evidence shape closure differs')
    schema = canonical_bytes(bundle['worker_schema'])
    for spec in bundle['shapes']:
        name, width, dims, count, limit = (spec[k] for k in ('name', 'width', 'dims', 'count', 'message_limit_bytes'))
        original = plain(name, width, dims, count)
        _exact(spec['original'], ref('generated:' + name, original), 'Sprintz original identity differs')
        sfb1 = _read(out, spec['native_frame'], 32 + 4 * limit)
        check_sfb1(sfb1, spec, original)
        computed = reductions(original, width, dims)
        lowdim = dims <= (4 if width == 8 else 2)
        rejected = ['truncated', 'trailing', 'wrong_raw_length', 'above_message_limit']
        if width == 16 and len(original) < limit:
            rejected.append('odd_u16_raw_length')
        _exact(native[name], {'native_frame': ref(spec['native_frame'], sfb1), 'restored': spec['original'],
                             'reductions': {'auto': {'backend': 'scalar' if lowdim else 'upstream_simd', **computed},
                                            'scalar': {'backend': 'scalar', **computed}, 'query_rejections': rejected,
                                            'lowdim_forced_simd_rejected': True if lowdim else None}},
               f'Sprintz reductions, backend, rejection or native recovery differs: {name}')
        if spec['worker_frame']:
            bmk = _read(out, spec['worker_frame'], 32 + len(schema) + len(sfb1))
            require(bmk == struct.pack('<8sIQIQ', b'BMKSPR\x01\x00', 4, count, len(schema), len(sfb1)) + schema + sfb1,
                    'Sprintz worker envelope or native bytes differ')
            info = {'algorithm': 'fire', 'lanes': 4, 'path': 'generic_rle', 'threads': 1}
            _exact(worker[name], {'frame': ref(spec['worker_frame'], bmk), 'restored': spec['original'],
                                  'schema': ref('schema.json', schema), 'encode': {**info, 'operation': 'encode'},
                                  'decode': {**info, 'operation': 'decode'}, 'rejected': bundle['decode_rejections']},
                   f'Sprintz worker recovery, metadata or rejections differ: {name}')
