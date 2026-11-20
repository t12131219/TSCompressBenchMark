from binascii import crc32
from collections import Counter
from pathlib import Path

import pytest

from tsbench.application.m3_huff0_fec1 import asset, call, frames
from tsbench.assets import ContractError, load_json
from tsbench.planner.huff0 import BLOCK, ENVELOPE, FEC, MAGIC, RECORD
from tsbench.planner.m3_huff0_fec1 import DIRECTORY, UNIT, bind
from tsbench.recovery import stage_recovery

ROOT = Path(__file__).resolve().parents[2]


def raw_frame(raw, schema):
    records = b''.join(RECORD.pack(0, len(block), len(block), crc32(block))+block
                       for off in range(0, len(raw), BLOCK) for block in (raw[off:off+BLOCK],))
    data = FEC.pack(b'FEC1', 2, b'\0'*3, BLOCK, len(raw), (len(raw)+BLOCK-1)//BLOCK)+records
    return ENVELOPE.pack(MAGIC, 2, len(raw), len(schema), len(data))+schema+data


def test_fec1_frozen_units_and_charge():
    raw, schema = bytes(range(256))*257, b'{}'
    wire = raw_frame(raw[:UNIT], schema)+raw_frame(raw[UNIT:], schema)
    rows = list(frames(wire, raw, schema))
    assert [r['decoded']['bytes'] for _, r in rows] == [UNIT, 256]
    assert [[x['decoded_bytes'] for x in r['records']] for _, r in rows] == [[BLOCK, BLOCK], [256]]
    assert sum(r['frame']['bytes'] for _, r in rows) == len(wire)


@pytest.mark.parametrize('case,why', [('crc', 'CRC'), ('size', 'extent'), ('trailing', 'unaccounted'), ('schema', 'schema')])
def test_fec1_parser_fails_closed(case, why):
    raw, schema = bytes(range(256))*13, b'{}'
    wire = raw_frame(raw, schema)
    if case == 'crc':
        index = ENVELOPE.size+len(schema)+FEC.size+9
        wire = wire[:index]+bytes([wire[index]^1])+wire[index+1:]
    elif case == 'size':
        wire = wire[:-1]
    elif case == 'trailing':
        wire += b'!'
    else:
        schema = b'[]'
    with pytest.raises(ContractError, match=why):
        list(frames(wire, raw, schema))


@pytest.mark.skipif(not Path('/usr/bin/bwrap').is_file(), reason='requires Bubblewrap')
def test_native_bounded_detached_fec1(tmp_path):
    # Enable in the isolated integration invocation, not for ordinary pytest runs
    # inside a restricted outer namespace.
    import os
    if os.environ.get('TSBENCH_TEST_BWRAP') != '1':
        pytest.skip('requires an outer environment that permits unshare-net')
    p = ROOT / 'results/m3-real-r8-20261119/build-lock.json'
    binding = bind(ROOT, load_json(p)) if p.is_file() else None
    if binding is None:
        pytest.skip('build tsbench_huff0_fec1_control first')
    stage_recovery(ROOT, tmp_path, binding['decoder'], directory=DIRECTORY)
    raw = bytes(range(256))*(BLOCK//256)+b'z'*BLOCK+bytes(range(5))*177
    schema = b'{"dtype":"u8"}'
    source, header = tmp_path/'source', tmp_path/'schema'
    source.write_bytes(raw)
    header.write_bytes(schema)
    wire, e, _ = call(tmp_path, binding, tmp_path/'encode', 'encode', {'input.bin': source, 'schema.json': header})
    encoded = wire.read_bytes()
    rows = list(frames(encoded, raw, schema))
    assert Counter(r['mode'] for _, f in rows for r in f['records']) == {'raw': 1, 'rle': 1, 'huffman': 1}
    source.unlink()
    header.unlink()
    out, d, obs = call(tmp_path, binding, tmp_path/'decode', 'decode', {'frames.bmk': wire})
    assert d == e and out.read_bytes() == raw and obs['input_mounts'] == {'frames.bmk': asset(encoded)}
    index = ENVELOPE.size+len(schema)+FEC.size+9
    corrupt = tmp_path/'corrupt.bmk'
    corrupt.write_bytes(encoded[:index]+bytes([encoded[index]^1])+encoded[index+1:])
    with pytest.raises(ContractError, match='native Huff0 decode or CRC check failed'):
        call(tmp_path, binding, tmp_path/'bad-crc', 'decode', {'frames.bmk': corrupt})
