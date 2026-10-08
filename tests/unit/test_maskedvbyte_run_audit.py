"""False wire semantics and unexecuted task claims must fail independent review."""

from __future__ import annotations

import hashlib
import json
import runpy
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
KEYS = ("maskedvbyte-u32", "delta-maskedvbyte-u32")


def current_run(key: str, kind: str) -> Path:
    evidence = json.loads((ROOT / f"build/source-audits/{key}-five-layer-audit.json").read_text())
    assert evidence["status"] == "PASS", "Current independently audited evidence is required"
    return ROOT / "runs" / evidence[f"{kind}_run"]


@pytest.fixture
def auditor(monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    return runpy.run_path(str(ROOT / "tools/audit_maskedvbyte_run.py"))


def current(auditor: dict, key: str) -> tuple:
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    return auditor["source_and_runtime"](registry, key)[:3]


@pytest.mark.parametrize("key", KEYS)
def test_actual_supported_and_rejected_qualification(auditor: dict, key: str) -> None:
    manifest, source, runtime = current(auditor, key)
    with np.load(ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz", allow_pickle=False) as archive:
        values = archive["values"]
    records, streams = auditor["audit_supported"](
        current_run(key, "qualification"),
        manifest,
        source,
        runtime,
        False,
        values,
    )
    rejected = auditor["audit_unsupported"](
        current_run(key, "unsupported"),
        manifest,
        source,
        runtime,
    )
    assert (len(records), len(streams), len(rejected)) == (
        (4, 1, 8) if key == KEYS[0] else (16, 4, 32)
    )


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("mutation", ["isa", "missing", "timing", "dtype", "stage", "source"])
def test_rejected_tasks_cannot_claim_execution_or_change_input(
    tmp_path: Path, auditor: dict, key: str, mutation: str
) -> None:
    original = current_run(key, "unsupported")
    shutil.copytree(original, tmp_path / "run")
    run = tmp_path / "run"
    manifest, source, runtime = current(auditor, key)
    filename = (
        "run_components.jsonl"
        if mutation in {"missing", "timing"}
        else "source_registry_snapshot.json"
        if mutation == "source"
        else "task_plan.jsonl"
    )
    path = run / filename
    if mutation == "source":
        document = json.loads(path.read_text())
        matched = next(
            item for item in document["sources"] if item["identity"] == source["identity"]
        )
        matched["identity"]["commit"] = "0" * 40
        path.write_text(json.dumps(document))
    else:
        records = [json.loads(line) for line in path.read_text().splitlines()]
        if mutation == "missing":
            records.pop()
        elif mutation == "timing":
            records[0]["timing"] = {"native_encode_wall_ns": 123}
        elif mutation == "isa":
            records[0]["execution"]["actual_isa"] = "SSE4_1"
        elif mutation == "stage":
            records[0]["preprocess"]["stages"] = [{"name": "HIDDEN_CAST"}]
        else:
            records[0]["compatibility"]["input_descriptor"]["dtype_vector"] = ["<u4"]
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
    with pytest.raises(RuntimeError):
        auditor["audit_unsupported"](run, manifest, source, runtime)


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("mutation", ["residual", "descriptor", "seed"])
def test_correct_checksums_do_not_authorize_false_wire_semantics(
    auditor: dict, key: str, mutation: str
) -> None:
    run = current_run(key, "qualification")
    record = json.loads((run / "run_components.jsonl").read_text().splitlines()[0])
    configs = json.loads((run / "resolved_configs.json").read_text())["configs"]
    params = next(
        item["parameters"] for item in configs if item["config_id"] == record["config_id"]
    )
    path = run / "artifacts" / (record["run_id"].rsplit(":", 1)[-1] + ".bin")
    wire = path.read_bytes()
    with np.load(ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz", allow_pickle=False) as archive:
        original = archive["values"]
    auditor["independent_frame"](wire, params, original, key)
    prefix = auditor["PREFIX"]
    _, length, _ = prefix.unpack_from(wire)
    info = json.loads(wire[prefix.size : prefix.size + length])
    frame = bytearray(wire[prefix.size + length :])
    if mutation == "residual":
        frame[32] ^= 1
    elif mutation == "seed":
        struct.pack_into("<I", frame, 12, (params["starting_point"] + 1) % 2**32)
    else:
        info["parameters"]["decoder_api"] = "COUNT"
    checksum = 14695981039346656037
    for byte in frame[:-8]:
        checksum = ((checksum ^ byte) * 1099511628211) % 2**64
    struct.pack_into("<Q", frame, len(frame) - 8, checksum)
    descriptor = canonical_json_bytes(info)
    forged = prefix.pack(b"TSCBMVP1", len(descriptor), hashlib.sha256(descriptor).digest())
    with pytest.raises(RuntimeError, match="oracle|seed|semantics"):
        auditor["independent_frame"](forged + descriptor + frame, params, original, key)


@pytest.mark.parametrize(
    "field", ["pipeline_encode_ns_p25", "native_decode_ns_ci_low", "core_decode_ns_cv"]
)
def test_statistics_are_recomputed_from_actual_repetitions(auditor: dict, field: str) -> None:
    run = current_run(KEYS[0], "formal")
    report = json.loads((run / "report/report.json").read_text())
    summary = next(
        item for item in report["summaries"] if item["native_decode_ns_ci_low"] is not None
    )
    accepted = [
        record
        for record in auditor["rows"](run / "run_components.jsonl")
        if record["config_id"] == summary["config_id"] and record["eligibility"]
    ]
    auditor["audit_independent_statistics"](summary, accepted, report["policy"])
    summary[field] += 1
    with pytest.raises(RuntimeError, match="independently recomputed"):
        auditor["audit_independent_statistics"](summary, accepted, report["policy"])


@pytest.mark.parametrize("mutation", ["csv", "coverage"])
def test_raw_projection_and_coverage_cannot_drop_or_rebill_attempts(
    tmp_path: Path, auditor: dict, mutation: str
) -> None:
    original = current_run(KEYS[0], "qualification")
    run = tmp_path / "run"
    shutil.copytree(original, run)
    tasks, records = (
        auditor["rows"](run / "task_plan.jsonl"),
        auditor["rows"](run / "run_components.jsonl"),
    )
    auditor["audit_raw_projection_and_coverage"](run, tasks, records)
    if mutation == "coverage":
        path = run / "report/report.json"
        report = json.loads(path.read_text())
        report["coverage"][0]["run_ids"] = []
        path.write_text(json.dumps(report))
    else:
        import csv

        path = run / "runs.csv"
        with path.open(newline="") as file:
            projection = list(csv.DictReader(file))
        projection[0]["final_bits"] = str(int(projection[0]["final_bits"]) + 8)
        with path.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(projection[0]))
            writer.writeheader()
            writer.writerows(projection)
    with pytest.raises(RuntimeError, match="CSV value drift|coverage"):
        auditor["audit_raw_projection_and_coverage"](run, tasks, records)
