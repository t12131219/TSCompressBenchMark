"""Run preserved source drivers in an isolated tree without replacing old evidence.

This issues scoped source-execution evidence, never FULL_PARITY or Bench/FORMAL
qualification. The Java dependencies must already match the preserved lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA_PACKAGES = ("chimp", "elf", "elf-plus", "elf-star", "self-star")
CLI_NAMES = {
    "chimp": "chimp_cli",
    "elf": "elf_vldb_cli",
    "elf-plus": "elf_plus_cli",
    "elf-star": "elf_star_cli",
    "self-star": "self_star_cli",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory: Path) -> dict[str, str]:
    return {
        str(p.relative_to(directory)): sha(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file() and not ({"__pycache__", "build"} & set(p.relative_to(directory).parts))
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--completed-build-root", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_root.resolve()
    if output.exists():
        raise SystemExit("Use a new output directory; historical evidence is never overwritten")
    output.mkdir(parents=True)
    isolated = output / "isolated"
    environment = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
    )
    report = {
        "schema_version": 1,
        "evidence_kind": "FRESH_SOURCE_EXECUTION_SCOPED",
        "full_parity_granted": False,
        "benchmark_qualification_granted": False,
        "formal_granted": False,
        "driver_sha256": sha(Path(__file__)),
        "commands": [],
        "packages": {},
        "completed": {},
    }
    original = {
        str(p.relative_to(ROOT)): sha(p)
        for base in (ROOT / "Compression_Rewrite/Source", ROOT / "Compression_Rewrite/ReWrite")
        for name in (*JAVA_PACKAGES, "abba", "fabba")
        for p in (base / name).rglob("*")
        if p.is_file() and not ({"__pycache__", "build"} & set(p.relative_to(base / name).parts))
    }

    def execute(label: str, command: list[str | Path], timeout: int = 1200) -> dict:
        start = time.monotonic()
        values = [str(x) for x in command]
        log = output / (label + ".log")
        try:
            result = subprocess.run(
                values, cwd=isolated, env=environment, capture_output=True, timeout=timeout
            )
            log.write_bytes(result.stdout + result.stderr)
            row = {
                "label": label,
                "command": values,
                "exit_code": result.returncode,
                "seconds": time.monotonic() - start,
                "log": str(log),
                "log_sha256": sha(log),
            }
        except subprocess.TimeoutExpired as error:
            log.write_bytes((error.stdout or b"") + (error.stderr or b""))
            row = {
                "label": label,
                "command": values,
                "exit_code": None,
                "status": "TIMEOUT",
                "seconds": time.monotonic() - start,
                "log": str(log),
                "log_sha256": sha(log),
            }
        report["commands"].append(row)
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(label, row["exit_code"], flush=True)
        if row["exit_code"] != 0:
            raise RuntimeError(f"{label} failed; see {log}")
        return row

    try:
        for name in (*JAVA_PACKAGES, "abba", "fabba"):
            for kind in ("Source", "ReWrite"):
                source = ROOT / "Compression_Rewrite" / kind / name
                destination = isolated / "Compression_Rewrite" / kind / name
                shutil.copytree(
                    source,
                    destination,
                    ignore=shutil.ignore_patterns("__pycache__", "build", "validation"),
                )
        (isolated / "datasets").symlink_to(ROOT / "datasets", target_is_directory=True)
        (isolated / "tools").mkdir()
        shutil.copy2(
            ROOT / "tools/build_elf_family_oracles.py",
            isolated / "tools/build_elf_family_oracles.py",
        )
        lock_path = ROOT / "Compression_Rewrite/Source/chimp/ORACLE_ENVIRONMENT_LOCK.json"
        lock = json.loads(lock_path.read_text())
        report["java_dependency_lock"] = {"path": str(lock_path), "sha256": sha(lock_path)}
        report["java_dependencies"] = []
        for package in lock["packages"]:
            path = Path("/tmp/tscb-elf-oracle-downloads") / package["name"]
            if sha(path) != package["sha256"]:
                raise RuntimeError(f"Oracle dependency hash mismatch: {path}")
            report["java_dependencies"].append(
                {**package, "actual_path": str(path), "actual_sha256": sha(path)}
            )
        execute("java-version", ["/tmp/tscb-elf-java8/bin/java", "-version"])
        execute(
            "chimp-source-build",
            [sys.executable, isolated / "Compression_Rewrite/Source/chimp/build_oracle.py"],
        )
        execute(
            "elf-family-source-build",
            [sys.executable, isolated / "tools/build_elf_family_oracles.py"],
        )
        execute(
            "elf-plus-source-build",
            [sys.executable, isolated / "Compression_Rewrite/Source/elf-plus/build_oracle.py"],
        )
        execute(
            "self-star-source-build",
            [
                sys.executable,
                isolated / "Compression_Rewrite/Source/self-star/build_oracle.py",
                "--repair-missing-temp",
            ],
        )
        for name in JAVA_PACKAGES:
            package = isolated / "Compression_Rewrite/ReWrite" / name
            build = output / "native" / name
            cli_name = CLI_NAMES[name]
            execute(
                name + "-native-configure",
                ["cmake", "-S", package, "-B", build, "-DCMAKE_BUILD_TYPE=Release"],
            )
            execute(
                name + "-native-build",
                ["cmake", "--build", build, "--target", cli_name, "--parallel", "2"],
            )
            if name == "self-star":
                command = [sys.executable, package / "tools/validate.py", "--build", build]
            else:
                command = [sys.executable, package / "tools/validate.py", "--cli", build / cli_name]
            execute(name + "-source-differential", command)
            result_path = package / "validation/differential/report.json"
            result = json.loads(result_path.read_text())
            statuses = {}
            for case in result["cases"]:
                statuses[case["status"]] = statuses.get(case["status"], 0) + 1
            report["packages"][name] = {
                "status": result["status"],
                "case_status_counts": statuses,
                "network_cases": len(result.get("network_cases", [])),
                "result": str(result_path),
                "result_sha256": sha(result_path),
                "cli": str(build / cli_name),
                "cli_sha256": sha(build / cli_name),
                "source_files": inventory(isolated / "Compression_Rewrite/Source" / name),
                "native_source_files": inventory(package),
            }
        completed = args.completed_build_root.resolve()
        package = isolated / "Compression_Rewrite/ReWrite/abba"
        oracle = output / "ckmeans_source_oracle"
        source = isolated / "Compression_Rewrite/Source/abba/upstream/src"
        execute(
            "ckmeans-source-build",
            [
                "c++",
                "-std=c++11",
                "-O2",
                "-fno-fast-math",
                "-ffp-contract=off",
                "-I",
                source,
                package / "tests/oracle/ckmeans_oracle_cli.cpp",
                *[
                    source / (n + ".cpp")
                    for n in (
                        "Ckmeans.1d.dp",
                        "dynamic_prog",
                        "fill_SMAWK",
                        "fill_log_linear",
                        "fill_quadratic",
                        "select_levels",
                    )
                ],
                "-o",
                oracle,
            ],
        )
        for name in ("abba", "fabba"):
            package = isolated / "Compression_Rewrite/ReWrite" / name
            cli = completed / name / "release/cmake/standalone" / (name + "_cli")
            command = [
                sys.executable,
                package / "tests/cross_decode/run_differential.py",
                "--cpp-cli",
                cli,
                "--oracle",
                package / "tests/oracle" / (name + "_oracle.py"),
                "--vectors",
                package / "tests/golden" / (name + "_vectors.json"),
            ]
            if name == "abba":
                command += ["--ckmeans-cli", oracle]
            differential = execute(name + "-source-differential", command)
            capability = execute(
                name + "-source-capability",
                [
                    sys.executable,
                    package / "tests/capability/run_capability_validation.py",
                    "--cpp-cli",
                    cli,
                    "--source-root",
                    isolated / "Compression_Rewrite/Source" / name / "upstream",
                ],
            )
            report["completed"][name] = {
                "status": "PASS_SCOPED_SEMANTIC",
                "cli": str(cli),
                "cli_sha256": sha(cli),
                "source_files": inventory(isolated / "Compression_Rewrite/Source" / name),
                "oracle_driver_sha256": sha(package / "tests/oracle" / (name + "_oracle.py")),
                "differential": differential,
                "capability": capability,
                "oracle_is_stage_composed": True,
                "unmodified_full_upstream_parity": False,
            }
        report["status"] = "PASS_FRESH_SOURCE_EXECUTION_SCOPED"
    except Exception as error:
        report.update(status="FAIL_OR_BLOCKED", error=str(error))
    finally:
        changes = [
            p
            for p, expected in original.items()
            if not (ROOT / p).exists() or sha(ROOT / p) != expected
        ]
        report["original_reference_or_report_changes"] = changes
        report["original_reference_or_report_hashes_checked"] = len(original)
        if changes:
            report.update(status="FAIL_ORIGINAL_EVIDENCE_CHANGED")
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "packages": list(report["packages"]),
                "completed": list(report["completed"]),
            }
        )
    )
    raise SystemExit(0 if report["status"] == "PASS_FRESH_SOURCE_EXECUTION_SCOPED" else 1)


if __name__ == "__main__":
    main()
