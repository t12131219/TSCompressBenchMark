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

from tscompbench.adapters.factory import AdapterFactoryError
from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
KEYS = ("simdcomp-u32",)


def archived_audit(key: str, kind: str) -> dict:
    # These saved records retain their original execution identity. Current SDK
    # admission is checked separately in test_simdcomp_sdk_evidence.py.
    filename = (
        "simdcomp_plain_formal_current_audit.json"
        if kind == "formal"
        else f"{key.replace('-', '_')}_qualification_current_audit.json"
    )
    evidence = json.loads((ROOT / "build/source-audits" / filename).read_text())
    assert evidence["status"] == "PASS", "Prior independently audited evidence is required"
    return evidence


def archived_run(key: str, kind: str) -> Path:
    return ROOT / "runs" / archived_audit(key, kind)[f"{kind}_run"]


@pytest.fixture(scope="module")
def evidence():
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "tools"))
        auditor = runpy.run_path(str(ROOT / "tools/audit_simdcomp_run.py"))
        states = {
            key: {
                kind: auditor["archived_run_identity"](
                    archived_run(key, kind), key, archived_audit(key, kind), kind,
                )
                for kind in ("qualification", "unsupported")
            }
            for key in KEYS
        }
        with np.load(ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz", allow_pickle=False) as f:
            values = f["values"]
        yield auditor, states, values


@pytest.mark.parametrize("key", KEYS)
def test_archived_supported_and_rejected_runs(evidence, key) -> None:
    auditor, states, values = evidence
    records, streams = auditor["audit_archived_supported"](
        archived_run(key, "qualification"), key, archived_audit(key, "qualification"), values,
    )
    rejected = auditor["audit_unsupported"](
        archived_run(key, "unsupported"), *states[key]["unsupported"],
    )
    assert (len(records), len(streams), len(rejected)) == ((12, 5, 24))


@pytest.mark.parametrize("mutation", ["codec", "source", "raw", "runtime"])
def test_archived_audit_rejects_frozen_identity_or_raw_tampering(evidence, tmp_path, mutation):
    import shutil

    auditor, _, values = evidence
    run = tmp_path / archived_run(KEYS[0], "qualification").name
    shutil.copytree(archived_run(KEYS[0], "qualification"), run)
    prior_audit = copy.deepcopy(archived_audit(KEYS[0], "qualification"))
    if mutation == "raw":
        path = run / "run_components.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
    elif mutation == "runtime":
        prior_audit["runtime_digest"] = "0" * 64
    else:
        path = run / f"{'codec' if mutation == 'codec' else 'source'}_registry_snapshot.json"
        snapshot = json.loads(path.read_text())
        if mutation == "codec":
            snapshot["codecs"][0]["manifest"]["adapter"]["version"] += "-forged"
        else:
            snapshot["sources"][0]["identity"]["commit"] = "0" * 40
        path.write_text(json.dumps(snapshot))
    with pytest.raises(RuntimeError, match="archived.*differ|task runtime identity differs"):
        auditor["audit_archived_supported"](run, KEYS[0], prior_audit, values)


def test_archived_audit_is_read_only_and_does_not_load_current_decoder(evidence, monkeypatch):
    auditor, _, values = evidence
    run = archived_run(KEYS[0], "qualification")
    paths = [path for path in run.rglob("*") if path.is_file()]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    def reject_current_decoder(*args):
        raise AssertionError("Historical scalar audit must not execute a current decoder")

    monkeypatch.setitem(
        auditor["audit_supported"].__globals__, "create_adapter", reject_current_decoder,
    )
    auditor["audit_archived_supported"](
        run, KEYS[0], archived_audit(KEYS[0], "qualification"), values,
    )
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before


def test_default_execution_audit_retains_current_factory_dependency_gate(evidence):
    auditor, states, values = evidence
    manifest, source, runtime = states[KEYS[0]]["qualification"]
    with pytest.raises(AdapterFactoryError, match="execution dependency drift"):
        auditor["audit_supported"](
            archived_run(KEYS[0], "qualification"), manifest, source, runtime, False, values,
        )


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("mutation", ["payload", "descriptor", "seed"])
def test_valid_checksums_do_not_hide_false_wire_semantics(evidence, key, mutation) -> None:
    auditor, _, original = evidence
    run = archived_run(key, "qualification")
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
    run = archived_run(key, "unsupported")
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
    source = archived_run(KEYS[0], "qualification")
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
    run = archived_run(KEYS[0], "formal")
    auditor["archived_run_identity"](run, KEYS[0], archived_audit(KEYS[0], "formal"), "formal")
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
