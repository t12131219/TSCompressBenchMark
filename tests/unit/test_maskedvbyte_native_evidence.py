"""Native qualification cannot be reused after any tested dependency changes."""

from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT = runpy.run_path(str(ROOT / "tools/audit_maskedvbyte_native.py"))["audit"]
SDK_AUDIT = runpy.run_path(str(ROOT / "tools/audit_maskedvbyte_sdk.py"))["audit"]


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    paths = {
        "adapters/maskedvbyte/SOURCE_LOCK.json",
        "adapters/maskedvbyte/tests/run_source_tests.py",
        "adapters/maskedvbyte/tests/source_guard.c",
        "adapters/maskedvbyte/tests/run_native_tests.py",
        "adapters/maskedvbyte/tests/abi_qualification.c",
        "adapters/maskedvbyte/build_native.py",
        "adapters/maskedvbyte/contract.md",
        "tests/native/native_timing_smoke.c",
        "tools/audit_maskedvbyte_source.py",
        "build/source-audits/maskedvbyte-source-both-tests.json",
        "build/source-audits/maskedvbyte-native-tests.json",
    }
    source = json.loads(
        (ROOT / "build/source-audits/maskedvbyte-source-both-tests.json").read_text()
    )
    paths.update(item["path"] for item in source["source_files"] + source["patches"])
    for build in source["builds"]:
        for field in ("source_translation_units", "compiled_source_closure", "objects"):
            paths.update(
                item["path"] for item in build[field] if not Path(item["path"]).is_absolute()
            )
    for test in source["tests"]:
        paths.add(test["executable"]["path"])
    # Audit compares all generated native files against the tested patched snapshot.
    for item in source["source_files"]:
        name = Path(item["path"]).relative_to("adapters/maskedvbyte/vendor/MaskedVByte")
        paths.add(str(Path("build/source-audits/maskedvbyte-source/patched") / name))
    native = json.loads((ROOT / "build/source-audits/maskedvbyte-native-tests.json").read_text())
    for build in native["builds"]:
        directory = "build/adapters/maskedvbyte_u32/" + build["profile"]
        paths.update(
            {
                directory + "/compile-command.json",
                directory + "/build-record.json",
                build["artifact"],
            }
        )
        for field in (
            "source_files",
            "patches",
            "generated_source_files",
            "binding_sources",
            "compiled_source_closure",
            "objects",
        ):
            paths.update(
                item["path"] for item in build[field] if not Path(item["path"]).is_absolute()
            )
    for test in native["tests"]:
        paths.add(str(Path(test["command"][0]).relative_to(ROOT)))
        paths.update(
            item["path"]
            for item in test.get("compiled_test_closure", [])
            if not Path(item["path"]).is_absolute()
        )
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    assert AUDIT(tmp_path)["status"] == "PASS"
    return tmp_path


@pytest.mark.parametrize(
    "target",
    [
        "shim",
        "patch",
        "contract",
        "driver",
        "source",
        "generated",
        "encoder",
        "binary",
        "test_binary",
        "command",
        "object",
        "matrix",
        "coverage",
        "routes",
        "wrappers",
    ],
)
def test_native_auditor_refuses_drift(snapshot: Path, target: str) -> None:
    native_path = snapshot / "build/source-audits/maskedvbyte-native-tests.json"
    if target in {
        "shim",
        "patch",
        "contract",
        "driver",
        "source",
        "generated",
        "encoder",
        "binary",
        "test_binary",
        "object",
    }:
        files = {
            "shim": "adapters/maskedvbyte/native/tscb_maskedvbyte.c",
            "patch": "adapters/maskedvbyte/patches/0001-unsigned-shifts.patch",
            "contract": "adapters/maskedvbyte/contract.md",
            "driver": "adapters/maskedvbyte/tests/run_native_tests.py",
            "source": "adapters/maskedvbyte/vendor/MaskedVByte/src/varintdecode.c",
            "generated": "build/adapters/maskedvbyte_u32/release/patched-source/src/varintdecode.c",
            "encoder": "build/adapters/maskedvbyte_u32/release/patched-source/src/varintencode.c",
            "binary": "build/adapters/maskedvbyte_u32/release/libtscb_maskedvbyte_u32.so",
            "test_binary": "build/source-audits/maskedvbyte-native/shared-release",
            "object": "build/adapters/maskedvbyte_u32/release/shim.o",
        }
        path = snapshot / files[target]
        path.write_bytes(path.read_bytes() + b"\ndrift\n")
    elif target == "command":
        path = snapshot / "build/adapters/maskedvbyte_u32/release/compile-command.json"
        document = json.loads(path.read_text())
        document["commands"][1].append("-march=native")
        path.write_text(json.dumps(document))
    else:
        report = json.loads(native_path.read_text())
        if target == "matrix":
            report["tests"] = [
                t
                for t in report["tests"]
                if not (t["kind"] == "shared" and t.get("profile") == "sanitizer")
            ]
        else:
            test = next(t for t in report["tests"] if t["kind"] == "instrumented")
            if target == "wrappers":
                original = list(test["compile_command"])
                test["compile_command"].remove("-Wl,--wrap=vbyte_encode_delta")
                for command in report["commands"]:
                    if command["command"] == original:
                        command["command"] = test["compile_command"]
            else:
                original = test["stdout"]
                test["stdout"] = (
                    original.replace("9360", "1")
                    if target == "coverage"
                    else original.replace("six original API routes", "skipped API routes")
                )
                for command in report["commands"]:
                    if command["stdout"] == original:
                        command["stdout"] = test["stdout"]
        native_path.write_text(json.dumps(report))
    with pytest.raises((RuntimeError, OSError)):
        AUDIT(snapshot)


@pytest.mark.parametrize("target", ["binding", "junit", "closure", "sdk_driver", "missing"])
def test_sdk_auditor_refuses_drift(snapshot: Path, target: str) -> None:
    report_path = ROOT / "build/source-audits/maskedvbyte-sdk-tests.json"
    report = json.loads(report_path.read_text())
    paths = {
        "build/source-audits/maskedvbyte-sdk-tests.json",
        "build/source-audits/maskedvbyte-sdk/pytest.xml",
        "build/source-audits/maskedvbyte-sdk/python-closure.json",
        "tools/audit_maskedvbyte_native.py",
        "tools/qualify_maskedvbyte_sdk.py",
    } | {item["path"] for item in report["source_snapshot"]}
    for name in paths:
        destination = snapshot / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    assert SDK_AUDIT(snapshot)["status"] == "PASS"
    files = {
        "binding": "src/tscompbench/adapters/maskedvbyte.py",
        "junit": "build/source-audits/maskedvbyte-sdk/pytest.xml",
        "closure": "build/source-audits/maskedvbyte-sdk/python-closure.json",
        "sdk_driver": "tools/qualify_maskedvbyte_sdk.py",
        "missing": "src/tscompbench/adapters/deflate_zlib.py",
    }
    changed = snapshot / files[target]
    if target == "missing":
        changed.unlink()
    else:
        changed.write_bytes(changed.read_bytes() + b"\ndrift\n")
    with pytest.raises((RuntimeError, OSError, json.JSONDecodeError)):
        SDK_AUDIT(snapshot)
