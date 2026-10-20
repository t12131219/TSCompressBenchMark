"""Keep direct codec, ABI, and object evidence in their measured scopes."""
from __future__ import annotations

import csv
import json

import pytest

from tsbench.records import append, file_hash, write_json
from tsbench.report import generate


def save_run(root, cases, rows, *, config_task=None):
    schedule = [{"case_id": case["case_id"], "session": 0, "round": index}
                for case in cases if case.get("status") == "ready"
                for index in range(2)]
    manifest = {"run_id": "scope-fixture", "cases": cases, "schedule": schedule}
    if config_task is not None:
        manifest["resolved_config"] = {"task": config_task}
    write_json(root / "manifest.json", manifest)
    for row in rows:
        append(root / "observations.jsonl", row)


def case(name, boundary=None, lifecycle=None, **extra):
    result = {"case_id": name, "codec": "fixture", "status": "ready", "raw_bytes": 1024, **extra}
    if boundary is not None:
        result["boundary"] = boundary
    if lifecycle is not None:
        result["lifecycle"] = lifecycle
    return result


def row(name, index, **extra):
    return {"event": "terminal", "phase": "measurement", "case_id": name,
            "session": 0, "round": index, "attempt": 0, "status": "ok",
            "encode_ns": 100.5, "decode_ns": 200.25, "stored_bytes": 2048,
            "value_count": 128, "bits_per_value": 128, **extra}


def test_legacy_without_boundary_stays_object_and_report_does_not_mutate_evidence(tmp_path):
    save_run(tmp_path, [case("legacy")], [row("legacy", n) for n in range(2)],
             config_task={"boundary": "native_core", "lifecycle": "prepared"})
    hashes = {name: file_hash(tmp_path / name) for name in ("manifest.json", "observations.jsonl")}
    result = generate(tmp_path)
    actual = result["cases"][0]
    assert actual["boundary"] == "object_memory" and actual["lifecycle"] == "independent_object"
    assert actual["compression_ratio"] == 0.5 and actual["stored_bytes"]["median"] == 2048
    assert actual["size_scope"] == "complete_object_wire" and actual["report_role"] == "auxiliary"
    assert actual["codec_complete_bytes"]["n"] == 0 and actual["native_encode_total_ns"]["n"] == 0
    assert result["primary_case_ids"] == []
    assert all(file_hash(tmp_path / name) == digest for name, digest in hashes.items())
    text = (tmp_path / "report/README.md").read_text()
    assert "object_memory / independent_object" in text and "No requested cases" in text


def test_verified_native_size_and_native_average_use_real_totals_and_preserve_trace(tmp_path):
    rows = [row("core", n, boundary="native_core", lifecycle="prepared", loops=8,
                codec_complete_bytes=256, native_output_bytes=280, stored_bytes=99999,
                encode_batch_ns=804, decode_batch_ns=1602,
                sampling_unit="one batch per round",
                native_batch={"clock": "CLOCK_MONOTONIC", "clock_resolution_ns": 1,
                              "encoded_outputs": 8, "decoded_outputs": 8, "verified_outputs": 8},
                native_products=[{"phase": "measurement", "index": k, "verification": {"passed": True}} for k in range(8)]) for n in range(2)]
    save_run(tmp_path, [case("core", "native_core", "prepared")], rows)
    result = generate(tmp_path)
    actual = result["cases"][0]
    assert actual["compression_ratio"] == 4 and actual["bits_per_value_median"] == 16
    assert actual["native_output_bytes"]["median"] == 280
    assert actual["stored_bytes"]["median"] == 256  # Native never uses a framework or API fallback.
    assert actual["encode_ns"]["median"] == 100.5
    assert actual["encode_MiB_s"] == pytest.approx(1024 * 1e9 / 100.5 / 2**20)
    assert actual["native_encode_total_ns"]["median"] == 804
    assert actual["loops"]["median"] == 8
    assert actual["clock_metadata"] == [{"clock": "CLOCK_MONOTONIC", "clock_resolution_ns": 1}]
    assert actual["sampling_units"] == ["one batch per round"]
    assert actual["encode_batch_ns"]["median"] == 804
    assert len(actual["measurement_trace"][0]["native_products"]) == 8
    assert actual["measurement_trace"][0]["native_batch"]["verified_outputs"] == 8
    assert actual["measurement_trace"][0]["observation_line"] == 1
    assert result["primary_case_ids"] == ["core"]
    with (tmp_path / "report/summary.csv").open(newline="") as stream:
        exported = list(csv.DictReader(stream))[0]
    assert exported["boundary"] == "native_core" and exported["lifecycle"] == "prepared"
    assert float(exported["compression_ratio"]) == 4 and float(exported["bits_per_value_median"]) == 16
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("known_first", [False, True])
def test_unknown_codec_size_never_uses_api_output_or_known_subset(tmp_path, known_first):
    rows = [row("api", n, boundary="native_api", lifecycle="prepared", loops=4,
                codec_complete_bytes=128 if known_first and n == 0 else None,
                codec_complete_bytes_null_reason=None if known_first and n == 0 else "ABI frame not audited",
                native_output_bytes=256, stored_bytes=256, bits_per_value=16) for n in range(2)]
    save_run(tmp_path, [case("api", "native_api", "prepared")], rows)
    actual = generate(tmp_path)["cases"][0]
    assert actual["stored_bytes"]["median"] is None
    assert actual["codec_complete_bytes"]["median"] is None
    assert actual["compression_ratio"] is None and actual["stored_fraction"] is None
    assert actual["bits_per_value"]["median"] is None
    assert actual["native_output_bytes"]["median"] == 256
    assert actual["codec_complete_bytes_known_subset"]["n"] == int(known_first)
    assert actual["codec_complete_bytes_null_reason"] == "ABI frame not audited"
    assert actual["metric_null_reasons"]["compression_ratio"] == "ABI frame not audited"
    assert actual["encode_MiB_s"] > 0  # Known API time remains useful auxiliary evidence.


def test_lifecycles_boundaries_and_rejections_keep_separate_denominators(tmp_path):
    cases = [case("core", "native_core", "prepared"),
             case("fresh", "native_core", "fresh_request"),
             case("api", "native_api", "prepared"),
             case("object", "object_memory", "independent_object"),
             case("missing", "native_core", "prepared", status="unsupported", reason="direct core not implemented")]
    rows = [row(c["case_id"], n, boundary=c["boundary"], lifecycle=c["lifecycle"], codec_complete_bytes=256)
            for c in cases if c["status"] == "ready" for n in range(2)]
    # Preserve an actual primary failure even when a retry later succeeds.
    rows[1].update(status="error", reason="quality_violation")
    rows.append(row("core", 1, attempt=1, boundary="native_core", lifecycle="prepared", codec_complete_bytes=64))
    save_run(tmp_path, cases, rows)
    result = generate(tmp_path)
    assert result["requested_cases"] == 5 and result["planned_trials"] == 8
    assert result["primary_case_ids"] == ["core", "missing"]
    assert result["auxiliary_case_ids"] == ["fresh", "api", "object"]
    assert len(result["measurement_groups"]) == 4
    main = next(group for group in result["measurement_groups"] if group["report_role"] == "primary")
    assert main["requested_cases"] == 2 and main["planned_trials"] == 2 and main["ok_primary_trials"] == 1
    actual = next(c for c in result["cases"] if c["case_id"] == "core")
    assert actual["primary_reasons"] == {"quality_violation": 1}
    assert not actual["complete_case"] and actual["primary_trial_status_counts"] == {"ok": 1, "error": 1}
    text = (tmp_path / "report/README.md").read_text()
    primary, auxiliary = text.split("## Auxiliary measurements")
    assert "| fresh |" not in primary and "| fresh |" in auxiliary
    assert "fresh_request" in auxiliary and "native_api / prepared" in auxiliary
    assert "object_memory / independent_object" in auxiliary
    assert "direct core not implemented" in primary and "quality_violation" in primary


@pytest.mark.parametrize("field,value", [("boundary", "object_memory"), ("lifecycle", "fresh_request")])
def test_mixed_scope_row_is_rejected_before_report_is_written(tmp_path, field, value):
    rows = [row("core", n, boundary="native_core", lifecycle="prepared", codec_complete_bytes=256)
            for n in range(2)]
    rows[1][field] = value
    save_run(tmp_path, [case("core", "native_core", "prepared")], rows)
    with pytest.raises(ValueError, match="differs from case scope"):
        generate(tmp_path)
    assert not (tmp_path / "report").exists()
