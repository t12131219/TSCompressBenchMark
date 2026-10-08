"""Audit LittleIntPacker uint32 five-layer streams, diagnostics and formal statistics."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import struct
from collections import Counter
from pathlib import Path

import numpy as np
from audit_littleintpacker_sdk import audit, require, sha
from audit_maskedvbyte_run import COMPONENTS, audit_independent_statistics
from audit_simdcomp_run import audit_common
from streamvbyte_audit_common import audit_summary

from tscompbench.adapters.factory import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.datasets.canonical import read_canonical
from tscompbench.ids import canonical_json_bytes, stable_id

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("PACK32", "TURBO", "SC", "BMI2", "HORIZONTAL")
KEYS = tuple("littleintpacker-" + variant.lower() + "-u32" for variant in VARIANTS)
ISA_FOR = dict(zip(KEYS, ("SCALAR", "SCALAR", "SCALAR", "AVX2_BMI2", "SSE4_1"), strict=True))
PREFIX = struct.Struct("<8sI32s")
SCOPE = "SYNTHETIC_UINT32_VALUE_UTS_FIXED_AUTO_FIVE_APIS_ONLY"
QUALIFICATION_KINDS = (
    "qualification",
    "unsupported-qualification",
    "source-domain-rejection-qualification",
)


def configuration_matrix(run: Path, manifest, domain: bool = False) -> dict:
    configs = json.loads((run / "resolved_configs.json").read_text())["configs"]
    choices = (
        [("FIXED", width, timer) for width in (0, 1, 31) for timer in (False, True)]
        if domain
        else [(mode, 32, timer) for mode in ("AUTO", "FIXED") for timer in (False, True)]
    )
    require(
        len(configs) == len(choices) and len({c["config_id"] for c in configs}) == len(choices),
        "width/timer configuration universe incomplete",
    )
    require(
        {
            (
                c["parameters"]["width_mode"],
                c["parameters"]["bit_width"],
                c["parameters"]["native_timing"],
            )
            for c in configs
        }
        == set(choices),
        "width/timer matrix differs",
    )
    for config in configs:
        params = config["parameters"]
        require(
            set(params) == {"isa", "width_mode", "bit_width", "native_timing"}
            and params["isa"] == ISA_FOR[manifest.key]
            and type(params["native_timing"]) is bool
            and type(params["bit_width"]) is int
            and config["status"] == "PLANNED",
            "hidden parameters or invalid configuration",
        )
        require(
            config["config_id"]
            == stable_id(
                "config",
                {
                    "algorithm_id": manifest.algorithm_id,
                    "parameters": params,
                    "framework_parameters": config["framework_parameters"],
                    "parameter_schema_version": "tscb.codec-parameters.v2",
                },
            ),
            "ConfigID/default parameters differ",
        )
    return {c["config_id"]: c["parameters"] for c in configs}


def source_and_runtime(registry: CodecRegistry, key: str) -> tuple:
    manifest = registry.get(key)
    source = registry.sources.get(manifest.source_artifact_id)
    lock = json.loads((ROOT / "adapters/littleintpacker/SOURCE_LOCK.json").read_text())
    patch = json.loads((ROOT / "adapters/littleintpacker/PATCH_LOCK.json").read_text())
    closure = source["build"]["source_closure"]
    require(
        source["identity"]["repository"] == lock["repository"]
        and source["identity"]["commit"] == lock["commit"]
        and closure == lock["files"]
        and len(closure) == 14
        and source["identity"]["source_closure_sha256"]
        == hashlib.sha256(canonical_json_bytes(closure)).hexdigest()
        and source["identity"]["patch_series"] == source["build"]["patches"] == [patch["patch"]]
        and source["build"]["submodules"] == []
        and source["license"]["status"] == "RUN_ALLOWED"
        and source["license"]["spdx"] == "Apache-2.0",
        "source/license/patch identity differs",
    )
    for item in closure + source["build"]["patches"]:
        require(sha(ROOT / item["path"]) == item["sha256"], "registered source/patch bytes drift")
    require(
        manifest.document["execution"]["isa"] == [ISA_FOR[key]]
        and manifest.document["execution"].get("required_cpu_flags", [])
        == (["ssse3", "sse4_1"] if key == KEYS[-1] else []),
        "registered ISA requirements differ",
    )
    card = validate_onboarding_card(
        json.loads((ROOT / f"registry/onboarding/{key}.json").read_text())
    )
    require(card["source_artifact_id"] == manifest.source_artifact_id, "onboarding source differs")
    require(
        {b["kind"] for b in card["builds"]} == {"release", "debug", "sanitizer"},
        "onboarding build matrix incomplete",
    )
    for test in card["upstream_tests"]:
        require(
            test["status"] == "PASS" and sha(ROOT / test["evidence"]) == test["log_sha256"],
            "onboarding test evidence stale",
        )
    for build in card["builds"]:
        record = json.loads(
            (ROOT / f"build/adapters/littleintpacker/{build['kind']}/build-record.json").read_text()
        )
        require(
            build["artifact_sha256"] == record["artifact_sha256"]
            and build["compile_commands_sha256"] == record["compile_commands_sha256"],
            "onboarding build stale",
        )
    artifact, supports = adapter_artifacts(ROOT, manifest)
    runtime = hashlib.sha256(
        canonical_json_bytes(
            [
                {"role": "PRIMARY_ADAPTER", "sha256": sha(artifact)},
                *[
                    {"role": f"SUPPORTING_COMPONENT_{i}", "sha256": sha(p)}
                    for i, p in enumerate(supports)
                ],
            ]
        )
    ).hexdigest()
    return manifest, source, runtime


def independent_frame(stream: bytes, params: dict, original: np.ndarray, key: str) -> dict:
    require(len(stream) >= PREFIX.size + 40, "truncated complete stream")
    magic, length, digest = PREFIX.unpack_from(stream)
    require(magic == b"TSCBLPC1" and length <= 4096, "wrong LittleIntPacker stream prefix")
    header = stream[PREFIX.size : PREFIX.size + length]
    require(hashlib.sha256(header).digest() == digest, "descriptor checksum differs")
    expected = {
        "schema_version": "tscb.littleintpacker-container.v1",
        "algorithm": key,
        "track": "VALUE",
        "count": len(original),
        "parameters": {
            "codec": VARIANTS[KEYS.index(key)],
            "isa": ISA_FOR[key],
            "width_mode": params["width_mode"],
            "bit_width": params["bit_width"],
        },
        "timestamp_unit": "NOT_APPLICABLE",
        "timestamp_epoch": "NOT_APPLICABLE",
        "value_units": ["count"],
        "buffer": {
            "name": "value/000000",
            "dtype": "<u4",
            "shape": [len(original)],
            "logical_bits": original.nbytes * 8,
        },
    }
    require(header == canonical_json_bytes(expected), "descriptor semantics differ")
    values = [int(v) for v in original]
    width = (
        max(values, default=0).bit_length()
        if params["width_mode"] == "AUTO"
        else params["bit_width"]
    )
    require(all(v < 2**width for v in values), "fixed width cannot encode source values")
    payload = bytearray((len(values) * width + 7) // 8)
    for index, value in enumerate(values):
        for bit in range(width):
            position = index * width + bit
            payload[position // 8] |= ((value >> bit) & 1) << (position % 8)
    frame = (
        struct.pack(
            "<8s4IQ",
            b"TSCBLIP1",
            len(values),
            KEYS.index(key),
            width,
            int(params["width_mode"] == "AUTO"),
            len(payload),
        )
        + payload
    )
    checksum = 14695981039346656037
    for byte in frame:
        checksum = ((checksum ^ byte) * 1099511628211) % 2**64
    frame += struct.pack("<Q", checksum)
    require(stream[PREFIX.size + length :] == frame, "independent original wire oracle differs")
    return {
        "value_bits": len(values) * width,
        "padding_bits": len(payload) * 8 - len(values) * width,
        "metadata_bits": length * 8 + 192,
        "container_bits": 160,
        "checksum_bits": 320,
        "payload_bytes": len(payload),
        "header_bytes": length,
        "actual_width": width,
    }


def audit_telemetry(record: dict, params: dict, physical: dict, raw: int, key: str) -> None:
    telemetry, timing = record["diagnostics"]["codec_telemetry"], record["timing"]
    require(
        telemetry["scope"] == "LAST_INNER_ITERATION"
        and telemetry["observed_iteration_index"] == timing["inner_iterations"] - 1,
        "telemetry scope differs",
    )
    payload, n, variant = physical["payload_bytes"], raw // 4, KEYS.index(key)
    packers = ("pack32", "turbopack32", "scpack32", "bmipack32", "pack32")
    unpackers = ("unpack32", "turbounpack32", "scunpack32", "bmiunpack32", "horizontalunpack32")
    for direction in ("encode", "decode"):
        data, encode = telemetry[direction], direction == "encode"
        expected = {
            "actual_original_api": (packers if encode else unpackers)[variant],
            "codec_variant": VARIANTS[variant],
            "actual_isa": "SCALAR" if encode and variant == 4 else ISA_FOR[key],
            "scope": f"ONE_{direction.upper()}_OBJECT",
            "native_api_calls": 1,
            "count": n,
            "bit_width": physical["actual_width"],
            "native_payload_bytes": payload,
            "native_raw_bytes": raw,
            "native_staging_allocation_count": 2,
            "native_staging_allocation_bytes": raw + payload + (264 if encode else 1040),
            "native_staging_input_copy_bytes": raw if encode else payload,
            "native_staging_output_copy_bytes": payload if encode else raw,
            "internal_input_padding_bytes": 128 if encode else 528,
            "internal_output_headroom_bytes": 136 if encode else 512,
            "external_padding_bytes": 0,
            "python_payload_copy_bytes": 0,
            "included_in_native_api_timing": False,
            "is_peak_rss_measurement": False,
            "cost_scope": "CORE_PIPELINE",
        }
        require(
            all(data[k] == v for k, v in expected.items()), "actual API/staging telemetry differs"
        )
        require(
            data.get("gather_bytes", 0) == 0
            and (encode or data["python_descriptor_copy_bytes"] == physical["header_bytes"]),
            "unexpected Python gather/descriptor copy",
        )


def audit_measurement(
    record: dict,
    task: dict,
    params: dict,
    physical: dict,
    stream: bytes,
    raw: int,
    formal: bool,
    key: str,
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
        "independent fixed-width billing differs",
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
    audit_telemetry(record, params, physical, raw, key)


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
        and profile["threads"] == profile["processes"] == 1,
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
            and execution["actual_isa"] == execution["requested_isa"] == ISA_FOR[manifest.key]
            and execution["fallback_used"] is execution["runtime_dispatch"] is False,
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
        physical = independent_frame(stream, params, original, manifest.key)
        marked = params["width_mode"]
        require(
            marked not in streams or streams[marked] == attempts[0]["bitstream_sha256"],
            "timer changes stream bytes",
        )
        streams[marked] = attempts[0]["bitstream_sha256"]
        session = create_adapter(ROOT, manifest).create_session(
            dict(params, width_mode="FIXED", bit_width=0, native_timing=False)
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
                record, task, params, physical, stream, original.nbytes, formal, manifest.key
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


def audit_rejection(record: dict, task: dict, domain: bool) -> None:
    reason = "SOURCE_DOMAIN_UNSUPPORTED" if domain else "CAPABILITY_MISMATCH"
    require(
        all(record[k] == task[k] for k in ("algorithm_id", "dataset_id", "config_id", "track"))
        and record["execution_path_hash"] == task["execution"]["execution_path_hash"]
        and record["status"] == "UNSUPPORTED"
        and record["reason_code"] == reason
        and record["record_kind"] == "DIAGNOSTIC"
        and record["eligibility"] is False
        and all(
            record[k] is None
            for k in (
                "accounting",
                "bitstream_sha256",
                "correctness",
                "finalize_bytes",
                "repetition_index",
                "resources",
                "timing",
                "workloads",
            )
        ),
        "rejection fabricated measurement/eligibility",
    )
    preflight = record["diagnostics"]["preflight"]
    require(
        preflight["status"] == "UNSUPPORTED"
        and preflight["reason_code"] == reason
        and preflight["eligible_for_formal_repetitions"] is False
        and preflight["correctness"] is preflight["accounting"] is None,
        "rejection preflight fabricated success",
    )
    if domain:
        require(
            task["status"] == "PLANNED"
            and task["track"] == "VALUE"
            and preflight["boundary"]["passed"]
            and preflight["diagnostics"]["exception_type"] == "SourceDomainError"
            and preflight["diagnostics"]["message"] == "LITTLEINTPACKER_SUPPLIED_WIDTH_OUT_OF_RANGE"
            and record["input_sha256"] == preflight["input_validation"]["input_sha256"],
            "source-domain rejection evidence differs",
        )
    else:
        require(
            task["status"] == "UNSUPPORTED"
            and task["reason_code"] == reason
            and task["execution"]["actual_isa"] == "NOT_EXECUTED"
            and preflight["boundary"] is None
            and record["input_sha256"] is None
            and task["compatibility"]["operations"] == []
            and task["compatibility"]["output_descriptor"] is None,
            "capability rejection claims execution/cast",
        )


def canonical_matches(run: Path, original: np.ndarray) -> None:
    paths = list((run / "datasets").glob("*/*.canonical.tscb"))
    require(len(paths) == 1, "Layer1 canonical artifact missing")
    require(
        list(read_canonical(paths[0], include_buffers=True).buffers.values())
        == [original.tobytes()],
        "source/canonical bytes differ",
    )


def audit_rejected_run(run: Path, manifest, source: dict, runtime: str, domain: bool) -> dict:
    tasks, records, report = audit_common(run, manifest, source, runtime)
    configs = configuration_matrix(run, manifest, domain)
    expected = set(itertools.product(configs, ("VALUE",) if domain else ("VALUE", "TIMESTAMP")))
    require(
        len(tasks) == len(records) == len(expected)
        and {(t["config_id"], t["track"]) for t in tasks} == expected
        and Counter(r["task_id"] for r in records) == Counter(t["task_id"] for t in tasks),
        "rejected task universe incomplete",
    )
    by_task = {t["task_id"]: t for t in tasks}
    for record in records:
        task = by_task[record["task_id"]]
        audit_rejection(record, task, domain)
        require(
            task["compatibility"]["input_descriptor"]["dtype_vector"]
            == (["<u4"] if domain else ["<i8"] if task["track"] == "TIMESTAMP" else ["<f8"] * 7),
            "unsupported input silently changed dtype",
        )
    require(
        not list((run / "artifacts").glob("*.bin"))
        and not list((run / "warmup").glob("*.json"))
        and report["summary_count"] == report["eligible_run_count"] == 0,
        "rejected task produced stream/warmup/ranking",
    )
    if domain:
        with np.load(
            ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz", allow_pickle=False
        ) as data:
            original = data["values"]
        require(np.any(original >= 2**31), "source-domain rejection fixture became valid")
        canonical_matches(run, original)
    return {"records": len(records), "eligible": 0, "statuses": {"UNSUPPORTED": len(records)}}


def driver_report_path(phase: str) -> Path:
    current = ROOT / f"build/source-audits/littleintpacker-{phase}-20261007-2/report.json"
    return current if current.exists() else ROOT / f"build/source-audits/littleintpacker_{phase}_five_layer_runs.json"


def audit_driver(phase: str, sdk: dict) -> dict:
    path = driver_report_path(phase)
    document = json.loads(path.read_text())
    if "execution_suffix" in document:
        out = ROOT / document["output_directory"]
        require(out == path.parent
                and document["actual_cpu_affinity"] == ([0] if phase == "formal" else [2])
                and (out / "driver.py").read_bytes()
                == (ROOT / "tools/qualify_littleintpacker_benchmark.py").read_bytes(),
                "five-layer immutable driver/affinity differs")
    require(
        document["status"] == "FIVE_LAYER_RUNS_EXECUTED_INDEPENDENT_AUDIT_PENDING"
        and document["phase"] == phase
        and document["sdk_current_audit"] == sdk
        and document["driver"]["path"] == "tools/qualify_littleintpacker_benchmark.py"
        and document["driver"]["sha256"] == sha(ROOT / document["driver"]["path"])
        and document["qualification_scope"] == SCOPE
        and document["full_logical_entries_qualified"] is False,
        "execution driver evidence stale/incomplete",
    )
    closure = document["actual_python_source_closure"]
    paths = {i["path"] for i in closure}
    require(
        len(paths) == len(closure)
        and {
            "src/tscompbench/runner.py",
            "src/tscompbench/execution/preflight.py",
            "src/tscompbench/execution/repetition.py",
            "src/tscompbench/adapters/littleintpacker.py",
            "src/tscompbench/statistics/engine.py",
            "src/tscompbench/reporting/generator.py",
            "tools/qualify_littleintpacker_benchmark.py",
        }
        <= paths,
        "actual executed Python closure incomplete",
    )
    for item in closure:
        require(sha(ROOT / item["path"]) == item["sha256"], "executed Python source drift")
        if "execution_suffix" in document:
            require((out / "sources" / item["path"]).read_bytes() == (ROOT / item["path"]).read_bytes(),
                    "five-layer frozen source differs")
    kinds = ("formal-20",) if phase == "formal" else QUALIFICATION_KINDS
    require(
        len(document["runs"]) == len(KEYS) * len(kinds)
        and {(r["key"], r["kind"]) for r in document["runs"]}
        == set(itertools.product(KEYS, kinds)),
        "driver run universe incomplete",
    )
    for entry in document["runs"]:
        require(sha(ROOT / entry["config"]["path"]) == entry["config"]["sha256"], "config drift")
        run = ROOT / "runs" / entry["run_set_id"]
        if "execution_suffix" in document:
            require(entry["run_set_id"] == f"{entry['key']}-{entry['kind']}-{document['execution_suffix']}",
                    "five-layer run suffix differs")
        files = entry["files"]
        require(
            {str(p.relative_to(ROOT)) for p in run.rglob("*") if p.is_file()}
            == {f["path"] for f in files}
            and len({f["path"] for f in files}) == len(files),
            "persisted run file universe differs",
        )
        for item in files:
            require(
                sha(ROOT / item["path"]) == item["sha256"], "persisted five-layer artifact drift"
            )
    return document


def audit_all(phase: str) -> dict:
    sdk = audit()
    driver = audit_driver(phase, sdk)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    dataset = json.loads((ROOT / "registry/datasets/streamvbyte_u32_uts.json").read_text())
    fixture = ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz"
    require(sha(fixture) == dataset["file"]["sha256"], "fixture drift")
    with np.load(fixture, allow_pickle=False) as archive:
        original = archive["values"]
    require(
        original.dtype.str == "<u4" and original.shape == (8193,) and np.any(original >= 2**31),
        "synthetic full uint32 fixture contract differs",
    )
    results = []
    for entry in driver["runs"]:
        key, kind = entry["key"], entry["kind"]
        manifest, source, runtime = source_and_runtime(registry, key)
        require(
            entry["algorithm_id"] == manifest.algorithm_id
            and entry["source_artifact_id"] == manifest.source_artifact_id,
            "driver registration identity differs",
        )
        run = ROOT / "runs" / entry["run_set_id"]
        if kind in ("qualification", "formal-20"):
            canonical_matches(run, original)
            result = audit_supported(run, manifest, source, runtime, original, phase == "formal")
        else:
            result = audit_rejected_run(
                run, manifest, source, runtime, kind == "source-domain-rejection-qualification"
            )
        require(
            result["records"] == entry["record_count"]
            and result["eligible"] == entry["eligible_count"]
            and result["statuses"] == entry["statuses"],
            "driver counts differ",
        )
        results.append({"key": key, "kind": kind, "run_set_id": entry["run_set_id"], **result})
    if phase == "formal":
        qualification = audit_all("qualification")
        for result in results:
            previous = next(
                r
                for r in qualification["runs"]
                if r["key"] == result["key"] and r["kind"] == "qualification"
            )
            require(result["streams"] == previous["streams"], "formal/qualification wire differs")
    dependencies = (
        "tools/audit_littleintpacker_sdk.py",
        "tools/audit_simdcomp_run.py",
        "tools/audit_maskedvbyte_run.py",
        "tools/streamvbyte_audit_common.py",
        "tests/adapters/test_littleintpacker.py",
    )
    return {
        "status": "PASS",
        "phase": phase,
        "scope": SCOPE,
        "runs": results,
        "records": sum(r["records"] for r in results),
        "eligible": sum(r["eligible"] for r in results),
        "full_logical_entries_qualified": False,
        "other_datasets_and_domains": "PENDING",
        "sdk_evidence": sdk,
        "auditor_sha256": sha(Path(__file__)),
        "audit_dependencies": [{"path": p, "sha256": sha(ROOT / p)} for p in dependencies],
        "driver_evidence_sha256": sha(driver_report_path(phase)),
        "driver_evidence_path": str(driver_report_path(phase).relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("qualification", "formal"), required=True)
    args = parser.parse_args()
    path = ROOT / f"build/source-audits/littleintpacker_{args.phase}_current_audit.json"
    try:
        result = audit_all(args.phase)
    except Exception as error:
        path.write_text(
            json.dumps(
                {
                    "status": "FAIL",
                    "phase": args.phase,
                    "scope": SCOPE,
                    "full_logical_entries_qualified": False,
                    "error": str(error),
                },
                indent=2,
            )
            + "\n"
        )
        raise
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "phase",
                    "scope",
                    "records",
                    "eligible",
                    "full_logical_entries_qualified",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
