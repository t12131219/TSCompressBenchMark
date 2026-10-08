"""Test every frozen SSE public API against independent wire and protected pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/simdcomp"
MODES = ("plain", "d1", "for", "query-d1", "query-for", "set-plain", "set-d1", "set-for")
PROFILES = {
    "release": ["-O3"],
    "debug": ["-O0", "-g", "-DSIMDCOMP_DEBUG"],
    "sanitizer": [
        "-O1",
        "-g",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
    ],
}


def record(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("original", "patched"), default="original")
    args = parser.parse_args()
    upstream_path = ROOT / f"build/source-audits/simdcomp-upstream-{args.kind}-tests.json"
    upstream = json.loads(upstream_path.read_text())
    if upstream["status"] not in {"PASS", "OBSERVED_FAILURES"} or len(upstream["tests"]) != 9:
        raise RuntimeError("upstream matrix is not terminal and complete")
    for build in upstream["builds"]:
        for item in [build["library"], *build["objects"], *build["compiled_source_closure"]]:
            if record(Path(item["path"]))["sha256"] != item["sha256"]:
                raise RuntimeError("upstream compiled library/input drift")
    path = ROOT / f"build/source-audits/simdcomp-source-{args.kind}-guards.json"
    guard = ADAPTER / "tests/source_guard.c"
    report = {
        "schema_version": "tscb.simdcomp-source-guards.v1",
        "status": "RUNNING",
        "source_kind": args.kind,
        "source_lock_sha256": upstream["source_lock_sha256"],
        "upstream_report": record(upstream_path),
        "driver": record(Path(__file__)),
        "guard": record(guard),
        "actual_isa": upstream["actual_isa"],
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "tests": [],
        "builds": [],
        "commands": [],
        "benchmark_adapter_qualification": "NOT_CLAIMED",
        "leak_detection": "DISABLED",
    }

    def save() -> None:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    def run(command: list[str], check: bool = False) -> dict:
        env = dict(os.environ)
        env["ASAN_OPTIONS"] = "detect_leaks=0:abort_on_error=1"
        env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, env=env, timeout=120
        )
        observed = {
            "command": command,
            "cwd": str(ROOT),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        report["commands"].append(observed)
        save()
        if check and result.returncode:
            raise RuntimeError("guard compile failed: " + result.stderr)
        return observed

    for profile, flags in PROFILES.items():
        build = ROOT / "build/source-audits/simdcomp-upstream" / args.kind / profile
        include = (
            ADAPTER / "vendor/simdcomp/include"
            if args.kind == "original"
            else ROOT / "build/source-audits/simdcomp-upstream/patched-source/include"
        )
        executable = build / "source-guard"
        dependency = build / "source-guard.d"
        run(
            [
                "/usr/bin/cc",
                "-std=gnu11",
                "-march=x86-64",
                "-msse4.1",
                "-mno-avx",
                "-UNDEBUG",
                *flags,
                "-Wall",
                "-Wextra",
                "-Werror",
                "-MD",
                "-MF",
                str(dependency),
                "-I",
                str(include),
                str(guard),
                str(build / "libsimdcomp.a"),
                "-o",
                str(executable),
            ],
            True,
        )
        closure = [
            record(Path(filename))
            for filename in shlex.split(
                dependency.read_text().replace("\\\n", " ").split(":", 1)[1]
            )
        ]
        report["builds"].append(
            {
                "profile": profile,
                "executable": record(executable),
                "library": record(build / "libsimdcomp.a"),
                "compiled_source_closure": closure,
            }
        )
        for mode in MODES:
            observed = run([str(executable), mode])
            report["tests"].append(
                {
                    "profile": profile,
                    "mode": mode,
                    "status": "PASS" if observed["returncode"] == 0 else "FAIL",
                    **observed,
                }
            )
            save()
            print(
                json.dumps(
                    {
                        "profile": profile,
                        "mode": mode,
                        "returncode": observed["returncode"],
                        "stdout": observed["stdout"],
                        "stderr": observed["stderr"][:1600],
                    }
                ),
                flush=True,
            )
    report["failed_test_count"] = sum(t["status"] == "FAIL" for t in report["tests"])
    report["status"] = "OBSERVED_FAILURES" if report["failed_test_count"] else "PASS"
    save()
    print(
        json.dumps(
            {
                "status": report["status"],
                "tests": len(report["tests"]),
                "failed": report["failed_test_count"],
                "report": str(path),
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
