"""Real-corpus stream control tests: native state boundaries plus independent wire recovery."""
from pathlib import Path
import struct

import pytest

from tsbench.application.m3_titchy_stream import POLICY, SPEC, invoke, validate_stream
from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.qualification.titchy_wire import decode_tstr

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / 'build/m3-real-r8/plugins/codecs/titchy-batch/tsbench_titchy_corpus_stream_control'
PLAN = ROOT / 'results/m3-real-r14-20261119/plan.json'


@pytest.mark.skipif(not CONTROL.is_file(), reason='build tsbench_titchy_corpus_stream_control for integration')
@pytest.mark.parametrize(('n', 'first_phase', 'finish', 'finish_samples'), [
    (1, 'finish', 1, 1), (27, 'finish', 1, 27), (28, 'push', 0, 0), (29, 'push', 1, 1),
    (56, 'push', 0, 0), (4000, 'push', 1, 24), (4001, 'push', 2, 25), (8001, 'push', 2, 25),
])
def test_native_stream_archive_and_detached_decode(tmp_path, n, first_phase, finish, finish_samples):
    vals = (0x8000000000000000, 0x7ff8000000000051, 0x3ff0000000000000, 0x8000000100000000)
    raw = b''.join(struct.pack('<Q', vals[i % 4] ^ (i // 4)) for i in range(n))
    source = tmp_path / 'source'
    source.write_bytes(raw)
    encode, _ = invoke(CONTROL, tmp_path, 'encode', 'source', 'archive', 'config')
    source.unlink()
    decode, _ = invoke(CONTROL, tmp_path, 'decode', 'archive', 'config', 'out')
    wire, config = (tmp_path / 'archive').read_bytes(), (tmp_path / 'config').read_bytes()
    assert (tmp_path / 'out').read_bytes() == raw == decode_tstr(wire, config, {**SPEC, 'count': n}, POLICY)[0]
    accounting = validate_stream(n, wire, config, encode, decode)
    assert accounting['artifact_bytes'] == len(wire) + len(config)
    assert accounting['first_packet_phase'] == first_phase
    assert encode['packets_emitted_on_finish'] == finish
    assert accounting['finish_logical_samples'] == finish_samples
    assert accounting['padding_samples'] == -n % POLICY['chunk']
    assert encode['backpressure_replay_checks'] == (3 if first_phase == 'push' else 0)
    for archive, conf in ((wire[:-1], config), (wire + b'\0', config), (wire, config[:-1] + b'\x01')):
        (tmp_path / 'bad-archive').write_bytes(archive)
        (tmp_path / 'bad-config').write_bytes(conf)
        with pytest.raises(ContractError, match='Titchy decode exited'):
            invoke(CONTROL, tmp_path, 'decode', 'bad-archive', 'bad-config', 'bad-out')
        assert not (tmp_path / 'bad-out').exists()
    with pytest.raises(ContractError, match='stream accounting differs'):
        validate_stream(n, wire, config, {**encode, 'payload_bytes': encode['payload_bytes'] + 1}, decode)


@pytest.mark.skipif(not PLAN.is_file(), reason='requires locally frozen r14 plan')
def test_stream_binding_and_scope():
    plan = load_json(PLAN)
    check_m3_real_corpus_plan(ROOT, plan)
    load_contract(ROOT, 'm3-real-corpus-plan').validate(plan, 'plan')
    stream_items = [x for x in plan['work_items'] if x['route'] == 'packet-stream']
    assert len(stream_items) == 23 and all(x['input']['slice_extent']['max_per_unit'] is None for x in stream_items)
    assert all(x['execution_state'] == 'not_run' for x in plan['obligations'] if x['route'] == 'packet-stream')
    plan['build']['titchy_stream']['invoker']['sha256'] = '0' * 64
    plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
    with pytest.raises(ContractError, match='Titchy stream control binding is stale'):
        check_m3_real_corpus_plan(ROOT, plan)
