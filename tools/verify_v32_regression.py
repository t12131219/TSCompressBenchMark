"""Run the complete regression suite and freeze the actual test definitions."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audit_v32_completion import file_evidence, sha, test_source_manifest  # noqa: E402

from tscompbench.comparison.runner import control_plane_snapshot  # noqa: E402
from tscompbench.ids import canonical_json_bytes  # noqa: E402


def project_configuration_manifest(root: Path) -> list[dict]:
    return [
        file_evidence(path)
        for directory in ("configs", "registry", "schemas")
        for path in sorted((root / directory).rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT):
        parser.error("regression evidence must be retained inside the project")
    output.mkdir(parents=True, exist_ok=True)
    log, report = output / "full-suite.log", output / "validation.json"
    if log.exists() or report.exists():
        parser.error("preserve existing evidence and choose a new output directory")
    current = control_plane_snapshot(ROOT)
    tests = test_source_manifest(ROOT)
    configuration = [file_evidence(ROOT / "pyproject.toml")]
    project_configuration = project_configuration_manifest(ROOT)
    driver = file_evidence(Path(__file__))
    invocation = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    overrides = {
        "PYTHONPATH": str(ROOT / "src"),
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    environment.update(overrides)
    with log.open("xb") as handle:
        result = subprocess.run(
            invocation, cwd=ROOT, env=environment, stdout=handle, stderr=subprocess.STDOUT
        )
    matches = re.findall(r"(?m)^.*?([0-9]+) passed[^\n]*$", log.read_text())
    configuration_unchanged = project_configuration == project_configuration_manifest(ROOT)
    driver_unchanged = driver == file_evidence(Path(__file__))
    unchanged = (
        current == control_plane_snapshot(ROOT)
        and tests == test_source_manifest(ROOT)
        and configuration == [file_evidence(ROOT / "pyproject.toml")]
        and configuration_unchanged
        and driver_unchanged
    )
    document = {
        "schema_version": "tscb.full-regression-verification.v2",
        "status": "PASS" if result.returncode == 0 and unchanged else "FAIL",
        "full_suite_exit_code": result.returncode,
        "full_suite_command": invocation,
        "tests_passed": int(matches[-1]) if matches else 0,
        "control_plane": current,
        "test_source_manifest": tests,
        "test_configuration": configuration,
        "project_configuration_manifest": project_configuration,
        "configuration_snapshot_unchanged": configuration_unchanged,
        "driver_snapshot_unchanged": driver_unchanged,
        "input_snapshot_unchanged": unchanged,
        "execution_environment_overrides": overrides,
        "pytest_addopts_environment": "REMOVED_TO_PREVENT_IMPLICIT_FILTERING",
        "pytest_version": importlib.metadata.version("pytest"),
        "python_executable": {"path": sys.executable, "sha256": sha(Path(sys.executable))},
        "verification_driver": driver,
        "artifacts": [{"role": "FULL_SUITE_LOG", **file_evidence(log)}],
    }
    with report.open("xb") as handle:
        handle.write(canonical_json_bytes(document) + b"\n")
    print(
        json.dumps(
            {
                "status": document["status"],
                "tests_passed": document["tests_passed"],
                "input_snapshot_unchanged": unchanged,
                "validation": str(report),
            }
        ),
        flush=True,
    )
    raise SystemExit(0 if document["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
