from pathlib import Path

import numpy as np
import pytest

from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.pipelines import (
    ChildSpec,
    LogicalObjectSchema,
    PipelineCodecAdapter,
    PipelineRecipe,
)
from tscompbench.pipelines.adapter import PipelineAdapterError

ROOT = Path(__file__).resolve().parents[2]


def _case(n=9, block_size=8):
    values = np.arange(n, dtype=np.int16)
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": [
                {
                    "name": "v",
                    "dtype": "<i2",
                    "shape": [n],
                    "axes": ["time"],
                    "time_axis": 0,
                    "unit": "counts",
                    "entity": "e",
                    "feature": "f",
                }
            ],
            "timestamp": {
                "present": False,
                "dtype": "NOT_APPLICABLE",
                "unit": "NOT_APPLICABLE",
                "epoch": "NOT_APPLICABLE",
                "pairing": "NOT_APPLICABLE",
            },
            "null_recovery_contract": "BITWISE",
        }
    )
    recipe = PipelineRecipe({"v": ChildSpec("lz4-frame", {})}, None, None, block_size)
    adapter = PipelineCodecAdapter(ROOT, schema, recipe, ("value/000000",))
    routed = RoutedInput(
        "D",
        BenchmarkTrack.VALUE,
        (LogicalBuffer("value/000000", values, values.nbytes * 8),),
        None,
        None,
        n,
        1,
        values.nbytes * 8,
        hash_logical_buffers((LogicalBuffer("value/000000", values, values.nbytes * 8),)),
    )
    return adapter, routed, values


@pytest.mark.parametrize("n,block_size", [(0, 8), (9, 8), (67, 1)])
def test_pipeline_codec_adapter_roundtrip_and_accounting(n, block_size):
    adapter, routed, values = _case(n, block_size)
    session = adapter.create_session()
    bound = session.output_bound(routed)
    out = bytearray(bound)
    used = session.compress_update(routed, memoryview(out))
    assert used <= bound
    assert session.finalize(memoryview(out)[used:]) == 0
    ledger = session.accounting(bytes(out[:used]), routed)
    decoded = session.decompress(bytes(out[:used]))
    assert np.array_equal(decoded.buffers[0].array, values)
    assert ledger.final_physical_bytes == used
    session.close()


def test_pipeline_session_lifecycle_is_single_object():
    adapter, routed, _ = _case()
    session = adapter.create_session()
    destination = memoryview(bytearray(session.output_bound(routed)))
    with pytest.raises(PipelineAdapterError, match="exactly one update"):
        session.finalize(destination)
    used = session.compress_update(routed, destination)
    with pytest.raises(PipelineAdapterError, match="finalized"):
        session.accounting(bytes(destination[:used]), routed)
    with pytest.raises(PipelineAdapterError, match="fresh session"):
        session.compress_update(routed, destination)
    session.finalize(destination[used:])
    with pytest.raises(PipelineAdapterError, match="exactly one update"):
        session.finalize(destination[used:])
    session.close()
    with pytest.raises(PipelineAdapterError, match="closed"):
        session.output_bound(routed)


def test_pipeline_insufficient_capacity_keeps_destination_unpublished():
    adapter, routed, _ = _case()
    session = adapter.create_session()
    destination = bytearray(b"sentinel")
    with pytest.raises(PipelineAdapterError, match="capacity"):
        session.compress_update(routed, memoryview(destination))
    assert destination == b"sentinel"
    session.close()
