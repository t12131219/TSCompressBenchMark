"""Freeze actual RLE SDK execution and its imported Python/native dependencies."""

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

from audit_fastpfor_simple8b_rle_native import audit, identity, require

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/source-audits/fastpfor-simple8b-rle-sdk-20261007-1"
REPORT = OUT / "report.json"


def worker() -> None:
    import numpy as np
    import pytest

    require(sorted(os.sched_getaffinity(0)) == [2], "SDK worker requires CPU2")
    before = {p.resolve(): identity(p)["sha256"]
              for directory in (ROOT / "src", ROOT / "tools", ROOT / "tests")
              for p in directory.rglob("*.py")}
    code = pytest.main([str(ROOT / "tests/adapters/test_fastpfor_simple8b_rle.py"),
                        "-q", "--junitxml=" + str(OUT / "pytest.xml")])
    if code:
        raise SystemExit(code)
    paths = {Path(__file__).resolve()}
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if name and str(name).endswith(".py") and Path(name).resolve().is_relative_to(ROOT):
            paths.add(Path(name).resolve())
    for path in paths:
        require(before.get(path) == identity(path)["sha256"], "SDK dependency changed during tests")
    closure = [identity(p) for p in sorted(paths)]
    libraries = {Path(line.split()[-1]).resolve() for line in Path("/proc/self/maps").read_text().splitlines()
                 if "/libtscb_" in line and line.split()[-1].endswith(".so")}
    (OUT / "python-closure.json").write_text(json.dumps({
        "status": "PASS", "source_snapshot": closure, "native_libraries_loaded": [identity(p) for p in sorted(libraries)],
        "actual_cpu_affinity": sorted(os.sched_getaffinity(0)), "python": platform.python_version(),
        "executable": sys.executable, "numpy": np.__version__, "pytest": pytest.__version__,
    }, indent=2) + "\n")


def main() -> None:
    require(not OUT.exists(), "preserve previous SDK execution")
    require(sorted(os.sched_getaffinity(0)) == [2], "SDK qualification requires CPU2")
    native = audit()
    OUT.mkdir(parents=True)
    (OUT / "driver.py").write_bytes(Path(__file__).read_bytes())
    report = {
        "status": "RUNNING", "scope": "DIRECT_PYTHON_UINT32_MARKED_UNMARKED_RLE_SDK_ONLY",
        "driver": identity(Path(__file__)), "driver_snapshot": identity(OUT / "driver.py"),
        "native_current_audit": native, "commands": [], "actual_cpu_affinity": [2],
        "python_sdk_audit": "PENDING", "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING", "full_logical_entry_qualified": False,
    }

    def save() -> None:
        REPORT.write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        result = subprocess.run([sys.executable, str(Path(__file__)), "--worker"], cwd=ROOT,
                                env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                                capture_output=True, text=True, timeout=180)
        raw = {"command": result.args, "returncode": result.returncode,
               "stdout": result.stdout, "stderr": result.stderr}
        (OUT / "worker.json").write_text(json.dumps(raw, indent=2) + "\n")
        report["commands"].append(identity(OUT / "worker.json"))
        require(result.returncode == 0, "SDK worker failed: " + result.stderr[-4000:])
        suites = ET.parse(OUT / "pytest.xml").getroot().findall("testsuite")
        totals = {k: sum(int(s.get(k, "0")) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
        require(totals == {"tests": 466, "failures": 0, "errors": 0, "skipped": 0}, "SDK test universe incomplete")
        closure = json.loads((OUT / "python-closure.json").read_text())
        for item in closure["source_snapshot"]:
            require(identity(ROOT / item["path"]) == item, "SDK dependency changed after tests")
            target = OUT / "sources" / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / item["path"]).read_bytes())
        require(audit() == native, "native evidence changed during SDK tests")
        report.update(
            status="SDK_TESTS_EXECUTED_INDEPENDENT_AUDIT_PENDING", test_totals=totals,
            junit=identity(OUT / "pytest.xml"), closure=identity(OUT / "python-closure.json"),
            source_snapshot=closure["source_snapshot"], native_libraries_loaded=closure["native_libraries_loaded"],
            source_snapshot_sha256=hashlib.sha256(json.dumps(closure["source_snapshot"], sort_keys=True).encode()).hexdigest(),
            python_runtime={k: closure[k] for k in ("python", "executable", "numpy", "pytest")},
        )
        print(result.stdout, end="")
    except Exception as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    if parser.parse_args().worker:
        worker()
    else:
        main()
