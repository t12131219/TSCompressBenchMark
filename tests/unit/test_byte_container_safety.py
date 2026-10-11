from __future__ import annotations

import copy
import importlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from tscompbench.adapters.byte_container import (
    MAX_METADATA_BYTES,
    decode_byte_payload,
    parse_byte_metadata,
    validate_byte_descriptors,
)
from tscompbench.adapters.native_streaming import NativeByteStreamingSession
from tscompbench.execution.protocol import ExecutionContractError

FAMILIES = (
    ("lz4_frame", "Lz4FrameSession", "tscb.lz4-frame-container.v1"),
    ("zstd_frame", "ZstdFrameSession", "tscb.zstd-frame-container.v1"),
    ("snappy_raw", "SnappyRawSession", "tscb.snappy-raw-container.v1"),
    ("brotli_stream", "BrotliStreamSession", "tscb.brotli-stream-container.v1"),
    ("deflate_zlib", "DeflateZlibSession", "tscb.deflate-zlib-container.v1"),
    ("xz_stream", "XzStreamSession", "tscb.xz-stream-container.v1"),
)


def descriptor():
    return {"name": "value", "dtype": "<f8", "shape": [1], "payload_bytes": 8, "logical_bits": 64}


def invalid_headers():
    base = {"buffers": [descriptor()]}
    yield []
    for key, value in (
        ("dtype", "O"),
        ("dtype", ["<f8"]),
        ("shape", [True]),
        ("shape", [-1]),
        ("shape", [2**62, 4]),
        ("shape", [0, 2**62, 4]),
        ("payload_bytes", "8"),
        ("logical_bits", -1),
        ("logical_bits", 63),
        ("name", ""),
        ("name", ["value"]),
    ):
        header = copy.deepcopy(base)
        header["buffers"][0][key] = value
        yield header
    yield {"buffers": [descriptor(), descriptor()]}
    yield {"buffers": [False]}
    yield {"buffers": []}
    yield {
        "buffers": [
            {
                "name": "value",
                "dtype": "|u1",
                "shape": [2**31],
                "payload_bytes": 2**31,
                "logical_bits": 2**34,
            }
        ]
    }
    for layout in ({}, [], "UNKNOWN"):
        yield {**base, "payload_layout": layout}
    yield {**base, "payload_layout": "BLOCK_MAJOR_BUFFER_ORDER", "stream_block_size": True}


@pytest.mark.parametrize("family,session_name,schema", FAMILIES)
@pytest.mark.parametrize("header", list(invalid_headers()))
def test_rejects_metadata_before_native_access_or_payload_allocation(
    family, session_name, schema, header
):
    module = importlib.import_module(f"tscompbench.adapters.{family}")
    session_type = getattr(module, session_name)
    session = session_type.__new__(session_type)
    # No native handle exists: accessing it would raise AttributeError. The tiny
    # invalid frame must be rejected solely from its untrusted metadata.
    if isinstance(header, dict):
        header = {**header, "schema_version": schema}
    data = json.dumps(header).encode()
    stream = module._PREFIX.pack(module._MAGIC, len(data)) + data + b"invalid-native-stream"
    with pytest.raises(ExecutionContractError):
        session.decompress(stream)


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(ExecutionContractError):
        parse_byte_metadata(b'{"buffers":[],"buffers":[]}')


@pytest.mark.parametrize("family,session_name,schema", FAMILIES)
def test_metadata_budget_is_checked_before_slicing_or_parsing(family, session_name, schema):
    module = importlib.import_module(f"tscompbench.adapters.{family}")
    session = getattr(module, session_name).__new__(getattr(module, session_name))
    stream = module._PREFIX.pack(module._MAGIC, MAX_METADATA_BYTES + 1)
    with pytest.raises(ExecutionContractError, match="resource limit"):
        session.decompress(stream)


@pytest.mark.parametrize("header", list(invalid_headers())[1:])
def test_stream_decoder_rejects_before_reset_or_allocation(header):
    session = NativeByteStreamingSession.__new__(NativeByteStreamingSession)
    session._owner = SimpleNamespace(_parse_container=lambda stream: (header, b"invalid"))
    with pytest.raises(ExecutionContractError):
        session.stream_decompress(b"invalid")


@pytest.mark.parametrize("family", ["lzss_raw", "lzss_dipperstein", "huff0", "fse"])
@pytest.mark.parametrize("header", list(invalid_headers()))
def test_lzss_and_entropy_validate_all_descriptors_before_native_access(family, header):
    if family in {"huff0", "fse"}:
        module = importlib.import_module("tscompbench.adapters.entropy_fse")
        session = module.EntropySession.__new__(module.EntropySession)
        session.algorithm = family
        magic = module._MAGICS[family]
        prefix = module._PREFIX
        schema = f"tscb.{family}-container.v1"
    else:
        module = importlib.import_module(f"tscompbench.adapters.{family}")
        name = "LzssRawSession" if family == "lzss_raw" else "LzssDippersteinSession"
        session = getattr(module, name).__new__(getattr(module, name))
        magic, schema = session._VARIANT.magic, session._VARIANT.schema_version
        prefix = importlib.import_module("tscompbench.adapters.lzss_common")._PREFIX
    if isinstance(header, dict):
        header = {**header, "schema_version": schema}
    data = json.dumps(header).encode()
    stream = prefix.pack(magic, len(data)) + data + b"invalid-native-stream"
    with pytest.raises(ExecutionContractError):
        session.decompress(stream)


def test_decoder_resource_limit_is_explicit_and_separate_from_dtype_domain():
    header = {"buffers": [descriptor()]}
    with pytest.raises(ExecutionContractError, match="resource limit"):
        validate_byte_descriptors(header, max_output_bytes=7)
    assert validate_byte_descriptors(header, max_output_bytes=8)[1] == 8


def test_zero_byte_stream_does_not_iterate_untrusted_row_count():
    header = {
        "buffers": [
            {
                "name": "value",
                "dtype": "|u1",
                "shape": [2**40, 0],
                "payload_bytes": 0,
                "logical_bits": 0,
            }
        ],
        "payload_layout": "BLOCK_MAJOR_BUFFER_ORDER",
        "stream_block_size": 1,
    }
    output = decode_byte_payload(header, memoryview(b""))
    assert output.buffers[0].array.shape == (2**40, 0)


def test_empty_stream_buffers_do_not_multiply_payload_processing_work(monkeypatch):
    module = importlib.import_module("tscompbench.adapters.byte_container")
    rows, empty_buffers = 256, 128
    descriptors = [
        {
            "name": "value",
            "dtype": "|u1",
            "shape": [rows],
            "payload_bytes": rows,
            "logical_bits": rows * 8,
        },
        *[
            {
                "name": f"empty/{i}",
                "dtype": "<f8",
                "shape": [rows, 0],
                "payload_bytes": 0,
                "logical_bits": 0,
            }
            for i in range(empty_buffers)
        ],
    ]
    header = {
        "buffers": descriptors,
        "payload_layout": "BLOCK_MAJOR_BUFFER_ORDER",
        "stream_block_size": 1,
    }
    dimension_work = 0
    original_prod = module.math.prod

    def count_dimension_work(values, **kwargs):
        nonlocal dimension_work
        dimension_work += 1
        return original_prod(values, **kwargs)

    monkeypatch.setattr(module.math, "prod", count_dimension_work)
    payload = bytes(range(rows))
    output = decode_byte_payload(header, memoryview(payload))
    assert output.buffers[0].array.tobytes() == payload
    for buffer in output.buffers[1:]:
        assert buffer.array.dtype == np.dtype("<f8")
        assert buffer.array.shape == (rows, 0)
        assert buffer.array.nbytes == 0
        assert not buffer.array.flags.writeable
    # Bound metadata work plus real payload blocks, independent of the product
    # of block count and number of empty buffer descriptors.
    assert dimension_work <= 4 * len(descriptors) + rows


@pytest.mark.parametrize("block_major", [False, True])
def test_mixed_buffers_and_ieee_bits_restore_in_original_order(block_major):
    arrays = [
        np.arange(10, dtype="<i2").reshape(5, 2),
        np.array([0, 2**63, 0x7FF8000000000123, 1, 0x7FF0000000000000], dtype="<u8").view("<f8"),
    ]
    header = {
        "buffers": [
            {
                "name": f"value/{i}",
                "dtype": a.dtype.str,
                "shape": list(a.shape),
                "payload_bytes": a.nbytes,
                "logical_bits": a.nbytes * 8,
            }
            for i, a in enumerate(arrays)
        ]
    }
    if block_major:
        header.update(payload_layout="BLOCK_MAJOR_BUFFER_ORDER", stream_block_size=2)
        data = b"".join(a[start : start + 2].tobytes() for start in range(0, 5, 2) for a in arrays)
    else:
        data = b"".join(a.tobytes() for a in arrays)
    decoded = decode_byte_payload(header, memoryview(data))
    for expected, observed in zip(arrays, decoded.buffers, strict=True):
        assert observed.array.dtype == expected.dtype
        assert observed.array.shape == expected.shape
        assert observed.array.tobytes() == expected.tobytes()
        assert not observed.array.flags.writeable
