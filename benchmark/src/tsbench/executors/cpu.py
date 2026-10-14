"""CPU resource requests and completed object measurements."""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any


def apply_profile(profile: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    if profile.get("device", "cpu") != "cpu":
        raise RuntimeError("unavailable: this executor supports CPU only")
    if profile.get("object_workers", 1) != 1:
        raise ValueError("unsupported: object_workers>1 requires the separate workload executor")
    requested = profile.get("native_threads", 1)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[key] = str(requested)
    affinity = profile.get("affinity")
    affinity_effective = None
    if hasattr(os, "sched_getaffinity"):
        if affinity is not None:
            os.sched_setaffinity(0, set(affinity))
        affinity_effective = sorted(os.sched_getaffinity(0))
    elif affinity is not None:
        raise RuntimeError("unavailable: affinity cannot be enforced on this platform")
    memory_mb = profile.get("memory_limit_mb", execution.get("memory_limit_mb", 4096))
    limit = {"requested_mb": memory_mb, "implemented": False, "mechanism": None,
             "effective_soft_bytes": None, "effective_hard_bytes": None,
             "scope": "process virtual address space; not resident-set peak"}
    if memory_mb is not None:
        try:
            import resource
            amount = int(memory_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (amount, amount))
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            limit.update(implemented=soft == amount and hard == amount, mechanism="RLIMIT_AS",
                         effective_soft_bytes=soft, effective_hard_bytes=hard,
                         readback_source="getrlimit(RLIMIT_AS) in actual worker before NumPy/native imports")
        except (ImportError, ValueError, OSError) as error:
            limit["reason"] = str(error)
    return {"device": "cpu", "requested_native_threads": requested,
            "effective_native_threads": None,
            "thread_evidence": "codec capability checked separately; environment alone is not proof",
            "object_workers": 1, "affinity": affinity_effective,
            "memory_limit": limit}


def fingerprint(obj: Any) -> str:
    from ..data import fingerprint as object_fingerprint
    return object_fingerprint(obj)


def measure_object(scheme: Any, original: Any, task: dict[str, Any], *, asset_root: Any = None,
                   build_root: Any = None, on_stage: Any = None,
                   expected_fingerprint: str | None = None) -> tuple[dict[str, Any], bytes]:
    from ..schemes import decode_once
    from ..validate import verify
    initial = fingerprint(original)
    if expected_fingerprint is not None and initial != expected_fingerprint:
        from ..errors import ValidationError
        raise ValidationError("trusted canonical input was modified before this operation", stage="input_validation")
    stage = "encode"
    if on_stage:
        on_stage(stage)
    started = time.perf_counter_ns()
    try:
        artifact = scheme.encode_once(original)
    except BaseException as error:
        error.measurement_stage = stage
        error.diagnostic_encode_ns = time.perf_counter_ns() - started
        raise
    encoded = time.perf_counter_ns()
    stage = "decode"
    if on_stage:
        on_stage(stage)
    decode_started = time.perf_counter_ns()
    try:
        restored = decode_once(artifact, asset_root=asset_root, build_root=build_root)
    except BaseException as error:
        error.measurement_stage = stage
        error.artifact_wire = artifact.wire
        error.diagnostic_encode_ns = encoded - started
        error.diagnostic_decode_ns = time.perf_counter_ns() - decode_started
        raise
    decoded = time.perf_counter_ns()
    stage = "validation"
    if on_stage:
        on_stage(stage)
    try:
        verification = verify(original, restored, task)
        from ..quality_metadata import extract
        codec_quality = extract(artifact.wire)
    except BaseException as error:
        error.measurement_stage = stage
        error.artifact_wire = artifact.wire
        error.diagnostic_encode_ns = encoded - started
        error.diagnostic_decode_ns = decoded - decode_started
        raise
    unchanged = initial == fingerprint(original)
    verification["input_unchanged"] = unchanged
    passed = bool(verification.get("passed", False)) and unchanged
    verification["passed"] = passed
    reason = None if passed else ("input_modified" if not unchanged else verification.get("reason", "validation_failed"))
    wire = artifact.wire
    if not isinstance(wire, bytes):
        raise TypeError("EncodedObject.wire must be bytes")
    raw_bytes = sum(array.nbytes for array in original.components.values())
    descriptor = artifact.descriptor
    roles = original.schema.get("roles", {})
    value_count = sum(array.size for name, array in original.components.items() if roles.get(name, name) == "V")
    timestamp_count = sum(array.size for name, array in original.components.items() if roles.get(name, name) == "T")
    payload_bytes = artifact.payload_bytes
    return {"status": "ok" if passed else "error", "stage": "complete" if passed else stage,
            "reason": reason, "encode_ns": encoded - started,
            "decode_ns": decoded - decode_started, "raw_bytes": raw_bytes,
            "stored_bytes": len(wire), "artifact_hash": "sha256:" + hashlib.sha256(wire).hexdigest(),
            "codec_input_id": descriptor.get("codec_input_id"), "codec_input_bytes": descriptor.get("codec_input_bytes"),
            "transform_id": descriptor.get("transform_id"), "payload_bytes": payload_bytes,
            "header_bytes": len(wire) - payload_bytes, "value_count": value_count, "timestamp_count": timestamp_count,
            "bits_per_value": 8 * len(wire) / value_count if value_count else None,
            "bits_per_timestamp": 8 * len(wire) / timestamp_count if timestamp_count else None,
            "metric_null_reasons": {"bits_per_value": "no values" if not value_count else None,
                                    "bits_per_timestamp": "no timestamps" if not timestamp_count else None,
                                    "compression_ratio": "empty task" if not raw_bytes else None},
            "verification": verification, "codec_quality_metadata": codec_quality, "loops": 1}, wire
