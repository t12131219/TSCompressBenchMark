from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np
import pytest

from tsbench.artifact import EncodedObject, PREFIX, MAGIC, pack_bundle, read_bundle_prefix
from tsbench.data import TimeSeriesObject, array_order, fingerprint, load_dataset, object_id, project, raw_bytes
from tsbench.schemes import ObjectScheme, decode_once
from tsbench.validate import verify


def obj(array: np.ndarray) -> TimeSeriesObject:
    return TimeSeriesObject({"V": array}, {"roles": {"V": "V"}, "masked_value_policy": "preserve_all_bits"})


@pytest.mark.parametrize("array", [
    np.array([0x7FF8000000000001, 0x7FF8000000000002, 0x8000000000000000,
              0x7FF0000000000000, 0xFFF0000000000000], dtype=np.uint64).view(np.float64),
    np.array([0x7FC00001, 0x7FC00002, 0x80000000], dtype=np.uint32).view(np.float32),
    np.asfortranarray(np.arange(15, dtype=np.int16).reshape(5, 3)),
    np.empty((0, 2), dtype=np.float64),
])
def test_raw_store_preserves_bits_dtype_shape_and_order(array):
    original = obj(array)
    before = fingerprint(original)
    encoded = ObjectScheme({"id": "raw", "codec": "raw-store"}).encode_once(original)
    restored = decode_once(EncodedObject(bytes(encoded.wire)))
    assert verify(original, restored, {"fidelity": "bitwise"})["passed"]
    assert fingerprint(original) == before
    assert not np.shares_memory(restored.components["V"], array)
    assert encoded.stored_bytes == len(encoded.wire)
    assert encoded.stored_bytes > raw_bytes(original)  # Actual envelope is charged.


def test_records_projection_denominators_and_masked_bits():
    values = np.array([[1., -0.], [3., 99.]], dtype=np.float64)
    original = TimeSeriesObject({"V": values, "T": np.array([9, 9], dtype=np.int64),
                                "mask": np.array([[1, 1], [1, 0]], dtype=np.uint8)},
                               {"roles": {"V": "V", "T": "T", "mask": "mask"}, "time_unit": "ns"})
    assert raw_bytes(project(original, {"kind": "values"})) == values.nbytes + 4
    assert raw_bytes(project(original, {"kind": "timestamps"})) == 16
    assert raw_bytes(project(original, {"kind": "records"})) == 52
    wire = ObjectScheme({"id": "raw", "codec": "raw-store"}).encode_once(original)
    assert verify(original, decode_once(wire), {"fidelity": "bitwise"})["passed"]
    changed = {k: a.copy() for k, a in original.components.items()}
    changed["V"][1, 1] = 0
    assert not verify(original, TimeSeriesObject(changed, original.schema), {"fidelity": "bitwise"})["passed"]


def test_source_lineage_is_not_raw_content_identity():
    array = np.arange(5, dtype=np.float32)
    first = TimeSeriesObject({"V": array}, {"roles": {"V": "V"}}, {"path": "one.npy"})
    second = TimeSeriesObject({"V": array.copy()}, first.schema, {"path": "two.npy"})
    assert object_id(first) == object_id(second)
    assert object_id(first) != object_id(obj(array.astype(np.float64)))


def test_wire_only_new_process_recovers_without_original_or_encoder_config(tmp_path):
    original = obj(np.asfortranarray(np.arange(21, dtype=np.float32).reshape(7, 3)))
    encoded = ObjectScheme({"id": "raw", "codec": "raw-store"}).encode_once(original)
    wire = tmp_path / "saved.tsb"
    wire.write_bytes(encoded.wire)
    destination = tmp_path / "decoder-only"
    result = subprocess.run([sys.executable, "-m", "tsbench.worker", "decode", str(wire), str(destination)],
                            capture_output=True, text=True, timeout=30, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    metadata = json.loads((destination / "object.json").read_text())
    restored = TimeSeriesObject({k: np.load(destination / v, allow_pickle=False)
                                for k, v in metadata["components"].items()}, metadata["schema"])
    assert verify(original, restored, {"fidelity": "bitwise"})["passed"]


@pytest.mark.parametrize("wire", [b"", b"TSB4", PREFIX.pack(MAGIC, 999, 0),
                                 PREFIX.pack(MAGIC, 1, 2**31), PREFIX.pack(MAGIC, 1, 3) + b"{}"])
def test_wire_prefix_rejects_truncation_and_unknown_versions(wire):
    with pytest.raises(ValueError):
        read_bundle_prefix(wire)


def test_wire_json_rejects_duplicate_keys_and_nonfinite_numbers():
    for header in (b'{"schema":1,"schema":2}', b'{"x":NaN}', b'{"x":Infinity}'):
        with pytest.raises(ValueError):
            read_bundle_prefix(PREFIX.pack(MAGIC, 1, len(header)) + header)


def test_wire_header_integrity_protects_integer_transform_in_standalone_decoder(tmp_path):
    original = TimeSeriesObject({'T': np.array([0, 60_000_000_000], dtype='<i8')}, {'roles': {'T': 'T'}})
    encoded = ObjectScheme({'codec': 'raw-store', 'transform': 'integer_affine_gcd'}).encode_once(original)
    magic, version, size = PREFIX.unpack_from(encoded.wire)
    assert version == 2
    header = encoded.wire[PREFIX.size:PREFIX.size+size]
    changed = header.replace(b'"bias":0', b'"bias":1')
    assert changed != header and len(changed) == len(header)
    damaged = PREFIX.pack(magic, version, size) + changed + encoded.wire[PREFIX.size+size:]
    wire = tmp_path/'damaged.tsb'
    wire.write_bytes(damaged)
    result = subprocess.run([sys.executable, '-m', 'tsbench.worker', 'decode', str(wire), str(tmp_path/'restored')],
                            capture_output=True, text=True, timeout=30, env=os.environ.copy())
    assert result.returncode != 0 and 'descriptor checksum mismatch' in result.stderr
    assert not (tmp_path/'restored/object.json').exists()
    descriptor, body = read_bundle_prefix(encoded.wire)
    del descriptor['descriptor_sha256']
    missing = json.dumps(descriptor, separators=(',', ':')).encode()
    with pytest.raises(ValueError, match='descriptor checksum'):
        read_bundle_prefix(PREFIX.pack(MAGIC, 2, len(missing)) + missing + body)


def test_historical_wire_version_one_remains_decodable():
    original = obj(np.arange(5, dtype='<i2'))
    artifact = ObjectScheme({'codec':'raw-store'}).encode_once(original)
    descriptor, body = read_bundle_prefix(artifact.wire)
    del descriptor['descriptor_sha256']
    header = json.dumps(descriptor, sort_keys=True, separators=(',', ':')).encode()
    legacy = EncodedObject(PREFIX.pack(MAGIC, 1, len(header)) + header + body)
    assert verify(original, decode_once(legacy), {'fidelity':'bitwise'})['passed']


def test_decoder_rejects_corruption_unaccounted_bytes_and_overlarge_shape():
    encoded = ObjectScheme({"id": "raw", "codec": "raw-store"}).encode_once(obj(np.arange(5, dtype=np.int16)))
    descriptor, body = read_bundle_prefix(encoded.wire)
    for corrupt in (body[:-1] + bytes([body[-1] ^ 1]), body + b"unaccounted"):
        with pytest.raises(ValueError):
            decode_once(EncodedObject(pack_bundle(descriptor, corrupt)))
    oversized = copy.deepcopy(descriptor)
    oversized["components"][0]["shape"] = [2**31]
    with pytest.raises(ValueError):
        decode_once(EncodedObject(pack_bundle(oversized, body)))


def test_decoder_rejects_overlapping_payload_intervals():
    encoded = ObjectScheme({"id": "raw", "codec": "raw-store"}).encode_once(obj(np.arange(5, dtype=np.int16)))
    descriptor, body = read_bundle_prefix(encoded.wire)
    descriptor["components"][0]["parts"] *= 2
    with pytest.raises(ValueError):
        decode_once(EncodedObject(pack_bundle(descriptor, body)))


def test_loader_preserves_npy_precision_and_requires_csv_rules(tmp_path):
    path = tmp_path / "source.npy"
    np.save(path, np.array([1.25, 2.5], dtype=np.float32))
    loaded = load_dataset({"id": "f32", "path": path.name, "format": "npy"}, tmp_path)
    assert loaded.components["V"].dtype == np.dtype("float32")
    assert not loaded.components["V"].flags.writeable
    csv = tmp_path / "source.csv"
    csv.write_text("date,x\n1970-01-01 00:00:00,1.25\n1970-01-01 00:00:01,\n")
    with pytest.raises(ValueError, match="dtype"):
        load_dataset({"id": "csv", "path": csv.name, "format": "csv"}, tmp_path)
    loaded = load_dataset({"id": "csv", "path": csv.name, "format": "csv", "dtype": "<f4",
                           "columns": ["x"], "timestamp_column": "date", "timestamp_parser": "datetime64",
                           "time_unit": "ns", "missing": "mask", "fill_value": -12}, tmp_path)
    assert loaded.components["T"].tolist() == [0, 1_000_000_000]
    assert loaded.components["mask"].tolist() == [1, 0]
    assert loaded.components["V"].tolist() == [1.25, -12]


def test_integer_csv_overflow_is_rejected_before_cast(tmp_path):
    (tmp_path / "overflow.csv").write_text("x\n256\n")
    with pytest.raises(ValueError, match="overflow"):
        load_dataset({"path": "overflow.csv", "format": "csv", "columns": ["x"], "dtype": "|u1"}, tmp_path)
