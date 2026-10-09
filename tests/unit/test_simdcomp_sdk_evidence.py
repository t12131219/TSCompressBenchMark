"""Direct SDK admission rejects drift, missing closures and forged test results."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_simdcomp_sdk import audit  # noqa: E402


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    for relative in (
        "adapters/simdcomp",
        "native/include",
        "build/adapters/simdcomp_u32",
        "build/source-audits/simdcomp-upstream",
        "build/source-audits/simdcomp-avx2",
        "build/source-audits/simdcomp-avx2-initial",
        "build/source-audits/simdcomp-native",
        "build/source-audits/simdcomp-native-initial",
        "build/source-audits/simdcomp-sdk",
    ):
        shutil.copytree(
            ROOT / relative,
            tmp_path / relative,
            copy_function=lambda src, dst: os.symlink(src, dst),
        )
    snapshot = json.loads((ROOT / "build/source-audits/simdcomp_sdk_tests.json").read_text())[
        "source_snapshot"
    ]
    for relative in [
        *(i["path"] for i in snapshot),
        "tools/freeze_simdcomp_source.py",
        "tools/qualify_simdcomp_upstream.py",
        "tools/qualify_simdcomp_avx2.py",
        "tests/native/native_timing_smoke.c",
    ]:
        target = tmp_path / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(ROOT / relative)
    for path in (ROOT / "build/source-audits").glob("simdcomp*.json"):
        (tmp_path / "build/source-audits" / path.name).write_bytes(path.read_bytes())
    card = json.loads((ROOT / "registry/onboarding/simdcomp-u32.json").read_text())
    selected = next(item["evidence"] for item in card["upstream_tests"] if item["name"] == "direct_sdk")
    current = json.loads((ROOT / selected).read_text())
    current_out = ROOT / current.get("output_directory", "build/source-audits/simdcomp-sdk")
    mirror_out = tmp_path / "build/source-audits/simdcomp-sdk"
    for source in current_out.rglob("*"):
        if source.is_file():
            target = mirror_out / source.relative_to(current_out)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(source)
    for item in current["source_snapshot"]:
        target = tmp_path / item["path"]
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(ROOT / item["path"])
    current["output_directory"] = "build/source-audits/simdcomp-sdk"
    (tmp_path / "build/source-audits/simdcomp_sdk_tests.json").write_text(json.dumps(current))
    return tmp_path


def replace(path: Path, content: bytes) -> None:
    path.unlink()
    path.write_bytes(content)


def mutate(path: Path, change) -> None:
    document = json.loads(path.read_text())
    change(document)
    replace(path, (json.dumps(document, indent=2) + "\n").encode())


def test_complete_direct_sdk_does_not_claim_five_layers(evidence: Path) -> None:
    result = audit(evidence)
    assert result["status"] == "PASS" and result["test_count"] == 888
    assert set(result["keys"]) == {"simdcomp-u32", "delta-simdcomp-u32", "for-simdcomp-u32"}
    assert result["benchmark_registration"] == result["benchmark_five_layers"] == "PENDING"
    assert not result["full_logical_entries_qualified"]


@pytest.mark.parametrize(
    "relative",
    [
        "src/tscompbench/adapters/simdcomp.py",
        "src/tscompbench/adapters/maskedvbyte.py",
        "src/tscompbench/preprocess/simdcomp.py",
        "src/tscompbench/adapters/native_timing.py",
        "tests/adapters/test_simdcomp.py",
        "tools/qualify_simdcomp_sdk.py",
        "build/source-audits/simdcomp-sdk/pytest.xml",
    ],
)
def test_consumed_sdk_source_or_report_drift_is_rejected(evidence: Path, relative: str) -> None:
    path = evidence / relative
    replace(path, path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(RuntimeError, match="drift"):
        audit(evidence)


@pytest.mark.parametrize(
    "tamper",
    ["claim_five_layers", "omit_worker", "omit_dependency", "omit_buffer_helper", "wrong_total"],
)
def test_forged_direct_sdk_success_is_rejected(evidence: Path, tamper: str) -> None:
    path = evidence / "build/source-audits/simdcomp_sdk_tests.json"

    def change(doc):
        if tamper == "claim_five_layers":
            doc["benchmark_five_layers"] = "QUALIFIED"
        elif tamper == "omit_worker":
            doc["commands"] = [c for c in doc["commands"] if c["command"][-1] != "--worker"]
        elif tamper == "wrong_total":
            doc["test_totals"]["tests"] = 1
        else:
            omitted = (
                "src/tscompbench/adapters/maskedvbyte.py"
                if tamper == "omit_buffer_helper"
                else "src/tscompbench/adapters/simdcomp.py"
            )
            doc["source_snapshot"] = [i for i in doc["source_snapshot"] if i["path"] != omitted]
            doc["source_snapshot_sha256"] = hashlib.sha256(
                json.dumps(doc["source_snapshot"], sort_keys=True).encode()
            ).hexdigest()
            closure = evidence / "build/source-audits/simdcomp-sdk/python-closure.json"
            mutate(closure, lambda c: c.update(source_snapshot=doc["source_snapshot"]))
            doc["python_closure_sha256"] = hashlib.sha256(closure.read_bytes()).hexdigest()

    mutate(path, change)
    with pytest.raises(RuntimeError, match="premature|absent|incomplete|failed"):
        audit(evidence)
