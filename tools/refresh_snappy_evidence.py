"""Rebuild and qualify current Snappy identity; retain a hash-bound audit report.

This generates evidence without silently changing the onboarding card. After
reviewing/updating that card, --verify-card checks both profiles and run evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from tscompbench.adapters import adapter_artifacts
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/snappy_raw_evidence_refresh.json"
CARD = ROOT / "registry/onboarding/snappy-raw.json"
SOURCE = ROOT / "registry/sources/snappy-raw-lzbench.artifact.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def current_manifest():
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")).get(
        "snappy-raw"
    )


def verify_runs(manifest, run_ids):
    evidence, summaries = {}, {}
    artifact, modules = adapter_artifacts(ROOT, manifest)
    # This is the same artifact+Python-support digest used by task planning.
    components = [{"role": "PRIMARY_ADAPTER", "sha256": sha(artifact)}]
    components.extend(
        {"role": f"SUPPORTING_COMPONENT_{index}", "sha256": sha(path)}
        for index, path in enumerate(modules)
    )
    expected_digest = hashlib.sha256(canonical_json_bytes(components)).hexdigest()
    for mode, run_id in run_ids.items():
        directory = ROOT / "runs" / run_id
        records = rows(directory / "run_components.jsonl")
        expected = 10 if mode == "formal" else 1
        assert len(records) == expected
        assert len({r["run_id"] for r in records}) == expected
        assert {r["repetition_index"] for r in records} == set(range(expected))
        for r in records:
            assert r["algorithm_id"] == manifest.algorithm_id
            assert r["correctness"]["status"] == "PASS"
            assert r["status"] in {"PASS", "RESOURCE_PRESSURE"}
            if r["status"] == "RESOURCE_PRESSURE":
                assert mode == "formal" and not r["eligibility"]
                assert r["reason_code"] == "SWAP_OBSERVED_DURING_FORMAL_REPETITION"
            assert r["finalize_bytes"] == 0
            assert r["accounting"]["final_bits"] == r["accounting"]["final_physical_bytes"] * 8
            assert r["diagnostics"]["same_repetition_correctness_and_measurement"]
            assert r["diagnostics"]["measurement_policy"]["measurement_mode"] == mode.upper()
            for operation in ("encode", "decode"):
                t = r["timing"]
                assert 0 < t[f"native_{operation}_wall_ns"] <= t[f"core_{operation}_wall_ns"]
            if mode == "formal":
                assert r["timing"]["min_duration_satisfied"]
                assert r["timing"]["selected_wall_ns"] >= 1_000_000_000
            else:
                assert not r["eligibility"]
        (task,) = rows(directory / "task_plan.jsonl")
        assert task["algorithm_id"] == manifest.algorithm_id
        assert task["execution"]["artifact_sha256"] == expected_digest
        boundary = json.loads(
            (directory / "preflight" / (task["task_id"].split(":")[-1] + ".json")).read_text()
        )
        assert boundary["status"] == "PASS"
        observations = boundary["boundary"]["observations"]
        assert observations and all(r["status"] == "PASS" for r in observations)
        events = rows(directory / "events.jsonl")
        (summary,) = [e["payload"] for e in events if e["event_type"] == "LAYER_5_COMPLETED"]
        full_formal = mode == "formal" and all(
            r["status"] == "PASS" and r["eligibility"] for r in records
        )
        assert summary["summary_count"] == (1 if full_formal else 0)
        assert summary["eligible_run_count"] == (10 if full_formal else 0)
        if mode == "formal":
            (warmup,) = [e["payload"] for e in events if e["event_type"] == "TASK_WARMUP_COMPLETED"]
            assert warmup["completed_iterations"] >= 3 and warmup["elapsed_wall_ns"] >= 500_000_000
        for name in (
            "run_components.jsonl",
            "task_plan.jsonl",
            "codec_registry_snapshot.json",
            "events.jsonl",
            "summary.csv",
        ):
            path = directory / name
            evidence[str(path.relative_to(ROOT))] = sha(path)
        summaries[mode] = dict(
            run_set_id=run_id,
            status="PASS" if mode == "qualification" or full_formal else "RESOURCE_PRESSURE",
            correctness_passed=expected,
            passed=sum(r["status"] == "PASS" for r in records),
            raw_eligible_repetitions=sum(bool(r["eligibility"]) for r in records),
            resource_pressure_repetitions=sum(r["status"] == "RESOURCE_PRESSURE" for r in records),
            eligible=summary["eligible_run_count"],
            boundary_observations=len(observations),
            report=summary,
            combined_artifact_sha256=expected_digest,
        )
    return summaries, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-card", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT,
        help="Versioned evidence output; existing reports are never overwritten",
    )
    parser.add_argument(
        "--resume-checkpoint",
        action="store_true",
        help="Audit saved command outputs and runs without rebuilding or rerunning",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(
            "/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/inikep_lzbench"
        ),
    )
    args = parser.parse_args()
    report_path = args.report.resolve()
    manifest = current_manifest()
    if args.verify_card:
        report = json.loads(report_path.read_text())
        card = validate_onboarding_card(json.loads(CARD.read_text()))
        assert report["status"] == "PASS"
        assert (
            card["source_artifact_id"]
            == manifest.source_artifact_id
            == report["source_artifact_id"]
        )
        assert report["algorithm_id"] == manifest.algorithm_id
        for relative, digest in report["evidence_sha256"].items():
            assert sha(ROOT / relative) == digest, relative
        for build in report["builds"]:
            assert any(
                b["artifact_sha256"] == build["artifact_sha256"]
                and b["compile_commands_sha256"] == build["compile_commands_sha256"]
                for b in card["builds"]
            )
        verify_runs(manifest, {k: v["run_set_id"] for k, v in report["runs"].items()})
        print(json.dumps({"status": "PASS", "card_builds_and_current_runs": "VERIFIED"}))
        return
    assert not report_path.exists(), (
        "Preserve earlier evidence; choose a new report path for another refresh"
    )
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    commands = []

    checkpoint = ROOT / "build/source-audits/snappy-refresh-commands.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    saved_commands = json.loads(checkpoint.read_text()) if args.resume_checkpoint else []

    def run(command, extra_env=None):
        if args.resume_checkpoint:
            previous = next(r for r in reversed(saved_commands) if r["command"] == command)
            assert previous["returncode"] == 0
            commands.append(previous)
            return previous["output"]
        print("Running: " + " ".join(command), flush=True)
        result = subprocess.run(
            command,
            cwd=ROOT,
            env={**environment, **(extra_env or {})},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
        commands.append(dict(command=command, returncode=result.returncode, output=result.stdout))
        checkpoint.write_text(json.dumps(commands, ensure_ascii=False, indent=2) + "\n")
        print(result.stdout, flush=True)
        if result.returncode:
            raise RuntimeError("Snappy evidence step failed")
        return result.stdout

    prior_card = json.loads(CARD.read_text())
    prior_builds = {
        profile: json.loads(
            (ROOT / f"build/adapters/snappy_raw/{profile}/build-record.json").read_text()
        )
        for profile in ("release", "sanitizer")
    }
    vendor = ROOT / "adapters/snappy_raw/vendor/snappy"
    source = json.loads(SOURCE.read_text())
    assert (
        run(["git", "-C", str(args.source_root), "rev-parse", "HEAD"]).strip()
        == prior_card["commit"]
    )
    assert not run(
        ["git", "-C", str(args.source_root), "status", "--porcelain", "--", "lz/snappy"]
    ).strip()
    closure = hashlib.sha256()
    evidence = {}
    for path in sorted(p for p in vendor.rglob("*") if p.is_file()):
        relative = path.relative_to(vendor)
        assert path.read_bytes() == (args.source_root / "lz/snappy" / relative).read_bytes()
        closure.update(relative.as_posix().encode() + b"\0" + path.read_bytes())
        evidence[str(path.relative_to(ROOT))] = sha(path)
    # The legacy source card doesn't specify its digest serialization. Verify
    # every retained file against the pinned clean checkout and record an
    # explicit path-NUL-content inventory; don't relabel its old digest.
    run([sys.executable, "tools/build_codec.py", "snappy-raw", "--profile", "all"])
    builds = []
    for profile in ("release", "sanitizer"):
        directory = ROOT / f"build/adapters/snappy_raw/{profile}"
        build = json.loads((directory / "build-record.json").read_text())
        assert sha(ROOT / build["artifact"]) == build["artifact_sha256"]
        builds.append(build)
        evidence[build["artifact"]] = build["artifact_sha256"]
        evidence[str((directory / "build-record.json").relative_to(ROOT))] = sha(
            directory / "build-record.json"
        )
        executable = directory / "abi-smoke-refresh"
        command = ["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O1", "-g"]
        if profile == "sanitizer":
            command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
        command += [
            "-I",
            str(ROOT / "native/include"),
            str(ROOT / "adapters/snappy_raw/tests/abi_smoke.cc"),
            "-L",
            str(directory),
            "-ltscb_snappy_raw",
            f"-Wl,-rpath,{directory}",
            "-o",
            str(executable),
        ]
        run(command)
        run(
            [str(executable)],
            {
                "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            },
        )
    run([sys.executable, "-m", "pytest", "-q", "tests/adapters/test_snappy_raw.py"])
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/adapters/test_native_timing.py",
            "-k",
            "snappy_raw",
        ]
    )
    run_ids = {}
    for mode in ("qualification", "formal"):
        config = f"configs/experiments/snappy-raw-{mode}.toml"
        output = run(
            [
                sys.executable,
                "-m",
                "tscompbench",
                "run",
                "validate",
                config,
                "--output-root",
                "runs",
            ]
        )
        run_id = json.loads(output)["run_set_id"]
        run_ids[mode] = run_id
        run(
            [
                sys.executable,
                "-m",
                "tscompbench",
                "run",
                "report",
                config,
                "--output-root",
                "runs",
                "--run-set-id",
                run_id,
                "--resume",
            ]
        )
        if mode == "formal" and not args.resume_checkpoint:
            recorded = rows(ROOT / "runs" / run_id / "run_components.jsonl")
            if any(r["status"] == "RESOURCE_PRESSURE" for r in recorded):
                print("Resource pressure recorded; retain rejected run and retry once.", flush=True)
                output = run(
                    [
                        sys.executable,
                        "-m",
                        "tscompbench",
                        "run",
                        "validate",
                        config,
                        "--output-root",
                        "runs",
                    ]
                )
                run_id = json.loads(output)["run_set_id"]
                run_ids[mode] = run_id
                run(
                    [
                        sys.executable,
                        "-m",
                        "tscompbench",
                        "run",
                        "report",
                        config,
                        "--output-root",
                        "runs",
                        "--run-set-id",
                        run_id,
                        "--resume",
                    ]
                )
    summaries, run_evidence = verify_runs(manifest, run_ids)
    evidence.update(run_evidence)
    for name in (
        "registry/codecs/snappy-raw.json",
        "registry/sources/snappy-raw-lzbench.artifact.json",
        "adapters/snappy_raw/native/tscb_snappy_raw.cc",
        "native/include/tscb_native_timing.h",
        "native/include/tscb_adapter_v1.h",
        "adapters/snappy_raw/tests/abi_smoke.cc",
        "src/tscompbench/adapters/snappy_raw.py",
        "src/tscompbench/adapters/native_timing.py",
        "configs/experiments/snappy-raw-qualification.toml",
        "configs/experiments/snappy-raw-formal.toml",
        "tests/adapters/test_snappy_raw.py",
        "tests/adapters/test_native_timing.py",
    ):
        evidence[name] = sha(ROOT / name)
    result = dict(
        status="PASS",
        audit_scope="Build provenance and correctness evidence; "
        "formal performance status is separate in runs.formal.status",
        generated_at_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        algorithm_id=manifest.algorithm_id,
        source_artifact_id=manifest.source_artifact_id,
        declared_source_closure_sha256=source["identity"]["source_closure_sha256"],
        verified_vendor_inventory_sha256=closure.hexdigest(),
        vendor_inventory_method="sorted relative POSIX path + NUL + file bytes",
        pinned_vendor_files_byte_equal=True,
        previous_card_builds=prior_card["builds"],
        previous_build_records=prior_builds,
        builds=builds,
        release_rebuild_reproduces_previous_hash=builds[0]["artifact_sha256"]
        == prior_builds["release"]["artifact_sha256"],
        runs=summaries,
        commands=commands,
        evidence_sha256=evidence,
        limitations=[
            "LeakSanitizer disabled (detect_leaks=0); ASan/UBSan enabled.",
            "Formal run covers national_illness VALUE only, not all datasets/parameters.",
            "Formal attempts with system swap retain RESOURCE_PRESSURE; "
            "correctness PASS does not promote their performance eligibility.",
            "Raw stream, scalar CPU and single thread; "
            "no framed/streaming/query/checksum capability added.",
        ],
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {"status": "PASS", "report": str(report_path.relative_to(ROOT)), "runs": run_ids}
        )
    )


if __name__ == "__main__":
    main()
