"""Actual wire and unexecuted-task evidence must survive independent scrutiny."""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
KEYS = ("simdcomp-u32", "delta-simdcomp-u32", "for-simdcomp-u32")


def current_run(key: str, kind: str) -> Path:
    # Retain historical formal data for statistics tests; current codec checks
    # consume current qualification evidence independently of formal ranking.
    filename = (f"{key.replace('-', '_')}_five_layer_audit.json" if kind == "formal"
                else f"{key.replace('-', '_')}_qualification_current_audit.json")
    evidence = json.loads((ROOT / "build/source-audits" / filename).read_text())
    assert evidence["status"] == "PASS", "Current independently audited evidence is required"
    return ROOT / "runs" / evidence[f"{kind}_run"]


@pytest.fixture(scope="module")
def evidence():
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "tools"))
        auditor = runpy.run_path(str(ROOT / "tools/audit_simdcomp_run.py"))
        registry = CodecRegistry(
            ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")
        )
        states = {key: auditor["source_and_runtime"](registry, key)[:3] for key in KEYS}
        with np.load(ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz", allow_pickle=False) as f:
            values = f["values"]
        yield auditor, states, values


@pytest.mark.parametrize("key", KEYS)
def test_current_supported_and_rejected_runs(evidence, key) -> None:
    auditor, states, values = evidence
    manifest, source, runtime = states[key]
    records, streams = auditor["audit_supported"](
        current_run(key, "qualification"), manifest, source, runtime, False, values
    )
    rejected = auditor["audit_unsupported"](
        current_run(key, "unsupported"), manifest, source, runtime
    )
    assert (len(records), len(streams), len(rejected)) == (
        (12, 5, 24) if key == KEYS[0] else (16, 8, 32)
    )


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("mutation", ["payload", "descriptor", "seed"])
def test_valid_checksums_do_not_hide_false_wire_semantics(evidence, key, mutation) -> None:
    auditor, _, original = evidence
    run = current_run(key, "qualification")
    record = next(r for r in auditor["rows"](run / "run_components.jsonl") if r["status"] == "PASS")
    configs = json.loads((run / "resolved_configs.json").read_text())["configs"]
    params = next(c["parameters"] for c in configs if c["config_id"] == record["config_id"])
    wire = (run / "artifacts" / (record["run_id"].rsplit(":", 1)[-1] + ".bin")).read_bytes()
    auditor["independent_frame"](wire, params, original, key)
    prefix = auditor["PREFIX"]
    _, length, _ = prefix.unpack_from(wire)
    info = json.loads(wire[prefix.size : prefix.size + length])
    frame = bytearray(wire[prefix.size + length :])
    if mutation == "payload":
        at = 40
        while True:
            size = struct.unpack_from("<I", frame, at + 4)[0]
            if size:
                frame[at + 8] ^= 1
                break
            at += 8
    elif mutation == "seed":
        struct.pack_into("<I", frame, 12, (params["starting_point"] + 1) % 2**32)
    else:
        info["value_units"] = ["wrong-unit"]
    fnv = 14695981039346656037
    for byte in frame[:-8]:
        fnv = ((fnv ^ byte) * 1099511628211) % 2**64
    struct.pack_into("<Q", frame, len(frame) - 8, fnv)
    descriptor = canonical_json_bytes(info)
    forged = (
        prefix.pack(b"TSCBSCP1", len(descriptor), hashlib.sha256(descriptor).digest())
        + descriptor
        + frame
    )
    with pytest.raises(RuntimeError, match="scalar|seed|semantics|width"):
        auditor["independent_frame"](forged, params, original, key)


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("mutation", ["timing", "isa", "identity", "eligibility", "preflight"])
def test_capability_diagnostics_cannot_claim_execution(evidence, key, mutation) -> None:
    auditor, _, _ = evidence
    run = current_run(key, "unsupported")
    record = copy.deepcopy(
        next(
            r for r in auditor["rows"](run / "run_components.jsonl") if r["status"] == "UNSUPPORTED"
        )
    )
    task = copy.deepcopy(
        next(
            t for t in auditor["rows"](run / "task_plan.jsonl") if t["task_id"] == record["task_id"]
        )
    )
    auditor["audit_diagnostic"](record, task, False)
    if mutation == "timing":
        record["timing"] = {"native_encode_wall_ns": 123}
    elif mutation == "isa":
        task["execution"]["actual_isa"] = "SSE4_1"
    elif mutation == "identity":
        record["config_id"] = "wrong-config"
    elif mutation == "eligibility":
        record["eligibility"] = True
    else:
        record["diagnostics"]["preflight"]["boundary"] = {"passed": True}
    with pytest.raises(RuntimeError):
        auditor["audit_diagnostic"](record, task, False)


@pytest.mark.parametrize("mutation", ["csv", "coverage"])
def test_raw_projection_and_coverage_recompute_actual_attempts(
    evidence, tmp_path, mutation
) -> None:
    import csv
    import shutil

    auditor, _, _ = evidence
    source = current_run(KEYS[0], "qualification")
    run = tmp_path / "run"
    shutil.copytree(source, run)
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
        path = run / "runs.csv"
        with path.open(newline="") as f:
            projection = list(csv.DictReader(f))
        first = next(row for row in projection if row["status"] == "PASS")
        first["final_bits"] = str(int(first["final_bits"]) + 8)
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(projection[0]))
            writer.writeheader()
            writer.writerows(projection)
    with pytest.raises(RuntimeError, match="CSV value drift|coverage"):
        auditor["audit_raw_projection_and_coverage"](run, tasks, records)


@pytest.mark.parametrize(
    "field", ["pipeline_encode_ns_p25", "native_decode_ns_ci_low", "core_decode_ns_cv"]
)
def test_formal_statistics_are_independently_recomputed(evidence, field) -> None:
    auditor, _, _ = evidence
    run = current_run(KEYS[0], "formal")
    report = json.loads((run / "report/report.json").read_text())
    summary = next(s for s in report["summaries"] if s["native_decode_ns_ci_low"] is not None)
    records = [
        r
        for r in auditor["rows"](run / "run_components.jsonl")
        if r["config_id"] == summary["config_id"] and r["eligibility"]
    ]
    auditor["audit_independent_statistics"](summary, records, report["policy"])
    summary[field] += 1
    with pytest.raises(RuntimeError, match="independently recomputed"):
        auditor["audit_independent_statistics"](summary, records, report["policy"])
