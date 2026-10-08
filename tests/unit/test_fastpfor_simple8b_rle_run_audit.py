"""Exercise independently reconstructed RLE bytes and reject false execution evidence."""

from __future__ import annotations

import copy
import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_fastpfor_simple8b_rle_run import (  # noqa: E402
    KEY, audit_all, audit_driver, audit_measurement, independent_frame,
)

RUN = ROOT / "runs" / f"{KEY}-qualification-20261007-2"
DRIVER = ROOT / "build/source-audits/fastpfor-simple8b-rle-qualification-20261007-2/report.json"


@pytest.fixture
def actual() -> tuple:
    tasks = [json.loads(line) for line in (RUN / "task_plan.jsonl").read_text().splitlines()]
    records = [json.loads(line) for line in (RUN / "run_components.jsonl").read_text().splitlines()]
    configs = json.loads((RUN / "resolved_configs.json").read_text())["configs"]
    with np.load(ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz", allow_pickle=False) as archive:
        values = archive["values"]
    record = records[0]
    task = next(t for t in tasks if t["task_id"] == record["task_id"])
    params = next(c["parameters"] for c in configs if c["config_id"] == task["config_id"])
    stream = (RUN / "artifacts" / (record["run_id"].rsplit(":", 1)[-1] + ".bin")).read_bytes()
    return record, task, params, stream, values


def test_actual_five_layers_qualify_only_executed_scope() -> None:
    result = audit_all("qualification")
    assert result["status"] == "PASS" and result["records"] == 12
    assert result["runs"][0]["statuses"] == {"PASS": 4}
    assert result["runs"][1]["statuses"] == {"UNSUPPORTED": 8}
    assert result["eligible"] == 0 and result["formal_measurement"] == "PENDING"
    assert not result["full_logical_entry_qualified"]


@pytest.mark.parametrize("tamper", ["native_clock", "timing_enabled", "copy_bytes", "padding",
                                  "ledger", "eligibility", "resource_pressure", "selected_duration"])
def test_bad_measurement_or_billing_is_rejected(actual: tuple, tamper: str) -> None:
    record, task, params, stream, values = actual
    record = copy.deepcopy(record)
    if tamper == "native_clock":
        record["timing"]["native_timing_clock"] = "UNDECLARED"
    elif tamper == "timing_enabled":
        record["timing"]["native_timing_enabled"] = not params["native_timing"]
    elif tamper == "copy_bytes":
        record["diagnostics"]["codec_telemetry"]["encode"]["native_staging_input_copy_bytes"] += 4
    elif tamper == "padding":
        record["diagnostics"]["codec_telemetry"]["decode"]["internal_padding_bytes"] = 112
    elif tamper == "ledger":
        record["accounting"]["metadata_bits"] += 28
        record["accounting"]["value_bits"] -= 28
    elif tamper == "eligibility":
        record["eligibility"] = True
    elif tamper == "resource_pressure":
        record["status"] = "RESOURCE_PRESSURE"
    else:
        record["timing"]["selected_decode_wall_ns"] += 1
    with pytest.raises(ValueError):
        audit_measurement(record, task, params, independent_frame(stream, params, values),
                          stream, values.nbytes, False)


@pytest.mark.parametrize("tamper", ["descriptor", "frame", "input_order", "marker"])
def test_independent_wire_reconstruction_rejects_changes(actual: tuple, tamper: str) -> None:
    _, _, params, stream, values = actual
    if tamper in {"descriptor", "frame"}:
        changed = bytearray(stream)
        length = struct.unpack_from("<I", changed, 8)[0]
        changed[50 if tamper == "descriptor" else 44 + length + 32 + 4 * params["mark_length"]] ^= 1
        if tamper == "frame":
            checksum = 14695981039346656037
            for byte in changed[44 + length:-8]:
                checksum = ((checksum ^ byte) * 1099511628211) & ((1 << 64) - 1)
            struct.pack_into("<Q", changed, len(changed) - 8, checksum)
        stream = bytes(changed)
    elif tamper == "input_order":
        values = values[::-1]
    else:
        params = dict(params, mark_length=not params["mark_length"])
    with pytest.raises(ValueError):
        independent_frame(stream, params, values)


@pytest.mark.parametrize("tamper", ["omit_run", "omit_factory", "omit_file", "forge_file",
                                  "duplicate_file", "wrong_affinity", "full_claim", "wrong_suffix"])
def test_driver_cannot_hide_execution_changes(tmp_path: Path, tamper: str) -> None:
    document = json.loads(DRIVER.read_text())
    sdk = copy.deepcopy(document["sdk_current_audit"])
    if tamper == "omit_run":
        document["runs"].pop()
    elif tamper == "omit_factory":
        document["actual_python_source_closure"] = [i for i in document["actual_python_source_closure"]
                                                   if i["path"] != "src/tscompbench/adapters/factory.py"]
    elif tamper == "omit_file":
        document["runs"][0]["files"].pop()
    elif tamper == "forge_file":
        document["runs"][0]["files"][0]["sha256"] = "0" * 64
    elif tamper == "duplicate_file":
        document["runs"][0]["files"].append(document["runs"][0]["files"][0])
    elif tamper == "wrong_affinity":
        document["actual_cpu_affinity"] = [0]
    elif tamper == "full_claim":
        document["full_logical_entry_qualified"] = True
    else:
        document["runs"][0]["run_set_id"] = document["runs"][0]["run_set_id"].replace("-2", "-1")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        audit_driver("qualification", sdk, report_path=path)


def test_actual_formal_statistics_retain_all_attempts_and_exclude_swap() -> None:
    result = audit_all("formal")
    assert result["status"] == "PASS" and result["records"] == 80 and result["eligible"] == 74
    assert result["runs"][0]["statuses"] == {"PASS": 74, "RESOURCE_PRESSURE": 6}
    assert result["formal_measurement"] == "QUALIFIED_SYNTHETIC_UINT32_ONLY"
    assert not result["full_logical_entry_qualified"]
