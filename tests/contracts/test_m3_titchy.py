"""Route identity, extent and ABI envelope tests for the r22 Titchy binding."""
from collections import Counter
from pathlib import Path
import struct

import pytest

from tsbench.application.m3_titchy import inspect_frame, invoke_abi, restore_batch
from tsbench.application.m3_titchy_access import WIRE_POLICY
from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.planner.m3_titchy import BATCH, BATCH_DRIVER
from tsbench.qualification.titchy_wire import decode_tchy

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'results/m3-real-r22-20261119/plan.json'


def test_r22_adds_only_titchy_binding_and_batch_driver():
    plan = load_json(PLAN)
    earlier = load_json(ROOT / 'results/m3-real-r21-20261119/plan.json')
    check_m3_real_corpus_plan(ROOT, plan)
    load_contract(ROOT, 'm3-real-corpus-plan').validate(plan, 'plan')
    for key in ('build', 'definition', 'coverage', 'work_items', 'obligations'):
        assert plan[key] == earlier[key]
    assert {name: b for name, b in plan['specialized'].items() if name != 'titchy'} == earlier['specialized']
    for new, old in zip(plan['routes'], earlier['routes'], strict=True):
        assert new == ({**old, 'driver': BATCH_DRIVER} if (old['selection'], old['route']) == BATCH else old)
    bundle = plan['specialized']['titchy']
    assert Counter(slot['method'] for slot in bundle['slots'].values()) == {
        'titchy-batch': 15, 'titchy-loaded-reader': 1, 'titchy-stateless-range': 1, 'titchy-packet-stream': 1}
    assert len(bundle['obligation_slots']) == 22
    assert sum(bool(s.get('expected_status')) for s in bundle['slots'].values()) == 3


def test_rehash_cannot_swap_titchy_case_between_routes():
    plan = load_json(PLAN)
    bundle = plan['specialized']['titchy']
    ids = bundle['obligation_slots']
    a, b = [next(o['obligation_id'] for o in plan['obligations'] if o['selection'] == 85 and o['route'] == r)
            for r in ('batch', 'packet-stream')]
    ids[a], ids[b] = ids[b], ids[a]
    plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
    with pytest.raises(ContractError, match='Titchy'):
        check_m3_real_corpus_plan(ROOT, plan)


def test_detached_batch_and_wire_reader_preserve_special_f64_bits(tmp_path):
    source, detached = tmp_path / 'source', tmp_path / 'detached'
    source.mkdir(); detached.mkdir()
    raw = struct.pack('<7Q', 0x8000000000000000, 0x7ff8000000000012, 0x7ff0000000000000,
                      0xfff0000000000000, 1, 0, 0x3ff0000000000000)
    schema = b'{"layout":"f64-bitcast","rows":7}'
    (source / 'raw').write_bytes(raw); (source / 'schema').write_bytes(schema)
    binding = load_json(PLAN)['specialized']['titchy']
    frame = detached / 'frame'
    invoke_abi(ROOT, binding, source, 'encode', ['8', 'raw', 'schema', frame])
    (source / 'raw').unlink(); (source / 'schema').unlink(); source.rmdir()
    wire = frame.read_bytes()
    native, fees = inspect_frame(wire, 7, schema)
    assert fees['native_frame_bytes'] + fees['abi_envelope_bytes'] == fees['artifact_bytes'] == len(wire)
    assert decode_tchy(native, 64, 7, WIRE_POLICY)[0] == raw
    with pytest.raises(ContractError):
        inspect_frame(wire + b'!', 7, schema)
    decoded, _ = restore_batch(ROOT, binding, detached, frame)
    assert decoded[0] == {'columns': [{'dtype': 8, 'count': 7}]}
    assert (detached / 'raw').read_bytes() == raw and (detached / 'schema').read_bytes() == schema
