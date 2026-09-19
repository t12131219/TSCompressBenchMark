import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import SprintzAdapter
from tscompbench.codecs import CodecRegistry, DataDescriptor, SourceRegistry, negotiate
from tscompbench.contracts import (
    BenchmarkTrack,
    CapabilityStatus,
    Topology,
    ValidityShape,
)
from tscompbench.execution.protocol import (
    ExecutionContractError,
    LogicalBuffer,
    RoutedInput,
)
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers

ROOT = Path(__file__).resolve().parents[2]
ALGORITHMS = ("sprintz-delta", "sprintz-fire", "sprintz-fire-huff0")
DTYPES = ("|u1", "|i1", "<u2", "<i2")


def codec(name):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(name)
    library = ROOT / manifest.document["adapter"]["artifact_path"]
    if not library.is_file():
        pytest.skip(f"build {name} first")
    return SprintzAdapter(library, manifest.document["adapter"], name), manifest


def route(dtype, rows, dimensions, seed=1):
    target = np.dtype(dtype)
    unsigned = np.dtype("u1" if target.itemsize == 1 else "<u2")
    high = 1 << (8 * target.itemsize)
    rng = np.random.default_rng(seed + rows + dimensions)
    buffers = []
    for column in range(dimensions):
        values = rng.integers(0, high, rows, dtype=unsigned)
        values = np.ascontiguousarray(values).view(target)
        values.flags.writeable = False
        buffers.append(LogicalBuffer(
            f"value/{column:06d}", values, values.nbytes * 8
        ))
    items = tuple(buffers)
    return RoutedInput(
        dataset_id="dataset:sprintz-full-test",
        track=BenchmarkTrack.VALUE,
        buffers=items,
        timestamp_reference=None,
        validity_reference=None,
        n=rows,
        m=dimensions,
        canonical_raw_bits=sum(item.logical_bits for item in items),
        input_sha256=hash_logical_buffers(items),
    )


def matrix_route(dtype="<i2", rows=137, dimensions=4):
    target = np.dtype(dtype)
    unsigned = np.dtype("u1" if target.itemsize == 1 else "<u2")
    values = np.arange(rows * dimensions, dtype=unsigned).reshape(rows, dimensions)
    values = np.ascontiguousarray(values).view(target)
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    return RoutedInput(
        dataset_id="dataset:sprintz-matrix-test",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=rows,
        m=dimensions,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize("name", ALGORITHMS)
@pytest.mark.parametrize("dtype", DTYPES)
@pytest.mark.parametrize("dimensions", [1, 2, 3, 4, 5, 9, 127, 128])
def test_roundtrip_all_native_dispatch_paths(name, dtype, dimensions):
    adapter, _ = codec(name)
    routed = route(dtype, 137, dimensions)
    result = perform_roundtrip(adapter, routed, {"isa": "AVX2_BMI2_LZCNT"})
    expected = {item.name: item.array.tobytes() for item in routed.buffers}
    actual = {
        name: item.array.tobytes()
        for name, item in result.decoded.by_name().items()
    }
    assert actual == expected
    assert result.encoded.ledger.final_bits == len(result.encoded.stream) * 8
    assert result.input_immutable and result.canary_intact and result.determinism_match
    assert result.encoded.native_encode_wall_ns is not None


@pytest.mark.parametrize("name", ALGORITHMS)
@pytest.mark.parametrize("rows", [0, 1, 7, 8, 127, 128, 129])
def test_boundary_lengths_and_hostile_streams(name, rows):
    adapter, _ = codec(name)
    routed = route("<u2", rows, 3)
    result = perform_roundtrip(adapter, routed, {})
    session = adapter.create_session({})
    try:
        stream = result.encoded.stream
        header_size = struct.unpack_from("<I", stream, 8)[0]
        corrupted = bytearray(stream)
        frame_start = 12 + header_size
        if name == "sprintz-fire-huff0":
            corrupted[frame_start + 5] = 3
        else:
            corrupted[frame_start + 16 + 6] ^= 1
        for invalid in (stream[:-1], stream + b"x", bytes(corrupted)):
            with pytest.raises(ExecutionContractError):
                session.decompress(invalid)
    finally:
        session.close()


def test_negotiation_is_lossless_and_requires_homogeneous_width():
    _, manifest = codec("sprintz-delta")
    base = dict(
        dataset_id="dataset:test",
        track=BenchmarkTrack.VALUE,
        topology=Topology.SYNCHRONOUS_MTS,
        n=128,
        m=2,
        shape=(128, 2),
        physical_layout="SOA_COLUMNS",
        endianness="little",
        alignment_bytes=1,
        canonical_raw_bits=4096,
        validity_shape=ValidityShape.NONE,
        timestamp_present=False,
        preserve_order=False,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
    )
    direct = negotiate(manifest, DataDescriptor(
        **base, dtype_vector=("<i2", "<u2")
    ))
    mixed = negotiate(manifest, DataDescriptor(
        **base, dtype_vector=("|u1", "<u2")
    ))
    floating = negotiate(manifest, DataDescriptor(
        **base, dtype_vector=("<f8", "<f8")
    ))
    assert direct.status is CapabilityStatus.DIRECT_SUPPORTED
    assert mixed.status is CapabilityStatus.UNSUPPORTED
    assert mixed.reason_code == "HETEROGENEOUS_ITEMSIZE_UNSUPPORTED"
    assert floating.status is CapabilityStatus.UNSUPPORTED
    assert floating.reason_code == "LOSSY_DTYPE_CONVERSION_UNDECLARED"


def test_fire_huff0_negotiation_enforces_single_huff0_block_limit():
    _, manifest = codec("sprintz-fire-huff0")
    base = dict(
        dataset_id="dataset:test",
        track=BenchmarkTrack.VALUE,
        topology=Topology.UTS,
        n=122881,
        m=1,
        shape=(122881,),
        dtype_vector=("|u1",),
        physical_layout="ROW_MAJOR_CONTIG",
        endianness="little",
        alignment_bytes=1,
        validity_shape=ValidityShape.NONE,
        timestamp_present=False,
        preserve_order=False,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
    )
    plan = negotiate(manifest, DataDescriptor(
        **base, canonical_raw_bits=122881 * 8
    ))
    assert plan.status is CapabilityStatus.UNSUPPORTED
    assert {"n", "total_raw_bytes"}.issubset(plan.missing_capabilities)


@pytest.mark.parametrize("name", ALGORITHMS)
def test_native_two_dimensional_buffer_is_not_reduced_to_first_column(name):
    adapter, _ = codec(name)
    routed = matrix_route()
    result = perform_roundtrip(adapter, routed, {})
    decoded = result.decoded.by_name()["value/000000"].array
    assert decoded.shape == (137, 4)
    assert decoded.dtype == np.dtype("<i2")
    assert decoded.tobytes() == routed.buffers[0].array.tobytes()
