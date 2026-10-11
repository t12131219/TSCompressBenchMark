"""Validate untrusted typed byte containers before allocation or native calls.

The default 1 GiB limit is a decoder resource policy, not a codec value-domain
claim. Callers with a larger, independently budgeted object can explicitly pass
``max_output_bytes``. This does not change any encoded wire format.
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any

import numpy as np

from tscompbench.execution.protocol import DecodedOutput, ExecutionContractError, LogicalBuffer

DEFAULT_MAX_OUTPUT_BYTES = 1 << 30
MAX_METADATA_BYTES = 1 << 20
MAX_BUFFERS = 65536
_DTYPES = {"<i8", "<i4", "<i2", "|i1", "<u8", "<u4", "<u2", "|u1", "<f8", "<f4", "|b1"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate metadata key")
        result[key] = value
    return result


def parse_byte_metadata(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_METADATA_BYTES:
        raise ExecutionContractError("byte container metadata exceeds decoder resource limit")
    try:
        header = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ExecutionContractError("invalid byte container metadata") from error
    if not isinstance(header, dict):
        raise ExecutionContractError("byte container metadata must be an object")
    return header


def validate_byte_descriptors(
    header: dict[str, Any], *, max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
) -> tuple[list[dict[str, Any]], int]:
    if type(max_output_bytes) is not int or not 0 <= max_output_bytes <= sys.maxsize:
        raise ExecutionContractError("invalid decoder output resource limit")
    descriptors = header.get("buffers")
    if not isinstance(descriptors, list) or not 1 <= len(descriptors) <= MAX_BUFFERS:
        raise ExecutionContractError("invalid byte container buffer descriptor count")
    total = 0
    names: set[str] = set()
    for item in descriptors:
        if not isinstance(item, dict):
            raise ExecutionContractError("byte buffer descriptor must be an object")
        name, dtype, shape = item.get("name"), item.get("dtype"), item.get("shape")
        length, bits = item.get("payload_bytes"), item.get("logical_bits")
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or not isinstance(dtype, str)
            or dtype not in _DTYPES
            or not isinstance(shape, list)
            or not 1 <= len(shape) <= 4
            or any(type(n) is not int or not 0 <= n <= sys.maxsize for n in shape)
            or type(length) is not int
            or length < 0
            or type(bits) is not int
            or bits < 0
        ):
            raise ExecutionContractError("invalid byte buffer descriptor")
        itemsize = np.dtype(dtype).itemsize
        # Check nonzero dimensions too: zero-size arrays still need representable
        # NumPy strides and shape. Python integers avoid int64 product overflow.
        if math.prod(n for n in shape if n) > sys.maxsize // itemsize:
            raise ExecutionContractError("byte descriptor shape exceeds addressable size")
        elements = math.prod(shape)
        if elements * itemsize != length:
            raise ExecutionContractError("byte descriptor shape/dtype/length mismatch")
        expected_bits = elements if name == "validity" and dtype == "|b1" else length * 8
        if bits != expected_bits:
            raise ExecutionContractError("byte descriptor logical bit count mismatch")
        total += length
        if total > max_output_bytes:
            raise ExecutionContractError("byte output exceeds decoder resource limit")
        names.add(name)
    layout = header.get("payload_layout")
    if layout is not None and layout != "BLOCK_MAJOR_BUFFER_ORDER":
        raise ExecutionContractError("unsupported byte payload layout")
    if layout == "BLOCK_MAJOR_BUFFER_ORDER":
        block_size = header.get("stream_block_size")
        if type(block_size) is not int or not 1 <= block_size <= sys.maxsize:
            raise ExecutionContractError("invalid streaming block size")
        if any(item["shape"][0] != descriptors[0]["shape"][0] for item in descriptors):
            raise ExecutionContractError("stream buffer row counts disagree")
    return descriptors, total


def decode_byte_payload(
    header: dict[str, Any], payload: memoryview, *, max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
) -> DecodedOutput:
    descriptors, total = validate_byte_descriptors(header, max_output_bytes=max_output_bytes)
    if len(payload) != total:
        raise ExecutionContractError("byte decoded payload length disagrees with metadata")
    if header.get("payload_layout") == "BLOCK_MAJOR_BUFFER_ORDER":
        separated = [bytearray() for _ in descriptors]
        cursor = 0
        # Empty multidimensional buffers may have a huge row dimension. They
        # require no payload traversal; iterating those rows would be unbounded
        # work for a zero-byte object.
        rows_to_restore = descriptors[0]["shape"][0] if total else 0
        for offset in range(0, rows_to_restore, header["stream_block_size"]):
            rows = min(header["stream_block_size"], descriptors[0]["shape"][0] - offset)
            for index, descriptor in enumerate(descriptors):
                length = (
                    rows
                    * math.prod(descriptor["shape"][1:])
                    * np.dtype(descriptor["dtype"]).itemsize
                )
                separated[index].extend(payload[cursor : cursor + length])
                cursor += length
        chunks = separated
    else:
        chunks = []
        cursor = 0
        for descriptor in descriptors:
            end = cursor + descriptor["payload_bytes"]
            chunks.append(payload[cursor:end])
            cursor = end
    decoded = []
    for descriptor, chunk in zip(descriptors, chunks, strict=True):
        array = np.frombuffer(chunk, dtype=descriptor["dtype"]).copy().reshape(descriptor["shape"])
        array.flags.writeable = False
        decoded.append(LogicalBuffer(descriptor["name"], array, descriptor["logical_bits"]))
    return DecodedOutput(tuple(decoded))
