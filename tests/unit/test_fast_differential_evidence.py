"""Completed qualification must stop being usable after any consumed input drifts."""

from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT = runpy.run_path(str(ROOT / "tools/audit_fast_differential_native.py"))["audit"]


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    paths = {
        "adapters/fast_differential/SOURCE_LOCK.json",
        "adapters/fast_differential/tests/run_source_tests.py",
        "adapters/fast_differential/tests/run_native_tests.py",
        "adapters/fast_differential/tests/source_guard.c",
        "adapters/fast_differential/tests/abi_qualification.c",
        "tests/native/native_timing_smoke.c",
        "build/source-audits/fast-differential-source-tests.json",
        "build/source-audits/fast-differential-native-tests.json",
    }
    native = json.loads(
        (ROOT / "build/source-audits/fast-differential-native-tests.json").read_text()
    )
    for record in native["builds"]:
        directory = "build/adapters/fast_differential_u32/" + record["profile"]
        paths.update(
            {
                directory + "/compile-command.json",
                directory + "/build-record.json",
                record["artifact"],
            }
        )
        for field in ("source_files", "binding_sources", "compiled_source_closure", "objects"):
            paths.update(
                item["path"] for item in record[field] if not Path(item["path"]).is_absolute()
            )
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    assert AUDIT(tmp_path)["status"] == "PASS"
    return tmp_path


@pytest.mark.parametrize(
    "target", ["source", "binding", "binary", "command", "compiled", "missing"]
)
def test_native_evidence_refuses_current_dependency_drift(snapshot: Path, target: str) -> None:
    if target == "source":
        path = snapshot / "adapters/fast_differential/vendor/FastDifferentialCoding/src/fastdelta.c"
        path.write_bytes(path.read_bytes() + b"\n/* drift */\n")
    elif target == "binding":
        path = snapshot / "src/tscompbench/adapters/fast_differential.py"
        path.write_bytes(path.read_bytes() + b"\n# drift\n")
    elif target == "binary":
        path = (
            snapshot
            / "build/adapters/fast_differential_u32/release/libtscb_fast_differential_u32.so"
        )
        path.write_bytes(path.read_bytes() + b"drift")
    elif target == "command":
        path = snapshot / "build/adapters/fast_differential_u32/release/compile-command.json"
        document = json.loads(path.read_text())
        document["commands"][0].append("-march=native")
        path.write_text(json.dumps(document))
    elif target == "compiled":
        # Keep qualified/current record equality while invalidating the actual
        # compiler-discovered closure. This must fail the dependency hash check.
        path = snapshot / "build/source-audits/fast-differential-native-tests.json"
        report = json.loads(path.read_text())
        build = next(record for record in report["builds"] if record["profile"] == "release")
        build["compiled_source_closure"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(report))
        path = snapshot / "build/adapters/fast_differential_u32/release/build-record.json"
        path.write_text(json.dumps(build))
    else:
        (snapshot / "src/tscompbench/adapters/fast_differential.py").unlink()
    with pytest.raises((RuntimeError, OSError)):
        AUDIT(snapshot)
