"""Reject incomplete, forged-success or drifted SIMDComp source qualification evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "simdcomp_auditor", ROOT / "tools/audit_simdcomp_source.py"
)
auditor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auditor)


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    # Read-only links avoid copying large objects. Every tamper unlinks its private
    # path first, so no original source, binary or report can be modified.
    for relative in ("adapters/simdcomp", "build/source-audits/simdcomp-upstream"):
        shutil.copytree(
            ROOT / relative,
            tmp_path / relative,
            copy_function=lambda src, dst: os.symlink(src, dst),
        )
    for relative in ("tools/freeze_simdcomp_source.py", "tools/qualify_simdcomp_upstream.py"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(ROOT / relative)
    for path in (ROOT / "build/source-audits").glob("simdcomp-*-*.json"):
        target = tmp_path / "build/source-audits" / path.name
        target.write_bytes(path.read_bytes())
    return tmp_path


def replace(path: Path, content: bytes) -> None:
    path.unlink()
    path.write_bytes(content)


def mutate(path: Path, function) -> None:
    document = json.loads(path.read_text())
    function(document)
    path.write_text(json.dumps(document, indent=2) + "\n")


def test_current_complete_source_evidence(evidence: Path) -> None:
    result = auditor.audit(evidence)
    assert result["status"] == "PASS"
    assert result["original_failures_retained"] == 13
    assert result["bounded_abi"] == result["benchmark_five_layers"] == "PENDING"
    assert not result["full_logical_entry_qualified"]


@pytest.mark.parametrize(
    "relative",
    [
        "adapters/simdcomp/vendor/simdcomp/src/simdbitpacking.c",
        "adapters/simdcomp/tests/source_guard.c",
        "adapters/simdcomp/tests/run_source_guards.py",
        "adapters/simdcomp/patches/0001-fastset-width32-defined-mask.patch",
        "build/source-audits/simdcomp-upstream/patched/release/source-guard",
        "build/source-audits/simdcomp-upstream/patched-source/src/simdfor.c",
    ],
)
def test_source_patch_or_binary_drift_is_rejected(evidence: Path, relative: str) -> None:
    path = evidence / relative
    replace(path, path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(RuntimeError, match="drift|reproducible"):
        auditor.audit(evidence)


def test_retained_original_failure_cannot_be_relabeled_pass(evidence: Path) -> None:
    path = evidence / "build/source-audits/simdcomp-source-original-guards.json"

    def tamper(document):
        test = next(t for t in document["tests"] if t["mode"] == "query-for")
        test.update(status="PASS", returncode=0)

    mutate(path, tamper)
    with pytest.raises(RuntimeError, match="failure.*misreported"):
        auditor.audit(evidence)


def test_a_missing_public_api_path_cannot_qualify(evidence: Path) -> None:
    path = evidence / "build/source-audits/simdcomp-source-patched-guards.json"
    mutate(path, lambda document: document["tests"].pop())
    with pytest.raises(RuntimeError, match="API matrix incomplete"):
        auditor.audit(evidence)


def test_success_label_without_actual_query_coverage_is_rejected(evidence: Path) -> None:
    path = evidence / "build/source-audits/simdcomp-source-patched-guards.json"

    def tamper(document):
        test = next(t for t in document["tests"] if t["mode"] == "query-d1")
        test["stdout"] = test["stdout"].replace("248754", "100")
        observation = next(c for c in document["commands"] if c["command"] == test["command"])
        observation["stdout"] = test["stdout"]

    mutate(path, tamper)
    with pytest.raises(RuntimeError, match="coverage differs"):
        auditor.audit(evidence)


def test_declared_pass_without_command_observation_is_rejected(evidence: Path) -> None:
    path = evidence / "build/source-audits/simdcomp-source-patched-guards.json"
    mutate(
        path,
        lambda document: document.update(
            commands=[c for c in document["commands"] if "-o" in c["command"]]
        ),
    )
    with pytest.raises(RuntimeError, match="command observation missing"):
        auditor.audit(evidence)


def test_native_tuning_cannot_be_labeled_fixed_sse(evidence: Path) -> None:
    report = (
        evidence / "build/source-audits/simdcomp-upstream/patched/release/compile_commands.json"
    )
    commands = json.loads(report.read_text())
    commands[0]["command"] = commands[0]["command"].replace("-march=x86-64", "-march=native")
    replace(report, (json.dumps(commands) + "\n").encode())
    path = evidence / "build/source-audits/simdcomp-upstream-patched-tests.json"

    def tamper(document):
        build = next(b for b in document["builds"] if b["profile"] == "release")
        build["commands"] = commands
        build["compile_commands"]["sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()

    mutate(path, tamper)
    with pytest.raises(RuntimeError, match="ISA/assertion flags differ"):
        auditor.audit(evidence)


def test_compiled_dependency_omission_is_rejected(evidence: Path) -> None:
    path = evidence / "build/source-audits/simdcomp-upstream-patched-tests.json"
    mutate(path, lambda document: document["builds"][0]["compiled_source_closure"].pop())
    with pytest.raises(RuntimeError, match="dependency universe differs"):
        auditor.audit(evidence)


def test_guard_dependency_omission_is_rejected(evidence: Path) -> None:
    path = evidence / "build/source-audits/simdcomp-source-patched-guards.json"
    mutate(path, lambda document: document["builds"][0]["compiled_source_closure"].pop())
    with pytest.raises(RuntimeError, match="guard dependency universe differs"):
        auditor.audit(evidence)


def test_uninstrumented_guard_cannot_be_labeled_sanitized(evidence: Path) -> None:
    path = evidence / "build/source-audits/simdcomp-source-patched-guards.json"

    def tamper(document):
        build = next(b for b in document["builds"] if b["profile"] == "sanitizer")
        command = next(
            c
            for c in document["commands"]
            if c["command"][-2:] == ["-o", build["executable"]["path"]]
        )
        command["command"].remove("-fsanitize=address,undefined")

    mutate(path, tamper)
    with pytest.raises(RuntimeError, match="guard sanitizer instrumentation missing"):
        auditor.audit(evidence)
