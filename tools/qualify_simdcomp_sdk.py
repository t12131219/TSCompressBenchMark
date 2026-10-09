"""Save source-backed direct SDK tests and the actual imported Python closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from audit_simdcomp_native import audit, require, sha

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/simdcomp"
SDK_SUFFIX = os.environ.get("TSCB_SDK_EXECUTION_SUFFIX")
if SDK_SUFFIX and (Path(SDK_SUFFIX).name != SDK_SUFFIX or ".." in SDK_SUFFIX):
    raise ValueError("unsafe SDK execution suffix")
OUT = ROOT / "build/source-audits" / ("simdcomp-sdk-" + SDK_SUFFIX if SDK_SUFFIX else "simdcomp-sdk")
REPORT = OUT / "report.json" if SDK_SUFFIX else ROOT / "build/source-audits/simdcomp_sdk_tests.json"


def worker() -> None:
    import numpy as np
    import pytest

    before = {
        path.resolve(): sha(path)
        for directory in (ROOT / "src", ROOT / "tools", ROOT / "tests", ADAPTER)
        for path in directory.rglob("*.py")
    }
    code = pytest.main(
        [
            str(ROOT / "tests/adapters/test_simdcomp.py"),
            "-q",
            "--junitxml=" + str(OUT / "pytest.xml"),
        ]
    )
    if code:
        raise SystemExit(code)
    paths = {Path(__file__).resolve()}
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path and Path(path).resolve().is_relative_to(ROOT) and str(path).endswith(".py"):
            paths.add(Path(path).resolve())
    for path in paths:
        require(before.get(path) == sha(path), "Python dependency changed during SDK tests")
    closure = [{"path": str(path.relative_to(ROOT)), "sha256": sha(path)} for path in sorted(paths)]
    (OUT / "python-closure.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "source_snapshot": closure,
                "python": platform.python_version(),
                "executable": sys.executable,
                "numpy": np.__version__,
                "pytest": pytest.__version__,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=not bool(SDK_SUFFIX))
    evidence: dict = {"status": "RUNNING", "commands": [], "output_directory": str(OUT.relative_to(ROOT))}

    def save() -> None:
        REPORT.write_text(json.dumps(evidence, indent=2) + "\n")

    def run(command: list[str]) -> str:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
        )
        evidence["commands"].append(
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        save()
        require(result.returncode == 0, "SDK qualification command failed: " + str(command))
        return result.stdout

    save()
    try:
        native = audit()
        evidence["native_current_audit"] = native
        original = ROOT.parent / "Compression_Source_Code/Source_Code/_repos/lemire_simdcomp"
        lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
        require(
            run(["git", "-C", str(original), "rev-parse", "HEAD"]).strip() == lock["commit"],
            "source pin drift",
        )
        require(
            not run(["git", "-C", str(original), "status", "--porcelain"]).strip(),
            "source repository dirty",
        )
        require(
            not run(["git", "-C", str(original), "submodule", "status"]).strip(),
            "unexpected source submodule",
        )
        for item in lock["files"]:
            name = Path(item["path"]).relative_to("adapters/simdcomp/vendor/simdcomp")
            require(sha(original / name) == item["sha256"], "original/vendor divergence")
        stdout = run([sys.executable, str(Path(__file__)), "--worker"])
        junit = OUT / "pytest.xml"
        suites = ET.parse(junit).getroot().findall("testsuite")
        totals = {
            field: sum(int(s.get(field, "0")) for s in suites)
            for field in ("tests", "failures", "errors", "skipped")
        }
        require(
            totals == {"tests": 888, "failures": 0, "errors": 0, "skipped": 0},
            "SDK qualification incomplete/failed/skipped",
        )
        closure_path = OUT / "python-closure.json"
        closure = json.loads(closure_path.read_text())
        require(closure["status"] == "PASS", "Python actual dependency closure missing")
        for item in closure["source_snapshot"]:
            require(sha(ROOT / item["path"]) == item["sha256"], "SDK dependency drift")
        require(audit() == native, "native evidence changed during SDK tests")
        evidence.update(
            status="PASS",
            qualification_scope="DIRECT_PYTHON_UINT32_PLAIN_MODULAR_D1_AND_FIXED_FOR_SDK",
            driver_sha256=sha(Path(__file__)),
            native_auditor_sha256=sha(ROOT / "tools/audit_simdcomp_native.py"),
            junit_sha256=sha(junit),
            python_closure_sha256=sha(closure_path),
            test_totals=totals,
            source_repository_unmodified=True,
            original_vendor_equal_file_count=len(lock["files"]),
            source_snapshot=closure["source_snapshot"],
            source_snapshot_sha256=hashlib.sha256(
                json.dumps(closure["source_snapshot"], sort_keys=True).encode()
            ).hexdigest(),
            python_runtime={
                key: closure[key] for key in ("python", "executable", "numpy", "pytest")
            },
            benchmark_registration="PENDING",
            benchmark_five_layers="PENDING",
        )
        save()
        print(stdout, end="")
    except Exception as error:
        evidence.update(status="FAIL", error=str(error))
        save()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    if parser.parse_args().worker:
        worker()
    else:
        main()
