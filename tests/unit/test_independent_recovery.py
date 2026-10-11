import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import OracleAdapter
from tscompbench.codecs import CodecRegistry, DataDescriptor, SourceRegistry, negotiate
from tscompbench.contracts import BenchmarkTrack, LossMode, RunStatus, Topology, ValidityShape
from tscompbench.execution import DecodedOutput, LogicalBuffer, RoutedInput, hash_logical_buffers
from tscompbench.execution.isolation import run_isolated
from tscompbench.execution.preparation import prepare_execution_input
from tscompbench.execution.protocol import ExecutionContractError
from tscompbench.execution.recovery import (
    DecodeContext,
    bind_decode_context,
    decode_in_fresh_worker,
    restore_decoded_output,
)
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.ids import canonical_json_bytes
from tscompbench.validation import validate_common_correctness

ROOT = Path(__file__).resolve().parents[2]


def _case(dtype="<f4", codec="oracle-lossless-adapter"):
    array = np.arange(9, dtype=dtype)
    array.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", array, array.nbytes * 8),)
    route = RoutedInput(
        "recovery-test",
        BenchmarkTrack.VALUE,
        buffers,
        None,
        None,
        9,
        1,
        array.nbytes * 8,
        hash_logical_buffers(buffers),
    )
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(codec)
    descriptor = DataDescriptor(
        route.dataset_id,
        route.track,
        Topology.UTS,
        9,
        1,
        (9,),
        (dtype,),
        "SOA_COLUMNS",
        "little",
        8,
        array.nbytes * 8,
        ValidityShape.NONE,
        False,
        True,
        False,
        False,
        False,
    )
    plan = negotiate(manifest, descriptor)
    adapter = OracleAdapter(manifest_adapter=manifest.document["adapter"])
    return route, manifest, plan, adapter


def test_persisted_context_restores_widened_output_without_original_arrays(tmp_path):
    route, manifest, plan, adapter = _case()
    assert plan.operations
    context = DecodeContext.from_routed(route, plan, adapter_id=adapter.adapter_id)
    prepared = prepare_execution_input(route, plan)
    result = perform_roundtrip(adapter, prepared.codec_input, {})
    encoded = bind_decode_context(result.encoded, context)
    expected = route.buffers[0].array.tobytes()
    path = tmp_path / "object.decode.json"
    path.write_bytes(encoded.recovery_context)
    stream_path = tmp_path / "object.bin"
    stream_path.write_bytes(encoded.stream)
    del route, prepared, result, adapter, context

    call = run_isolated(
        decode_in_fresh_worker,
        ROOT,
        manifest.document,
        manifest.key,
        path.read_bytes(),
        stream_path.read_bytes(),
        encoded.stream_sha256,
        timeout_seconds=10,
        start_method="spawn",
    )
    assert call.status is RunStatus.PASS, call.message
    restored, evidence = call.value
    assert restored.buffers[0].array.dtype == np.dtype("<f4")
    assert restored.buffers[0].array.tobytes() == expected
    assert evidence["output_owned_in_worker"] is True
    assert evidence["worker_pid"] != os.getpid()
    assert evidence["original_input_available"] is False
    assert encoded.ledger.final_bits == encoded.ledger.serialized_bits + path.stat().st_size * 8


def test_context_missing_corrupt_or_inconsistent_fails_closed():
    route, _, plan, adapter = _case()
    prepared = prepare_execution_input(route, plan)
    observation = perform_roundtrip(adapter, prepared.codec_input, {})
    report = validate_common_correctness(
        route,
        observation.decoded,
        plan,
        loss_mode=LossMode.LOSSLESS,
        parameters={},
        deterministic_match=None,
        input_immutable=True,
        canary_intact=True,
    )
    assert report.first_failure_stage == "DECODE_CONTEXT_REQUIRED"
    context = DecodeContext.from_routed(route, plan)
    corrupted = context.to_document()
    corrupted["schema_version"] = "future"
    with pytest.raises(ExecutionContractError):
        DecodeContext(canonical_json_bytes(corrupted))
    with pytest.raises(ExecutionContractError):
        restore_decoded_output(DecodedOutput(()), context)
    corrupted = context.to_document()
    corrupted["buffers"][0]["shape"] = [100]
    with pytest.raises(ExecutionContractError, match="shape"):
        restore_decoded_output(observation.decoded, DecodeContext(canonical_json_bytes(corrupted)))
    artifact = bind_decode_context(observation.encoded, context)
    with pytest.raises(ExecutionContractError, match="already charged"):
        bind_decode_context(artifact, context)


def test_fresh_decoder_checks_stream_integrity():
    route, manifest, plan, adapter = _case(codec="oracle-direct", dtype="<f8")
    context = DecodeContext.from_routed(route, plan, adapter_id=adapter.adapter_id)
    encoded = perform_roundtrip(adapter, route, {}).encoded
    with pytest.raises(ExecutionContractError, match="checksum"):
        decode_in_fresh_worker(
            ROOT,
            manifest.document,
            manifest.key,
            context.serialized,
            encoded.stream + b"extra",
            encoded.stream_sha256,
        )


def test_direct_recovery_materializes_entire_owned_immutable_buffer():
    route, _, plan, _ = _case(codec="oracle-direct", dtype="<f8")
    restored = restore_decoded_output(
        DecodedOutput(route.buffers), DecodeContext.from_routed(route, plan)
    )
    array = restored.buffers[0].array
    assert array.flags.owndata and array.flags.c_contiguous and not array.flags.writeable
    assert not np.shares_memory(array, route.buffers[0].array)


def test_validity_does_not_inherit_value_adapter_operations():
    route, _, plan, _ = _case()
    mask = np.array([True] * 9)
    route = replace(route, buffers=route.buffers + (LogicalBuffer("validity", mask, 9),))
    context = DecodeContext.from_routed(route, plan)
    assert context.to_document()["buffers"][1]["inverse"] == []
    assert context.to_document()["buffers"][1]["dtype"] == mask.dtype.str
