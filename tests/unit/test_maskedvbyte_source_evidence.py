"""Source qualification must retain the original UB and reject any consumed drift."""

from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT = runpy.run_path(str(ROOT / "tools/audit_maskedvbyte_source.py"))["audit"]


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    paths = {
        "adapters/maskedvbyte/SOURCE_LOCK.json",
        "adapters/maskedvbyte/tests/run_source_tests.py",
        "adapters/maskedvbyte/tests/source_guard.c",
        "build/source-audits/maskedvbyte-source-both-tests.json",
    }
    report = json.loads(
        (ROOT / "build/source-audits/maskedvbyte-source-both-tests.json").read_text()
    )
    paths.update(item["path"] for item in report["source_files"] + report["patches"])
    paths.update(test["executable"]["path"] for test in report["tests"])
    for build in report["builds"]:
        for field in ("source_translation_units", "compiled_source_closure", "objects"):
            paths.update(
                item["path"] for item in build[field] if not Path(item["path"]).is_absolute()
            )
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    assert AUDIT(tmp_path)["status"] == "PASS"
    return tmp_path


@pytest.mark.parametrize(
    "target", ["source", "patch", "driver", "test", "patched", "executable", "original-failure"]
)
def test_source_evidence_cannot_hide_ub_or_survive_dependency_drift(
    snapshot: Path, target: str
) -> None:
    if target == "original-failure":
        path = snapshot / "build/source-audits/maskedvbyte-source-both-tests.json"
        report = json.loads(path.read_text())
        test = next(t for t in report["tests"] if t["status"] == "FAIL")
        test.update(status="PASS", returncode=0, stderr="")
        report["failed_test_count"] = 0
        path.write_text(json.dumps(report))
    else:
        relative = {
            "source": "adapters/maskedvbyte/vendor/MaskedVByte/src/varintdecode.c",
            "patch": "adapters/maskedvbyte/patches/0001-unsigned-shifts.patch",
            "driver": "adapters/maskedvbyte/tests/run_source_tests.py",
            "test": "adapters/maskedvbyte/tests/source_guard.c",
            "patched": "build/source-audits/maskedvbyte-source/patched/src/varintdecode.c",
            "executable": "build/source-audits/maskedvbyte-source/patched/sanitizer/decode_guard",
        }[target]
        path = snapshot / relative
        path.write_bytes(path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(RuntimeError):
        AUDIT(snapshot)
