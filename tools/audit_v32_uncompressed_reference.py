"""Complete uncompressed object references; size evidence only, never a codec.

Canonical whole objects and public NumPy/P2 raw readers provide independent
recovery. Matched Track references pay both NPZ framing and semantic context.
Full object costs cannot be compared with NATIVE_COMPONENT/CORE costs.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
import zipfile
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
from tscompbench.comparison.runner import control_plane_snapshot, prepare_comparison  # noqa: E402
from tscompbench.comparison.workload_runner import validate_workload_plan  # noqa: E402
from tscompbench.contracts import BenchmarkTrack  # noqa: E402
from tscompbench.datasets import DatasetRegistry, read_canonical  # noqa: E402
from tscompbench.execution.preparation import prepare_execution_input  # noqa: E402
from tscompbench.execution.protocol import LogicalBuffer  # noqa: E402
from tscompbench.execution.routing import (  # noqa: E402
    hash_logical_buffers,
    route_canonical_artifact,
)
from tscompbench.ids import canonical_json_bytes, stable_id  # noqa: E402
from tscompbench.pipelines import validate_restored_object  # noqa: E402

LANES = ("comparison", "workload", "pipeline")
VERSION = "tscb.uncompressed-object-reference.v3.2"
PERFORMANCE_REASON = "SIZE_BASELINE_ONLY_NO_UNCOMPRESSED_PERFORMANCE_TRIAL"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read(path: Path) -> Any:
    return json.loads(path.read_bytes())


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha(path.read_bytes()),
        "physical_bytes": path.stat().st_size,
    }


def _immutable(path: Path, data: bytes, *, writing: bool) -> None:
    if path.exists():
        _require(path.read_bytes() == data, "immutable uncompressed reference changed")
    elif writing:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)
    else:
        raise ValueError("missing uncompressed reference artifact")


def _npz(arrays: dict[str, np.ndarray]) -> bytes:
    handle = io.BytesIO()
    np.savez(handle, **arrays)
    return handle.getvalue()


def _raw_npz_read(path: Path, expected: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    # NPZ is a stored ZIP container; no entropy codec or compression is used.
    with zipfile.ZipFile(path) as archive:
        _require(
            all(entry.compress_type == zipfile.ZIP_STORED for entry in archive.infolist()),
            "uncompressed reference contains compressed ZIP members",
        )
    with np.load(path, allow_pickle=False) as arrays:
        _require(arrays.files == list(expected), "uncompressed ordered buffer inventory changed")
        restored = {name: arrays[name].copy() for name in arrays.files}
    for name, value in restored.items():
        original = expected[name]
        _require(
            value.dtype.str == original.dtype.str
            and value.shape == original.shape
            and value.tobytes(order="C") == original.tobytes(order="C"),
            "public uncompressed decoder changed dtype/shape/original bits",
        )
    return restored


def read_uncompressed_track(frame_path: Path, context_path: Path) -> tuple[LogicalBuffer, ...]:
    """Restore only from the two paid artifacts, without an original input argument."""
    _require(
        context_path.stat().st_size <= 16 * 1024 * 1024, "uncompressed Track context exceeds budget"
    )
    document = _read(context_path)
    fields = {
        "schema_version",
        "dataset_id",
        "track",
        "logical_descriptor",
        "n",
        "m",
        "input_sha256",
        "canonical_raw_bits",
        "timestamp_unit",
        "timestamp_epoch",
        "value_units",
        "pairing_reference_sha256_provenance_only",
        "buffers",
        "excluded_track_buffers",
        "excluded_payload_is_not_required_to_restore_selected_track",
        "artifact_sha256",
        "context_id",
    }
    _require(
        isinstance(document, dict) and set(document) == fields, "invalid paid Track context fields"
    )
    _require(
        document["schema_version"] == "tscb.uncompressed-track-context.v1"
        and document["track"] in {"VALUE", "TIMESTAMP", "SYSTEM"},
        "invalid paid Track context version/track",
    )
    identity = {key: value for key, value in document.items() if key != "context_id"}
    _require(
        document["context_id"] == stable_id("uncompressed-track-context-v32", identity),
        "paid Track context identity changed",
    )
    _require(
        context_path.read_bytes() == canonical_json_bytes(document) + b"\n",
        "paid Track context is not canonical",
    )
    _require(
        frame_path.stat().st_size <= 528 * 1024 * 1024
        and _sha(frame_path.read_bytes()) == document["artifact_sha256"],
        "paid Track artifact hash/budget changed",
    )
    _require(
        type(document["n"]) is int
        and document["n"] >= 0
        and type(document["m"]) is int
        and document["m"] >= 0,
        "invalid original Track dimensions",
    )
    rows = document["buffers"]
    _require(
        isinstance(rows, list) and 1 <= len(rows) <= 100_000,
        "invalid ordered Track buffer inventory",
    )
    names, payload_bytes, raw_bits = [], 0, 0
    for index, row in enumerate(rows):
        _require(
            isinstance(row, dict)
            and set(row) == {"wire_name", "name", "dtype", "shape", "logical_bits"},
            "invalid Track buffer fields",
        )
        _require(
            row["wire_name"] == f"buffer_{index}" and isinstance(row["name"], str) and row["name"],
            "invalid ordered Track buffer names",
        )
        _require(isinstance(row["dtype"], str), "Track dtype must use explicit wire spelling")
        dtype = np.dtype(row["dtype"])
        shape = row["shape"]
        _require(
            dtype.str == row["dtype"]
            and dtype.kind in "biuf"
            and dtype.itemsize <= 8
            and isinstance(shape, list)
            and 1 <= len(shape) <= 32
            and all(type(size) is int and size >= 0 for size in shape),
            "invalid explicit Track dtype/shape",
        )
        _require(
            math.prod(max(1, size) for size in shape) * dtype.itemsize <= 512 * 1024 * 1024,
            "Track shape exceeds checked budget",
        )
        size = math.prod(shape)
        expected_bits = size if row["name"] == "validity" else size * dtype.itemsize * 8
        _require(
            type(row["logical_bits"]) is int and row["logical_bits"] == expected_bits,
            "paid original Track logical bits disagree with buffer",
        )
        _require(
            row["name"] != "validity" or dtype == np.dtype(np.bool_),
            "validity requires explicit boolean raw array",
        )
        names.append(row["name"])
        payload_bytes += size * dtype.itemsize
        raw_bits += expected_bits
    _require(
        len(set(names)) == len(names)
        and payload_bytes <= 512 * 1024 * 1024
        and type(document["canonical_raw_bits"]) is int
        and raw_bits == document["canonical_raw_bits"],
        "paid Track identity/RawBits does not close",
    )
    _require(
        document["track"] != "TIMESTAMP"
        or names == ["timestamp"]
        and rows[0]["shape"] == [document["n"]]
        and np.dtype(rows[0]["dtype"]).kind in "iu"
        and np.dtype(rows[0]["dtype"]).itemsize == 8,
        "Timestamp reference must restore only original T",
    )
    _require(
        document["track"] != "VALUE" or "timestamp" not in names,
        "Value reference contains task-external timestamp payload",
    )
    with zipfile.ZipFile(frame_path) as archive:
        entries = archive.infolist()
        _require(
            [entry.filename for entry in entries] == [row["wire_name"] + ".npy" for row in rows]
            and all(entry.compress_type == zipfile.ZIP_STORED for entry in entries),
            "uncompressed Track container has hidden/reordered/compressed members",
        )
        # Check every NPY header against bounded paid instructions before np.load
        # can allocate from a forged array-header shape.
        for row, entry in zip(rows, entries, strict=True):
            with archive.open(entry) as handle:
                version = np.lib.format.read_magic(handle)
                _require(version in {(1, 0), (2, 0)}, "unsupported raw NPY header")
                reader = (
                    np.lib.format.read_array_header_1_0
                    if version == (1, 0)
                    else np.lib.format.read_array_header_2_0
                )
                shape, _, dtype = reader(handle)
                _require(
                    list(shape) == row["shape"]
                    and dtype.str == row["dtype"]
                    and handle.tell() + math.prod(shape) * dtype.itemsize == entry.file_size,
                    "stored NPY header/payload differs from paid schema",
                )
    with np.load(frame_path, allow_pickle=False) as arrays:
        result = tuple(
            LogicalBuffer(row["name"], arrays[row["wire_name"]].copy(), row["logical_bits"])
            for row in rows
        )
    _require(
        hash_logical_buffers(result) == document["input_sha256"],
        "public uncompressed Track input identity changed",
    )
    for buffer in result:
        buffer.array.flags.writeable = False
    return result


def _ledger(
    raw_bits: int, payload_bytes: int, artifact_bytes: int, context_bytes=0
) -> dict[str, int]:
    _require(
        type(raw_bits) is int and raw_bits >= 0 and artifact_bytes >= payload_bytes >= 0,
        "invalid uncompressed reference ledger",
    )
    return {
        "canonical_raw_bits": raw_bits,
        "payload_physical_bits": payload_bytes * 8,
        "metadata_and_frame_bits": (artifact_bytes - payload_bytes) * 8,
        "serialized_bits": artifact_bytes * 8,
        "required_external_bits": context_bytes * 8,
        "final_bits": (artifact_bytes + context_bytes) * 8,
    }


def _inputs(run_path: Path, lane: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load and validate existing frozen plans and original data, without codecs."""
    if lane == "pipeline":
        plan = _read(run_path / "plan.json")
        validate_pipeline_plan(plan)
        _require(Path(plan["project_root"]).resolve() == ROOT, "P2 reference project differs")
        used = {row["dataset_key"] for row in plan["cells"]}
        objects, bindings = [], [run_path / "plan.json"]
        for dataset in plan["datasets"]:
            if dataset["dataset_key"] not in used:
                continue
            original = load_pipeline_input(dataset["test"])
            objects.append(
                {
                    "key": dataset["dataset_key"],
                    "original": original,
                    "source": dataset["test"],
                    "track": "COMPLETE_LOGICAL_OBJECT",
                    "cost_boundary": "SCHEMA_BOUND_OBJECT",
                    "native_input_sizes": [],
                }
            )
            bindings.append(Path(dataset["test"]["path"]))
            bindings.extend(Path(row["path"]) for row in dataset.get("source_files", []))
        identity = {"run_set_id": plan["run_set_id"], "closure": plan["closure"]}
    else:
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
                _read(run_path / "workload_plan.json")["protocol"] if lane == "workload" else None
            ),
        )
        _require(
            _read(run_path / "control_plane.json") == control_plane_snapshot(ROOT),
            "uncompressed reference run has stale control plane",
        )
        plan = _read(run_path / "execution_plan.json")
        identity = {"comparison_id": plan["comparison_id"]}
        bindings = [
            run_path / name for name in ("bundle.json", "execution_plan.json", "control_plane.json")
        ]
        if lane == "workload":
            workload = _read(run_path / "workload_plan.json")
            validate_workload_plan(workload, plan, run.bundle, run_path)
            identity["workload_id"] = workload["workload_id"]
            bindings.append(run_path / "workload_plan.json")
        objects = []
        for dataset_id in sorted({cell["dataset_id"] for cell in run.cells.values()}):
            artifact = read_canonical(run.artifacts[dataset_id].path)
            cells = [cell for cell in run.cells.values() if cell["dataset_id"] == dataset_id]
            task = run.tasks[cells[0]["cell_id"]]
            native = []
            if run.bundle["contract"]["cost_boundary"] == "NATIVE_COMPONENT":
                for cell in cells:
                    current = run.tasks[cell["cell_id"]]
                    routed = route_canonical_artifact(artifact, current.track)
                    prepared = prepare_execution_input(
                        routed,
                        current.compatibility,
                        max_abs_error=cell["parameters"].get("error_bound"),
                    )
                    native.append(
                        {
                            "cell_id": cell["cell_id"],
                            "codec_key": cell["codec_key"],
                            "execution_job_id": cell["execution_job_id"],
                            "input_payload_bytes": sum(
                                b.array.nbytes for b in prepared.codec_input.buffers
                            ),
                            "buffers": [
                                {
                                    "name": b.name,
                                    "dtype": b.array.dtype.str,
                                    "shape": list(b.array.shape),
                                    "physical_bytes": b.array.nbytes,
                                }
                                for b in prepared.codec_input.buffers
                            ],
                            "codec_invoked": False,
                            "performance": None,
                            "performance_unavailable_reason": PERFORMANCE_REASON,
                            "scope": "NATIVE_INPUT_SIZE_ONLY_NO_CONTAINER_OR_CAPACITY",
                        }
                    )
            objects.append(
                {
                    "key": dataset_id,
                    "original": artifact,
                    "track": task.track.value,
                    "source": _binding(artifact.path),
                    "cost_boundary": run.bundle["contract"]["cost_boundary"],
                    "native_input_sizes": native,
                    "allow_missing_timestamp": all(
                        cell["dataset_role"] != "CORE"
                        and cell["expected_outcome"] == "REJECT"
                        and cell["expected"]["stage"] == "INPUT_NEGOTIATION"
                        for cell in cells
                    ),
                }
            )
            bindings.append(artifact.path)
        for directory in ("dataset_manifests",):
            bindings.extend(sorted((run_path / directory).glob("*.json")))
    _require(bool(objects), "uncompressed reference has no original objects")
    return {**identity, "bindings": [_binding(path) for path in sorted(set(bindings))]}, objects


def _canonical_reference(row, directory, writing):
    original = row["original"]
    stem = stable_id("uncompressed-reference-object", {"key": row["key"]}).rsplit(":", 1)[-1]
    complete = directory / (stem + ".canonical.tscb")
    _immutable(complete, original.path.read_bytes(), writing=writing)
    restored = read_canonical(complete)
    _require(
        restored.metadata == original.metadata and restored.buffers == original.buffers,
        "public canonical reader did not recover complete original object",
    )
    object_raw_bits = int(original.metadata["accounting"]["canonical_raw_bits"])
    whole = {
        "scope": "COMPLETE_DATASET_OBJECT_ALL_T_V_VALIDITY",
        "artifact": _binding(complete),
        "required_context": None,
        "ledger": _ledger(
            object_raw_bits,
            sum(len(data) for data in original.buffers.values()),
            complete.stat().st_size,
        ),
        "can_compare_to_formal_final_bits": row["track"] == "SYSTEM"
        and row["cost_boundary"] == "SCHEMA_BOUND_OBJECT",
        "independent_decoder": "tscompbench.datasets.read_canonical",
        "original_available_to_decoder": False,
        "recovery": "BIT_EXACT_COMPLETE_OBJECT",
    }
    if row["track"] == "TIMESTAMP" and "timestamp" not in original.buffers:
        _require(
            row.get("allow_missing_timestamp") is True,
            "legal/core Timestamp reference unexpectedly lacks original T",
        )
        matched = {
            "status": "NOT_APPLICABLE",
            "reason": "TIMESTAMP_UNAVAILABLE_EXPECTED_EXTENSION",
            "can_compare_to_formal_final_bits": False,
            "ledger": None,
        }
    else:
        routed = route_canonical_artifact(original, BenchmarkTrack(row["track"]))
        arrays = {f"buffer_{index}": buffer.array for index, buffer in enumerate(routed.buffers)}
        frame = directory / (stem + ".track.npz")
        context = directory / (stem + ".track.context.json")
        data = _npz(arrays)
        document = {
            "schema_version": "tscb.uncompressed-track-context.v1",
            "dataset_id": routed.dataset_id,
            "track": routed.track.value,
            "logical_descriptor": original.metadata["logical_descriptor"],
            "n": routed.n,
            "m": routed.m,
            "input_sha256": routed.input_sha256,
            "canonical_raw_bits": routed.canonical_raw_bits,
            "timestamp_unit": routed.timestamp_unit,
            "timestamp_epoch": routed.timestamp_epoch,
            "value_units": list(routed.value_units),
            "pairing_reference_sha256_provenance_only": routed.pairing_reference_sha256,
            "buffers": [
                {
                    "wire_name": f"buffer_{index}",
                    "name": buffer.name,
                    "dtype": buffer.array.dtype.str,
                    "shape": list(buffer.array.shape),
                    "logical_bits": buffer.logical_bits,
                }
                for index, buffer in enumerate(routed.buffers)
            ],
            "excluded_track_buffers": [
                name
                for name in original.buffers
                if name not in {buffer.name for buffer in routed.buffers}
            ],
            "excluded_payload_is_not_required_to_restore_selected_track": True,
            "artifact_sha256": _sha(data),
        }
        document["context_id"] = stable_id("uncompressed-track-context-v32", document)
        _immutable(frame, data, writing=writing)
        _immutable(context, canonical_json_bytes(document) + b"\n", writing=writing)
        paid_context = _read(context)
        _require(paid_context == document, "paid uncompressed Track context changed")
        rebuilt = read_uncompressed_track(frame, context)
        # The standalone reader receives only NPZ + paid context; source metadata
        # is used here solely to validate that its complete Track output matches.
        _require(
            all(
                buffer.name == original_buffer.name
                and buffer.array.tobytes(order="C") == original_buffer.array.tobytes(order="C")
                and buffer.array.dtype.str == original_buffer.array.dtype.str
                and buffer.array.shape == original_buffer.array.shape
                and buffer.logical_bits == original_buffer.logical_bits
                for buffer, original_buffer in zip(rebuilt, routed.buffers, strict=True)
            ),
            "public Track recovery changed original values/schema/validity",
        )
        _require(
            hash_logical_buffers(rebuilt) == document["input_sha256"],
            "independent Track recovery identity differs",
        )
        matched = {
            "status": "PASS",
            "scope": "COMPLETE_SELECTED_TRACK_WITH_PAID_SCHEMA",
            "artifact": _binding(frame),
            "required_context": _binding(context),
            "ledger": _ledger(
                routed.canonical_raw_bits,
                sum(value.nbytes for value in arrays.values()),
                frame.stat().st_size,
                context.stat().st_size,
            ),
            "can_compare_to_formal_final_bits": row["cost_boundary"] == "SCHEMA_BOUND_OBJECT",
            "independent_decoder": "audit_v32_uncompressed_reference.read_uncompressed_track",
            "original_available_to_decoder": False,
            "recovery": "BIT_EXACT_SELECTED_TRACK",
            "input_sha256": routed.input_sha256,
            "paid_context": document,
        }
    return {
        "object_key": row["key"],
        "source": row["source"],
        "track": row["track"],
        "cost_boundary": row["cost_boundary"],
        "dataset_complete_raw_bits": object_raw_bits,
        "complete_object_reference": whole,
        "matched_boundary_reference": matched,
        "native_input_sizes": row["native_input_sizes"],
    }


def _pipeline_reference(row, directory, writing):
    original = row["original"]
    stem = stable_id("uncompressed-reference-object", {"key": row["key"]}).rsplit(":", 1)[-1]
    frame = directory / (stem + ".logical.npz")
    context = directory / (stem + ".logical.context.json")
    arrays = {f"value_{index}": value for index, value in enumerate(original.values.values())}
    if original.timestamp is not None:
        arrays["timestamp"] = original.timestamp
    if original.validity is not None:
        arrays.update(
            {f"mask_{index}": mask for index, mask in enumerate(original.validity.values())}
        )
    data = _npz(arrays)
    document = {
        "schema": original.schema.to_document(),
        "logical_content_id": original.content_id,
        "underlying_bytes_sha256": original.underlying_bytes_sha256,
        "canonical_raw_bits": original.canonical_raw_bits,
        "validity_present": original.validity is not None,
        "path": frame.name,
        "file_sha256": _sha(data),
    }
    _immutable(frame, data, writing=writing)
    _immutable(context, canonical_json_bytes(document) + b"\n", writing=writing)
    _raw_npz_read(frame, arrays)
    paid_context = _read(context)
    _require(paid_context == document, "paid P2 raw context changed")
    restored = load_pipeline_input({**paid_context, "path": str(frame.resolve())})
    _require(
        validate_restored_object(original, restored)["passed"]
        and original.underlying_bytes_sha256 == restored.underlying_bytes_sha256,
        "public raw P2 decoder did not restore the complete original object",
    )
    whole = {
        "status": "PASS",
        "scope": "COMPLETE_LOGICAL_OBJECT_ALL_T_V_VALIDITY",
        "artifact": _binding(frame),
        "required_context": _binding(context),
        "ledger": _ledger(
            original.canonical_raw_bits,
            sum(value.nbytes for value in arrays.values()),
            frame.stat().st_size,
            context.stat().st_size,
        ),
        "can_compare_to_formal_final_bits": True,
        "independent_decoder": "tscompbench.comparison.pipeline_runner.load_pipeline_input",
        "original_available_to_decoder": False,
        "recovery": "BIT_EXACT_COMPLETE_OBJECT",
        "schema_id": original.schema.schema_id,
        "content_id": original.content_id,
        "underlying_bytes_sha256": original.underlying_bytes_sha256,
        "paid_context": document,
    }
    return {
        "object_key": row["key"],
        "source": row["source"],
        "track": row["track"],
        "cost_boundary": row["cost_boundary"],
        "dataset_complete_raw_bits": original.canonical_raw_bits,
        "complete_object_reference": whole,
        "matched_boundary_reference": whole,
        "native_input_sizes": [],
    }


def build_uncompressed_reference(run_path: Path, lane: str, *, writing=False) -> dict[str, Any]:
    _require(lane in LANES, "unknown uncompressed-reference lane")
    run_path = run_path.resolve()
    control_before = control_plane_snapshot(ROOT)
    frozen, inputs = _inputs(run_path, lane)
    rows = [
        (_pipeline_reference if lane == "pipeline" else _canonical_reference)(
            row, run_path / "reference_artifacts", writing
        )
        for row in inputs
    ]
    for row in rows:
        files = {}
        for reference in (row["complete_object_reference"], row["matched_boundary_reference"]):
            for role in ("artifact", "required_context"):
                if reference.get(role) is not None:
                    item = reference[role]
                    files[item["path"]] = item
        row["files"] = list(files.values())
    _require(control_before == control_plane_snapshot(ROOT), "uncompressed reference source drift")
    document = {
        "schema_version": VERSION,
        "status": "UNCOMPRESSED_REFERENCE_AUDIT",
        "baseline_kind": "SIZE_BASELINE",
        "lane": lane,
        "run_path": str(run_path),
        "control_plane": control_before,
        "audit_tool": _binding(Path(__file__)),
        "frozen_evidence": frozen,
        "object_count": len(rows),
        "objects": rows,
        "codec_invoked": False,
        "registered_codec": False,
        "statistical_method_count": 0,
        "formal_performance_eligible": False,
        "formal_eligible": False,
        "performance_remeasured": False,
        "performance": None,
        "performance_unavailable_reason": PERFORMANCE_REASON,
        "storage_cost_boundary": "ARTIFACT_PLUS_ALL_REQUIRED_EXTERNAL_CONTEXT",
        "raw_bits_are_not_complete_storage_cost": True,
        "native_component_vs_complete_object_cost_comparable": False,
    }
    document["reference_id"] = stable_id("uncompressed-object-reference-v32", document)
    document["audit_id"] = document["reference_id"]
    return document


def validate_uncompressed_reference(run_path: Path, lane: str) -> dict[str, Any]:
    document = _read(run_path / "uncompressed_reference.json")
    _require(
        document == build_uncompressed_reference(run_path, lane),
        "uncompressed reference differs from current frozen inputs or saved paid artifacts",
    )
    return document


def write_uncompressed_reference(run_path: Path, lane: str) -> dict[str, Any]:
    document = build_uncompressed_reference(run_path, lane, writing=True)
    _immutable(
        run_path / "uncompressed_reference.json",
        canonical_json_bytes(document) + b"\n",
        writing=True,
    )
    text = (
        "# V3.2 完整未压缩对象参考\n\n"
        f"状态 `UNCOMPRESSED_REFERENCE_AUDIT`；SIZE_BASELINE；lane `{lane}`；"
        f"{document['object_count']} 个原对象。\n\n"
        "保存完整 canonical 或未压缩 NPZ 与全部付费恢复 context，公开 raw reader 独立恢复原"
        "schema/dtype/shape/T/V/validity 与位模式。FinalBits 计入文件及必要外部 context；"
        "RawBits 保留原任务分母，不代替完整存储成本。\n\n"
        "SCHEMA_BOUND_OBJECT 另有匹配所选 Track 的完整 schema 参考；完整数据对象保留任务外"
        "T/V 但不与仅 Track 成本混用。P2 匹配完整逻辑对象。NATIVE_COMPONENT/CORE 只报告独立"
        "native 输入 size，完整对象参考的 can_compare=false。\n\n"
        "该参考不注册 codec，不增加统计方法数；没有 encode/decode 性能试验，performance=null"
        "并记录原因。不调用压缩算法，不授予正式性能资格。\n"
    )
    _immutable(run_path / "uncompressed_reference.md", text.encode(), writing=True)
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_path", type=Path)
    parser.add_argument("--lane", choices=LANES, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    document = (validate_uncompressed_reference if args.check else write_uncompressed_reference)(
        args.run_path.resolve(), args.lane
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "reference_id": document["reference_id"],
                "object_count": document["object_count"],
                "codec_invoked": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
