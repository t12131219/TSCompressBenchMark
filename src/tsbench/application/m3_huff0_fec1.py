"""Verify FEC1 ABI products in two disjoint, offline process lanes."""
from binascii import crc32
from collections import Counter
from hashlib import sha256

from ..assets import digest, parse_json, require
from ..planner.huff0 import BLOCK, ENVELOPE, FEC, MAGIC, MODE, RECORD
from ..planner.m3_huff0_fec1 import BATCH, DIRECTORY, DRIVER, TARGET, UNIT
from ..qualification.huff0 import _bitstreams, _weights_size
from ..supervisor.isolated_worker import invoke_isolated_tool


def call(run, binding, work, operation, inputs):
    library = '/runtime/lib/libbmk_huff0_reference.so'
    args = ([operation, library, '/inputs/input.bin', '/inputs/schema.json', '/out/result.bin'] if operation == 'encode'
            else [operation, library, '/inputs/frames.bmk', '/out/result.bin'])
    work.mkdir()
    logs = work / 'logs'
    logs.mkdir()
    out, row = invoke_isolated_tool(run / DIRECTORY, binding['decoder'], TARGET, binding['limits'], work, logs,
                                    operation, inputs, args, lambda: False, file_ceiling=5 << 20, bind_inputs=True)
    stderr = (logs / (operation + '.stderr')).read_text()
    require(row['status'] == 'completed' and row['returncode'] == 0 and not stderr,
            f'FEC1 {operation}: {stderr.strip() or row["reason"] or row["status"]}')
    require({p.name for p in out.iterdir()} == {'result.bin'}, f'unexpected FEC1 {operation} output')
    return out / 'result.bin', parse_json((logs / (operation + '.stdout')).read_bytes(), f'FEC1 {operation}'), row


def asset(data):
    return {'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def frames(wire, raw, schema):
    """Parse and count every wire byte, checking CRC against the source oracle."""
    pos = 0
    for start in range(0, len(raw), UNIT):
        n = min(UNIT, len(raw)-start)
        first = pos
        require(len(wire)-pos >= ENVELOPE.size, 'truncated Huff0 ABI header')
        magic, dtype, logical, schema_n, payload_n = ENVELOPE.unpack_from(wire, pos)
        pos += ENVELOPE.size
        require((magic, dtype, logical, schema_n) == (MAGIC, 2, n, len(schema)) and wire[pos:pos+schema_n] == schema,
                'FEC1 envelope shape or schema differs')
        pos += schema_n
        end = pos + payload_n
        k = (n+BLOCK-1)//BLOCK
        require(FEC.size <= payload_n <= FEC.size + RECORD.size*k + n and end <= len(wire) and
                FEC.unpack_from(wire, pos) == (b'FEC1', 2, b'\0'*3, BLOCK, n, k), 'invalid FEC1 header or payload extent')
        pos += FEC.size
        records = []
        for off in range(0, n, BLOCK):
            require(pos+RECORD.size <= end, 'truncated FEC1 record header')
            tag, d, c, crc = RECORD.unpack_from(wire, pos)
            pos += RECORD.size
            expected = raw[start+off:start+min(n, off+BLOCK)]
            require(tag in range(3) and d == len(expected) and 0 < c <= end-pos and crc == crc32(expected),
                    'invalid FEC1 record extent, mode or CRC')
            body = wire[pos:pos+c]
            if tag == 0:
                require(c == d and body == expected, 'FEC1 raw bytes differ')
            elif tag == 1:
                require(c == 1 and c < d and body*d == expected, 'FEC1 RLE bytes differ')
            else:
                require(c < d, 'invalid FEC1 Huffman stored extent')
                _bitstreams(body[_weights_size(body):], 4)
            records.append({'mode': MODE[tag], 'decoded_bytes': d, 'body_bytes': c, 'crc32': crc})
            pos += c
        require(pos == end, 'unaccounted FEC1 payload bytes')
        yield (first, pos), {'frame': asset(wire[first:pos]), 'decoded': asset(raw[start:start+n]), 'records': records}
    require(pos == len(wire), 'unaccounted Huff0 ABI bytes')


def run_fec1(plan, item, entry, staged, work, run):
    binding = plan['build']['huff0_fec1']
    schema_path = staged['schema']
    schema = schema_path.read_bytes()
    source, = staged['paths']
    ref = {'bytes': entry['rows']*entry['value_count']*8, 'sha256': entry['canonical']['values_sha256']}
    estimate = item['input']['size_estimate']
    require(ref == {'bytes': source.stat().st_size, 'sha256': digest(source)} and ref['bytes'] > 0 and
            ref['bytes'] == estimate['native_input_bytes_one_pass'] and item['input']['slice_extent']['max_per_unit'] == UNIT,
            'FEC1 staged object differs from frozen corpus extent')
    census, cost = Counter(), Counter()
    groups = []
    recovered = sha256()
    with source.open('rb') as stream:
        offset = 0
        while raw := stream.read(BATCH):
            group = work / f'group-{len(groups):05d}'
            group.mkdir()
            chunk = group / 'input.bin'
            chunk.write_bytes(raw)
            encoded, e, _ = call(run, binding, group / 'encode', 'encode', {'input.bin': chunk, 'schema.json': schema_path})
            wire = encoded.read_bytes()
            parsed = list(frames(wire, raw, schema))
            restored, d, obs = call(run, binding, group / 'decode', 'decode', {'frames.bmk': encoded})
            actual = restored.read_bytes()
            wire_ref = asset(wire)
            require(e == d == {'frames': len(parsed), 'input_bytes': len(raw), 'frame_bytes': len(wire)} and actual == raw and
                    obs['input_mounts'] == {'frames.bmk': wire_ref}, 'FEC1 detached restoration, isolation or byte accounting differs')
            recovered.update(actual)
            rows = []
            for (a, b), row in parsed:
                records = row['records']
                cost.update({'abi_header': ENVELOPE.size, 'schema': len(schema), 'fec_header': FEC.size,
                             'record_headers': RECORD.size*len(records)})
                for r in records:
                    census[r['mode']] += 1
                    cost[r['mode']+'_body'] += r['body_bytes']
                if (offset == 0 and a == 0) or (offset+len(raw) == ref['bytes'] and b == len(wire)):
                    name = 'first.bmk' if offset == 0 and a == 0 else 'last.bmk'
                    target = run / 'retained' / item['work_item_id'] / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as retained:
                        retained.write(wire[a:b])
                    row['retained'] = {'path': target.relative_to(run).as_posix(), **row['frame']}
                rows.append(row)
            groups.append({'offset': offset, 'decoded': asset(raw), 'wire': wire_ref, 'frames': rows,
                           'detached_process': {key: obs[key] for key in ('session_id', 'pid', 'input_mounts')}})
            offset += len(raw)
            # Drop bulk staging immediately; only the evidence and small samples remain.
            for p in (chunk, encoded, restored):
                p.unlink()
    require(offset == ref['bytes'] and recovered.hexdigest() == ref['sha256'] and
            sum(len(g['frames']) for g in groups) == estimate['input_units'] and
            sum(cost.values()) == sum(g['wire']['bytes'] for g in groups), 'FEC1 full coverage or cost differs')
    return {'driver': DRIVER, 'input': ref, 'recovered': ref, 'schema': asset(schema), 'groups': groups,
            'native_block_bytes': BLOCK, 'abi_unit_bytes': UNIT, 'modes': dict(census), 'byte_cost': dict(cost),
            'complete_bytes': sum(cost.values()), 'timing_admitted': False}
