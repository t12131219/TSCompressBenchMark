from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from tscompbench.codecs import CodecManifest
from tscompbench.contracts import BenchmarkTrack, LossMode
from tscompbench.execution.protocol import (
    CodecAdapter,
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
)
from tscompbench.execution.repetition import _encode, perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers, hash_reference_array
from tscompbench.ids import stable_id

from .lossy import validate_error_bound


@dataclass(frozen=True)
class BoundaryCase:
    case_id: str
    axis: str
    n: int
    m: int
    dtype: str
    pattern: str
    layout: str
    expected: str = "PASS"


@dataclass(frozen=True)
class BoundaryObservation:
    case_id: str
    status: str
    reason: str


@dataclass(frozen=True)
class BoundarySuiteReport:
    suite_id: str
    observations: tuple[BoundaryObservation, ...]
    required_case_count: int
    passed: bool

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.boundary-suite-report.v2",
            "suite_id": self.suite_id,
            "required_case_count": self.required_case_count,
            "passed": self.passed,
            "observations": [item.__dict__ for item in self.observations],
        }


def _case(
    axis: str,
    n: int,
    m: int,
    dtype: str,
    pattern: str,
    layout: str,
    expected: str = "PASS",
) -> BoundaryCase:
    document = {
        "axis": axis,
        "n": n,
        "m": m,
        "dtype": dtype,
        "pattern": pattern,
        "layout": layout,
        "expected": expected,
    }
    return BoundaryCase(stable_id("boundary-case", document), **document)


def build_boundary_suite(
    manifest: CodecManifest, parameters: dict[str, Any]
) -> tuple[BoundaryCase, ...]:
    contract = manifest.document["input"]
    minimum = int(contract["min_n"])
    maximum = int(contract["max_n"])
    block = int(parameters.get("block_size", max(1, minimum)))
    length_candidates = {0, 1, 2, max(0, minimum - 1), minimum, minimum + 1}
    length_candidates.update(
        {
            max(0, block - 1),
            block,
            block + 1,
            max(0, 2 * block - 1),
            2 * block,
            2 * block + 1,
        }
    )
    length_candidates = {value for value in length_candidates if value <= maximum}
    supported_dtypes = tuple(str(item) for item in contract["dtypes"])
    base_dtype = supported_dtypes[0]
    cases: list[BoundaryCase] = []
    for n in sorted(length_candidates):
        expected = "CAPABILITY_REJECTED" if n < minimum else "PASS"
        cases.append(_case("N", n, 1, base_dtype, "INCREASING", "C", expected))

    min_m = int(contract["min_m"])
    max_m = int(contract["max_m"])
    for m in (1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 32, 64):
        if m <= max_m:
            expected = "CAPABILITY_REJECTED" if m < min_m else "PASS"
            cases.append(_case("M", max(minimum, 2), m, base_dtype, "CONSTANT", "C", expected))

    integer_dtype = next(
        (item for item in supported_dtypes if np.issubdtype(np.dtype(item), np.integer)),
        None,
    )
    float_dtype = next(
        (item for item in supported_dtypes if np.issubdtype(np.dtype(item), np.floating)),
        None,
    )
    if integer_dtype:
        for pattern in ("INTEGER_EXTREMES", "DELTA_OVERFLOW", "ALTERNATING_BITS"):
            cases.append(_case("SPECIAL", max(minimum, 9), 1, integer_dtype, pattern, "C"))
    if float_dtype:
        for pattern in ("FLOAT_SPECIALS", "ADJACENT_FLOATS", "ALTERNATING_BITS"):
            cases.append(_case("SPECIAL", max(minimum, 9), 1, float_dtype, pattern, "C"))
    for pattern in ("ZERO", "CONSTANT", "RANDOM", "INCOMPRESSIBLE"):
        cases.append(
            _case(
                "ENTROPY",
                max(minimum, min(block + 1, maximum)),
                1,
                base_dtype,
                pattern,
                "C",
            )
        )
    for layout in ("C", "F", "STRIDED", "MISALIGNED"):
        cases.append(_case("LAYOUT", max(minimum, 9), 1, base_dtype, "INCREASING", layout))
    for pattern in ("EMPTY_FINAL", "PARTIAL_BLOCK", "EXACT_BLOCK", "MULTI_BLOCK", "RESET"):
        n = {
            "EMPTY_FINAL": 0,
            "PARTIAL_BLOCK": max(1, block - 1),
            "EXACT_BLOCK": block,
            "MULTI_BLOCK": 2 * block + 1,
            "RESET": max(1, minimum),
        }[pattern]
        if n <= maximum:
            expected = "CAPABILITY_REJECTED" if n < minimum else "PASS"
            cases.append(_case("STREAM", n, 1, base_dtype, pattern, "C", expected))
    cases.append(
        _case(
            "STREAM",
            max(minimum, 1),
            1,
            base_dtype,
            "REPEATED_FINALIZE",
            "C",
        )
    )
    if manifest.document["classification"]["tracks"] and any(
        item in {"TIMESTAMP", "SYSTEM"} for item in manifest.document["classification"]["tracks"]
    ):
        for pattern in (
            "TIMESTAMP_REGULAR",
            "TIMESTAMP_JITTER",
            "TIMESTAMP_DUPLICATE",
            "TIMESTAMP_OUT_OF_ORDER",
            "TIMESTAMP_NEGATIVE_DELTA",
            "TIMESTAMP_LARGE_GAP",
            "TIMESTAMP_EPOCH_EXTREMES",
        ):
            cases.append(_case("TIMESTAMP", max(minimum, 9), 1, "<i8", pattern, "C"))
    cases.append(
        _case(
            "CAPACITY",
            max(minimum, 2),
            1,
            base_dtype,
            "BOUND_MINUS_ONE",
            "C",
            "CAPACITY_REJECTED",
        )
    )
    unique = {item.case_id: item for item in cases}
    return tuple(unique[key] for key in sorted(unique))


def _values(case: BoundaryCase) -> np.ndarray[Any]:
    dtype = np.dtype(case.dtype)
    n = case.n
    if case.pattern in {"ZERO", "EMPTY_FINAL"}:
        values = np.zeros(n, dtype=dtype)
    elif case.pattern == "CONSTANT":
        values = np.full(n, 7, dtype=dtype)
    elif case.pattern in {"RANDOM", "INCOMPRESSIBLE"}:
        rng = np.random.default_rng(20260910 + n + case.m)
        raw = rng.integers(0, 256, size=n * dtype.itemsize, dtype=np.uint8)
        values = raw.view(dtype)[:n]
    elif case.pattern == "INTEGER_EXTREMES":
        info = np.iinfo(dtype)
        seeds = [0, 1, -1 if info.min < 0 else info.max, info.min, info.max]
        values = np.resize(np.asarray(seeds, dtype=dtype), n)
    elif case.pattern == "DELTA_OVERFLOW":
        info = np.iinfo(dtype)
        values = np.resize(np.asarray([info.min, info.max, info.min], dtype=dtype), n)
    elif case.pattern == "FLOAT_SPECIALS":
        payload = np.asarray(
            [
                0.0,
                -0.0,
                np.inf,
                -np.inf,
                np.nan,
                np.nextafter(0, 1),
                np.finfo(dtype).max,
            ],
            dtype=dtype,
        )
        values = np.resize(payload, n)
    elif case.pattern == "ADJACENT_FLOATS":
        base = np.asarray([1.0], dtype=dtype)[0]
        values = np.resize(
            np.asarray(
                [base, np.nextafter(base, np.asarray(np.inf, dtype=dtype))],
                dtype=dtype,
            ),
            n,
        )
    elif case.pattern == "ALTERNATING_BITS":
        raw = np.resize(np.asarray([0xAA, 0x55], dtype=np.uint8), n * dtype.itemsize)
        values = raw.view(dtype)
    else:
        values = np.arange(n, dtype=dtype)
    if case.layout == "STRIDED" and n:
        base = np.empty(n * 2, dtype=dtype)
        base[::2] = values
        values = base[::2]
    elif case.layout == "MISALIGNED" and n:
        raw = np.empty(n * dtype.itemsize + 1, dtype=np.uint8)
        values = raw[1:].view(dtype)
        values[...] = np.arange(n, dtype=dtype)
    values.flags.writeable = False
    return values


def _routed(case: BoundaryCase, track: BenchmarkTrack) -> RoutedInput:
    arrays: list[LogicalBuffer] = []
    if track in {BenchmarkTrack.TIMESTAMP, BenchmarkTrack.SYSTEM}:
        timestamp = np.arange(case.n, dtype="<i8")
        if case.pattern == "TIMESTAMP_JITTER" and case.n:
            timestamp = np.cumsum(np.resize(np.asarray([1, 2, 1, 3], dtype="<i8"), case.n))
        elif case.pattern == "TIMESTAMP_DUPLICATE" and case.n > 1:
            timestamp[1] = timestamp[0]
        elif case.pattern in {"TIMESTAMP_OUT_OF_ORDER", "TIMESTAMP_NEGATIVE_DELTA"} and case.n > 2:
            timestamp[2] = timestamp[0] - 1
        elif case.pattern == "TIMESTAMP_LARGE_GAP" and case.n > 1:
            timestamp[1:] += np.int64(1 << 50)
        elif case.pattern == "TIMESTAMP_EPOCH_EXTREMES" and case.n:
            timestamp = np.resize(
                np.asarray([np.iinfo(np.int64).min, 0, np.iinfo(np.int64).max], dtype="<i8"),
                case.n,
            )
        timestamp.flags.writeable = False
        arrays.append(LogicalBuffer("timestamp", timestamp, timestamp.nbytes * 8))
    if track in {BenchmarkTrack.VALUE, BenchmarkTrack.SYSTEM}:
        for index in range(case.m):
            values = _values(case)
            arrays.append(LogicalBuffer(f"value/{index:06d}", values, values.nbytes * 8))
    buffers = tuple(arrays)
    canonical_raw_bits = sum(item.logical_bits for item in buffers)
    timestamp_reference = arrays[0].array if arrays and arrays[0].name == "timestamp" else None
    return RoutedInput(
        dataset_id="v2:dataset:boundary-suite",
        track=track,
        buffers=buffers,
        timestamp_reference=timestamp_reference,
        validity_reference=None,
        n=case.n,
        m=case.m,
        canonical_raw_bits=canonical_raw_bits,
        input_sha256=hash_logical_buffers(buffers),
        segment_plan_id="v2:segment-plan:boundary" if track is BenchmarkTrack.SYSTEM else None,
        pairing_reference_sha256=hash_reference_array(timestamp_reference),
    )


def run_boundary_suite(
    adapter: CodecAdapter,
    manifest: CodecManifest,
    track: BenchmarkTrack,
    parameters: dict[str, Any],
) -> BoundarySuiteReport:
    cases = build_boundary_suite(manifest, parameters)
    observations: list[BoundaryObservation] = []
    for case in cases:
        if case.expected == "CAPABILITY_REJECTED":
            observations.append(
                BoundaryObservation(case.case_id, "PASS", "CAPABILITY_REJECTED_WITHOUT_INVOCATION")
            )
            continue
        routed = _routed(case, track)
        try:
            if case.expected == "CAPACITY_REJECTED":
                session = adapter.create_session(parameters)
                try:
                    bound = session.output_bound(routed)
                finally:
                    session.close()
                try:
                    _encode(adapter, routed, parameters, capacity_override=max(0, bound - 1))
                except OutputCapacityError:
                    observations.append(
                        BoundaryObservation(case.case_id, "PASS", "BOUND_MINUS_ONE_REJECTED")
                    )
                else:
                    observations.append(
                        BoundaryObservation(case.case_id, "FAIL", "BOUND_MINUS_ONE_ACCEPTED")
                    )
                continue
            if case.pattern == "REPEATED_FINALIZE":
                session = adapter.create_session(parameters)
                try:
                    bound = session.output_bound(routed)
                    storage = bytearray(bound)
                    used = session.compress_update(routed, memoryview(storage))
                    finalized = session.finalize(memoryview(storage)[used:])
                    try:
                        session.finalize(memoryview(storage)[used + finalized :])
                    except ExecutionContractError:
                        observations.append(
                            BoundaryObservation(
                                case.case_id, "PASS", "REPEATED_FINALIZE_DEFINED_REJECT"
                            )
                        )
                    else:
                        observations.append(
                            BoundaryObservation(case.case_id, "FAIL", "REPEATED_FINALIZE_UNDEFINED")
                        )
                finally:
                    session.close()
                continue
            result = perform_roundtrip(adapter, routed, parameters)
            original = {item.name: item.array for item in routed.buffers}
            decoded = {item.name: item.array for item in result.decoded.buffers}
            loss_mode = manifest.loss_modes[0]
            if loss_mode is LossMode.ERROR_BOUNDED_LOSSY:
                value_original = {
                    name: value for name, value in original.items() if name.startswith("value/")
                }
                value_decoded = {
                    name: value for name, value in decoded.items() if name.startswith("value/")
                }
                loss = validate_error_bound(
                    value_original,
                    value_decoded,
                    error_bound_type=str(parameters.get("error_bound_type", "ABSOLUTE")),
                    error_bound=str(parameters.get("error_bound", "0")),
                    error_aggregation_mode=str(
                        parameters.get("error_aggregation_mode", "PER_CHANNEL")
                    ),
                )
                exact = loss.bound_passed and all(
                    original[name].tobytes(order="C") == decoded[name].tobytes(order="C")
                    for name in original
                    if name == "timestamp" or name == "validity"
                )
                mismatch_reason = "ROUNDTRIP_WITHIN_BOUND" if exact else "BOUND_VIOLATION"
            else:
                exact = tuple(original) == tuple(decoded) and all(
                    original[name].dtype == decoded[name].dtype
                    and original[name].shape == decoded[name].shape
                    and original[name].tobytes(order="C") == decoded[name].tobytes(order="C")
                    for name in original
                )
                mismatch_reason = "ROUNDTRIP_EXACT" if exact else "ROUNDTRIP_MISMATCH"
            passed = exact and result.input_immutable and result.canary_intact
            if result.determinism_match is False:
                passed = False
                mismatch_reason = "NONDETERMINISTIC"
            observations.append(
                BoundaryObservation(
                    case.case_id,
                    "PASS" if passed else "FAIL",
                    mismatch_reason,
                )
            )
            if case.pattern == "RESET" and passed:
                repeated = perform_roundtrip(adapter, routed, parameters)
                if repeated.encoded.stream != result.encoded.stream and adapter.deterministic:
                    observations[-1] = BoundaryObservation(
                        case.case_id, "FAIL", "RESET_DID_NOT_RESTORE_DETERMINISTIC_STATE"
                    )
        except MemoryError:
            raise
        except Exception as error:
            observations.append(
                BoundaryObservation(case.case_id, "FAIL", f"{type(error).__name__}:{error}")
            )
    passed = all(item.status == "PASS" for item in observations)
    suite_document = {
        "algorithm_id": manifest.algorithm_id,
        "adapter_id": adapter.adapter_id,
        "track": track,
        "case_ids": [item.case_id for item in cases],
    }
    return BoundarySuiteReport(
        stable_id("boundary-suite", suite_document), tuple(observations), len(cases), passed
    )
