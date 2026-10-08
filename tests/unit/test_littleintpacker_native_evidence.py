"""Native success must bind full matrices, sanitizer and the shipped objects."""

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
from audit_littleintpacker_native import audit  # noqa: E402


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    for relative in (
        "adapters/littleintpacker",
        "native/include",
        "build/adapters/littleintpacker",
        "build/source-audits/littleintpacker-source",
        "build/source-audits/littleintpacker-patched",
        "build/source-audits/littleintpacker-native",
        "build/source-audits/littleintpacker-initial-zero-width-failure",
    ):
        shutil.copytree(
            ROOT / relative,
            tmp_path / relative,
            copy_function=lambda src, dst: os.symlink(src, dst),
        )
    for name in (
        "freeze_littleintpacker_source.py",
        "prepare_littleintpacker_patch.py",
        "qualify_littleintpacker_source.py",
        "qualify_littleintpacker_patched.py",
        "audit_littleintpacker_source.py",
    ):
        path = tmp_path / "tools" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(ROOT / "tools" / name)
    for kind in ("source", "patched", "native"):
        name = f"build/source-audits/littleintpacker_{kind}_tests.json"
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    return tmp_path


def replace(path: Path, data: bytes) -> None:
    path.unlink()
    path.write_bytes(data)


def save_native(root: Path, doc: dict) -> None:
    replace(
        root / "build/source-audits/littleintpacker_native_tests.json",
        (json.dumps(doc) + "\n").encode(),
    )


def save_build(root: Path, holder: dict) -> None:
    path = root / holder["record"]["path"]
    replace(path, (json.dumps(holder["build"]) + "\n").encode())
    holder["record"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def test_current_native_qualification_cannot_claim_sdk_or_five_layers(evidence: Path) -> None:
    result = audit(evidence)
    assert result["status"] == "PASS"
    assert result["bounded_abi"] == "QUALIFIED"
    assert result["native_cases"] == 284625
    assert result["native_fault_checks"] == 510
    assert result["python_sdk"] == result["benchmark_five_layers"] == "PENDING"
    assert not result["full_logical_entries_qualified"]


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_profile",
        "missing_fault",
        "missing_command",
        "missing_dependency",
        "other_shipped_objects",
        "forged_case_count",
        "forged_fault_output",
        "claim_sdk",
        "claim_full",
        "remove_sanitizer",
        "remove_avx2",
        "remove_runtime_dependency",
        "omit_source_snapshot",
    ],
)
def test_forged_native_success_is_rejected(evidence: Path, tamper: str) -> None:
    doc = json.loads(
        (evidence / "build/source-audits/littleintpacker_native_tests.json").read_text()
    )
    if tamper == "missing_profile":
        doc["tests"].pop()
    elif tamper == "missing_fault":
        doc["fault_tests"].pop()
    elif tamper == "missing_command":
        doc["commands"].pop()
    elif tamper == "missing_dependency":
        doc["tests"][0]["compiler_closure"].pop()
    elif tamper == "other_shipped_objects":
        doc["fault_tests"][0]["shipped_objects"] = doc["builds"][1]["build"]["objects"]
    elif tamper == "forged_case_count":
        doc["native_cases"] = 1
    elif tamper == "forged_fault_output":
        test = doc["fault_tests"][0]
        test["observation"]["checks"] = 1
        test["result"]["stdout"] = json.dumps(test["observation"])
        next(r for r in doc["commands"] if r["command"] == test["result"]["command"])["stdout"] = (
            test["result"]["stdout"]
        )
    elif tamper == "claim_sdk":
        doc["python_sdk"] = "QUALIFIED"
    elif tamper == "claim_full":
        doc["full_logical_entries_qualified"] = True
    elif tamper in {"remove_sanitizer", "remove_avx2"}:
        holder = doc["builds"][2 if tamper == "remove_sanitizer" else 0]
        build = holder["build"]
        unit = build["translation_units"][0 if tamper == "remove_sanitizer" else 3]
        raw = next(r for r in build["commands"] if r["command"] == unit["command"])
        flag = "-fsanitize=address,undefined" if tamper == "remove_sanitizer" else "-mavx2"
        unit["command"].remove(flag)
        raw["command"].remove(flag)
        save_build(evidence, holder)
    elif tamper == "remove_runtime_dependency":
        holder = doc["builds"][0]
        holder["build"]["runtime_dependencies"].pop()
        save_build(evidence, holder)
    else:
        doc["source_snapshot"].pop()
    save_native(evidence, doc)
    with pytest.raises(RuntimeError):
        audit(evidence)


@pytest.mark.parametrize(
    "relative",
    [
        "adapters/littleintpacker/native/tscb_littleintpacker.cpp",
        "build/adapters/littleintpacker/release/shim.o",
        "build/adapters/littleintpacker/release/bmipacking32.c.o",
        "build/adapters/littleintpacker/release/libtscb_littleintpacker.so",
        "build/source-audits/littleintpacker-native/faults-sanitizer",
    ],
)
def test_shipped_source_object_library_and_fault_binary_drift_is_rejected(
    evidence: Path,
    relative: str,
) -> None:
    path = evidence / relative
    replace(path, path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(RuntimeError, match="drift"):
        audit(evidence)
