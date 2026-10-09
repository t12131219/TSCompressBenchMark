from __future__ import annotations

import ctypes
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.accounting import AccountingLedger
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import (
    DecodedOutput,
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
    SourceDomainError,
)
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.planning.sweep import PlanningError, _normalize_value, _validate_constraints

_PREFIX = struct.Struct("<8sI32s32s")
_RECORD = struct.Struct("<QQ")
_MAGIC = b"TSCBCR1\0"
_HISTOGRAMS = {"prometheus-histogram-st", "prometheus-float-histogram-st"}
_HISTOGRAM_UNITS = (
    "HISTOGRAM_ST_INT64_BITS",
    "HISTOGRAM_COUNT_BITS",
    "HISTOGRAM_ZERO_COUNT_BITS",
    "HISTOGRAM_SUM_BINARY64_BITS",
    "HISTOGRAM_ZERO_THRESHOLD_BINARY64_BITS",
    "HISTOGRAM_BUCKET_BITS",
)


class _Config(ctypes.Structure):
    _fields_ = [
        ("rows", ctypes.c_uint64),
        ("columns", ctypes.c_uint64),
        *[(key, ctypes.c_uint32) for key in ("a", "b", "c", "d", "seed", "mode")],
        *[(key, ctypes.c_double) for key in ("x", "y", "z")],
        ("model", ctypes.c_char_p),
    ]


def _domain(reason: str) -> None:
    error = SourceDomainError(reason)
    error.rejection_atomic = True
    raise error


@dataclass(frozen=True)
class CompletedRewriteAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> CompletedRewriteSession:
        return CompletedRewriteSession(
            self.library_path, self.manifest_adapter, self.algorithm, parameters
        )


class CompletedRewriteSession:
    def __init__(
        self, path: Path, manifest: dict[str, Any], algorithm: str, parameters: dict[str, Any]
    ):
        self.algorithm, self.manifest = algorithm, manifest
        self.parameters = self._parameters(parameters)
        parameters = self.parameters
        self._library = ctypes.CDLL(str(path))
        lib = self._library
        lib.rw_version.restype = ctypes.c_uint32
        lib.rw_algorithm.restype = ctypes.c_char_p
        if lib.rw_version() != 1 or lib.rw_algorithm().decode() != algorithm:
            raise ExecutionContractError("completed rewrite binary identity mismatch")
        ptr, size = ctypes.c_void_p, ctypes.c_size_t
        lib.rw_bound.argtypes = [
            ctypes.POINTER(_Config),
            ptr,
            size,
            ctypes.POINTER(size),
            ptr,
            size,
        ]
        lib.rw_encode.argtypes = [
            ctypes.POINTER(_Config),
            ptr,
            size,
            ptr,
            size,
            ctypes.POINTER(size),
            ptr,
            size,
        ]
        lib.rw_decode.argtypes = [ptr, size, ptr, size, ctypes.POINTER(size), ptr, size]
        for name in ("rw_bound", "rw_encode", "rw_decode"):
            getattr(lib, name).restype = ctypes.c_int
        self._closed = False
        self._updated = False
        self._finalized = False
        self._model = b""
        self._alphabet_size = None
        self._model_verified = False
        self._model_record = None
        model_key = parameters.get("model_key")
        if model_key is not None:
            record = manifest["models"][model_key]
            model = path.resolve().parents[4] / record["path"]
            self._model = str(model).encode()
            self._alphabet_size = record.get("alphabet_size")
            self._model_record = record

    def _ensure_model(self):
        if self._model_verified or self._model_record is None:
            return
        model = Path(self._model.decode())
        if hashlib.sha256(model.read_bytes()).hexdigest() != self._model_record["sha256"]:
            raise ExecutionContractError("model hash mismatch")
        if self.algorithm == "deepzip":
            lib = self._library
            ptr = ctypes.c_void_p
            size = ctypes.c_size_t
            lib.rw_model_alphabet.argtypes = [
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_uint32),
                ptr,
                size,
            ]
            lib.rw_model_alphabet.restype = ctypes.c_int
            width = ctypes.c_uint32()
            error = ctypes.create_string_buffer(2048)
            if (
                lib.rw_model_alphabet(self._model, ctypes.byref(width), error, len(error))
                or width.value != self._alphabet_size
            ):
                raise ExecutionContractError(
                    "native model alphabet differs from frozen model contract"
                )
        self._model_verified = True

    def _parameters(self, parameters):
        contract = self.manifest["parameter_contract"]
        specs = contract["properties"]
        try:
            if not isinstance(parameters, dict) or set(parameters) - set(specs):
                raise PlanningError("unknown rewrite parameters")
            normalized = {
                key: _normalize_value(parameters.get(key, spec["default"]), spec)
                for key, spec in specs.items()
            }
            _validate_constraints(normalized, contract["constraints"])
            if any(
                isinstance(value, str)
                and specs[key]["type"] == "decimal-string"
                and not np.isfinite(float(value))
                for key, value in normalized.items()
            ):
                raise PlanningError("decimal parameter exceeds native binary64 range")
            return normalized
        except (PlanningError, ValueError, OverflowError) as error:
            raise ExecutionContractError(str(error)) from error

    def _config(self, rows: int, columns: int = 1) -> _Config:
        p = self.parameters
        c = _Config(rows, columns, 0, 0, 0, 0, p.get("model_seed", 0), 0, 0, 0, 0, self._model)
        if self.algorithm == "abba":
            c.a, c.b, c.c, c.d = p["min_k"], p["max_k"], p["max_len"], p["norm"]
            c.x, c.y, c.z = (
                float(p["compression_tolerance"]),
                float(p["digitization_tolerance"]),
                float(p["scl"]),
            )
            c.mode = int(p["clustering"] == "INCREMENTAL")
        elif self.algorithm == "fabba":
            c.a = p["max_len"]
            c.x, c.y, c.z = float(p["tolerance"]), float(p["alpha"]), float(p["scl"])
        elif self.algorithm == "influxdb-tsm-adaptive-timestamp":
            c.mode = int(p["encoding_profile"] == "BATCH")
        elif self.algorithm in {"tristan", "corad"}:
            c.a, c.b, c.c, c.d = p["window_size"], p["atoms"], p["nonzeros"], p["requested_n_iter"]
            c.x = float(p["alpha"])
            c.mode = p["solver"]
            if self.algorithm == "corad":
                c.y = float(p["correlation_threshold"])
        elif self.algorithm == "deepzip":
            c.a = p["lanes"]
        elif self.algorithm == "dzip":
            c.mode = int(p["mode"] == "COMBINED")
        return c

    def _native(
        self, operation: str, data: bytes, config: _Config | None = None, capacity: int = 0
    ) -> bytes | int:
        if self._closed:
            raise ExecutionContractError("session closed")
        error = ctypes.create_string_buffer(2048)
        used = ctypes.c_size_t()
        source = ctypes.create_string_buffer(data, max(1, len(data)))
        if operation == "bound":
            status = self._library.rw_bound(
                ctypes.byref(config), source, len(data), ctypes.byref(used), error, len(error)
            )
        else:
            output = ctypes.create_string_buffer(max(1, capacity))
            args = [source, len(data), output, capacity, ctypes.byref(used), error, len(error)]
            if operation == "encode":
                args.insert(0, ctypes.byref(config))
            status = getattr(self._library, "rw_" + operation)(*args)
        if status == 3:
            raise OutputCapacityError("completed rewrite native output capacity")
        if (
            status
            and self.algorithm in {"tristan", "corad"}
            and operation == "encode"
            and error.value.decode()
            in {"Invalid population standard deviation", "Nonfinite normalized input"}
        ):
            _domain("NORMALIZATION_ARITHMETIC_UNSUPPORTED")
        if status:
            raise ExecutionContractError(
                f"{self.algorithm} {operation}: {error.value.decode(errors='replace')}"
            )
        if operation == "bound":
            return used.value
        if used.value > capacity:
            raise ExecutionContractError("native output exceeds capacity")
        return output.raw[: used.value]

    def _validate(self, routed: RoutedInput) -> None:
        track = (
            BenchmarkTrack.TIMESTAMP
            if self.algorithm == "influxdb-tsm-adaptive-timestamp"
            else BenchmarkTrack.SYSTEM
            if self.algorithm == "prometheus-xor2-chunk" or self.algorithm in _HISTOGRAMS
            else BenchmarkTrack.VALUE
        )
        if routed.track is not track or routed.validity_reference is not None:
            raise ExecutionContractError("unsupported rewrite track/validity")
        contract = self.manifest["input_contract"]
        if (
            not contract["min_n"] <= routed.n <= contract["max_n"]
            or not contract["min_m"] <= routed.m <= contract["max_m"]
            or routed.n * routed.m > 16777216
        ):
            raise ExecutionContractError("unsupported rewrite dimensions")
        names = [b.name for b in routed.buffers]
        if len(names) != len(set(names)) or not names:
            raise ExecutionContractError("duplicate or absent logical buffers")
        if track in {BenchmarkTrack.TIMESTAMP, BenchmarkTrack.SYSTEM}:
            if names[0] != "timestamp" or names.count("timestamp") != 1:
                raise ExecutionContractError("timestamp must be first and unique")
            if routed.timestamp_reference is None or not np.array_equal(
                routed.timestamp_reference, routed.buffers[0].array
            ):
                raise ExecutionContractError("timestamp pairing reference mismatch")
            if track is BenchmarkTrack.TIMESTAMP and len(names) != 1:
                raise ExecutionContractError("timestamp track has extra fields")
            if track is BenchmarkTrack.SYSTEM and not routed.segment_plan_id:
                raise ExecutionContractError("system segment plan required")
        elif "timestamp" in names:
            raise ExecutionContractError("value track contains timestamps")
        value_names = (
            names[1:]
            if track is BenchmarkTrack.SYSTEM
            else []
            if track is BenchmarkTrack.TIMESTAMP
            else names
        )
        expected_names = (
            [value_names[0]]
            if len(value_names) == 1
            and routed.buffers[-1].array.ndim == 2
            and value_names[0] in {"value/matrix", "value/000000"}
            else [f"value/{i:06d}" for i in range(routed.m)]
        )
        if value_names and value_names != expected_names:
            raise ExecutionContractError("logical value roles mismatch")
        if contract.get("required_value_units") and tuple(routed.value_units) != tuple(
            contract["required_value_units"]
        ):
            raise ExecutionContractError("required value units mismatch")
        # Canonical bits describe the original logical view. Compatibility
        # preparation can widen its dtype; buffer bits describe the codec view.
        if (type(routed.canonical_raw_bits) is not int
            or routed.canonical_raw_bits < sum(b.array.size for b in routed.buffers) * 8
            or routed.canonical_raw_bits % 8):
            raise ExecutionContractError("invalid canonical bit accounting")
        allowed = (
            {"<i8"}
            if track is BenchmarkTrack.TIMESTAMP
            else {"<u8"}
            if self.algorithm in _HISTOGRAMS
            else {"<u1", "|u1"}
            if self.algorithm in {"deepzip", "dzip"}
            else {"<f4"}
            if self.algorithm == "walloc-1d"
            else {"<f8"}
        )
        for b in routed.buffers:
            if b.name == "timestamp":
                if b.array.dtype.str != "<i8" or b.array.shape != (routed.n,):
                    raise ExecutionContractError("timestamp contract mismatch")
            elif b.array.dtype.str not in allowed:
                raise ExecutionContractError("rewrite dtype unsupported")
            if b.logical_bits != b.array.nbytes * 8:
                raise ExecutionContractError("logical buffer bits mismatch")
        if self.algorithm in {"abba", "fabba", "tristan", "corad", "walloc-1d"}:
            if any(not np.all(np.isfinite(b.array)) for b in routed.buffers):
                _domain("FINITE_INPUT_REQUIRED")
        if self.algorithm in {"abba", "fabba"} and routed.n < 2:
            raise ExecutionContractError("segmentation requires at least two samples")
        if self.algorithm in {"abba", "fabba"}:
            for column in self._columns(routed):
                with np.errstate(all="ignore"):
                    residual = column[:-1] + (column[1:] - column[:-1]) - column[1:]
                    error = (
                        np.abs(residual)
                        if self.algorithm == "abba" and self.parameters["norm"] == 1
                        else residual * residual
                    )
                if np.any(~np.isfinite(error)) or np.any(error > np.finfo(np.float64).eps):
                    _domain("SEGMENT_ENDPOINT_ARITHMETIC_UNSUPPORTED")
        if self.algorithm in {"tristan", "corad"}:
            size = self.parameters["window_size"]
            if routed.n < size or routed.n % size:
                _domain("INCOMPLETE_WINDOW_UNSUPPORTED")
            for b in routed.buffers:
                a = b.array.reshape(routed.n, -1)
                if np.any(np.all(a == a[0], axis=0)):
                    _domain("CONSTANT_COLUMN_UNSUPPORTED")
        if self.algorithm == "deepzip" and any(
            np.any(b.array >= self._alphabet_size) for b in routed.buffers
        ):
            _domain("MODEL_ALPHABET_UNSUPPORTED")
        if self.algorithm == "dzip" and any(
            np.unique(column).size == 9 for column in self._columns(routed)
        ):
            _domain("MODEL_ALPHABET_UNSUPPORTED")
        if self.algorithm == "walloc-1d" and routed.m != 2:
            raise ExecutionContractError("WaLLoC stereo input required")
        if self.algorithm in _HISTOGRAMS and (
            routed.m != 6 or routed.n > 16383 or tuple(routed.value_units) != _HISTOGRAM_UNITS
        ):
            raise ExecutionContractError("explicit Histogram-ST record schema required")

    def _columns(self, routed: RoutedInput) -> list[np.ndarray[Any]]:
        value = [b.array for b in routed.buffers if b.name != "timestamp"]
        if len(value) == 1 and value[0].ndim == 2:
            if value[0].shape != (routed.n, routed.m):
                raise ExecutionContractError("value matrix dimensions mismatch")
            return [value[0][:, i] for i in range(routed.m)]
        if len(value) != routed.m or any(a.shape != (routed.n,) for a in value):
            raise ExecutionContractError("all value columns must be present")
        return value

    def _inputs(self, routed: RoutedInput) -> list[tuple[bytes, _Config, int]]:
        self._ensure_model()
        self._validate(routed)
        if routed.track is BenchmarkTrack.TIMESTAMP:
            return [(routed.buffers[0].array.tobytes(), self._config(routed.n), routed.n * 8)]
        columns = self._columns(routed)
        if self.algorithm in _HISTOGRAMS:
            a = np.column_stack([routed.buffers[0].array.view("<u8"), *columns])
            return [(a.tobytes(), self._config(routed.n, 7), a.nbytes)]
        if self.algorithm == "prometheus-xor2-chunk":
            if routed.n > 65535:
                raise ExecutionContractError("XOR2 sample limit")
            timestamps = routed.buffers[0].array.view("<u8")
            result = []
            for column in columns:
                a = np.empty((routed.n, 3), dtype="<u8")
                a[:, 0] = np.uint64(self.parameters["start_timestamp"] % (1 << 64))
                a[:, 1] = timestamps
                a[:, 2] = column.view("<u8")
                result.append((a.tobytes(), self._config(routed.n), routed.n * 24))
            return result
        if self.algorithm in {"tristan", "corad"}:
            a = np.column_stack(columns)
            return [(a.tobytes(), self._config(routed.n, routed.m), a.nbytes)]
        if self.algorithm == "walloc-1d":
            a = np.stack(columns)
            return [(a.tobytes(), self._config(routed.n, routed.m), a.nbytes)]
        return [
            (np.ascontiguousarray(a).tobytes(), self._config(routed.n), a.nbytes) for a in columns
        ]

    def _header(self, routed: RoutedInput) -> bytes:
        return canonical_json_bytes(
            {
                "schema_version": "tscb.completed-rewrite-container.v1",
                "algorithm": self.algorithm,
                "rows": routed.n,
                "columns": routed.m,
                "track": routed.track,
                "segment_plan_id": routed.segment_plan_id,
                "timestamp_unit": routed.timestamp_unit,
                "timestamp_epoch": routed.timestamp_epoch,
                "value_units": routed.value_units,
                "parameters": self.parameters,
                "buffers": [
                    {
                        "name": b.name,
                        "dtype": b.array.dtype.str,
                        "shape": list(b.array.shape),
                        "logical_bits": b.logical_bits,
                    }
                    for b in routed.buffers
                ],
            }
        )

    def output_bound(self, routed: RoutedInput) -> int:
        return (
            _PREFIX.size
            + len(self._header(routed))
            + sum(
                _RECORD.size + self._native("bound", data, c) for data, c, _ in self._inputs(routed)
            )
        )

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated or self._finalized:
            raise ExecutionContractError("fresh session required")
        bound = self.output_bound(routed)
        if len(destination) < bound:
            raise OutputCapacityError("completed rewrite bound capacity")
        payload = bytearray()
        for data, c, raw_size in self._inputs(routed):
            capacity = self._native("bound", data, c)
            frame = self._native("encode", data, c, capacity)
            payload += _RECORD.pack(len(frame), raw_size) + frame
        header = self._header(routed)
        stream = (
            _PREFIX.pack(
                _MAGIC,
                len(header),
                hashlib.sha256(header).digest(),
                hashlib.sha256(payload).digest(),
            )
            + header
            + payload
        )
        if len(stream) > len(destination):
            raise OutputCapacityError("completed rewrite final stream capacity")
        destination[: len(stream)] = stream
        self._updated = True
        return len(stream)

    def finalize(self, destination: memoryview) -> int:
        if self._closed or not self._updated or self._finalized:
            raise ExecutionContractError("exactly one finalize required")
        self._finalized = True
        return 0

    def _parse(self, stream: bytes) -> tuple[dict[str, Any], list[tuple[bytes, int]], int]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated rewrite container")
        magic, size, hd, pd = _PREFIX.unpack_from(stream)
        if magic != _MAGIC or size > min(16 << 20, len(stream) - _PREFIX.size):
            raise ExecutionContractError("invalid rewrite prefix")
        header = stream[_PREFIX.size : _PREFIX.size + size]
        payload = stream[_PREFIX.size + size :]
        if hashlib.sha256(header).digest() != hd or hashlib.sha256(payload).digest() != pd:
            raise ExecutionContractError("rewrite checksum mismatch")
        try:
            desc = json.loads(header)
            self._check_descriptor(desc)
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            raise ExecutionContractError("invalid rewrite descriptor") from error
        if (
            desc["algorithm"] != self.algorithm
            or desc["schema_version"] != "tscb.completed-rewrite-container.v1"
        ):
            raise ExecutionContractError("rewrite identity mismatch")
        if (
            desc["rows"] < 0
            or not 1 <= desc["columns"] <= 65535
            or desc["rows"] * desc["columns"] > 16777216
        ):
            raise ExecutionContractError("decoded dimensions exceed limit")
        records = []
        offset = 0
        while offset < len(payload):
            if len(payload) - offset < _RECORD.size:
                raise ExecutionContractError("truncated rewrite record")
            length, raw_size = _RECORD.unpack_from(payload, offset)
            offset += _RECORD.size
            if length > len(payload) - offset or raw_size > 512 << 20:
                raise ExecutionContractError("invalid rewrite record length")
            records.append((payload[offset : offset + length], raw_size))
            offset += length
            if len(records) > 65535:
                raise ExecutionContractError("too many rewrite records")
        expected = (
            1
            if self.algorithm
            in {"tristan", "corad", "walloc-1d", "influxdb-tsm-adaptive-timestamp"}
            or self.algorithm in _HISTOGRAMS
            else desc["columns"]
        )
        if len(records) != expected:
            raise ExecutionContractError("rewrite record count mismatch")
        stride = (
            56
            if self.algorithm in _HISTOGRAMS
            else 24
            if self.algorithm == "prometheus-xor2-chunk"
            else np.dtype(desc["buffers"][-1]["dtype"]).itemsize
        )
        raw_size = (
            desc["rows"]
            * stride
            * (desc["columns"] if self.algorithm in {"tristan", "corad", "walloc-1d"} else 1)
        )
        if any(capacity != raw_size for _, capacity in records):
            raise ExecutionContractError("decoded record capacity differs from logical dimensions")
        return desc, records, _PREFIX.size + size + len(records) * _RECORD.size

    def _check_descriptor(self, desc):
        if not isinstance(desc, dict) or set(desc) != {
            "schema_version",
            "algorithm",
            "rows",
            "columns",
            "track",
            "segment_plan_id",
            "timestamp_unit",
            "timestamp_epoch",
            "value_units",
            "parameters",
            "buffers",
        }:
            raise ValueError("descriptor keys")
        n, m = desc["rows"], desc["columns"]
        contract = self.manifest["input_contract"]
        if (
            type(n) is not int
            or type(m) is not int
            or not contract["min_n"] <= n <= contract["max_n"]
            or not contract["min_m"] <= m <= contract["max_m"]
            or n * m > 16777216
        ):
            raise ValueError("dimensions")
        track = (
            "TIMESTAMP"
            if self.algorithm == "influxdb-tsm-adaptive-timestamp"
            else "SYSTEM"
            if self.algorithm == "prometheus-xor2-chunk" or self.algorithm in _HISTOGRAMS
            else "VALUE"
        )
        if desc["track"] != track or self._parameters(desc["parameters"]) != desc["parameters"]:
            raise ValueError("track or parameters")
        buffers = desc["buffers"]
        if not isinstance(buffers, list) or not buffers:
            raise ValueError("buffers")
        values = buffers[1:] if track == "SYSTEM" else [] if track == "TIMESTAMP" else buffers
        matrix = len(values) == 1 and values[0].get("shape") == [n, m]
        expected_names = (
            [values[0]["name"]]
            if matrix and values[0]["name"] in {"value/matrix", "value/000000"}
            else [f"value/{i:06d}" for i in range(m)]
        )
        if [b["name"] for b in values] != expected_names and track != "TIMESTAMP":
            raise ValueError("value roles")
        if track in {"SYSTEM", "TIMESTAMP"} and (
            buffers[0]["name"] != "timestamp" or track == "TIMESTAMP" and len(buffers) != 1
        ):
            raise ValueError("timestamp role")
        for b in buffers:
            if set(b) != {"name", "dtype", "shape", "logical_bits"}:
                raise ValueError("buffer keys")
            dtype = np.dtype(b["dtype"])
            allowed = (
                ["<i8"]
                if b["name"] == "timestamp"
                else contract.get("component_dtypes", {}).get("value", contract["dtypes"])
            )
            is_matrix = matrix and b is values[0]
            if (
                b["dtype"] not in allowed
                or b["shape"] != ([n, m] if is_matrix else [n])
                or type(b["logical_bits"]) is not int
                or b["logical_bits"] != n * (m if is_matrix else 1) * dtype.itemsize * 8
            ):
                raise ValueError("logical buffer descriptor")
        if (
            contract.get("required_value_units")
            and desc["value_units"] != contract["required_value_units"]
        ):
            raise ValueError("value units")
        if (
            not isinstance(desc["value_units"], list)
            or (track != "TIMESTAMP" and len(desc["value_units"]) not in {m, 1, 0})
            or any(not isinstance(x, str) for x in desc["value_units"])
        ):
            raise ValueError("units")
        if track == "SYSTEM" and not isinstance(desc["segment_plan_id"], str):
            raise ValueError("segment plan")

    def decompress(self, stream: bytes) -> DecodedOutput:
        if self._closed:
            raise ExecutionContractError("session closed")
        desc, records, _ = self._parse(stream)
        decoded = [self._native("decode", data, capacity=capacity) for data, capacity in records]
        if any(len(data) != capacity for data, (_, capacity) in zip(decoded, records, strict=True)):
            raise ExecutionContractError("native decoded length differs from descriptor")
        n, m = desc["rows"], desc["columns"]
        if self.algorithm in _HISTOGRAMS:
            a = np.frombuffer(decoded[0], dtype="<u8").reshape(n, 7)
            arrays = [a[:, 0].view("<i8"), *[a[:, i] for i in range(1, 7)]]
        elif self.algorithm == "prometheus-xor2-chunk":
            triples = [np.frombuffer(data, dtype="<u8").reshape(n, 3) for data in decoded]
            if any(not np.array_equal(a[:, 1], triples[0][:, 1]) for a in triples):
                raise ExecutionContractError("XOR2 timestamp pairing mismatch")
            if any(
                np.any(a[:, 0] != (desc["parameters"]["start_timestamp"] % (1 << 64)))
                for a in triples
            ):
                raise ExecutionContractError("XOR2 start timestamp mismatch")
            arrays = [triples[0][:, 1].view("<i8"), *[a[:, 2].view("<f8") for a in triples]]
        elif self.algorithm in {"tristan", "corad", "walloc-1d"}:
            dtype = desc["buffers"][0]["dtype"]
            matrix = np.frombuffer(decoded[0], dtype=dtype).reshape(
                (m, n) if self.algorithm == "walloc-1d" else (n, m)
            )
            if self.algorithm == "walloc-1d":
                matrix = matrix.T
            arrays = (
                [matrix]
                if len(desc["buffers"]) == 1 and len(desc["buffers"][0]["shape"]) == 2
                else [matrix[:, i] for i in range(m)]
            )
        elif len(desc["buffers"]) == 1 and len(desc["buffers"][0]["shape"]) == 2:
            arrays = [
                np.column_stack(
                    [np.frombuffer(data, dtype=desc["buffers"][0]["dtype"]) for data in decoded]
                )
            ]
        else:
            arrays = [
                np.frombuffer(data, dtype=b["dtype"])
                for data, b in zip(decoded, desc["buffers"], strict=True)
            ]
        if (
            desc["track"] == "SYSTEM"
            and len(desc["buffers"]) == 2
            and desc["buffers"][1]["shape"] == [n, m]
        ):
            arrays = [arrays[0], np.column_stack(arrays[1:])]
        buffers = []
        for a, b in zip(arrays, desc["buffers"], strict=True):
            a = np.array(a, copy=True, order="C")
            if (
                list(a.shape) != b["shape"]
                or a.dtype.str != b["dtype"]
                or a.nbytes * 8 != b["logical_bits"]
            ):
                raise ExecutionContractError("decoded logical descriptor mismatch")
            a.flags.writeable = False
            buffers.append(LogicalBuffer(b["name"], a, b["logical_bits"]))
        return DecodedOutput(tuple(buffers))

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if self._closed or not self._finalized:
            raise ExecutionContractError("accounting requires open finalized session")
        desc, records, overhead = self._parse(stream)
        if desc != json.loads(self._header(routed)):
            raise ExecutionContractError("accounting descriptor mismatch")
        total = len(stream) * 8
        components = {"container_bits": overhead * 8}
        bucket = (
            "unallocated_shared_bits"
            if routed.track is BenchmarkTrack.SYSTEM
            else "timestamp_bits"
            if routed.track is BenchmarkTrack.TIMESTAMP
            else "value_bits"
        )
        components[bucket] = sum(len(frame) * 8 for frame, _ in records)
        return AccountingLedger(
            track=routed.track,
            **components,
            serialized_bits=total,
            final_bits=total,
            final_physical_bytes=len(stream),
            canonical_raw_bits=routed.canonical_raw_bits,
            accounting_method="EXACT_CONTAINER_AND_OPAQUE_COMPLETE_NATIVE_FRAMES",
        )

    def close(self) -> None:
        self._closed = True
