"""Independently revalidate the exact bounded MaskedVByte native qualification."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() and path.is_relative_to(ROOT):
        path = path.relative_to(ROOT)
    return root / path


def audit(root: Path = ROOT) -> dict:
    adapter = root / "adapters/maskedvbyte"
    source_audit = runpy.run_path(str(ROOT / "tools/audit_maskedvbyte_source.py"))["audit"](root)
    require(source_audit["status"] == "PASS", "source API evidence not current")
    report_path = root / "build/source-audits/maskedvbyte-native-tests.json"
    report = json.loads(report_path.read_text())
    require(report["status"] == "PASS", "native qualification not PASS")
    for field, path in (
        ("source_report_sha256", root / "build/source-audits/maskedvbyte-source-both-tests.json"),
        ("driver_sha256", adapter / "tests/run_native_tests.py"),
        ("build_driver_sha256", adapter / "build_native.py"),
        ("contract_sha256", adapter / "contract.md"),
        ("source_lock_sha256", adapter / "SOURCE_LOCK.json"),
        ("source_audit_driver_sha256", root / "tools/audit_maskedvbyte_source.py"),
    ):
        require(report[field] == sha(path), "native evidence drift: " + field)
    require(report["source_audit"] == source_audit, "source qualification changed")
    require(
        report["cases_per_executable"] == 9360
        and report["benchmark_five_layers"] == "NOT_CLAIMED"
        and report["python_sdk"] == "PENDING"
        and report["platform"] == "LINUX_X86_64_SSE4_1"
        and report["leak_detection"] == "DISABLED",
        "wrong scope or untested qualification claim",
    )
    expected = {
        (kind, profile)
        for kind in ("shared", "instrumented")
        for profile in ("release", "debug", "sanitizer")
    }
    require(
        len(report["tests"]) == 7
        and {(t["kind"], t.get("profile")) for t in report["tests"]}
        == expected | {("shared_timer_overflow", None)},
        "native qualification matrix incomplete",
    )
    for test in report["tests"]:
        path = (
            root / "tests/native/native_timing_smoke.c"
            if test["kind"] == "shared_timer_overflow"
            else adapter / "tests/abi_qualification.c"
        )
        require(
            test["returncode"] == 0 and sha(path) == test["test_sha256"],
            "native test drift or failure",
        )
        require(
            sha(resolve(root, test["command"][0])) == test["executable_sha256"],
            "tested native executable drift",
        )
        require(
            any(
                command == {key: test[key] for key in ("command", "returncode", "stdout", "stderr")}
                for command in report["commands"]
            ),
            "native test lacks actual command output",
        )
        if test["kind"] != "shared_timer_overflow":
            require(
                "cases PASS: 9360" in test["stdout"]
                and "canonical LEB128/lifecycle/atomic failure PASS" in test["stdout"],
                "guard or canonical grammar coverage absent",
            )
            compile_command = test["compile_command"]
            require(
                any(
                    c["command"] == compile_command and c["returncode"] == 0
                    for c in report["commands"]
                ),
                "native test compilation evidence absent",
            )
            require(
                "-DNDEBUG" not in compile_command and "-MD" in compile_command,
                "qualification assertions or dependency capture disabled",
            )
            if test["kind"] == "shared":
                require(
                    "-ltscb_maskedvbyte_u32" in compile_command
                    and "-DINSTRUMENTED" not in compile_command,
                    "shipped shared ABI was not tested",
                )
            else:
                for name in (
                    "malloc",
                    "calloc",
                    "free",
                    "clock_gettime",
                    "vbyte_encode",
                    "vbyte_encode_delta",
                    "masked_vbyte_decode",
                    "masked_vbyte_decode_delta",
                    "masked_vbyte_decode_fromcompressedsize",
                    "masked_vbyte_decode_fromcompressedsize_delta",
                ):
                    require(
                        "-Wl,--wrap=" + name in compile_command,
                        "fault/source-route wrapper absent: " + name,
                    )
                require(
                    "-DINSTRUMENTED" in compile_command
                    and all(
                        any(c.endswith("/" + name + ".o") for c in compile_command)
                        for name in ("shim", "encoder", "decoder")
                    ),
                    "same compiled objects were not fault-tested",
                )
            require(test["compiled_test_closure"], "test compiler dependency closure missing")
            for item in test["compiled_test_closure"]:
                require(
                    sha(resolve(root, item["path"])) == item["sha256"],
                    "native test compiled dependency drift",
                )
        if test["kind"] == "instrumented":
            require(
                "six original API routes/allocation sizes and failures/API length faults/"
                "native timer faults/accumulation PASS" in test["stdout"],
                "source route or fault injection absent",
            )
    require(
        len(report["builds"]) == 3
        and {b["profile"] for b in report["builds"]} == {"release", "debug", "sanitizer"},
        "native build matrix incomplete",
    )
    lock = json.loads((adapter / "SOURCE_LOCK.json").read_text())
    closure_counts = {}
    for qualified in report["builds"]:
        directory = root / "build/adapters/maskedvbyte_u32" / qualified["profile"]
        current = json.loads((directory / "build-record.json").read_text())
        require(
            current == qualified and current["status"] == "PASS", "qualified build record changed"
        )
        require(
            current["algorithm"] == "maskedvbyte-source-u32"
            and current["runtime_fallback"] is False,
            "wrong build identity or fallback",
        )
        require(
            current["source_files"] == lock["files"]
            and current["source_lock_sha256"] == sha(adapter / "SOURCE_LOCK.json"),
            "build source lock changed",
        )
        require(
            sha(root / current["artifact"]) == current["artifact_sha256"],
            "native shared binary drift",
        )
        command = json.loads((directory / "compile-command.json").read_text())
        canonical = json.dumps(command, sort_keys=True, separators=(",", ":")).encode()
        require(
            hashlib.sha256(canonical).hexdigest() == current["compile_commands_sha256"],
            "native compile commands drift",
        )
        compile_calls = [c for c in command["commands"] if "-c" in c]
        require(
            len(command["commands"]) == 5 and len(compile_calls) == 3,
            "separate shim/encoder/decoder translation units missing",
        )
        for i, c in enumerate(compile_calls):
            require(
                "-march=native" not in c
                and "-march=x86-64" in c
                and "-mno-avx" in c
                and "-mno-avx2" in c,
                "ISA build limits changed",
            )
            require(("-msse4.1" in c) == (i == 2), "ISA gate or encoder improperly requires SSE4.1")
            require(i == 2 or "-fno-tree-vectorize" in c, "baseline TU autovectorization enabled")
            require("-MD" in c and "-MF" in c, "actual dependency capture absent")
        for field in (
            "source_files",
            "patches",
            "generated_source_files",
            "binding_sources",
            "compiled_source_closure",
            "objects",
            "runtime_dependencies",
        ):
            require(bool(current[field]), "native build evidence missing: " + field)
            for item in current[field]:
                require(
                    sha(resolve(root, item["path"])) == item["sha256"],
                    "native consumed dependency drift: " + item["path"],
                )
        require(
            len(current["objects"]) == 3
            and len(current["generated_source_files"]) == 11
            and len(current["patches"]) == 1,
            "native objects, generated source or patch series incomplete",
        )
        require(
            current["patches"][0]["sha256"] == source_audit["patch_sha256"],
            "native patch differs from qualified source patch",
        )
        # The source auditor independently reapplies the patch. Compare every generated
        # native file to that verified snapshot, including unchanged encoder and headers.
        for item in lock["files"]:
            name = Path(item["path"]).relative_to("adapters/maskedvbyte/vendor/MaskedVByte")
            native_source = directory / "patched-source" / name
            original_source = root / item["path"]
            reference = root / "build/source-audits/maskedvbyte-source/patched" / name
            require(
                sha(native_source) == sha(reference),
                "native patch output differs from qualified patched source",
            )
            if str(name) != "src/varintdecode.c":
                require(
                    sha(native_source) == sha(original_source),
                    "native patch changed another original file",
                )
        closure_counts[qualified["profile"]] = len(current["compiled_source_closure"])
    return {
        "status": "PASS",
        "qualification_scope": "BOUNDED_NATIVE_UINT32_PLAIN_AND_MODULAR_DELTA",
        "native_report_sha256": sha(report_path),
        "source_report_sha256": report["source_report_sha256"],
        "source_lock_sha256": report["source_lock_sha256"],
        "patch_sha256": source_audit["patch_sha256"],
        "bounded_cases_per_executable": 9360,
        "bounded_executables": 6,
        "compiled_dependency_counts": closure_counts,
        "original_apis": [
            "vbyte_encode",
            "vbyte_encode_delta",
            "masked_vbyte_decode",
            "masked_vbyte_decode_delta",
            "masked_vbyte_decode_fromcompressedsize",
            "masked_vbyte_decode_fromcompressedsize_delta",
        ],
        "original_source_modified": False,
        "original_ubsan_failure_retained": True,
        "python_sdk": "PENDING",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "logical_entries": [93, 113],
        "full_logical_entries_qualified": False,
        "platform": "LINUX_X86_64_SSE4_1",
        "leak_detection": "DISABLED",
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    path = ROOT / "build/source-audits/maskedvbyte-native-current-audit.json"
    try:
        result = audit()
    except Exception as error:
        path.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
