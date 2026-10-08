"""Independently verify current RLE bounded ABI execution, without qualifying SDK/Benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
from pathlib import Path

from audit_fastpfor_simple8b_rle_source import audit as audit_source

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "adapters/fastpfor_simple8b_rle"
FAULT_REPORT = ROOT / "build/source-audits/fastpfor-simple8b-rle-native-faults-20261007-1/report.json"
SAFETY_REPORT = ROOT / "build/source-audits/fastpfor-simple8b-rle-native-safety-20261007-1/report.json"
SMOKE_REPORT = ROOT / "build/source-audits/fastpfor-simple8b-rle-native-smoke-20261007-2/report.json"
FLAGS = {
    "release": ["-O3"], "debug": ["-O0", "-g"],
    "sanitizer": ["-O1", "-g", "-fsanitize=address,undefined",
                  "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
}
EXPECTED = {
    "safety": {"status": "PASS", "matrix_cases": 35244, "malformed_cases": 35453,
               "descriptor_alias_lifecycle_checks": 158, "guard_cases": 2376,
               "cycled_input_offsets": 4, "all_legal_selectors": True,
               "readonly_exact_guard_pages": True, "atomic_recoverable_failures": True},
    "allocation-clock": {"status": "PASS", "checks": 22, "allocation_exception_atomicity": True,
                         "clock_failure_backward_overflow": True, "same_shipped_object": True},
    "source-faults": {"status": "PASS", "source_fault_checks": 12,
                      "intentional_source_api_replacement": True, "same_shipped_object": True},
}
FILES = {"safety": "native_safety.cpp", "allocation-clock": "native_faults.cpp",
         "source-faults": "native_source_faults.cpp"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "sha256": sha(path)}


def verify(item: dict, expected: Path | None = None) -> Path:
    path = ROOT / item["path"]
    require(expected is None or path == expected, "evidence artifact substituted")
    require(path.is_file() and sha(path) == item["sha256"], "native evidence drift: " + str(path))
    return path


def closure(dep: dict, recorded: list[dict]) -> set[Path]:
    path = verify(dep)
    actual = {Path(p).resolve() for p in shlex.split(
        path.read_text().replace("\\\n", " ").split(":", 1)[1])}
    require(len(recorded) == len(actual) and {verify(i) for i in recorded} == actual,
            "compiler closure incomplete")
    return actual


def audit_build(profile: str) -> dict:
    directory = ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2" / profile
    path = directory / "build-record.json"
    build = json.loads(path.read_text())
    require(build["status"] == "PASS" and build["profile"] == profile
            and build["build_id"] == "20261007-2" and build["actual_cpu_affinity"] == [2],
            "shipped build profile/affinity differs")
    verify(build["artifact"], directory / "libtscb_fastpfor_simple8b_rle.so")
    require(len(build["objects"]) == len(build["dependency_files"]) == 1,
            "shipped object universe differs")
    verify(build["objects"][0], directory / "shim.o")
    deps = closure(build["dependency_files"][0], build["compiled_source_closure"])
    require(COMPONENT / "native/tscb_fastpfor_simple8b_rle.cpp" in deps
            and directory / "generated/headers/simple8b_rle.h" in deps,
            "shipped source closure does not contain wrapper and patched codec")
    for key in ("binding_sources", "runtime_dependencies", "generated_source_files"):
        for item in build[key]:
            verify(item)
    compile_commands = [i for i in build["commands"] if "-c" in i["command"]]
    link_commands = [i for i in build["commands"] if "-shared" in i["command"]]
    require(len(compile_commands) == len(link_commands) == 1
            and all(i["returncode"] == 0 for i in build["commands"]), "shipped build failed")
    command = compile_commands[0]["command"]
    require(all(f in command for f in FLAGS[profile]) and "-fPIC" in command
            and "-march=x86-64" in command and "-fno-tree-vectorize" in command
            and "-march=native" not in command, "shipped compilation profile differs")
    require("-Wl,-Bsymbolic" in link_commands[0]["command"]
            and str(directory / "shim.o") in link_commands[0]["command"],
            "shared library does not bind shipped functions/vtables")
    require(build["source_isa"] == "BASELINE_X86_64_NO_AUTOVECTORIZATION"
            and build["runtime_fallback"] is False, "native execution path differs")
    return build


def audit_suite(report_path: Path, suite: str) -> dict:
    report = json.loads(report_path.read_text())
    require(report["status"] == "NATIVE_SUITES_EXECUTED_INDEPENDENT_AUDIT_PENDING"
            and report["suite"] == suite and report["actual_cpu_affinity"] == [2],
            "suite incomplete or affinity differs")
    require(report["full_logical_entry_qualified"] is False
            and report["independent_native_audit"] == "PENDING"
            and report["python_sdk"] == report["benchmark_five_layers"] == "PENDING",
            "native suite qualification scope expanded")
    require(report["leak_sanitizer"] == "NOT_QUALIFIED_DETECT_LEAKS_ZERO"
            and report["sanitizer_environment"] == {
                "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}, "sanitizer scope differs")
    verify(report["driver"], COMPONENT / "tests/run_native_qualification.py")
    driver_snapshot = verify(report["driver_snapshot"])
    require(sha(driver_snapshot) == report["driver"]["sha256"], "driver snapshot differs")
    out = driver_snapshot.parent
    compiler = verify(report["compiler_binary"], Path("/usr/bin/g++").resolve())
    suites = ["safety"] if suite == "safety" else ["allocation-clock", "source-faults"]
    universe = [(p, s) for p in FLAGS for s in suites]
    require([(i["profile"], i["suite"]) for i in report["tests"]] == universe,
            "native execution universe incomplete")
    require([i["profile"] for i in report["builds"]] == list(FLAGS), "native build universe incomplete")
    names = ["compiler-version"] + [p + "-" + s + "-" + a
             for p, s in universe for a in ("compile", "execute", "symbols", "ldd")]
    commands = {}
    require(len(report["commands"]) == len(names), "raw command universe incomplete")
    for item, name in zip(report["commands"], names, strict=True):
        path = verify(item, out / (name + ".json"))
        raw = json.loads(path.read_text())
        require(raw["name"] == name and raw["returncode"] == 0, "native command failed")
        if name.endswith("execute"):
            require(raw["stderr"] == "", "native execution has diagnostics")
        commands[name] = raw
    require(report["compiler_version"] == commands["compiler-version"]
            and commands["compiler-version"]["command"] == [str(compiler), "--version"],
            "compiler identity differs")
    for item, profile in zip(report["builds"], FLAGS, strict=True):
        build = audit_build(profile)
        verify(item["record"], ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2" / profile / "build-record.json")
        require(item["library"] == build["artifact"] and item["objects"] == build["objects"],
                "suite used different shipped build")
    for test in report["tests"]:
        profile, group = test["profile"], test["suite"]
        name = profile + "-" + group
        directory = ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2" / profile
        source = verify(test["source"], COMPONENT / "tests" / FILES[group])
        snapshot = verify(test["source_snapshot"], out / FILES[group])
        require(sha(snapshot) == sha(source), "executed source snapshot differs")
        exe = verify(test["executable"], out / name)
        dep = verify(test["dependency_file"], out / (name + ".d"))
        deps = closure(test["dependency_file"], test["compiler_closure"])
        require(source in deps and ROOT / "native/include/tscb_adapter_v1.h" in deps,
                "test ABI compiler closure incomplete")
        require(not any(p.name == "simple8b_rle.h" for p in deps), "test contains source codec definitions")
        wraps = [] if group == "safety" else ["-Wl,--wrap=clock_gettime"]
        if group == "allocation-clock":
            wraps += ["-Wl,--wrap=_Znwm"]
        linkage = (["-L", str(directory), "-ltscb_fastpfor_simple8b_rle", "-Wl,-rpath," + str(directory)]
                   if group == "safety" else [str(directory / "shim.o"), *wraps])
        expected_command = [str(compiler), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-UNDEBUG", "-fno-pie", "-no-pie", "-march=x86-64", "-fno-tree-vectorize",
                            *FLAGS[profile], "-I", str(ROOT / "native/include"), "-MD", "-MF", str(dep),
                            str(source), *linkage, "-o", str(exe)]
        require(commands[name + "-compile"]["command"] == expected_command, "native test compile/link flags differ")
        execution_path = verify(test["execution"], out / (name + "-execute.json"))
        raw = commands[name + "-execute"]
        require(json.loads(execution_path.read_text()) == raw and raw["command"] == [str(exe)]
                and json.loads(raw["stdout"]) == test["observation"] == EXPECTED[group],
                "native raw observation/cardinality differs")
        symbols = commands[name + "-symbols"]
        require(symbols["command"] == ["/usr/bin/nm", "-C", "--defined-only", str(exe)], "symbols command differs")
        if group == "safety":
            require("FastPForLib::Simple8b" not in symbols["stdout"], "test can substitute shipped source")
            require(test["shipped_library"] == identity(directory / "libtscb_fastpfor_simple8b_rle.so")
                    and test["shipped_object"] is None, "shared suite used wrong library")
        else:
            require(test["shipped_object"] == identity(directory / "shim.o")
                    and test["shipped_library"] is None, "fault suite used wrong shipped object")
            if group == "source-faults":
                strong = re.findall(r" T FastPForLib::Simple8b_RLE<(?:true|false)>::(?:encodeArray|decodeArray)\(", symbols["stdout"])
                require(len(strong) == 4, "source fault replacements not strong or incomplete")
        ldd = commands[name + "-ldd"]
        require(ldd["command"] == ["/usr/bin/ldd", str(exe)], "runtime command differs")
        runtime = {Path(p).resolve() for p in ldd["stdout"].split() if p.startswith("/") and Path(p).is_file()}
        require(len(test["runtime_closure"]) == len(runtime)
                and {verify(i) for i in test["runtime_closure"]} == runtime, "native runtime closure incomplete")
        if group == "safety":
            require(directory / "libtscb_fastpfor_simple8b_rle.so" in runtime, "shipped library not loaded")
    return {"status": "PASS", "report": identity(report_path), "executions": len(universe)}


def audit() -> dict:
    source = audit_source()
    faults, safety = audit_suite(FAULT_REPORT, "faults"), audit_suite(SAFETY_REPORT, "safety")
    smoke = json.loads(SMOKE_REPORT.read_text())
    require(smoke["status"] == "FUNCTIONAL_SHARED_LIBRARY_MATRICES_PASS_NATIVE_QUALIFICATION_PENDING"
            and smoke["actual_cpu_affinity"] == [2] and smoke["native_functional_cases"] == 80784,
            "original shared functional evidence incomplete")
    verify(smoke["driver"], COMPONENT / "tests/run_native_smoke.py")
    require(sha(SMOKE_REPORT.parent / "driver.py") == smoke["driver"]["sha256"], "functional driver snapshot differs")
    require([i["profile"] for i in smoke["profiles"]] == list(FLAGS), "functional profile universe incomplete")
    names = [p + "-" + a for p in FLAGS for a in ("compile", "execute", "defined-symbols")]
    require([i["name"] for i in smoke["commands"]] == names, "functional raw command universe incomplete")
    for raw in smoke["commands"]:
        require(raw["returncode"] == 0 and
                json.loads((SMOKE_REPORT.parent / (raw["name"] + ".json")).read_text()) == raw,
                "functional raw command differs")
    raw_commands = {i["name"]: i for i in smoke["commands"]}
    for item in smoke["profiles"]:
        profile = item["profile"]
        directory = ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2" / item["profile"]
        verify(item["build_record"], directory / "build-record.json")
        verify(item["library"], directory / "libtscb_fastpfor_simple8b_rle.so")
        verify(item["executable"])
        closure(item["dependency_file"], item["compiler_closure"])
        require(item["observation"] == {"status": "PASS", "native_functional_cases": 26928,
                                       "full_native_qualification": False}, "functional observation differs")
        raw = raw_commands[profile + "-execute"]
        require(raw == item["result"] and json.loads(raw["stdout"]) == item["observation"]
                and raw["stderr"] == "" and raw["command"] == [str(ROOT / item["executable"]["path"])],
                "functional raw observation differs")
        require("FastPForLib::Simple8b" not in raw_commands[profile + "-defined-symbols"]["stdout"],
                "functional test substitutes source implementation")
    return {
        "status": "PASS", "scope": "PATCHED_RLE_BOUNDED_UINT32_C_ABI_ONLY",
        "source_api_audit": source, "fault_audit": faults, "safety_audit": safety,
        "original_shared_functional_report": identity(SMOKE_REPORT),
        "original_shared_functional_cases": 80784, "additional_functional_cases": 105732,
        "malformed_truncation_cases": 106359, "guard_page_cases": 7128,
        "descriptor_alias_lifecycle_checks": 474, "same_object_fault_checks": 102,
        "bounded_abi": "QUALIFIED_SCOPED_UINT32_ONLY", "python_sdk": "PENDING",
        "benchmark_registration": "PENDING", "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False, "leak_sanitizer": "NOT_QUALIFIED_DETECT_LEAKS_ZERO",
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    output = ROOT / "build/source-audits/fastpfor_simple8b_rle_native_current_audit.json"
    try:
        result = audit()
    except Exception as error:
        output.write_text(json.dumps({"status": "FAIL", "error": str(error),
                                     "full_logical_entry_qualified": False}, indent=2) + "\n")
        raise
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
