"""Execute original wire and patched RLE matrices, then the complete patched factory unit."""

from __future__ import annotations

import argparse
import json
import os
import re
import resource
import shlex
import subprocess
from pathlib import Path

from audit_fastpfor_simple_upstream import FLAGS as UPSTREAM_FLAGS
from audit_fastpfor_simple_upstream import audit as audit_upstream
from freeze_fastpfor_simple8b_rle_source import ADAPTER, PIN, ROOT, SOURCES, sha, tracked
from prepare_fastpfor_simple8b_rle_patch import corrected

PROFILES = {
    "release": ["-O3", "-DNDEBUG"],
    "debug": ["-O0", "-g", "-UNDEBUG"],
    "sanitizer": ["-O1", "-g", "-UNDEBUG", "-fsanitize=address,undefined",
                  "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"],
}
BASE_FLAGS = ["-std=c++17", "-march=x86-64", "-fno-tree-vectorize"]


def identity(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "sha256": sha(path.read_bytes())}


def dependencies(path: Path) -> list[dict]:
    body = path.read_text().replace("\\\n", " ").split(":", 1)[1]
    return [identity(p) for p in sorted({Path(p).resolve() for p in shlex.split(body)})]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="20261007-1")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,63}", args.run_id):
        raise ValueError("invalid run ID")
    out = ROOT / "build/source-audits" / ("fastpfor-simple8b-rle-source-" + args.run_id)
    if out.exists():
        raise RuntimeError("preserve prior source execution; choose a new run ID")
    out.mkdir(parents=True)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    report_path = out / "report.json"
    report = {
        "status": "RUNNING", "run_id": args.run_id,
        "scope": "PATCHED_RLE_VALID_UINT32_OBJECT_SOURCE_APIS_ONLY",
        "driver": identity(Path(__file__)), "commands": [], "builds": [], "matrices": [],
        "source_lock": identity(ADAPTER / "SOURCE_LOCK.json"),
        "patch_lock": identity(ADAPTER / "PATCH_LOCK.json"),
        "matrix_source": identity(ADAPTER / "tests/source_matrix.cpp"),
        "original_failure_report": identity(
            ROOT / "build/source-audits/fastpfor-simple8b-rle-discovery/report.json"),
        "full_logical_entry_qualified": False, "bounded_abi": "PENDING",
        "python_sdk": "PENDING", "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING", "leak_sanitizer": "NOT_QUALIFIED_DETECT_LEAKS_ZERO",
    }
    (out / "driver.py").write_bytes(Path(__file__).read_bytes())

    def save() -> None:
        report_path.write_text(json.dumps(report, indent=2) + "\n")

    def run(command: list[str], name: str, timeout: int = 240) -> dict:
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
                           UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                timeout=timeout, env=environment)
        entry = {"name": name, "command": command, "returncode": result.returncode,
                 "stdout": result.stdout, "stderr": result.stderr,
                 "sanitizer_environment": {k: environment[k]
                                           for k in ("ASAN_OPTIONS", "UBSAN_OPTIONS")}}
        report["commands"].append(entry)
        (out / (name + ".json")).write_text(json.dumps(entry, indent=2) + "\n")
        save()
        if result.returncode:
            raise RuntimeError(name + " failed: " + result.stderr[-4000:])
        return entry

    save()
    try:
        lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
        patch = json.loads((ADAPTER / "PATCH_LOCK.json").read_text())
        if patch["source_lock_sha256"] != report["source_lock"]["sha256"]:
            raise RuntimeError("patch source lock drift")
        for path, expected in (
            (ROOT / "tools/freeze_fastpfor_simple8b_rle_source.py", lock["freezer_sha256"]),
            (ROOT / "tools/prepare_fastpfor_simple8b_rle_patch.py", patch["generator_sha256"]),
            (ROOT / patch["patch"]["path"], patch["patch"]["sha256"]),
        ):
            if identity(path)["sha256"] != expected:
                raise RuntimeError("source/patch driver drift")
        report["driver_dependencies"] = [
            identity(ROOT / "tools" / name) for name in (
                "freeze_fastpfor_simple8b_rle_source.py", "prepare_fastpfor_simple8b_rle_patch.py",
                "freeze_fastpfor_simple_source.py", "audit_fastpfor_simple_source.py",
                "audit_fastpfor_simple_upstream.py",
            )
        ]
        original_repo = SOURCES / "fast-pack_FastPFOR"
        generated = out / "generated"
        for item in lock["files"]:
            data = (ROOT / item["path"]).read_bytes()
            if sha(data) != item["sha256"] or data != tracked(
                original_repo, PIN, item["upstream_path"]
            ):
                raise RuntimeError("original source drift: " + item["path"])
            if item["role"] == "ORIGINAL_ALGORITHM":
                target = generated / item["upstream_path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        run(["/usr/bin/patch", "--batch", "--forward", "-p1", "-d", str(generated),
             "-i", str(ROOT / patch["patch"]["path"])], "apply-patch")
        patched_header = generated / "headers/simple8b_rle.h"
        if patched_header.read_text() != corrected(
            (ADAPTER / "vendor/fastpfor/headers/simple8b_rle.h").read_text()
        ) or identity(patched_header)["sha256"] != patch["patched_sha256"]:
            raise RuntimeError("applied patch bytes differ")
        report["generated_source_files"] = [identity(p) for p in sorted(generated.rglob("*"))
                                            if p.is_file()]
        for original, profiles in ((True, ("release", "debug")), (False, tuple(PROFILES))):
            for profile in profiles:
                label = ("original-" if original else "patched-") + profile
                directory = out / label
                directory.mkdir()
                executable, dep = directory / "source-matrix", directory / "source-matrix.d"
                headers = ADAPTER / "vendor/fastpfor/headers" if original else generated / "headers"
                flags = [*BASE_FLAGS, *PROFILES[profile]]
                if original:
                    flags.append("-DTSCB_ORIGINAL_RLE=1")
                command = ["/usr/bin/g++", *flags, "-I", str(headers), "-MD", "-MF", str(dep),
                           str(ADAPTER / "tests/source_matrix.cpp"), "-o", str(executable)]
                run(command, label + "-compile")
                report["builds"].append({"label": label, "command": command,
                                         "executable": identity(executable),
                                         "dependency_file": identity(dep),
                                         "compiler_closure": dependencies(dep)})
                command = [str(executable)] + (["wire-only"] if original else [])
                result = run(command, label + "-execute")
                observation = json.loads(result["stdout"])
                if observation != {"status": "PASS", "cases": 70488,
                                   "guard_roundtrips": 0 if original else 1596,
                                   "selectors": 15, "wire_only": original}:
                    raise RuntimeError("matrix universe or result differs: " + str(observation))
                report["matrices"].append({"label": label, "observation": observation,
                                          "result": result})
                save()
                print("SOURCE_MATRIX_PASS", label, observation, flush=True)
        upstream = audit_upstream()
        upstream_report_path = ROOT / "build/source-audits/fastpfor_simple_upstream_tests.json"
        old = json.loads(upstream_report_path.read_text())
        report["original_full_upstream"] = {"audit": upstream,
                                             "report": identity(upstream_report_path)}
        directory = out / "patched-full-upstream"
        directory.mkdir()
        vendor = ROOT / "adapters/fastpfor_simple/third_party/fastpfor_upstream_unit"
        factory, dep = directory / "codecfactory.o", directory / "codecfactory.d"
        command = ["/usr/bin/g++", "-std=c++11", *UPSTREAM_FLAGS,
                   "-I", str(generated / "headers"), "-I", str(vendor / "headers"),
                   "-MD", "-MF", str(dep), "-c", str(vendor / "src/codecfactory.cpp"),
                   "-o", str(factory)]
        run(command, "patched-full-factory-compile")
        report["patched_factory_build"] = {"command": command, "object": identity(factory),
                                           "dependency_file": identity(dep),
                                           "compiler_closure": dependencies(dep)}
        objects = []
        reused = []
        for item in old["builds"]:
            if item["source"]["path"].endswith("/src/codecfactory.cpp"):
                objects.append(str(factory))
            else:
                objects.append(str(ROOT / item["object"]["path"]))
                reused.append(item)
        report["reused_upstream_objects"] = reused
        executable = directory / "upstream-unit"
        run(["/usr/bin/g++", *UPSTREAM_FLAGS, *objects, "-o", str(executable)],
            "patched-full-unit-link")
        report["patched_full_executable"] = identity(executable)
        print("RUNNING complete unfiltered upstream unit with patched RLE", flush=True)
        result = run([str(executable)], "patched-full-unit-execute", timeout=1800)
        stdout = result["stdout"]
        if (
            re.findall(r"testing\.\.\. b = (\d+)", stdout) != [str(i) for i in range(29)]
            or re.findall(r"length = (\d+)", stdout) != [str(2**i) for i in (5, 10, 15, 20, 25)]
            or stdout.count("Simple8b_RLE encoding ... decoding ... ok!") != 5
            or not stdout.endswith("testing...ok. Your code is good.\n")
        ):
            raise RuntimeError("patched complete upstream unit universe incomplete")
        report["patched_full_result"] = result
        for item in report["generated_source_files"]:
            if identity(ROOT / item["path"])["sha256"] != item["sha256"]:
                raise RuntimeError("generated source changed during execution")
        report.update(status="PATCHED_RLE_SOURCE_MATRIX_AND_COMPLETE_RELEASE_UPSTREAM_PASS",
                      original_wire_cases=140976, patched_roundtrip_cases=211464,
                      patched_guard_roundtrips=4788,
                      source_capacity_and_malformed_frames="NOT_QUALIFIED_REQUIRE_BOUNDED_ABI")
        print(report["status"], flush=True)
    except Exception as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
