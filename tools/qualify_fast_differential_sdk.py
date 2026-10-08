"""Save direct Python SDK qualification without claiming five-layer admission."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from audit_fast_differential_native import audit, require, sha

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/fast_differential"
OUT = ROOT / "build/source-audits/fast-differential-sdk"
REPORT = ROOT / "build/source-audits/fast-differential-sdk-tests.json"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence: dict = {"status": "RUNNING", "commands": []}

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
        require(result.returncode == 0, "qualification command failed: " + str(command))
        return result.stdout

    save()
    try:
        current = audit()
        evidence["native_current_audit"] = current
        # Recheck the locally available original source rather than trusting its label.
        original = (
            ROOT.parent / "Compression_Source_Code/Source_Code/_repos/lemire_FastDifferentialCoding"
        )
        lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
        require(
            run(["git", "-C", str(original), "rev-parse", "HEAD"]).strip() == lock["commit"],
            "original repository pin drift",
        )
        require(
            not run(["git", "-C", str(original), "status", "--porcelain"]).strip(),
            "original repository dirty",
        )
        require(
            not run(["git", "-C", str(original), "submodule", "status"]).strip(),
            "unexpected original submodules",
        )
        for item in lock["files"]:
            relative = Path(item["path"]).relative_to(
                "adapters/fast_differential/vendor/FastDifferentialCoding"
            )
            require(sha(original / relative) == item["sha256"], "original/vendor divergence")
        junit = OUT / "pytest.xml"
        test = ROOT / "tests/adapters/test_fast_differential.py"
        stdout = run([sys.executable, "-m", "pytest", str(test), "-q", "--junitxml=" + str(junit)])
        suites = ET.parse(junit).getroot().findall("testsuite")
        totals = {
            field: sum(int(suite.get(field, "0")) for suite in suites)
            for field in ("tests", "failures", "errors", "skipped")
        }
        require(
            totals["tests"] >= 103
            and all(totals[key] == 0 for key in ("failures", "errors", "skipped")),
            "Python SDK qualification incomplete/failed/skipped",
        )
        # Ensure the build that was actually tested still matches all frozen inputs.
        require(audit() == current, "native evidence changed during SDK qualification")
        snapshot = [
            {"path": str(path.relative_to(ROOT)), "sha256": sha(path)}
            for path in (
                test,
                Path(__file__),
                ROOT / "tools/audit_fast_differential_native.py",
                ROOT / "src/tscompbench/adapters/fast_differential.py",
                ROOT / "src/tscompbench/adapters/native_timing.py",
                ROOT / "src/tscompbench/adapters/deflate_zlib.py",
                ROOT / "src/tscompbench/execution/protocol.py",
                ROOT / "src/tscompbench/execution/repetition.py",
            )
        ]
        evidence.update(
            status="PASS",
            classification="DIRECT_PYTHON_SDK_NOT_FIVE_LAYER_ADMISSION",
            junit_sha256=sha(junit),
            test_totals=totals,
            source_repository_unmodified=True,
            original_vendor_equal_file_count=len(lock["files"]),
            source_snapshot=snapshot,
            source_snapshot_sha256=hashlib.sha256(
                json.dumps(snapshot, sort_keys=True).encode()
            ).hexdigest(),
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
    main()
