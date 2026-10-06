"""Audit completed package coverage and the full, current five-layer evidence chain."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from build_completed_rewrite import KINDS
from qualify_completed_rewrites import PROFILES

from tscompbench.adapters import adapter_artifacts
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.reporting import generate_report

ROOT = Path(__file__).resolve().parents[1]
EXISTING = ("chimp", "chimp128", "elf", "elf-plus", "elf-star", "self-star", "prometheus-xor-chunk")
BLOCKED = ("terracodec-flextec", "terracodec-tec-tt")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def run_evidence(name, suffix, refresh):
    path = ROOT / "runs" / f"completed-{name}-formal-{suffix}"
    config = read(path / "frozen_config.json")
    raw = path / "run_components.jsonl"
    raw_hash = sha(raw)
    if refresh:
        generate_report(path, config["reporting"])
        assert sha(raw) == raw_hash, "report regeneration altered raw evidence"
    records = [json.loads(line) for line in raw.read_text().splitlines()]
    tasks = [json.loads(line) for line in (path / "task_plan.jsonl").read_text().splitlines()]
    assert len(tasks) == 1
    count = config["profile"]["repetitions"]
    assert len(records) == count >= 10
    assert {r["repetition_index"] for r in records} == set(range(count))
    assert all(r["correctness"]["status"] == "PASS" for r in records)
    assert all(r["status"] in {"PASS", "RESOURCE_PRESSURE"} for r in records)
    assert all(r["timing"]["min_duration_satisfied"] for r in records)
    assert config["profile"]["warmup_min_count"] >= 3
    assert float(config["profile"]["warmup_min_seconds"]) >= 0.5
    assert float(config["profile"]["min_repetition_seconds"]) >= 1
    with (path / "summary.csv").open() as stream:
        summaries = list(csv.DictReader(stream))
    assert len(summaries) == 1 and int(summaries[0]["n"]) >= 10
    assert int(summaries[0]["n"]) == sum(r["status"] == "PASS" for r in records)
    assert all(
        (path / f"{kind}.csv").is_file()
        for kind in ("coverage", "eligibility", "summary", "runs", "pareto", "ranking")
    )
    assert all(next(path.glob(f"layer{layer}-*.json"), None) for layer in (2, 3, 4, 5))
    assert (path / "report/report.json").is_file() and (path / "report/report.md").is_file()
    task = tasks[0]
    artifacts = []
    for file in sorted(path.rglob("*")):
        if file.is_file():
            artifacts.append({"path": str(file.relative_to(ROOT)), "sha256": sha(file)})
    return {
        "run_path": str(path.relative_to(ROOT)),
        "status": "PASS_WITH_RESOURCE_EXCLUSIONS"
        if any(r["status"] == "RESOURCE_PRESSURE" for r in records)
        else "PASS",
        "record_count": count,
        "summary_n": int(summaries[0]["n"]),
        "resource_excluded_count": sum(r["status"] == "RESOURCE_PRESSURE" for r in records),
        "raw_sha256": raw_hash,
        "task": task,
        "artifacts": artifacts,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suffix", default="acceptance20")
    parser.add_argument("--dzip-suffix", default="acceptance-threads3")
    parser.add_argument("--refresh-reports", action="store_true")
    args = parser.parse_args()
    lock = read(ROOT / "adapters/completed_rewrites/FROZEN_SOURCES.json")
    old_lock = read(ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json")
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    inventory = []
    issues = []
    packages = {name: [name] for name in lock["packages"]}
    packages["prometheus-histogram-st"].append("prometheus-float-histogram-st")
    for name in EXISTING:
        package = old_lock["algorithms"][name]["package"]
        packages.setdefault(package, []).append(name)
    original_root = ROOT / "Compression_Rewrite/ReWrite"
    assert {p.name for p in original_root.iterdir() if p.is_dir()} == set(packages) | set(BLOCKED)
    for package, names in sorted(packages.items()):
        port = original_root / package / "PORT_MANIFEST.yaml"
        assert "REWRITE_DONE" in port.read_text() and "BLOCKED" not in port.read_text()
        entry = {
            "package": package,
            "rewrite_status": "REWRITE_DONE",
            "port_manifest_sha256": sha(port),
            "codecs": [],
        }
        for name in names:
            try:
                manifest = codecs.get(name)
                card = validate_onboarding_card(read(ROOT / "registry/onboarding" / f"{name}.json"))
                assert card["source_artifact_id"] == manifest.source_artifact_id
                primary, supporting = adapter_artifacts(ROOT, manifest)
                assert primary.is_file() and all(p.is_file() for p in supporting)
                if name in KINDS:
                    frozen = lock["packages"][package]
                    assert frozen["port_manifest_sha256"] == sha(port)
                    assert sha(ROOT / frozen["source_manifest"]["path"]) == (
                        frozen["source_manifest"]["sha256"]
                    )
                    for file in frozen["files"]:
                        assert (
                            sha(ROOT / file["path"])
                            == file["sha256"]
                            == sha(ROOT / file["original"])
                        )
                    for profile in ("release", "sanitizer"):
                        folder = ROOT / "build/adapters" / name.replace("-", "_") / profile
                        q = read(folder / "qualification.json")
                        b = read(folder / "build-record.json")
                        assert q["status"] == "PASS"
                        assert q["artifact_sha256"] == sha(ROOT / b["artifact"])
                        assert q["build_record_sha256"] == sha(folder / "build-record.json")
                        assert q["log_sha256"] == sha(ROOT / q["log"])
                else:
                    frozen = old_lock["algorithms"][name]
                    vendor = ROOT / "adapters/rewrite_lossless/vendor" / package
                    origin = read(vendor / "UPSTREAM_PROVENANCE.json")
                    assert origin["standalone_port_manifest_sha256"] == sha(port)
                    for file in frozen["files"]:
                        assert sha(ROOT / file["path"]) == file["sha256"]
                        relative = (ROOT / file["path"]).relative_to(vendor)
                        if relative.parts[0] in {"src", "include"}:
                            assert sha(original_root / package / relative) == file["sha256"]
                    native = read(ROOT / "docs/requested_lossless_native_abi_qualification.json")
                    assert native["status"] == "PASS"
                    case = next(case for case in native["cases"] if case["algorithm"] == name)
                    assert case["status"] == "PASS"
                    for command in case["commands"]:
                        assert command["exit_code"] == 0
                        assert sha(ROOT / command["log"]) == command["log_sha256"]
                evidence = run_evidence(
                    name, args.dzip_suffix if name == "dzip" else args.suffix, args.refresh_reports
                )
                assert evidence["task"]["algorithm_id"] == manifest.algorithm_id
                assert evidence["task"]["execution"]["adapter_id"] == stable_id(
                    "adapter", manifest.document["adapter"]
                )
                components = (
                    {"role": "PRIMARY_ADAPTER", "sha256": sha(primary)},
                    *(
                        {"role": f"SUPPORTING_COMPONENT_{index}", "sha256": sha(file)}
                        for index, file in enumerate(supporting)
                    ),
                )
                current_artifact = (
                    hashlib.sha256(canonical_json_bytes(components)).hexdigest()
                    if supporting
                    else sha(primary)
                )
                assert evidence["task"]["execution"]["artifact_sha256"] == current_artifact, (
                    "frozen execution artifact differs from current source/binary/runtime closure"
                )
                evidence.update(
                    algorithm=name,
                    algorithm_id=manifest.algorithm_id,
                    source_artifact_id=manifest.source_artifact_id,
                    onboarding_id=card["source_onboarding_id"],
                    qualification_scope="REGISTERED_CPU_INDEPENDENT_OBJECT_PROFILE",
                    admitted_input=manifest.document["input"],
                    known_limitations=card["known_limitations"],
                    binary_sha256=sha(primary),
                    integration_status="QUALIFIED",
                )
                output = ROOT / "docs/completed_rewrites" / f"{name}-formal.json"
                output.write_text(json.dumps(evidence, indent=2) + "\n")
                entry["codecs"].append(evidence)
                print(name, "QUALIFIED", "summary n", evidence["summary_n"], flush=True)
            except (AssertionError, OSError, KeyError, ValueError) as error:
                issues.append(
                    {"algorithm": name, "error": str(error) or "evidence assertion failed"}
                )
                entry["codecs"].append(
                    {"algorithm": name, "integration_status": "INCOMPLETE", "error": str(error)}
                )
                print(name, "INCOMPLETE", str(error), flush=True)
        inventory.append(entry)
    excluded = []
    for name in BLOCKED:
        port = original_root / name / "PORT_MANIFEST.yaml"
        assert "BLOCKED" in port.read_text()
        excluded.append(
            {
                "package": name,
                "rewrite_status": "BLOCKED",
                "integrated": False,
                "port_manifest_sha256": sha(port),
                "reason": "Canonical rewrite has not completed its required gates",
            }
        )
    pytest_log = ROOT / "build/completed-rewrites-pytest.log"
    pytest_tail = pytest_log.read_text().splitlines()[-1]
    pytest_result = re.fullmatch(r"=+ (\d+) passed(?:, \d+ warnings)? in .+ =+", pytest_tail)
    assert pytest_result, "full pytest log must end with a successful test summary"
    ruff_log = ROOT / "build/completed-rewrites-ruff.log"
    assert ruff_log.read_text().strip() == "All checks passed!"
    document = {
        "schema_version": "tscb.completed-rewrite-integration-audit.v1",
        "status": "PASS" if not issues else "INCOMPLETE",
        "completed_package_count": len(packages),
        "codec_count": len(PROFILES),
        "new_codec_count": len(KINDS),
        "previous_codec_count": len(EXISTING),
        "blocked_packages": excluded,
        "inventory": inventory,
        "issues": issues,
        "validation": {
            "pytest_log": str(pytest_log.relative_to(ROOT)),
            "pytest_log_sha256": sha(pytest_log),
            "pytest_passed": int(pytest_result.group(1)),
            "ruff_log": str(ruff_log.relative_to(ROOT)),
            "ruff_log_sha256": sha(ruff_log),
            "integration_verifier_sha256": sha(Path(__file__)),
            "source_locks": [
                {"path": str(path.relative_to(ROOT)), "sha256": sha(path)}
                for path in (
                    ROOT / "adapters/completed_rewrites/FROZEN_SOURCES.json",
                    ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json",
                )
            ],
        },
        "normative_references": [
            {"path": p, "sha256": sha(ROOT / p)}
            for p in (
                "TimeSeries_Compression_Benchmark_V2_工程实施总计划.md",
                "Compression_Algorithm_CPP_Porting_Standard_v2.0.md",
            )
        ],
        "qualification_claim": (
            "Only the explicitly registered input/runtime profiles; "
            "not every upstream capability or real-world performance"
        ),
        "statistics_policy": (
            "All planned observations retained; minimum ten eligible PASS; "
            "failures excluded from statistics and retained in Coverage"
        ),
    }
    destination = ROOT / "docs/completed_rewrite_integration_audit.json"
    destination.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    raise SystemExit(bool(issues))


if __name__ == "__main__":
    main()
