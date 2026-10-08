"""Execute safety/fault suites using the frozen shipped RLE libraries and objects."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/fastpfor_simple8b_rle"
ENV = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
           UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
PROFILES = {
    "release": ["-O3"],
    "debug": ["-O0", "-g"],
    "sanitizer": ["-O1", "-g", "-fsanitize=address,undefined",
                  "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
}


def identity(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify(item: dict) -> None:
    if identity(ROOT / item["path"]) != item:
        raise RuntimeError("evidence dependency drift: " + item["path"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("all", "faults", "safety"), default="all")
    parser.add_argument("--execution-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,63}", args.execution_id):
        raise ValueError("invalid execution ID")
    out = ROOT / "build/source-audits" / args.execution_id
    if out.exists():
        raise RuntimeError("preserve existing execution; choose a new execution ID")
    out.mkdir(parents=True)
    (out / "driver.py").write_bytes(Path(__file__).read_bytes())
    report = {
        "status": "RUNNING", "suite": args.suite,
        "driver": identity(Path(__file__)), "driver_snapshot": identity(out / "driver.py"),
        "actual_cpu_affinity": sorted(os.sched_getaffinity(0)),
        "sanitizer_environment": {k: ENV[k] for k in ("ASAN_OPTIONS", "UBSAN_OPTIONS")},
        "commands": [], "tests": [], "builds": [],
        "independent_native_audit": "PENDING", "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING", "full_logical_entry_qualified": False,
        "leak_sanitizer": "NOT_QUALIFIED_DETECT_LEAKS_ZERO",
    }

    def save() -> None:
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(command: list[str], name: str) -> dict:
        result = subprocess.run(command, cwd=ROOT, env=ENV, capture_output=True,
                                text=True, timeout=240)
        record = {"name": name, "command": command, "returncode": result.returncode,
                  "stdout": result.stdout, "stderr": result.stderr}
        log = out / (name + ".json")
        log.write_text(json.dumps(record, indent=2) + "\n")
        report["commands"].append(identity(log))
        save()
        if result.returncode:
            raise RuntimeError(name + " failed: " + result.stderr[-4000:])
        return record

    save()
    try:
        if report["actual_cpu_affinity"] != [2]:
            raise RuntimeError("auxiliary compilation and execution require CPU2")
        compiler = Path("/usr/bin/g++").resolve()
        report["compiler_binary"] = identity(compiler)
        report["compiler_version"] = run([str(compiler), "--version"], "compiler-version")
        suites = []
        if args.suite in ("all", "safety"):
            suites.append(("safety", "native_safety.cpp", [], None))
        if args.suite in ("all", "faults"):
            suites += [
                ("allocation-clock", "native_faults.cpp",
                 ["-Wl,--wrap=clock_gettime", "-Wl,--wrap=_Znwm"],
                 {"status": "PASS", "checks": 22, "allocation_exception_atomicity": True,
                  "clock_failure_backward_overflow": True, "same_shipped_object": True}),
                ("source-faults", "native_source_faults.cpp", ["-Wl,--wrap=clock_gettime"],
                 {"status": "PASS", "source_fault_checks": 12,
                  "intentional_source_api_replacement": True, "same_shipped_object": True}),
            ]
        for profile, flags in PROFILES.items():
            directory = ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2" / profile
            build_path = directory / "build-record.json"
            build = json.loads(build_path.read_text())
            if build["status"] != "PASS" or build["actual_cpu_affinity"] != [2]:
                raise RuntimeError("unqualified shipped build")
            for key in ("objects", "compiled_source_closure", "binding_sources",
                        "runtime_dependencies", "generated_source_files"):
                for item in build[key]:
                    verify(item)
            verify(build["artifact"])
            report["builds"].append({"profile": profile, "record": identity(build_path),
                                     "library": build["artifact"], "objects": build["objects"]})
            for suite, filename, wraps, expected in suites:
                name = profile + "-" + suite
                source = ADAPTER / "tests" / filename
                snapshot = out / filename
                if not snapshot.exists():
                    snapshot.write_bytes(source.read_bytes())
                exe, dep = out / name, out / (name + ".d")
                linkage = (["-L", str(directory), "-ltscb_fastpfor_simple8b_rle",
                            "-Wl,-rpath," + str(directory)] if suite == "safety"
                           else [str(directory / "shim.o"), *wraps])
                run([str(compiler), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                     "-UNDEBUG", "-fno-pie", "-no-pie", "-march=x86-64",
                     "-fno-tree-vectorize", *flags, "-I", str(ROOT / "native/include"),
                     "-MD", "-MF", str(dep), str(source), *linkage, "-o", str(exe)],
                    name + "-compile")
                result = run([str(exe)], name + "-execute")
                observed = json.loads(result["stdout"])
                if observed.get("status") != "PASS" or (expected and observed != expected):
                    raise RuntimeError("unexpected suite observation: " + name)
                symbols = run(["/usr/bin/nm", "-C", "--defined-only", str(exe)], name + "-symbols")
                if suite == "safety" and "FastPForLib::Simple8b" in symbols["stdout"]:
                    raise RuntimeError("functional suite substitutes source implementation")
                deps = sorted({Path(p).resolve() for p in shlex.split(
                    dep.read_text().replace("\\\n", " ").split(":", 1)[1])})
                ldd = run(["/usr/bin/ldd", str(exe)], name + "-ldd")
                runtime = sorted({Path(p).resolve() for p in ldd["stdout"].split()
                                  if p.startswith("/") and Path(p).is_file()})
                report["tests"].append({
                    "profile": profile, "suite": suite, "source": identity(source),
                    "source_snapshot": identity(snapshot), "executable": identity(exe),
                    "dependency_file": identity(dep), "compiler_closure": [identity(p) for p in deps],
                    "runtime_closure": [identity(p) for p in runtime], "observation": observed,
                    "execution": identity(out / (name + "-execute.json")),
                    "shipped_library": build["artifact"] if suite == "safety" else None,
                    "shipped_object": build["objects"][0] if suite != "safety" else None,
                })
                save()
                print("NATIVE_SUITE_PASS", name, json.dumps(observed), flush=True)
        report["status"] = "NATIVE_SUITES_EXECUTED_INDEPENDENT_AUDIT_PENDING"
    except Exception as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
