"""Reject stale binaries and forged SIMDComp AVX2/ABI qualification evidence."""

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
from audit_simdcomp_avx2 import audit as audit_avx2  # noqa: E402
from audit_simdcomp_native import audit as audit_native  # noqa: E402


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
    ):
        shutil.copytree(
            ROOT / relative,
            tmp_path / relative,
            copy_function=lambda src, dst: os.symlink(src, dst),
        )
    for relative in (
        "tools/freeze_simdcomp_source.py",
        "tools/qualify_simdcomp_upstream.py",
        "tools/qualify_simdcomp_avx2.py",
        "tools/audit_simdcomp_source.py",
        "tools/audit_simdcomp_avx2.py",
        "tests/native/native_timing_smoke.c",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(ROOT / relative)
    for path in (ROOT / "build/source-audits").glob("simdcomp*.json"):
        target = tmp_path / "build/source-audits" / path.name
        target.write_bytes(path.read_bytes())
    return tmp_path


def replace(path: Path, content: bytes) -> None:
    path.unlink()
    path.write_bytes(content)


def mutate(path: Path, function) -> None:
    document = json.loads(path.read_text())
    function(document)
    replace(path, (json.dumps(document, indent=2) + "\n").encode())


def test_complete_avx2_and_bounded_abi_scope(evidence: Path) -> None:
    source = audit_avx2(evidence)
    native = audit_native(evidence)
    assert source["status"] == native["status"] == "PASS"
    assert source["original_failures_retained"] == 16
    assert native["cases_per_profile_and_linkage"] == 31878
    assert native["original_abi_fault_paths_retained"] == 6
    assert native["python_sdk"] == native["benchmark_five_layers"] == "PENDING"
    assert not source["full_logical_entry_qualified"] and not native["full_logical_entry_qualified"]


@pytest.mark.parametrize(
    "relative",
    [
        "adapters/simdcomp/patches/avx2/0001-zero-width-unpack-byte-count.patch",
        "adapters/simdcomp/tests/source_avx2_guard.c",
        "build/source-audits/simdcomp-avx2/patched/release/avx2-source-guard",
        "build/source-audits/simdcomp-avx2-initial/patched/debug/avx2-source-guard",
    ],
)
def test_avx2_file_drift_is_rejected(evidence: Path, relative: str) -> None:
    path = evidence / relative
    replace(path, path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(RuntimeError, match="drift|missing"):
        audit_avx2(evidence)


@pytest.mark.parametrize(
    "tamper", ["missing_mode", "zero_failure", "coverage", "dependency", "sanitizer"]
)
def test_forged_avx2_success_is_rejected(evidence: Path, tamper: str) -> None:
    path = evidence / "build/source-audits/simdcomp_avx2_source_tests.json"

    def change(doc):
        if tamper == "missing_mode":
            doc["tests"].pop()
        elif tamper == "zero_failure":
            test = next(
                t for t in doc["tests"] if t["source_kind"] == "original" and t["mode"] == "avx2"
            )
            observation = next(c for c in doc["commands"] if c["command"] == test["command"])
            test["returncode"] = observation["returncode"] = 0
        elif tamper == "coverage":
            test = next(
                t for t in doc["tests"] if t["source_kind"] == "patched" and t["mode"] == "avx2"
            )
            observation = next(c for c in doc["commands"] if c["command"] == test["command"])
            test["stdout"] = observation["stdout"] = test["stdout"].replace("1584", "10")
        elif tamper == "dependency":
            doc["builds"][0]["compiled_source_closure"].pop()
        else:
            build = next(b for b in doc["builds"] if b["profile"] == "sanitizer")
            command = next(
                c
                for c in doc["commands"]
                if c["command"][-2:] == ["-o", build["guard_executable"]["path"]]
            )
            command["command"].remove("-fsanitize=address,undefined")

    mutate(path, change)
    with pytest.raises(
        RuntimeError,
        match="matrix|success differs|evidence missing|closure differs|sanitizer missing",
    ):
        audit_avx2(evidence)


@pytest.mark.parametrize(
    "relative",
    [
        "adapters/simdcomp/native/tscb_simdcomp.c",
        "adapters/simdcomp/tests/abi_qualification.c",
        "build/adapters/simdcomp_u32/release/libtscb_simdcomp_u32.so",
        "build/source-audits/simdcomp-native/instrumented-sanitizer",
        "build/source-audits/simdcomp-native-initial/pointer-return-guard",
    ],
)
def test_native_file_drift_is_rejected(evidence: Path, relative: str) -> None:
    path = evidence / relative
    replace(path, path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(RuntimeError, match="drift|differs"):
        audit_native(evidence)


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_test",
        "missing_command",
        "missing_wrap",
        "no_assertions",
        "coverage",
        "test_dependency",
    ],
)
def test_forged_native_success_is_rejected(evidence: Path, tamper: str) -> None:
    path = evidence / "build/source-audits/simdcomp_native_tests.json"

    def change(doc):
        test = next(
            t for t in doc["tests"] if t["kind"] == "instrumented" and t["profile"] == "sanitizer"
        )
        if tamper == "missing_test":
            doc["tests"].remove(test)
        elif tamper == "missing_command":
            doc["commands"] = [c for c in doc["commands"] if c["command"] != test["command"]]
        elif tamper in ("missing_wrap", "no_assertions"):
            compilation = next(
                c for c in doc["commands"] if c["command"] == test["compile_command"]
            )
            removed = "-Wl,--wrap=posix_memalign" if tamper == "missing_wrap" else "-UNDEBUG"
            compilation["command"].remove(removed)
            test["compile_command"].remove(removed)
        elif tamper == "coverage":
            observation = next(c for c in doc["commands"] if c["command"] == test["command"])
            test["stdout"] = observation["stdout"] = test["stdout"].replace("31878", "100")
        else:
            test["compiled_test_closure"].pop()

    mutate(path, change)
    with pytest.raises(
        RuntimeError,
        match="matrix|observation|wrapper missing|disabled|coverage differs|universe differs",
    ):
        audit_native(evidence)


@pytest.mark.parametrize("tamper", ["shim_avx", "dependency"])
def test_forged_native_build_metadata_is_rejected(evidence: Path, tamper: str) -> None:
    directory = evidence / "build/adapters/simdcomp_u32/release"
    build_path = directory / "build-record.json"
    build = json.loads(build_path.read_text())
    if tamper == "dependency":
        build["compiled_source_closure"].pop()
    else:
        commands_path = directory / "compile-command.json"
        commands = json.loads(commands_path.read_text())
        shim = next(c for c in commands["commands"] if "-c" in c and c[-1].endswith("/shim.o"))
        observation = next(c for c in build["commands"] if c["command"] == shim)
        shim.remove("-mno-avx")
        shim.append("-mavx2")
        observation["command"] = shim
        canonical = json.dumps(commands, sort_keys=True, separators=(",", ":")).encode()
        replace(commands_path, canonical + b"\n")
        build["compile_commands_sha256"] = hashlib.sha256(canonical).hexdigest()
    replace(build_path, (json.dumps(build) + "\n").encode())
    report = evidence / "build/source-audits/simdcomp_native_tests.json"
    mutate(
        report,
        lambda doc: next(b for b in doc["builds"] if b["profile"] == "release")["record"].update(
            sha256=hashlib.sha256(build_path.read_bytes()).hexdigest()
        ),
    )
    with pytest.raises(RuntimeError, match="object flags differ|dependency universe differs"):
        audit_native(evidence)
