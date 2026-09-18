from __future__ import annotations

import csv
import fcntl
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tscompbench.accounting import AccountingLedger
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.validation import CorrectnessReport


class RunStoreError(ValueError):
    pass


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    run_set_id: str
    task_id: str
    dataset_id: str
    algorithm_id: str
    config_id: str
    execution_path_hash: str
    semantic_comparability_key: str
    execution_comparability_key: str
    resource_profile_key: str
    track: BenchmarkTrack
    record_kind: str
    repetition_index: int | None
    status: RunStatus
    reason_code: str
    eligibility: bool
    input_sha256: str | None
    bitstream_sha256: str | None
    finalize_bytes: int | None
    timing: dict[str, Any] | None
    resources: dict[str, Any] | None
    workloads: dict[str, Any] | None
    accounting: AccountingLedger | None
    correctness: CorrectnessReport | None
    diagnostics: dict[str, Any]

    def __post_init__(self) -> None:
        if self.record_kind not in {"DIAGNOSTIC", "FORMAL_REPETITION"}:
            raise RunStoreError(f"invalid record_kind: {self.record_kind}")
        if self.record_kind == "DIAGNOSTIC":
            if self.repetition_index is not None:
                raise RunStoreError("diagnostic records cannot have a repetition index")
            if self.eligibility:
                raise RunStoreError("diagnostic records cannot be benchmark eligible")
        elif (
            not isinstance(self.repetition_index, int)
            or isinstance(self.repetition_index, bool)
            or self.repetition_index < 0
        ):
            raise RunStoreError("formal repetition records require a non-negative integer index")
        if not self.reason_code:
            raise RunStoreError("reason_code must be explicit")
        if self.accounting is not None and self.accounting.track is not self.track:
            raise RunStoreError("accounting track must match the run track")
        if self.correctness is not None and self.correctness.status is not self.status:
            resource_terminal = self.status in {
                RunStatus.RESOURCE_PRESSURE,
                RunStatus.OVERSUBSCRIBED,
                RunStatus.INCOMPARABLE,
            }
            if not resource_terminal or self.correctness.status is not RunStatus.PASS:
                raise RunStoreError(
                    "correctness status may differ only for a resource terminal status"
                )
        if self.eligibility and (
            self.status is not RunStatus.PASS or self.record_kind != "FORMAL_REPETITION"
        ):
            raise RunStoreError("only passing formal repetitions may be eligible")
        if self.record_kind == "FORMAL_REPETITION" and self.status is RunStatus.PASS:
            required = {
                "input_sha256": self.input_sha256,
                "bitstream_sha256": self.bitstream_sha256,
                "finalize_bytes": self.finalize_bytes,
                "timing": self.timing,
                "resources": self.resources,
                "workloads": self.workloads,
                "accounting": self.accounting,
                "correctness": self.correctness,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise RunStoreError(
                    "passing formal repetition is missing evidence: " + ", ".join(missing)
                )

    @classmethod
    def create(
        cls,
        *,
        run_set_id: str,
        task_id: str,
        dataset_id: str,
        algorithm_id: str,
        config_id: str,
        execution_path_hash: str,
        semantic_comparability_key: str,
        execution_comparability_key: str,
        resource_profile_key: str,
        track: BenchmarkTrack,
        record_kind: str,
        repetition_index: int | None,
        status: RunStatus,
        reason_code: str,
        input_sha256: str | None = None,
        bitstream_sha256: str | None = None,
        finalize_bytes: int | None = None,
        timing: dict[str, Any] | None = None,
        resources: dict[str, Any] | None = None,
        workloads: dict[str, Any] | None = None,
        accounting: AccountingLedger | None = None,
        correctness: CorrectnessReport | None = None,
        diagnostics: dict[str, Any] | None = None,
        benchmark_eligible: bool = True,
    ) -> RunRecord:
        identity = {
            "run_set_id": run_set_id,
            "task_id": task_id,
            "record_kind": record_kind,
            "repetition_index": repetition_index,
        }
        eligibility = (
            status is RunStatus.PASS and record_kind == "FORMAL_REPETITION" and benchmark_eligible
        )
        return cls(
            run_id=stable_id("run", identity),
            run_set_id=run_set_id,
            task_id=task_id,
            dataset_id=dataset_id,
            algorithm_id=algorithm_id,
            config_id=config_id,
            execution_path_hash=execution_path_hash,
            semantic_comparability_key=semantic_comparability_key,
            execution_comparability_key=execution_comparability_key,
            resource_profile_key=resource_profile_key,
            track=track,
            record_kind=record_kind,
            repetition_index=repetition_index,
            status=status,
            reason_code=reason_code,
            eligibility=eligibility,
            input_sha256=input_sha256,
            bitstream_sha256=bitstream_sha256,
            finalize_bytes=finalize_bytes,
            timing=timing,
            resources=resources,
            workloads=workloads,
            accounting=accounting,
            correctness=correctness,
            diagnostics=diagnostics or {},
        )

    def to_document(self) -> dict[str, Any]:
        document = asdict(self)
        document["schema_version"] = "tscb.run-record.v2"
        document["accounting"] = None if self.accounting is None else self.accounting.to_document()
        document["correctness"] = (
            None if self.correctness is None else self.correctness.to_document()
        )
        return document

    def csv_row(self) -> dict[str, Any]:
        ledger = self.accounting
        timing = self.timing or {}
        resources = self.resources or {}
        workloads = self.workloads or {}
        query = workloads.get("query") or {}
        streaming = workloads.get("streaming") or {}
        return {
            "schema_version": "tscb.run-record.v2",
            "run_id": self.run_id,
            "run_set_id": self.run_set_id,
            "task_id": self.task_id,
            "dataset_id": self.dataset_id,
            "algorithm_id": self.algorithm_id,
            "config_id": self.config_id,
            "execution_path_hash": self.execution_path_hash,
            "semantic_comparability_key": self.semantic_comparability_key,
            "execution_comparability_key": self.execution_comparability_key,
            "resource_profile_key": self.resource_profile_key,
            "track": self.track,
            "record_kind": self.record_kind,
            "repetition_index": self.repetition_index,
            "status": self.status,
            "reason_code": self.reason_code,
            "eligibility": self.eligibility,
            "input_sha256": self.input_sha256,
            "bitstream_sha256": self.bitstream_sha256,
            "finalize_bytes": self.finalize_bytes,
            "canonical_raw_bits": None if ledger is None else ledger.canonical_raw_bits,
            "serialized_bits": None if ledger is None else ledger.serialized_bits,
            "external_side_information_bits": (
                None if ledger is None else ledger.external_side_information_bits
            ),
            "final_bits": None if ledger is None else ledger.final_bits,
            "final_physical_bytes": None if ledger is None else ledger.final_physical_bytes,
            "correctness_status": None if self.correctness is None else self.correctness.status,
            "first_failure_stage": (
                None if self.correctness is None else self.correctness.first_failure_stage
            ),
            "timing_scope": timing.get("timing_scope"),
            "inner_iterations": timing.get("inner_iterations"),
            "selected_encode_wall_ns": timing.get("selected_encode_wall_ns"),
            "selected_decode_wall_ns": timing.get("selected_decode_wall_ns"),
            "core_encode_wall_ns": timing.get("core_encode_wall_ns"),
            "core_decode_wall_ns": timing.get("core_decode_wall_ns"),
            "native_encode_wall_ns": timing.get("native_encode_wall_ns"),
            "native_decode_wall_ns": timing.get("native_decode_wall_ns"),
            "native_encode_mb_per_second": timing.get("native_encode_mb_per_second"),
            "native_decode_mb_per_second": timing.get("native_decode_mb_per_second"),
            "native_timing_enabled": timing.get("native_timing_enabled"),
            "native_timing_boundary": timing.get("native_timing_boundary"),
            "native_timing_clock": timing.get("native_timing_clock"),
            "pipeline_encode_wall_ns": timing.get("pipeline_encode_wall_ns"),
            "pipeline_decode_wall_ns": timing.get("pipeline_decode_wall_ns"),
            "e2e_wall_ns": timing.get("e2e_wall_ns"),
            "semantic_encode_mb_per_second": timing.get("semantic_encode_mb_per_second"),
            "semantic_decode_mb_per_second": timing.get("semantic_decode_mb_per_second"),
            "codec_input_encode_mb_per_second": timing.get("codec_input_encode_mb_per_second"),
            "codec_input_decode_mb_per_second": timing.get("codec_input_decode_mb_per_second"),
            "requested_resource_scope": resources.get("requested_scope"),
            "actual_resource_scope": resources.get("actual_scope"),
            "resource_scope_availability": resources.get("scope_availability"),
            "process_cpu_total_seconds": resources.get("process_total_seconds"),
            "cpu_equivalent_cores": resources.get("cpu_equivalent_cores"),
            "cpu_core_seconds_per_gb": resources.get("cpu_core_seconds_per_gb"),
            "peak_process_rss_bytes": resources.get("peak_process_rss_bytes"),
            "incremental_peak_memory_bytes": resources.get("incremental_peak_memory_bytes"),
            "minor_faults": resources.get("minor_faults"),
            "major_faults": resources.get("major_faults"),
            "voluntary_context_switches": resources.get("voluntary_context_switches"),
            "involuntary_context_switches": resources.get("involuntary_context_switches"),
            "logical_read_bytes": resources.get("logical_read_bytes"),
            "logical_write_bytes": resources.get("logical_write_bytes"),
            "physical_read_bytes": resources.get("physical_read_bytes"),
            "physical_write_bytes": resources.get("physical_write_bytes"),
            "query_status": query.get("status"),
            "streaming_status": streaming.get("status"),
        }


_CSV_FIELDS = tuple(
    RunRecord.create(
        run_set_id="x",
        task_id="x",
        dataset_id="x",
        algorithm_id="x",
        config_id="x",
        execution_path_hash="x",
        semantic_comparability_key="x",
        execution_comparability_key="x",
        resource_profile_key="x",
        track=BenchmarkTrack.VALUE,
        record_kind="DIAGNOSTIC",
        repetition_index=None,
        status=RunStatus.UNSUPPORTED,
        reason_code="SCHEMA_ONLY",
    ).csv_row()
)


def _existing_runs(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    result: dict[str, dict[str, Any]] = {}
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith(b"\n"):
                raise RunStoreError(f"run_components line {line_number} is incomplete")
            try:
                document = json.loads(line)
            except json.JSONDecodeError as error:
                raise RunStoreError(f"run_components line {line_number} is invalid") from error
            run_id = str(document["run_id"])
            if run_id in result:
                raise RunStoreError(f"duplicate RunID already stored: {run_id}")
            result[run_id] = document
    return result


def _csv_projection(document: dict[str, Any]) -> dict[str, Any]:
    accounting = document.get("accounting")
    correctness = document.get("correctness")
    timing = document.get("timing") or {}
    resources = document.get("resources") or {}
    workloads = document.get("workloads") or {}
    fields = {
        key: document.get(key)
        for key in _CSV_FIELDS
        if key
        not in {
            "canonical_raw_bits",
            "serialized_bits",
            "external_side_information_bits",
            "final_bits",
            "final_physical_bytes",
            "correctness_status",
            "first_failure_stage",
            "timing_scope",
            "inner_iterations",
            "selected_encode_wall_ns",
            "selected_decode_wall_ns",
            "core_encode_wall_ns",
            "core_decode_wall_ns",
            "native_encode_wall_ns",
            "native_decode_wall_ns",
            "native_encode_mb_per_second",
            "native_decode_mb_per_second",
            "native_timing_enabled",
            "native_timing_boundary",
            "native_timing_clock",
            "pipeline_encode_wall_ns",
            "pipeline_decode_wall_ns",
            "e2e_wall_ns",
            "semantic_encode_mb_per_second",
            "semantic_decode_mb_per_second",
            "codec_input_encode_mb_per_second",
            "codec_input_decode_mb_per_second",
            "requested_resource_scope",
            "actual_resource_scope",
            "resource_scope_availability",
            "process_cpu_total_seconds",
            "cpu_equivalent_cores",
            "cpu_core_seconds_per_gb",
            "peak_process_rss_bytes",
            "incremental_peak_memory_bytes",
            "minor_faults",
            "major_faults",
            "voluntary_context_switches",
            "involuntary_context_switches",
            "logical_read_bytes",
            "logical_write_bytes",
            "physical_read_bytes",
            "physical_write_bytes",
            "query_status",
            "streaming_status",
        }
    }
    fields.update(
        {
            "canonical_raw_bits": None if accounting is None else accounting["canonical_raw_bits"],
            "serialized_bits": None if accounting is None else accounting["serialized_bits"],
            "external_side_information_bits": (
                None if accounting is None else accounting["external_side_information_bits"]
            ),
            "final_bits": None if accounting is None else accounting["final_bits"],
            "final_physical_bytes": (
                None if accounting is None else accounting["final_physical_bytes"]
            ),
            "correctness_status": None if correctness is None else correctness["status"],
            "first_failure_stage": (
                None if correctness is None else correctness["first_failure_stage"]
            ),
            "timing_scope": timing.get("timing_scope"),
            "inner_iterations": timing.get("inner_iterations"),
            "selected_encode_wall_ns": timing.get("selected_encode_wall_ns"),
            "selected_decode_wall_ns": timing.get("selected_decode_wall_ns"),
            "core_encode_wall_ns": timing.get("core_encode_wall_ns"),
            "core_decode_wall_ns": timing.get("core_decode_wall_ns"),
            "native_encode_wall_ns": timing.get("native_encode_wall_ns"),
            "native_decode_wall_ns": timing.get("native_decode_wall_ns"),
            "native_encode_mb_per_second": timing.get("native_encode_mb_per_second"),
            "native_decode_mb_per_second": timing.get("native_decode_mb_per_second"),
            "native_timing_enabled": timing.get("native_timing_enabled"),
            "native_timing_boundary": timing.get("native_timing_boundary"),
            "native_timing_clock": timing.get("native_timing_clock"),
            "pipeline_encode_wall_ns": timing.get("pipeline_encode_wall_ns"),
            "pipeline_decode_wall_ns": timing.get("pipeline_decode_wall_ns"),
            "e2e_wall_ns": timing.get("e2e_wall_ns"),
            "semantic_encode_mb_per_second": timing.get("semantic_encode_mb_per_second"),
            "semantic_decode_mb_per_second": timing.get("semantic_decode_mb_per_second"),
            "codec_input_encode_mb_per_second": timing.get("codec_input_encode_mb_per_second"),
            "codec_input_decode_mb_per_second": timing.get("codec_input_decode_mb_per_second"),
            "requested_resource_scope": resources.get("requested_scope"),
            "actual_resource_scope": resources.get("actual_scope"),
            "resource_scope_availability": resources.get("scope_availability"),
            "process_cpu_total_seconds": resources.get("process_total_seconds"),
            "cpu_equivalent_cores": resources.get("cpu_equivalent_cores"),
            "cpu_core_seconds_per_gb": resources.get("cpu_core_seconds_per_gb"),
            "peak_process_rss_bytes": resources.get("peak_process_rss_bytes"),
            "incremental_peak_memory_bytes": resources.get("incremental_peak_memory_bytes"),
            "minor_faults": resources.get("minor_faults"),
            "major_faults": resources.get("major_faults"),
            "voluntary_context_switches": resources.get("voluntary_context_switches"),
            "involuntary_context_switches": resources.get("involuntary_context_switches"),
            "logical_read_bytes": resources.get("logical_read_bytes"),
            "logical_write_bytes": resources.get("logical_write_bytes"),
            "physical_read_bytes": resources.get("physical_read_bytes"),
            "physical_write_bytes": resources.get("physical_write_bytes"),
            "query_status": (workloads.get("query") or {}).get("status"),
            "streaming_status": (workloads.get("streaming") or {}).get("status"),
        }
    )
    return fields


def _rebuild_csv_projection(run_path: Path, documents: dict[str, dict[str, Any]]) -> None:
    csv_path = run_path / "runs.csv"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=run_path,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS, extrasaction="raise")
            writer.writeheader()
            for document in documents.values():
                writer.writerow(_csv_projection(document))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, csv_path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def append_run_record(run_path: Path, record: RunRecord) -> None:
    """Append the complete JSONL evidence first, then its CSV projection under one lock."""

    run_path.mkdir(parents=True, exist_ok=True)
    lock_path = run_path / ".run-store.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        components_path = run_path / "run_components.jsonl"
        documents = _existing_runs(components_path)
        document = record.to_document()
        if record.run_id in documents:
            if canonical_json_bytes(documents[record.run_id]) != canonical_json_bytes(document):
                raise RunStoreError(f"duplicate RunID has different content: {record.run_id}")
        else:
            encoded = canonical_json_bytes(document) + b"\n"
            component_fd = os.open(components_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                if os.write(component_fd, encoded) != len(encoded):
                    raise OSError("short append to run_components.jsonl")
                os.fsync(component_fd)
            finally:
                os.close(component_fd)
            documents[record.run_id] = document
        _rebuild_csv_projection(run_path, documents)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def rebuild_runs_csv(run_path: Path) -> int:
    """Recover the flat projection from authoritative append-only JSONL evidence."""

    run_path.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(run_path / ".run-store.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        documents = _existing_runs(run_path / "run_components.jsonl")
        if documents:
            _rebuild_csv_projection(run_path, documents)
        return len(documents)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
