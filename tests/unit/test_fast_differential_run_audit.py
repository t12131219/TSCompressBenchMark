"""Reject plausible but false execution claims and validly checksummed wrong D1 words."""

from __future__ import annotations

import json
import runpy
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry

ROOT = Path(__file__).resolve().parents[2]


def current_run(kind: str) -> Path:
    evidence = json.loads(
        (ROOT / "build/source-audits/fast-differential-u32-five-layer-audit.json").read_text()
    )
    assert evidence["status"] == "PASS", "Current independently audited evidence is required"
    return ROOT / "runs" / evidence[f"{kind}_run"]


@pytest.fixture
def auditor(monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    return runpy.run_path(str(ROOT / "tools/audit_fast_differential_run.py"))


@pytest.fixture
def unsupported_snapshot(tmp_path: Path) -> tuple:
    run = current_run("unsupported")
    report = json.loads((run / "report/report.json").read_text())
    paths = {
        "codec_registry_snapshot.json",
        "source_registry_snapshot.json",
        "resolved_configs.json",
        "task_plan.jsonl",
        "run_components.jsonl",
        "report/report.json",
        *(str(path.relative_to(run)) for path in run.glob("layer*-*.json")),
        *report["derived_artifact_hashes"],
        *report["source_hashes"],
    }
    for name in paths:
        if name.startswith("implementation/"):
            continue
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run / name, target)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get("fast-differential-u32")
    source = registry.sources.get(manifest.source_artifact_id)
    evidence = json.loads(
        (ROOT / "build/source-audits/fast-differential-u32-five-layer-audit.json").read_text()
    )
    return tmp_path, manifest, source, evidence["runtime_digest"]


def test_actual_unexecuted_diagnostics_pass(auditor: dict, unsupported_snapshot: tuple) -> None:
    assert len(auditor["audit_unsupported"](*unsupported_snapshot)) == 32


@pytest.mark.parametrize("mutation", ["isa", "missing", "timing", "dtype", "fallback", "source"])
def test_unexecuted_claims_cannot_be_forged(
    auditor: dict, unsupported_snapshot: tuple, mutation: str
) -> None:
    run = unsupported_snapshot[0]
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
        document["sources"][0]["identity"]["commit"] = "0" * 40
        path.write_text(json.dumps(document))
    else:
        records = [json.loads(line) for line in path.read_text().splitlines()]
        if mutation == "missing":
            records.pop()
        elif mutation == "timing":
            records[0]["timing"] = {"native_encode_wall_ns": 123}
        elif mutation == "isa":
            records[0]["execution"]["actual_isa"] = "SSE4_1"
        elif mutation == "fallback":
            records[0]["execution"]["fallback_used"] = True
        else:
            records[0]["compatibility"]["input_descriptor"]["dtype_vector"] = ["<u4"]
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
    with pytest.raises(RuntimeError):
        auditor["audit_unsupported"](*unsupported_snapshot)


def test_wrong_d1_words_fail_even_with_valid_frame_checksum(auditor: dict) -> None:
    run = current_run("formal")
    record = json.loads((run / "run_components.jsonl").read_text().splitlines()[0])
    configs = json.loads((run / "resolved_configs.json").read_text())["configs"]
    params = next(
        config["parameters"] for config in configs if config["config_id"] == record["config_id"]
    )
    stream = next(
        path.read_bytes()
        for path in (run / "artifacts").glob("*.bin")
        if auditor["sha"](path) == record["bitstream_sha256"]
    )
    with np.load(ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz", allow_pickle=False) as archive:
        original = archive["values"]
    auditor["independent_frame"](stream, params, original)
    forged = bytearray(stream)
    payload_start = auditor["PREFIX"].size + struct.unpack_from("<I", forged, 8)[0]
    forged[payload_start + 24] ^= 1
    checksum = 14695981039346656037
    for byte in forged[payload_start:-8]:
        checksum = ((checksum ^ byte) * 1099511628211) % 2**64
    struct.pack_into("<Q", forged, len(forged) - 8, checksum)
    with pytest.raises(RuntimeError, match="independent D1 oracle"):
        auditor["independent_frame"](bytes(forged), params, original)
