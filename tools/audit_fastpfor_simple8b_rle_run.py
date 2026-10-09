"""Independently audit actual RLE five-layer execution and serial formal statistics."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import struct
from collections import Counter
from pathlib import Path

import numpy as np

from audit_fastpfor_simple8b_rle_native import audit_build, identity, require, sha, verify
from audit_fastpfor_simple8b_rle_sdk import audit as audit_sdk
from audit_fastpfor_simple_run import configuration_matrix, canonical_matches, audit_rejection
from audit_maskedvbyte_run import COMPONENTS, audit_independent_statistics
from audit_simdcomp_run import audit_common
from streamvbyte_audit_common import audit_summary
from tscompbench.adapters.factory import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id

ROOT = Path(__file__).resolve().parents[1]
KEY = "fastpfor-simple8b-rle-u32"
SCOPE = "SYNTHETIC_UINT32_VALUE_UTS_MARKED_UNMARKED_RLE_ONLY"
PREFIX = struct.Struct("<8sI32s")
WIDTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 30, 60)
COUNTS = (0, 60, 30, 20, 15, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1)


def source_and_runtime(registry: CodecRegistry) -> tuple:
    manifest = registry.get(KEY)
    source = registry.sources.get(manifest.source_artifact_id)
    component = ROOT / "adapters/fastpfor_simple8b_rle"
    lock = json.loads((component / "SOURCE_LOCK.json").read_text())
    patch = json.loads((component / "PATCH_LOCK.json").read_text())
    require(source["identity"]["repository"] == lock["repository"]
            and source["identity"]["commit"] == lock["commit"]
            and source["build"]["source_closure"] == lock["files"]
            and source["identity"]["source_closure_sha256"]
            == hashlib.sha256(canonical_json_bytes(lock["files"])).hexdigest()
            and source["identity"]["patch_series"] == source["build"]["patches"] == [patch["patch"]]
            and source["build"]["submodules"] == []
            and source["license"]["status"] == "RUN_ALLOWED"
            and source["license"]["spdx"] == "Apache-2.0", "source/license/patch identity differs")
    for item in lock["files"] + [patch["patch"]]:
        verify(item)
    card = validate_onboarding_card(json.loads((ROOT / f"registry/onboarding/{KEY}.json").read_text()))
    require(card["source_artifact_id"] == manifest.source_artifact_id
            and card["repository"] == lock["repository"] and card["commit"] == lock["commit"]
            and card["input_contract"]["value_maximum"] == 2**32 - 1
            and card["input_contract"]["external_padding_bytes"] == 0
            and {b["kind"] for b in card["builds"]} == {"release", "debug", "sanitizer"}
            and len(card["builds"]) == 3, "onboarding scope/build matrix differs")
    for test in card["upstream_tests"]:
        require(test["status"] == "PASS" and sha(ROOT / test["evidence"]) == test["log_sha256"],
                "onboarding execution evidence stale")
    for build in card["builds"]:
        audit_build(build["kind"])
        record = json.loads((ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2"
                            / build["kind"] / "build-record.json").read_text())
        require(build["artifact_sha256"] == record["artifact"]["sha256"]
                and build["compile_commands_sha256"] == hashlib.sha256(canonical_json_bytes(
                    [i["command"] for i in record["commands"]])).hexdigest(), "onboarding build stale")
    artifact, supports = adapter_artifacts(ROOT, manifest)
    runtime = hashlib.sha256(canonical_json_bytes([
        {"role": "PRIMARY_ADAPTER", "sha256": sha(artifact)},
        *[{"role": f"SUPPORTING_COMPONENT_{i}", "sha256": sha(p)} for i, p in enumerate(supports)],
    ])).hexdigest()
    return manifest, source, runtime


def independent_frame(stream: bytes, params: dict, original: np.ndarray) -> dict:
    """Reconstruct every source bit without production codec/scanner/ledger calls."""
    require(len(stream) >= PREFIX.size + 40, "truncated complete stream")
    magic, length, digest = PREFIX.unpack_from(stream)
    require(magic == b"TSCB8BC1" and length <= 4096, "wrong RLE stream prefix")
    header = stream[PREFIX.size:PREFIX.size + length]
    require(hashlib.sha256(header).digest() == digest, "descriptor checksum differs")
    expected = {
        "schema_version": "tscb.simple8b-rle-container.v1", "algorithm": KEY,
        "track": "VALUE", "count": len(original),
        "parameters": {"codec": "SIMPLE8B_RLE", "isa": "SCALAR", "mark_length": params["mark_length"]},
        "timestamp_unit": "NOT_APPLICABLE", "timestamp_epoch": "NOT_APPLICABLE", "value_units": ["count"],
        "buffer": {"name": "value/000000", "dtype": "<u4", "shape": [len(original)],
                   "logical_bits": original.nbytes * 8},
    }
    require(header == canonical_json_bytes(expected), "RLE descriptor semantics differ")
    values = [int(v) for v in original]
    at = value_bits = padding_bits = run_bits = 0
    words = []
    while at < len(values):
        run = 1
        while at + run < len(values) and values[at + run] == values[at]:
            run += 1
        if (values[at] | 1).bit_length() * run >= 60:
            run = min(run, (1 << 28) - 1)
            words.append((15 << 60) | (run << 32) | values[at])
            value_bits += 32
            run_bits += 28
            at += run
            continue
        for selector in range(1, 15):
            part, width = values[at:at + COUNTS[selector]], WIDTHS[selector]
            if any(v.bit_length() > width for v in part):
                continue
            word = selector << 60
            for i, value in enumerate(part):
                for bit in range(min(width, 32)):
                    if value >> bit & 1:
                        word |= 1 << (i * width + bit)
            words.append(word)
            value_bits += len(part) * min(width, 32)
            padding_bits += 60 - len(part) * min(width, 32)
            at += len(part)
            break
        else:
            raise ValueError("uint32 source domain not represented")
    marked = int(params["mark_length"])
    frame = struct.pack("<8s6I", b"TSCB8BR1", len(values), 0, marked, 2 * len(words) + marked, 0, 0)
    if marked:
        frame += struct.pack("<I", len(values))
    frame += b"".join(struct.pack("<Q", word) for word in words)
    checksum = 14695981039346656037
    for byte in frame:
        checksum = ((checksum ^ byte) * 1099511628211) & ((1 << 64) - 1)
    frame += struct.pack("<Q", checksum)
    require(stream[PREFIX.size + length:] == frame, "independent RLE source wire differs")
    return {"value_bits": value_bits, "padding_bits": padding_bits,
            "metadata_bits": length * 8 + 192 + marked * 32 + len(words) * 4 + run_bits,
            "container_bits": 160, "checksum_bits": 320,
            "payload_bytes": len(frame) - 40, "header_bytes": length}


def audit_telemetry(record: dict, params: dict, physical: dict, raw: int) -> None:
    telemetry, timing = record["diagnostics"]["codec_telemetry"], record["timing"]
    require(telemetry["scope"] == "LAST_INNER_ITERATION"
            and telemetry["observed_iteration_index"] == timing["inner_iterations"] - 1,
            "telemetry scope differs")
    payload, n = physical["payload_bytes"], raw // 4
    for direction in ("encode", "decode"):
        data, encode = telemetry[direction], direction == "encode"
        expected = {
            "actual_original_api": f"FastPForLib::{direction}Array", "codec_variant": 0,
            "mark_length": params["mark_length"], "scope": f"ONE_{direction.upper()}_OBJECT",
            "native_payload_bytes": payload, "native_raw_bytes": raw,
            "native_staging_allocation_count": 2, "internal_padding_bytes": 0,
            "native_staging_allocation_bytes": (
                (max(n, 1) + max(2 * n + int(params["mark_length"]), 1)) * 4 if encode
                else max(payload, 4) + max(n, 1) * 4),
            "native_staging_input_copy_bytes": raw if encode else payload,
            "native_staging_output_copy_bytes": payload if encode else raw,
            "python_payload_copy_bytes": 0, "included_in_native_api_timing": False,
            "is_peak_rss_measurement": False, "cost_scope": "CORE_PIPELINE",
        }
        require(all(data[k] == v for k, v in expected.items()), "RLE API/staging telemetry differs")
        require(data.get("gather_bytes", 0) == 0
                and (encode or data["python_descriptor_copy_bytes"] == physical["header_bytes"]),
                "unexpected Python gather/descriptor copy")


def audit_measurement(
    record: dict,
    task: dict,
    params: dict,
    physical: dict,
    stream: bytes,
    raw: int,
    formal: bool,
) -> None:
    require(
        all(record[k] == task[k] for k in ("algorithm_id", "dataset_id", "config_id", "track"))
        and record["execution_path_hash"] == task["execution"]["execution_path_hash"]
        and record["correctness"]["status"] == "PASS"
        and record["diagnostics"]["same_repetition_correctness_and_measurement"]
        and record["finalize_bytes"] == 0,
        "same-repetition identity/correctness differs",
    )
    if record["status"] == "RESOURCE_PRESSURE":
        require(
            formal
            and not record["eligibility"]
            and record["resources"]["swap_observed"]
            and record["reason_code"] == "SWAP_OBSERVED_DURING_FORMAL_REPETITION",
            "unexplained resource pressure",
        )
    else:
        require(
            record["status"] == "PASS" and record["eligibility"] is formal,
            "failed/qualification attempt admitted",
        )
    ledger, timing = record["accounting"], record["timing"]
    require(
        record["diagnostics"]["measurement_policy"]["measurement_mode"]
        == ("FORMAL" if formal else "QUALIFICATION"),
        "record measurement mode differs",
    )
    require(
        sum(ledger[k] for k in COMPONENTS)
        == ledger["serialized_bits"]
        == ledger["final_bits"]
        == len(stream) * 8
        and ledger["final_physical_bytes"] == len(stream)
        and ledger["canonical_raw_bits"] == raw * 8
        and ledger["external_side_information_bits"] == ledger["timestamp_bits"] == 0,
        "physical accounting does not close",
    )
    require(
        all(
            ledger[k] == physical[k]
            for k in (
                "value_bits",
                "padding_bits",
                "metadata_bits",
                "container_bits",
                "checksum_bits",
            )
        ),
        "independent selector billing differs",
    )
    require(
        timing["native_timing_enabled"] is params["native_timing"]
        and timing["native_input_bytes_per_iteration"] == raw
        and timing["canonical_bytes_per_iteration"] == raw
        and timing["codec_input_bytes_per_iteration"] == raw
        and timing["pipeline_stage_timings"] is None,
        "timer/denominator/hidden stage differs",
    )
    if formal:
        require(
            timing["selected_encode_wall_ns"] >= 10**9
            and timing["selected_decode_wall_ns"] >= 10**9
            and timing["min_duration_satisfied"],
            "formal duration insufficient",
        )
    for direction in ("encode", "decode"):
        require(
            0
            < timing[f"core_{direction}_wall_ns"]
            <= timing[f"pipeline_{direction}_wall_ns"]
            == timing[f"selected_{direction}_wall_ns"],
            "timing boundaries differ",
        )
        if params["native_timing"]:
            require(
                0 < timing[f"native_{direction}_wall_ns"] <= timing[f"core_{direction}_wall_ns"]
                and timing["native_timing_clock"] == "CLOCK_MONOTONIC"
                and timing["native_timing_boundary"] == "CODEC_API_ONLY_V1",
                "native timing invalid",
            )
        else:
            require(
                timing[f"native_{direction}_wall_ns"] is None
                and timing[f"native_{direction}_mb_per_second"] is None
                and timing["native_timing_clock"] is timing["native_timing_boundary"] is None,
                "disabled timer falsely measured",
            )
    audit_telemetry(record, params, physical, raw)


def audit_supported(
    run: Path, manifest, source: dict, runtime: str, original: np.ndarray, formal: bool
) -> dict:
    tasks, records, report = audit_common(run, manifest, source, runtime)
    configs = configuration_matrix(run, manifest)
    require(
        len(tasks) == 4 and {t["config_id"] for t in tasks} == set(configs),
        "supported task universe incomplete",
    )
    profile = json.loads((run / "frozen_config.json").read_text())["profile"]
    repeats = 20 if formal else 1
    require(
        profile["measurement_mode"] == ("FORMAL" if formal else "QUALIFICATION")
        and profile["repetitions"] == repeats
        and profile["timing_scope"] == "PIPELINE"
        and profile["threads"] == profile["processes"] == 1
        and profile["cpu_affinity"] == ([0] if formal else [2]),
        "measurement policy differs",
    )
    if formal:
        require(
            profile["cpu_affinity"] == [0]
            and profile["warmup_min_count"] >= 3
            and float(profile["warmup_min_seconds"]) >= 0.5
            and float(profile["min_repetition_seconds"]) >= 1,
            "formal affinity/warmup policy differs",
        )
    require(len(records) == 4 * repeats, "measured attempt universe incomplete")
    streams = {}
    for task in tasks:
        params, execution = configs[task["config_id"]], task["execution"]
        attempts = [r for r in records if r["task_id"] == task["task_id"]]
        require(
            len(attempts) == repeats
            and {r["repetition_index"] for r in attempts} == set(range(repeats))
            and task["track"] == "VALUE"
            and task["preprocess"]["stages"] == []
            and task["compatibility"]["operations"] == []
            and task["status"] == execution["status"] == "PLANNED"
            and execution["actual_isa"] == execution["requested_isa"] == "SCALAR"
            and execution["fallback_used"] is execution["runtime_dispatch"] is False
            and execution["cpu_affinity"] == ([0] if formal else [2]),
            "supported task path/attempts differ",
        )
        if formal:
            require(
                execution["cpu_affinity"] == [0] and sum(r["eligibility"] for r in attempts) >= 10,
                "actual CPU/eligible attempt count differs",
            )
        preflight = json.loads(
            (run / "preflight" / (task["task_id"].rsplit(":", 1)[-1] + ".json")).read_text()
        )
        require(
            preflight["status"] == "PASS"
            and preflight["eligible_for_formal_repetitions"]
            and preflight["correctness"]["status"] == "PASS"
            and preflight["boundary"]["passed"]
            and preflight["boundary"]["required_case_count"]
            == len(preflight["boundary"]["observations"])
            and all(o["status"] == "PASS" for o in preflight["boundary"]["observations"])
            and preflight["diagnostics"].get("preprocess_stage_validation") is None,
            "preflight/boundary evidence missing",
        )
        require(len({r["bitstream_sha256"] for r in attempts}) == 1, "nondeterministic streams")
        stream = None
        for record in attempts:
            path = run / "artifacts" / (record["run_id"].rsplit(":", 1)[-1] + ".bin")
            require(sha(path) == record["bitstream_sha256"], "attempt stream hash differs")
            stream = path.read_bytes() if stream is None else stream
        physical = independent_frame(stream, params, original)
        marked = str(params["mark_length"])
        require(
            marked not in streams or streams[marked] == attempts[0]["bitstream_sha256"],
            "timer changes stream bytes",
        )
        streams[marked] = attempts[0]["bitstream_sha256"]
        session = create_adapter(ROOT, manifest).create_session(
            dict(params, mark_length=not params["mark_length"], native_timing=False)
        )
        try:
            require(
                session.decompress(stream).buffers[0].array.tobytes() == original.tobytes(),
                "fresh differently configured decoder differs",
            )
        finally:
            session.close()
        for record in attempts:
            audit_measurement(
                record, task, params, physical, stream, original.nbytes, formal
            )
    require(
        {p.name for p in (run / "artifacts").glob("*.bin")}
        == {r["run_id"].rsplit(":", 1)[-1] + ".bin" for r in records},
        "missing/unclaimed stream artifacts",
    )
    warmups = [json.loads(p.read_text()) for p in (run / "warmup").glob("*.json")]
    require(len(warmups) == 4, "warmup universe incomplete")
    if formal:
        require(
            all(
                w["threshold_satisfied"]
                and w["completed_iterations"] >= 3
                and w["elapsed_wall_ns"] >= 500_000_000
                for w in warmups
            ),
            "formal warmup insufficient",
        )
        require(report["summary_count"] == 4, "formal summary universe incomplete")
        audit_summary(run)
        for summary in report["summaries"]:
            accepted = [
                r for r in records if r["config_id"] == summary["config_id"] and r["eligibility"]
            ]
            accepted.sort(key=lambda r: r["repetition_index"])
            require(
                len({r["execution_path_hash"] for r in accepted}) == 1
                and summary["execution_path_hash"] == accepted[0]["execution_path_hash"],
                "summary mixes execution paths",
            )
            group = {
                k: summary[k]
                for k in (
                    "run_set_id",
                    "dataset_id",
                    "algorithm_id",
                    "config_id",
                    "execution_path_hash",
                    "profile_id",
                    "run_record_schema",
                )
            }
            require(
                summary["summary_id"]
                == stable_id("summary", {**group, "run_ids": [r["run_id"] for r in accepted]}),
                "summary identity differs",
            )
            audit_independent_statistics(summary, accepted, report["policy"])
    else:
        require(report["summary_count"] == 0, "qualification entered ranking")
    return {
        "records": len(records),
        "eligible": sum(r["eligibility"] for r in records),
        "statuses": dict(Counter(r["status"] for r in records)),
        "streams": streams,
    }


def audit_driver(phase: str, sdk: dict, suffix: str = "20261007-2", report_path: Path | None = None) -> dict:
    path = report_path or ROOT / "build/source-audits" / f"fastpfor-simple8b-rle-{phase}-{suffix}/report.json"
    document = json.loads(path.read_text())
    require(document["status"] == "FIVE_LAYER_RUNS_EXECUTED_INDEPENDENT_AUDIT_PENDING"
            and document["phase"] == phase and document["scope"] == SCOPE
            and document["sdk_current_audit"] == sdk and document["full_logical_entry_qualified"] is False
            and document["independent_run_audit"] == "PENDING"
            and document["actual_cpu_affinity"] == ([0] if phase == "formal" else [2]),
            "RLE execution driver evidence incomplete/stale")
    driver = verify(document["driver"], ROOT / "tools/qualify_fastpfor_simple8b_rle_benchmark.py")
    snapshot = verify(document["driver_snapshot"])
    require(driver.read_bytes() == snapshot.read_bytes(), "RLE executed driver snapshot differs")
    out = snapshot.parent
    closure = document["actual_python_source_closure"]
    paths = {item["path"] for item in closure}
    require(len(paths) == len(closure) and {
        "src/tscompbench/runner.py", "src/tscompbench/adapters/factory.py",
        "src/tscompbench/adapters/fastpfor_simple8b_rle.py", "src/tscompbench/adapters/fastpfor_simple.py",
        "src/tscompbench/execution/preflight.py", "src/tscompbench/execution/repetition.py",
        "src/tscompbench/statistics/engine.py", "src/tscompbench/reporting/generator.py",
        "tools/qualify_fastpfor_simple8b_rle_benchmark.py",
    } <= paths, "RLE actual Python execution closure incomplete")
    for item in closure:
        source = verify(item)
        require((out / "sources" / item["path"]).read_bytes() == source.read_bytes(),
                "RLE executed Python snapshot differs")
    kinds = {"formal-20"} if phase == "formal" else {"qualification", "unsupported-qualification"}
    require(len(document["runs"]) == len(kinds)
            and {(r["key"], r["kind"]) for r in document["runs"]} == {(KEY, k) for k in kinds},
            "RLE driver run universe incomplete")
    for entry in document["runs"]:
        verify(entry["config"], ROOT / f"configs/experiments/{KEY}-{entry['kind']}.toml")
        require(entry["run_set_id"] == f"{KEY}-{entry['kind']}-{suffix}", "RLE driver run identity differs")
        run = ROOT / "runs" / entry["run_set_id"]
        files = entry["files"]
        require({str(p.relative_to(ROOT)) for p in run.rglob("*") if p.is_file()}
                == {f["path"] for f in files} and len({f["path"] for f in files}) == len(files),
                "RLE persisted file universe differs")
        for item in files:
            verify(item)
    return document


def audit_rejected_run(run: Path, manifest, source: dict, runtime: str) -> dict:
    tasks, records, report = audit_common(run, manifest, source, runtime)
    configs = configuration_matrix(run, manifest)
    expected = set(itertools.product(configs, ("VALUE", "TIMESTAMP")))
    require(len(tasks) == len(records) == len(expected)
            and {(t["config_id"], t["track"]) for t in tasks} == expected
            and Counter(r["task_id"] for r in records) == Counter(t["task_id"] for t in tasks),
            "RLE rejection task universe incomplete")
    by_task = {t["task_id"]: t for t in tasks}
    for record in records:
        task = by_task[record["task_id"]]
        audit_rejection(record, task, False)
        require(task["compatibility"]["input_descriptor"]["dtype_vector"]
                == (["<i8"] if task["track"] == "TIMESTAMP" else ["<f8"] * 7),
                "RLE unsupported input silently changed dtype")
    require(not list((run / "artifacts").glob("*.bin"))
            and not list((run / "warmup").glob("*.json"))
            and report["summary_count"] == report["eligible_run_count"] == 0,
            "RLE rejected task produced stream/warmup/ranking")
    return {"records": len(records), "eligible": 0, "statuses": {"UNSUPPORTED": len(records)}}


def driver_report_path(phase: str) -> Path:
    """Resolve the executed receipt selected by the current independent audit."""
    pointer = ROOT / f"build/source-audits/fastpfor_simple8b_rle_{phase}_current_audit.json"
    if pointer.exists():
        document = json.loads(pointer.read_text())
        if document.get("status") == "PASS":
            path = verify(document["driver_evidence"])
            require(path.name == "report.json" and
                    path.parent.parent == ROOT / "build/source-audits" and
                    path.parent.name.startswith(f"fastpfor-simple8b-rle-{phase}-"),
                    "RLE current receipt path differs")
            return path
    return ROOT / f"build/source-audits/fastpfor-simple8b-rle-{phase}-20261007-2/report.json"


def audit_all(phase: str, suffix: str | None = None) -> dict:
    if suffix is None:
        suffix = driver_report_path(phase).parent.name.removeprefix(f"fastpfor-simple8b-rle-{phase}-")
    sdk = audit_sdk()
    driver = audit_driver(phase, sdk, suffix)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest, source, runtime = source_and_runtime(registry)
    dataset = json.loads((ROOT / "registry/datasets/streamvbyte_u32_uts.json").read_text())
    fixture = ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz"
    require(sha(fixture) == dataset["file"]["sha256"], "RLE fixture drift")
    with np.load(fixture, allow_pickle=False) as archive:
        original = archive["values"]
    require(original.dtype.str == "<u4" and original.shape == (8193,)
            and np.any(original >= 2**31), "RLE full uint32 fixture contract differs")
    results = []
    for entry in driver["runs"]:
        require(entry["algorithm_id"] == manifest.algorithm_id
                and entry["source_artifact_id"] == manifest.source_artifact_id, "RLE driver registration differs")
        run = ROOT / "runs" / entry["run_set_id"]
        if entry["kind"] == "unsupported-qualification":
            result = audit_rejected_run(run, manifest, source, runtime)
        else:
            canonical_matches(run, original)
            result = audit_supported(run, manifest, source, runtime, original, phase == "formal")
        require(result["records"] == entry["record_count"] and result["eligible"] == entry["eligible_count"]
                and result["statuses"] == entry["statuses"], "RLE driver counts differ")
        results.append({"key": KEY, "kind": entry["kind"], "run_set_id": entry["run_set_id"], **result})
    if phase == "formal":
        qualification = audit_all("qualification", suffix)
        require(results[0]["streams"] == qualification["runs"][0]["streams"],
                "RLE formal/qualification wire differs")
    dependencies = ("tools/audit_fastpfor_simple8b_rle_sdk.py", "tools/audit_fastpfor_simple_run.py",
                    "tools/audit_simdcomp_run.py", "tools/audit_maskedvbyte_run.py", "tools/streamvbyte_audit_common.py")
    return {"status": "PASS", "phase": phase, "scope": SCOPE, "runs": results,
            "records": sum(r["records"] for r in results), "eligible": sum(r["eligible"] for r in results),
            "benchmark_registration": "QUALIFIED_SCOPED_UINT32_ONLY",
            "benchmark_five_layers": "QUALIFIED_SYNTHETIC_UINT32_ONLY",
            "formal_measurement": "QUALIFIED_SYNTHETIC_UINT32_ONLY" if phase == "formal" else "PENDING",
            "full_logical_entry_qualified": False, "other_datasets_and_domains": "PENDING",
            "sdk_evidence": sdk, "auditor_sha256": sha(Path(__file__)),
            "audit_dependencies": [identity(ROOT / p) for p in dependencies],
            "driver_evidence": identity(ROOT / "build/source-audits" / f"fastpfor-simple8b-rle-{phase}-{suffix}/report.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("qualification", "formal"), required=True)
    parser.add_argument("--suffix", default="20261007-2")
    args = parser.parse_args()
    path = ROOT / f"build/source-audits/fastpfor_simple8b_rle_{args.phase}_current_audit.json"
    try:
        result = audit_all(args.phase, args.suffix)
    except Exception as error:
        path.write_text(json.dumps({"status": "FAIL", "phase": args.phase, "scope": SCOPE,
                                    "full_logical_entry_qualified": False, "error": str(error)}, indent=2) + "\n")
        raise
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "phase", "scope", "records", "eligible",
                                            "full_logical_entry_qualified")}, indent=2))


if __name__ == "__main__":
    main()
