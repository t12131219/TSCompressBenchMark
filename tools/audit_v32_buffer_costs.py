"""Reconstruct auxiliary buffer costs without invoking a codec or measuring performance.

The audit observes CPU preparation separately from the frozen performance trials.
Logical sizes and adapter output buffers are instrumented; adapter traffic is a
declared estimate. Native internals and unsaved capacities stay unknown.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.comparison.pipeline_runner import (  # noqa: E402
    load_pipeline_input,
    validate_pipeline_plan,
)
from tscompbench.comparison.runner import (  # noqa: E402
    control_plane_snapshot,
    evidence_document,
    prepare_comparison,
)
from tscompbench.comparison.workload_runner import validate_workload_plan  # noqa: E402
from tscompbench.contracts import BenchmarkTrack, CapabilityStatus  # noqa: E402
from tscompbench.datasets import DatasetRegistry  # noqa: E402
from tscompbench.execution.preparation import prepare_execution_input  # noqa: E402
from tscompbench.execution.routing import (  # noqa: E402
    hash_logical_buffers,
    route_canonical_artifact,
)
from tscompbench.ids import canonical_json_bytes, stable_id  # noqa: E402
from tscompbench.pipelines import ChildSpec, PipelineRecipe  # noqa: E402
from tscompbench.pipelines.runtime import _parse, _prepare_child  # noqa: E402

VERSION = "tscb.auxiliary-buffer-cost-audit.v1"
LANES = ("comparison", "workload", "pipeline")
NATIVE_REASON = "OPAQUE_NATIVE_INTERNAL_STAGE_NOT_INSTRUMENTED"
CAPACITY_REASON = "ACTUAL_DESTINATION_CAPACITY_NOT_RETAINED_IN_TRIAL"


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(value: int | None, method: str, detail: str) -> dict[str, Any]:
    require(value is None or type(value) is int and value >= 0, "invalid cost observation")
    require(method in {"ESTIMATED", "INSTRUMENTED", "MEASURED", "UNAVAILABLE"}, "cost method")
    require((value is None) == (method == "UNAVAILABLE"), "missing cost needs unavailable reason")
    return {
        "value": value,
        "evidence_method": method,
        "unavailable_reason": detail if value is None else None,
        "evidence_detail": detail,
    }


def unknown(reason: str = NATIVE_REASON) -> dict[str, Any]:
    return metric(None, "UNAVAILABLE", reason)


def file_binding(path: Path) -> dict[str, Any]:
    path = path.resolve()
    return {"path": str(path), "sha256": sha(path), "physical_bytes": path.stat().st_size}


def _backing_bytes(array: np.ndarray) -> int | None:
    base: Any = array
    visited = set()
    while id(base) not in visited:
        visited.add(id(base))
        if isinstance(base, np.ndarray):
            if base.base is None:
                return int(base.nbytes)
            base = base.base
        elif isinstance(base, memoryview):
            base = base.obj
        elif isinstance(base, (bytes, bytearray)):
            return len(base)
        else:
            return None
    return None


def array_cost(array: np.ndarray, *, logical_bits: int) -> dict[str, Any]:
    elements = math.prod(int(v) for v in array.shape)
    require(elements * array.dtype.itemsize == array.nbytes, "ND payload size mismatch")
    backing = _backing_bytes(array)
    return {
        "dtype": array.dtype.str,
        "shape": list(array.shape),
        "strides": list(array.strides),
        "logical_bits": metric(logical_bits, "INSTRUMENTED", "FROZEN_LOGICAL_BUFFER_CONTRACT"),
        "effective_elements": metric(elements, "INSTRUMENTED", "PYTHON_INTEGER_SHAPE_PRODUCT"),
        "effective_bytes": metric(int(array.nbytes), "INSTRUMENTED", "OBSERVED_NUMPY_VIEW_NBYTES"),
        "backing_storage_bytes": (
            unknown("NUMPY_BACKING_OWNER_NOT_INTROSPECTABLE")
            if backing is None
            else metric(backing, "INSTRUMENTED", "OBSERVED_BACKING_OWNER_IN_AUXILIARY_PREPARATION")
        ),
        "backing_aggregation": "SHARED_BACKINGS_MUST_NOT_BE_SUMMED_PER_VIEW",
        "alignment_slack_bytes": unknown("ALIGNMENT_SLACK_NOT_RETAINED_PER_BUFFER"),
        "device_staging_bytes": unknown("NO_DEVICE_STAGING_OBSERVATION_IN_THIS_CPU_AUDIT"),
    }


def opaque_native_costs() -> dict[str, Any]:
    return {
        "native_input_bytes": unknown("NO_EXPLICIT_NATIVE_SUBMISSION_COUNTER_IN_AUXILIARY_AUDIT"),
        **{
            name: unknown()
            for name in (
                "read_bytes",
                "write_bytes",
                "copy_count",
                "allocation_count",
                "allocated_bytes",
                "peak_live_bytes",
                "safe_overread_padding_bytes",
                "alignment_slack_bytes",
            )
        },
        "output_capacity_bytes": unknown(CAPACITY_REASON),
    }


def preparation_costs(routed, prepared) -> dict[str, Any]:
    require(
        routed.input_sha256 == hash_logical_buffers(routed.buffers),
        "original input mutated during auxiliary preparation",
    )
    require(
        routed.canonical_raw_bits == sum(b.logical_bits for b in routed.buffers),
        "original logical denominator does not close",
    )
    originals = {b.name: b for b in routed.buffers}
    buffers = []
    for output in prepared.codec_input.buffers:
        original = originals[output.name]
        buffers.append(
            {
                "name": output.name,
                "original": array_cost(original.array, logical_bits=original.logical_bits),
                "adapted": array_cost(output.array, logical_bits=output.logical_bits),
                "codec_input_bytes": metric(
                    int(output.array.nbytes), "INSTRUMENTED", "EXACT_PREPARED_SESSION_BUFFER"
                ),
                "native": opaque_native_costs(),
            }
        )
    stages = []
    for item in prepared.telemetry.stages:
        stages.append(
            {
                "buffer": item["buffer"],
                "kind": item["kind"],
                "before_dtype": item["before_dtype"],
                "before_shape": item["before_shape"],
                "after_dtype": item["after_dtype"],
                "after_shape": item["after_shape"],
                "input_bytes": metric(item["input_bytes"], "INSTRUMENTED", "OBSERVED_NUMPY_VIEW"),
                "output_bytes": metric(item["output_bytes"], "INSTRUMENTED", "OBSERVED_NUMPY_VIEW"),
                "read_bytes": metric(
                    item["bytes_read"], "ESTIMATED", "ONE_PASS_ADAPTER_COPY_MODEL"
                ),
                "write_bytes": metric(
                    item["bytes_written"], "ESTIMATED", "ONE_PASS_ADAPTER_COPY_OR_PADDING_MODEL"
                ),
                "copy_count": metric(
                    int(item["copied"]), "INSTRUMENTED", "OBSERVED_NUMPY_ALIASING"
                ),
                "allocation_count": metric(
                    int(item["copied"]), "INSTRUMENTED", "VISIBLE_ADAPTER_OUTPUT_ALLOCATION_ONLY"
                ),
                "allocated_bytes": metric(
                    item["allocation_bytes"],
                    "INSTRUMENTED",
                    "OBSERVED_ADAPTER_OUTPUT_BACKING_NBYTES",
                ),
                "safe_overread_padding_bytes": metric(
                    item["padding_bytes"], "INSTRUMENTED", "EXPLICIT_ADAPTER_PADDING_CONTRACT"
                ),
                "peak_live_bytes": unknown("ADAPTER_LIVE_ALLOCATION_PEAK_NOT_INSTRUMENTED"),
                "output_capacity_bytes": unknown(
                    "ADAPTER_DESTINATION_CAPACITY_NOT_A_DISTINCT_OBSERVATION"
                ),
                "alignment_slack_bytes": unknown(
                    "ALIGNMENT_SLACK_NOT_RETAINED_BY_ADAPTER_TELEMETRY"
                ),
                "planned": {
                    k: metric(item["planned_" + k], "ESTIMATED", "FROZEN_COMPATIBILITY_PLAN")
                    for k in ("bytes_read", "bytes_written", "allocation_bytes")
                },
            }
        )
    return {
        "canonical_raw_bits": metric(
            routed.canonical_raw_bits, "INSTRUMENTED", "ORIGINAL_TRACK_CONTRACT"
        ),
        "original_payload_bytes": metric(
            sum(int(b.array.nbytes) for b in routed.buffers),
            "INSTRUMENTED",
            "SUM_ORIGINAL_NUMPY_PAYLOADS",
        ),
        "adapted_payload_bytes": metric(
            sum(int(b.array.nbytes) for b in prepared.codec_input.buffers),
            "INSTRUMENTED",
            "SUM_PREPARED_NUMPY_PAYLOADS_EXCLUDES_CAPACITY_AND_PADDING",
        ),
        "buffers": buffers,
        "adapter_stages": stages,
        "adapter_totals": {
            "read_bytes": metric(
                prepared.telemetry.bytes_read, "ESTIMATED", "ADAPTER_COPY_MODEL_SUM"
            ),
            "write_bytes": metric(
                prepared.telemetry.bytes_written, "ESTIMATED", "ADAPTER_COPY_MODEL_SUM"
            ),
            "allocated_bytes": metric(
                prepared.telemetry.allocation_bytes,
                "INSTRUMENTED",
                "VISIBLE_ADAPTER_OUTPUT_ALLOCATIONS_SUM",
            ),
            "safe_overread_padding_bytes": metric(
                prepared.telemetry.padding_bytes, "INSTRUMENTED", "ADAPTER_PADDING_SUM"
            ),
            "peak_live_bytes": unknown("FULL_PREPARATION_LIVE_ALLOCATION_PEAK_NOT_INSTRUMENTED"),
        },
        "adapter_validation_and_hash_traffic": unknown(
            "INDEPENDENT_VALIDATOR_AND_HASH_SCANS_NOT_COUNTED"
        ),
        "native": opaque_native_costs(),
    }


def _retained_artifacts(run_path: Path, trials: list[dict], lane: str) -> list[dict]:
    observations = []
    for trial in trials:
        if lane == "comparison":
            record = trial.get("record")
            if not record or not record.get("bitstream_sha256"):
                continue
            stem = record["run_id"].rsplit(":", 1)[-1]
            directory, source = "artifacts", record
            suffixes = (".bin", ".decode.json", ".decoder.json")
        else:
            source = trial["observation"]
            if source.get("status") != "PASS":
                continue
            stem = trial["trial_id"].rsplit(":", 1)[-1]
            directory, suffixes = "workload_artifacts", (".bin", ".decode.json")
        require(
            len(stem) == 64 and all(c in "0123456789abcdef" for c in stem), "invalid artifact stem"
        )
        paths = [run_path / directory / (stem + suffix) for suffix in suffixes]
        stream, context = paths[:2]
        require(sha(stream) == source["bitstream_sha256"], "retained stream hash mismatch")
        ledger = source["accounting"]
        require(
            ledger["serialized_bits"] == stream.stat().st_size * 8
            and ledger["external_side_information_bits"] == context.stat().st_size * 8
            and ledger["final_bits"] == (stream.stat().st_size + context.stat().st_size) * 8,
            "retained physical storage cost mismatch",
        )
        observations.append(
            {
                "trial_id": trial["trial_id"],
                "cell_id": trial["cell_id"],
                "files": [file_binding(p) for p in paths],
                "artifact_physical_bytes": metric(
                    stream.stat().st_size, "MEASURED", "RETAINED_ARTIFACT_FILE_LENGTH"
                ),
                "required_external_bits": metric(
                    context.stat().st_size * 8, "MEASURED", "RETAINED_CONTEXT_FILE_LENGTH"
                ),
                "final_bits": metric(
                    ledger["final_bits"], "MEASURED", "RETAINED_STREAM_AND_CONTEXT_LENGTH"
                ),
                "output_capacity_bytes": unknown(CAPACITY_REASON),
            }
        )
    return observations


def _comparison_costs(run_path: Path, lane: str) -> tuple[dict, list[dict], list[dict]]:
    datasets = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    run = prepare_comparison(
        run_path / "bundle.json",
        run_path.parent,
        ROOT,
        datasets,
        codecs,
        run_set_id=run_path.name,
        resume=True,
        decision_workload_protocol=(
            read(run_path / "workload_plan.json")["protocol"] if lane == "workload" else None
        ),
    )
    plan = read(run_path / "execution_plan.json")
    require(
        read(run_path / "control_plane.json") == control_plane_snapshot(ROOT), "stale code closure"
    )
    raw_name = "comparison_trials.jsonl" if lane == "comparison" else "workload_trials.jsonl"
    raw_path = run_path / raw_name
    trials = [json.loads(line) for line in raw_path.read_text().splitlines()]
    if lane == "workload":
        workload = read(run_path / "workload_plan.json")
        validate_workload_plan(workload, plan, run.bundle, run_path)
        identity = {"comparison_id": plan["comparison_id"], "workload_id": workload["workload_id"]}
    else:
        identity = {"comparison_id": plan["comparison_id"]}
    rows = []
    for cell in run.cells.values():
        task = run.tasks[cell["cell_id"]]
        row = {
            "cell_id": cell["cell_id"],
            "dataset_id": cell["dataset_id"],
            "codec_key": cell["codec_key"],
            "execution_job_id": cell["execution_job_id"],
            "compatibility_plan_id": task.compatibility.compatibility_plan_id,
            "actual_method_path": cell["path"],
        }
        try:
            routed = route_canonical_artifact(run.artifacts[cell["dataset_id"]], task.track)
        except Exception as error:
            # Missing-track extension tasks are retained, never turned into zeros.
            require(
                task.status.value not in {"PLANNED", "ADAPTER_LOSSY_ROUTED"},
                "legal task failed routing",
            )
            row.update(status="NOT_PREPARED", reason=str(error), costs=None)
            rows.append(row)
            continue
        if task.compatibility.status is CapabilityStatus.UNSUPPORTED:
            row.update(status="NOT_PREPARED", reason=task.compatibility.reason_code, costs=None)
        else:
            prepared = prepare_execution_input(
                routed, task.compatibility, max_abs_error=cell["parameters"].get("error_bound")
            )
            row.update(status="AUXILIARY_PREPARED", costs=preparation_costs(routed, prepared))
        rows.append(row)
    snapshots = [
        run_path / n
        for n in (
            "bundle.json",
            "execution_plan.json",
            "control_plane.json",
            "schedule.json",
            raw_name,
        )
    ]
    if lane == "workload":
        snapshots.append(run_path / "workload_plan.json")
    for directory in ("jobs", "codecs", "sources", "dataset_manifests"):
        snapshots.extend(sorted((run_path / directory).glob("*.json")))
    snapshots.extend(a.path for a in run.artifacts.values())
    artifacts = _retained_artifacts(run_path, trials, lane)
    return (
        {
            **identity,
            "frozen_execution_plan_identity": run.plan["comparison_id"],
            "bindings": [file_binding(p) for p in sorted(set(snapshots))],
        },
        rows,
        artifacts,
    )


def _pipeline_blocks(
    original, recipe
) -> list[tuple[tuple, np.ndarray, int, ChildSpec | None, bool]]:
    result = []
    schema = original.schema.to_document()
    for description in schema["values"]:
        name, axis = description["name"], description["time_axis"]
        values = np.array(original.values[name], copy=True)
        if schema["null_recovery_contract"] == "SEMANTIC" and original.validity is not None:
            values[~original.validity[name]] = 0
        count = math.prod(v for i, v in enumerate(description["shape"]) if i != axis)
        columns = np.moveaxis(values, axis, 0).reshape(original.schema.n, count)
        for column in range(count):
            for start in range(0, original.schema.n, recipe.block_size):
                block = np.ascontiguousarray(columns[start : start + recipe.block_size, column])
                raw = block.size < recipe.block_size and recipe.tail_policy == "RAW_TAIL"
                result.append(
                    (
                        ("VALUE", name, column, start),
                        block,
                        block.nbytes * 8,
                        recipe.value_children[name],
                        raw,
                    )
                )
    if original.timestamp is not None:
        for start in range(0, original.schema.n, recipe.block_size):
            block = original.timestamp[start : start + recipe.block_size]
            raw = block.size < recipe.block_size and recipe.tail_policy == "RAW_TAIL"
            result.append(
                (
                    ("TIMESTAMP", "timestamp", 0, start),
                    block,
                    block.nbytes * 8,
                    recipe.timestamp_child,
                    raw,
                )
            )
    if original.validity is not None:
        for name, mask in original.validity.items():
            packed = np.packbits(mask.reshape(-1), bitorder="little")
            if packed.size:
                result.append(
                    (("VALIDITY", name, 0, 0), packed, mask.size, recipe.mask_child, False)
                )
    return result


def pipeline_profile(project_root: Path, original, recipe, stream: bytes) -> dict[str, Any]:
    header, payload = _parse(stream)
    require(
        header["logical_schema"] == original.schema.to_document()
        and header["logical_content_id"] == original.content_id
        and header["underlying_bytes_sha256"] == original.underlying_bytes_sha256
        and header["canonical_raw_bits"] == original.canonical_raw_bits
        and header["recipe"] == recipe.to_document()
        and header["recipe_id"] == recipe.recipe_id,
        "P2 original/recipe identity mismatch",
    )
    blocks = _pipeline_blocks(original, recipe)
    require(len(blocks) == len(header["nodes"]), "P2 missing or extra child")
    nodes, offset, original_bits = [], 0, 0
    schema = original.schema.to_document()
    for node, (slot, values, logical_bits, child, raw) in zip(header["nodes"], blocks, strict=True):
        require(
            (node["role"], node["owner"], node["column"], node["start"]) == slot
            and node["count"] == values.size
            and node["dtype"] == values.dtype.str
            and node["offset"] == offset
            and type(node["length"]) is int
            and node["length"] >= 0,
            "P2 child mapping/count/offset mismatch",
        )
        end = offset + node["length"]
        require(end <= len(payload), "P2 child beyond actual payload")
        part = payload[offset:end]
        require(hashlib.sha256(part).hexdigest() == node["sha256"], "P2 child stream hash mismatch")
        original_bits += logical_bits
        row = {
            "node_id": node["node_id"],
            "role": slot[0],
            "owner": slot[1],
            "column": slot[2],
            "start": slot[3],
            "encoding": node["encoding"],
            "logical": array_cost(values, logical_bits=logical_bits),
            "serialized_bytes": metric(
                len(part), "MEASURED", "ACTUAL_NONOVERLAPPING_RETAINED_CHILD_SLICE"
            ),
            "output_capacity_bytes": unknown(CAPACITY_REASON),
            "native": opaque_native_costs(),
        }
        if raw or child is None:
            require(
                node["encoding"] == "RAW" and node["child"] is None and part == values.tobytes(),
                "P2 raw bytes mismatch",
            )
            row["adapted_payload_bytes"] = metric(
                values.nbytes, "INSTRUMENTED", "RAW_CHILD_EXACT_PAYLOAD"
            )
            row["codec_input_bytes"] = metric(
                0, "INSTRUMENTED", "RAW_CHILD_HAS_NO_CODEC_SUBMISSION"
            )
            row["preparation"] = None
        else:
            require(node["encoding"] == "CODEC", "P2 child encoding mismatch")
            track = BenchmarkTrack.TIMESTAMP if slot[0] == "TIMESTAMP" else BenchmarkTrack.VALUE
            unit = (
                "BOOLEAN"
                if slot[0] == "VALIDITY"
                else next(
                    (v["unit"] for v in schema["values"] if v["name"] == slot[1]), "NOT_APPLICABLE"
                )
            )
            manifest, routed, prepared, context, parameters, plan = _prepare_child(
                project_root,
                child,
                values,
                track,
                {"kind": "LOSSLESS"} if slot[0] == "VALIDITY" else recipe.loss_contract,
                schema["timestamp"]["unit"],
                schema["timestamp"]["epoch"],
                unit,
            )
            saved = node["child"]
            require(
                saved["codec_key"] == child.codec_key
                and saved["manifest"] == manifest.document
                and saved["parameters"] == parameters
                and saved["compatibility_plan"] == evidence_document(plan.to_document())
                and saved["decode_context"] == context.to_document()
                and saved["accounting"]["serialized_bits"] == len(part) * 8,
                "P2 child input/codec/accounting metadata mismatch",
            )
            row["preparation"] = preparation_costs(routed, prepared)
            row["adapted_payload_bytes"] = row["preparation"]["adapted_payload_bytes"]
            row["codec_input_bytes"] = metric(
                sum(b.array.nbytes for b in prepared.codec_input.buffers),
                "INSTRUMENTED",
                "EXACT_P2_CHILD_SESSION_BUFFERS",
            )
        nodes.append(row)
        offset = end
    require(
        offset == len(payload) and original_bits == original.canonical_raw_bits,
        "P2 child payload/original denominator does not close",
    )
    object_buffers = {
        name: array_cost(values, logical_bits=values.nbytes * 8)
        for name, values in original.values.items()
    }
    if original.timestamp is not None:
        object_buffers["timestamp"] = array_cost(
            original.timestamp, logical_bits=original.timestamp.nbytes * 8
        )
    if original.validity is not None:
        for name, mask in original.validity.items():
            object_buffers["validity/" + name] = array_cost(mask, logical_bits=mask.size)
    return {
        "stream_sha256": hashlib.sha256(stream).hexdigest(),
        "canonical_raw_bits": metric(
            original_bits, "INSTRUMENTED", "SUM_ORIGINAL_CHILD_BITS_VALIDITY_NOT_BYTE_ROUNDED"
        ),
        "artifact_physical_bytes": metric(len(stream), "MEASURED", "RETAINED_P2_FILE_LENGTH"),
        "payload_bytes": metric(
            len(payload), "MEASURED", "SUM_NONOVERLAPPING_CHILD_PHYSICAL_SLICES"
        ),
        "metadata_and_frame_bytes": metric(
            len(stream) - len(payload), "MEASURED", "ACTUAL_FRAME_AND_PUBLIC_TREE_LENGTH"
        ),
        "final_bits": metric(len(stream) * 8, "MEASURED", "COMPLETE_RETAINED_P2_ARTIFACT"),
        "children": nodes,
        "original_object_buffers": object_buffers,
        "framework_column_block_assembly_costs": {
            "read_bytes": unknown("ASSEMBLY_AND_HASH_READ_TRAFFIC_NOT_INSTRUMENTED"),
            "write_bytes": unknown("ASSEMBLY_WRITE_TRAFFIC_NOT_INSTRUMENTED"),
            "allocated_bytes": unknown("FULL_OBJECT_ASSEMBLY_ALLOCATIONS_NOT_INSTRUMENTED"),
            "peak_live_bytes": unknown("OBJECT_TREE_AND_OUTPUT_PEAK_NOT_INSTRUMENTED"),
        },
    }


def _pipeline_costs(run_path: Path) -> tuple[dict, list[dict], list[dict]]:
    plan = read(run_path / "plan.json")
    validate_pipeline_plan(plan)
    require(Path(plan["project_root"]).resolve() == ROOT, "P2 belongs to another project")
    cells = {c["cell_id"]: c for c in plan["cells"]}
    datasets = {d["dataset_key"]: d for d in plan["datasets"]}
    snapshots = [run_path / "plan.json", run_path / "trials.jsonl"]
    for dataset in datasets.values():
        snapshots.extend(Path(dataset[s]["path"]) for s in ("test", "development"))
        snapshots.extend(Path(f["path"]) for f in dataset.get("source_files", []))
    profiles, artifacts = {}, []
    for line in (run_path / "trials.jsonl").read_text().splitlines():
        trial = json.loads(line)
        if "artifact_path" not in trial:
            continue
        cell = cells[trial["cell_id"]]
        path = Path(trial["artifact_path"]).resolve()
        require(path.is_relative_to(run_path), "P2 artifact escapes run directory")
        require(sha(path) == trial["artifact_sha256"], "P2 saved artifact hash mismatch")
        key = (cell["cell_id"], trial["artifact_sha256"])
        if key not in profiles:
            original = load_pipeline_input(datasets[cell["dataset_key"]]["test"])
            profiles[key] = {
                "cell_id": cell["cell_id"],
                "dataset_key": cell["dataset_key"],
                "method_id": cell["method_id"],
                "execution_job_id": cell["execution_job_id"],
                "recipe_id": cell["recipe_id"],
                "costs": pipeline_profile(
                    ROOT, original, PipelineRecipe.from_document(cell["recipe"]), path.read_bytes()
                ),
            }
        artifacts.append(
            {
                "trial_id": trial["trial_id"],
                "cell_id": cell["cell_id"],
                "artifact_profile_sha256": key[1],
                "files": [file_binding(path)],
            }
        )
    missing = set(cells) - {key[0] for key in profiles}
    rows = list(profiles.values()) + [
        {
            "cell_id": c,
            "status": "NO_RETAINED_ARTIFACT",
            "reason": "NO_OUTPUT_COST_OBSERVATION",
            "costs": None,
        }
        for c in sorted(missing)
    ]
    return (
        {
            "run_set_id": plan["run_set_id"],
            "closure": plan["closure"],
            "bindings": [file_binding(p) for p in sorted(set(snapshots))],
        },
        rows,
        artifacts,
    )


def build_buffer_cost_audit(run_path: Path, lane: str) -> dict[str, Any]:
    require(lane in LANES, "unknown cost-audit lane")
    run_path = run_path.resolve()
    identity, rows, artifacts = (
        _pipeline_costs(run_path) if lane == "pipeline" else _comparison_costs(run_path, lane)
    )
    document = {
        "schema_version": VERSION,
        "status": "AUXILIARY_COST_AUDIT",
        "lane": lane,
        "run_path": str(run_path),
        "audit_tool": file_binding(Path(__file__)),
        "control_plane": control_plane_snapshot(ROOT),
        "frozen_evidence": identity,
        "cells_or_artifact_profiles": rows,
        "retained_artifacts": artifacts,
        "codec_invoked": False,
        "formal_eligible": False,
        "performance_remeasured": False,
        "observation_relationship": (
            "SEPARATE_DETERMINISTIC_PREPARATION_NOT_SAME_PERFORMANCE_EXECUTION"
        ),
        "units": {"sizes": "BYTES_UNLESS_FIELD_ENDS_BITS", "counts": "INTEGER_COUNTS"},
        "limitations": [
            "CPU_BUFFER_PREPARATION_ONLY_NOT_FULL_MATHEMATICAL_DOMAIN_COVERAGE",
            "NUMPY_ALLOCATIONS_EXCLUDE_VALIDATOR_HASH_PYTHON_AND_NATIVE_TEMPORARIES",
            "ADAPTER_READ_WRITE_MODELS_ARE_ESTIMATED_NOT_HARDWARE_TRAFFIC",
            "BACKING_STORAGE_PER_VIEW_MAY_ALIAS_AND_CANNOT_BE_NAIVELY_SUMMED",
            "NATIVE_INPUT_AND_INTERNAL_COSTS_UNKNOWN_UNLESS_SEPARATELY_INSTRUMENTED",
            "CAPACITY_AND_PADDING_ARE_NOT_PAYLOAD_OR_FINALBITS",
            "NO_PERFORMANCE_QUALIFICATION_OR_FORMAL_STATUS_GRANTED",
        ],
    }
    document = evidence_document(document)
    document["audit_id"] = stable_id("auxiliary-buffer-cost-audit-v32", document)
    return document


def validate_buffer_cost_audit(run_path: Path, lane: str) -> dict[str, Any]:
    document = read(run_path / "buffer_cost_audit.json")
    require(
        document == build_buffer_cost_audit(run_path, lane),
        "buffer cost evidence differs from frozen inputs/artifacts/current code",
    )
    return document


def write_buffer_cost_audit(run_path: Path, lane: str) -> dict[str, Any]:
    document = build_buffer_cost_audit(run_path, lane)
    path = run_path / "buffer_cost_audit.json"
    payload = canonical_json_bytes(document) + b"\n"
    if path.exists():
        require(path.read_bytes() == payload, "immutable auxiliary cost audit differs")
    else:
        with path.open("xb") as handle:
            handle.write(payload)
    markdown = [
        "# V3.2 独立缓冲区成本审计",
        "",
        f"状态：`AUXILIARY_COST_AUDIT`；lane：`{lane}`；身份：`{document['audit_id']}`。",
        "",
        "该审计只运行冻结输入的 CPU 准备与散列、解析实际已保存的码流。"
        "它是独立成本观察，不是同次性能试验，不产生 FORMAL 资格，不调用编码或解码器。",
        "",
        "每个指标均记录 evidence_method 与 unavailable_reason。INSTRUMENTED 表示"
        "本次准备的 NumPy 载荷/可见 backing/适配器输出；ESTIMATED 表示公开复制模型与计划；"
        "MEASURED 表示实际工件长度。原生内部访问、分配、峰值和未保存容量为 null＋具体原因。",
        "",
        "原始逻辑 bits、adapted 与 codec 输入、容量/padding、最终存储成本独立记录。"
        "validity 逻辑 bit 不按 byte 扩大分母；共享 backing 不能逐视图相加。",
        "",
        f"观察 `{len(document['cells_or_artifact_profiles'])}` 个单元/工件形态，"
        f"绑定 `{len(document['retained_artifacts'])}` 个已保存试验工件。",
        "",
        "全部 frozen plan、输入、工件与当前控制代码散列见同目录 buffer_cost_audit.json。",
        "",
    ]
    (run_path / "buffer_cost_audit.md").write_text("\n".join(markdown))
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_path", type=Path)
    parser.add_argument("--lane", choices=LANES, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    document = (validate_buffer_cost_audit if args.check else write_buffer_cost_audit)(
        args.run_path.resolve(), args.lane
    )
    print(
        json.dumps(
            {"status": document["status"], "audit_id": document["audit_id"], "codec_invoked": False}
        )
    )


if __name__ == "__main__":
    main()
