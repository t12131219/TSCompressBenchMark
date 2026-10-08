"""Reject plausible forged wire, physical ledgers and rejection diagnostics."""

from __future__ import annotations

import copy
import json
import runpy
import struct
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
KEYS = tuple(
    "littleintpacker-" + name + "-u32" for name in ("pack32", "turbo", "sc", "bmi2", "horizontal")
)


@pytest.fixture(scope="module")
def evidence():
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "tools"))
        auditor = runpy.run_path(str(ROOT / "tools/audit_littleintpacker_run.py"))
        with np.load(
            ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz", allow_pickle=False
        ) as data:
            original = data["values"]
        yield auditor, original


def first_record(key, kind):
    run = ROOT / "runs" / f"{key}-{kind}-20261007-1"
    record = json.loads((run / "run_components.jsonl").read_text().splitlines()[0])
    task = next(
        json.loads(line)
        for line in (run / "task_plan.jsonl").read_text().splitlines()
        if json.loads(line)["task_id"] == record["task_id"]
    )
    params = next(
        c["parameters"]
        for c in json.loads((run / "resolved_configs.json").read_text())["configs"]
        if c["config_id"] == record["config_id"]
    )
    return run, record, task, params


@pytest.mark.parametrize("key", KEYS)
def test_valid_checksum_does_not_hide_changed_payload(evidence, key):
    auditor, original = evidence
    run, record, _, params = first_record(key, "qualification")
    wire = (run / "artifacts" / (record["run_id"].rsplit(":", 1)[-1] + ".bin")).read_bytes()
    auditor["independent_frame"](wire, params, original, key)
    prefix = auditor["PREFIX"]
    _, length, _ = prefix.unpack_from(wire)
    frame = bytearray(wire[prefix.size + length :])
    frame[32] ^= 1
    fnv = 14695981039346656037
    for byte in frame[:-8]:
        fnv = ((fnv ^ byte) * 1099511628211) % 2**64
    struct.pack_into("<Q", frame, len(frame) - 8, fnv)
    with pytest.raises(RuntimeError, match="wire oracle"):
        auditor["independent_frame"](wire[: prefix.size + length] + frame, params, original, key)


@pytest.mark.parametrize("mutation", ["ledger", "redistribute", "timer", "identity", "rank"])
def test_success_labels_cannot_hide_false_measurement(evidence, mutation):
    auditor, original = evidence
    key = KEYS[0]
    run, record, task, params = first_record(key, "qualification")
    wire = (run / "artifacts" / (record["run_id"].rsplit(":", 1)[-1] + ".bin")).read_bytes()
    physical = auditor["independent_frame"](wire, params, original, key)
    check = auditor["audit_measurement"]
    check(record, task, params, physical, wire, original.nbytes, False, key)
    if mutation == "ledger":
        record["accounting"]["final_bits"] += 8
    elif mutation == "redistribute":
        record["accounting"]["value_bits"] += 1
        record["accounting"]["padding_bits"] -= 1
    elif mutation == "timer":
        record["timing"]["native_encode_wall_ns"] = record["timing"]["core_encode_wall_ns"] + 1
    elif mutation == "identity":
        record["execution_path_hash"] = "forged-path"
    else:
        record["eligibility"] = True
    with pytest.raises(RuntimeError):
        check(record, task, params, physical, wire, original.nbytes, False, key)


@pytest.mark.parametrize("domain", [False, True])
@pytest.mark.parametrize("mutation", ["timing", "eligibility", "reason", "preflight"])
def test_rejected_tasks_cannot_claim_formal_qualification(evidence, domain, mutation):
    auditor, _ = evidence
    kind = "source-domain-rejection-qualification" if domain else "unsupported-qualification"
    _, record, task, _ = first_record(KEYS[0], kind)
    auditor["audit_rejection"](record, task, domain)
    record = copy.deepcopy(record)
    if mutation == "timing":
        record["timing"] = {"selected_encode_wall_ns": 10**9}
    elif mutation == "eligibility":
        record["eligibility"] = True
    elif mutation == "reason":
        record["reason_code"] = "PASS"
    else:
        record["diagnostics"]["preflight"]["eligible_for_formal_repetitions"] = True
    with pytest.raises(RuntimeError):
        auditor["audit_rejection"](record, task, domain)


def test_failed_current_audit_replaces_stale_pass(evidence, tmp_path, monkeypatch):
    auditor, _ = evidence
    output = tmp_path / "build/source-audits/littleintpacker_formal_current_audit.json"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({"status": "PASS", "records": 400}))

    def stale_evidence(phase):
        assert phase == "formal"
        raise RuntimeError("SDK consumed Python source drift")

    context = auditor["main"].__globals__
    monkeypatch.setitem(context, "ROOT", tmp_path)
    monkeypatch.setitem(context, "audit_all", stale_evidence)
    monkeypatch.setattr("sys.argv", ["audit_littleintpacker_run.py", "--phase", "formal"])
    with pytest.raises(RuntimeError, match="source drift"):
        auditor["main"]()
    current = json.loads(output.read_text())
    assert current["status"] == "FAIL"
    assert current["phase"] == "formal"
    assert current["full_logical_entries_qualified"] is False
    assert "source drift" in current["error"]
    assert "records" not in current
