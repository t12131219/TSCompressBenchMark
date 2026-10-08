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

from audit_littleintpacker_native import audit, require, sha

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/littleintpacker"
EXECUTION_SUFFIX = "20261007-2"
OUT = ROOT / "build/source-audits" / f"littleintpacker-sdk-{EXECUTION_SUFFIX}"
REPORT = OUT / "report.json"


def worker() -> None:
    import numpy as np
    import pytest

    require(sorted(os.sched_getaffinity(0)) == [2], "SDK worker affinity differs")
    before = {
        path.resolve(): sha(path)
        for directory in (ROOT / "src", ROOT / "tools", ROOT / "tests", ADAPTER)
        for path in directory.rglob("*.py")
    }
    code = pytest.main(
        [
            str(ROOT / "tests/adapters/test_littleintpacker.py"),
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
        frozen = OUT / "sources" / path.relative_to(ROOT)
        frozen.parent.mkdir(parents=True, exist_ok=True)
        frozen.write_bytes(path.read_bytes())
    closure = [{"path": str(path.relative_to(ROOT)), "sha256": sha(path)} for path in sorted(paths)]
    (OUT / "python-closure.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "actual_cpu_affinity": sorted(os.sched_getaffinity(0)),
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
    require(sorted(os.sched_getaffinity(0)) == [2], "SDK driver affinity differs")
    require(not OUT.exists(), "preserve prior SDK execution directory before rerunning")
    OUT.mkdir(parents=True)
    (OUT / "driver.py").write_bytes(Path(__file__).read_bytes())
    evidence: dict = {"status": "RUNNING", "commands": [], "execution_suffix": EXECUTION_SUFFIX,
                      "output_directory": str(OUT.relative_to(ROOT)), "actual_cpu_affinity": [2]}

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
        original = (
            ROOT.parent / "Compression_Source_Code/Source_Code/_repos/fast-pack_LittleIntPacker"
        )
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
        stdout = run([sys.executable, str(Path(__file__)), "--worker", "--suffix", EXECUTION_SUFFIX])
        junit = OUT / "pytest.xml"
        suites = ET.parse(junit).getroot().findall("testsuite")
        totals = {
            field: sum(int(s.get(field, "0")) for s in suites)
            for field in ("tests", "failures", "errors", "skipped")
        }
        require(
            totals == {"tests": 499, "failures": 0, "errors": 0, "skipped": 0},
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
            qualification_scope="DIRECT_PYTHON_UINT32_FIXED_AUTO_FIVE_API_SDK",
            driver_sha256=sha(Path(__file__)),
            native_auditor_sha256=sha(ROOT / "tools/audit_littleintpacker_native.py"),
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
            full_logical_entries_qualified=False,
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
    parser.add_argument("--suffix", default=EXECUTION_SUFFIX)
    args = parser.parse_args()
    require(args.suffix and "/" not in args.suffix and ".." not in args.suffix, "invalid SDK execution suffix")
    EXECUTION_SUFFIX = args.suffix
    OUT = ROOT / "build/source-audits" / f"littleintpacker-sdk-{EXECUTION_SUFFIX}"
    REPORT = OUT / "report.json"
    if args.worker:
        worker()
    else:
        main()
