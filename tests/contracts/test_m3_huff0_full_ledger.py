from binascii import crc32
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from verify_m3_huff0_full_ledger import (FEC1_DRIVER, ETB1_DRIVER, RETAIN_MAX, asset, fec1_cases,
                                        etb1_cases, expected, fec1_check)
from tsbench.assets import ContractError
from tsbench.planner.huff0 import BLOCK, ENVELOPE, FEC, MAGIC, RECORD


def test_fec1_uses_schema_inside_retained_abi_frame_and_checks_independent_crc(tmp_path):
    source = b'12345678'
    schema = b'{"dtype":"u8"}'
    payload = FEC.pack(b'FEC1', 2, b'\0' * 3, BLOCK, len(source), 1)
    payload += RECORD.pack(0, len(source), len(source), crc32(source)) + source
    wire = ENVELOPE.pack(MAGIC, 2, len(source), len(schema), len(payload)) + schema + payload
    path = tmp_path / 'retained/item/first.bmk'
    path.parent.mkdir(parents=True)
    path.write_bytes(wire)
    ref = {'path': 'retained/item/first.bmk', **asset(wire)}
    item = {'work_item_id': 'item', 'input': {'size_estimate': {'native_input_bytes_one_pass': len(source), 'input_units': 1}}}
    raw = asset(source)
    frame = {'frame': asset(wire), 'decoded': raw, 'retained': ref,
             'records': [{'mode': 'raw', 'decoded_bytes': len(source), 'body_bytes': len(source), 'crc32': crc32(source)}]}
    ev = {'driver': FEC1_DRIVER, 'input': raw, 'recovered': raw, 'schema': asset(schema),
          'groups': [{'offset': 0, 'decoded': raw, 'frames': [frame]}]}
    (case, mounts), = list(fec1_cases(tmp_path, item, ev))
    assert mounts == {'frame': path} and case['references'] == [ref]
    fec1_check(wire, source, case)
    with pytest.raises(ContractError, match='CRC'):
        fec1_check(wire, b'other123', case)
    with pytest.raises(ContractError, match='embedded schema'):
        fec1_check(wire, source, {**case, 'schema': asset(b'abc')})
    frame.pop('retained')
    with pytest.raises(ContractError, match='first/last'):
        list(fec1_cases(tmp_path, item, ev))


def test_etb1_records_only_retained_variants_and_verifies_complete_identity(tmp_path):
    folder = tmp_path / 'retained/item/1x'
    folder.mkdir(parents=True)
    identities, refs = {}, {}
    for file, field in [('model.etb1', 'model'), ('test.blocks', 'frame'), ('binding.json', 'binding')]:
        content = file.encode()
        path = folder / file
        path.write_bytes(content)
        identities[field] = asset(content)
        refs[file] = {'path': path.relative_to(tmp_path).as_posix(), **identities[field]}
    holdout = asset(b'holdout')
    one = {'status': 'verified', 'recovered': holdout, 'retained': refs, **identities,
           'blocks': [], 'decode': {'streams': 1}}
    four = {'status': 'verified', 'recovered': holdout, 'retained': {}, 'frame': {'bytes': RETAIN_MAX + 1}}
    ev = {'driver': ETB1_DRIVER, 'profiles': {'1': one, '4': four}, 'training': asset(b'train'), 'holdout': holdout}
    item = {'work_item_id': 'item'}
    (case, paths), (excluded, nothing) = etb1_cases(tmp_path, item, ev)
    assert set(paths) == {'model', 'blocks', 'binding'} and len(case['references']) == 3
    mounts, output, operation = expected(case, 'decode')
    assert mounts == {'model': identities['model'], 'blocks': identities['frame']} and output == holdout and operation['streams'] == 1
    assert nothing is None and excluded['streams'] == 4
    refs['binding.json']['bytes'] += 1
    with pytest.raises(ContractError, match='part identity'):
        list(etb1_cases(tmp_path, item, ev))
