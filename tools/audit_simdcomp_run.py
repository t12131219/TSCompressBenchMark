"""Independently decode actual SIMDComp streams and audit five-layer raw artifacts."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import struct
from collections import Counter
from pathlib import Path

import numpy as np
from audit_maskedvbyte_run import (
    COMPONENTS,
    audit_independent_statistics,
    audit_raw_projection_and_coverage,
    audit_stage_plan,
    report_source_path,
    rows,
)
from audit_simdcomp_sdk import audit, require, sha
from streamvbyte_audit_common import audit_summary

from tscompbench.adapters.factory import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.datasets.canonical import read_canonical
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.preprocess.simdcomp import EXECUTOR_IDS

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("simdcomp-u32", "delta-simdcomp-u32", "for-simdcomp-u32")
PREFIX = struct.Struct("<8sI32s")


def expected_matrix(key: str, formal: bool = False) -> set[tuple]:
    apis = (
        ("LENGTH", "MASKED", "WITHOUTMASK")
        if key == KEYS[0]
        else (("MASKED", "WITHOUTMASK") if key == KEYS[1] else ("LENGTH", "FULL"))
    )
    isas = ("SSE4_1", "AVX2") if key == KEYS[0] else ("SSE4_1",)
    seeds = (0,) if formal or key == KEYS[0] else (0, 1, 2**31, 2**32 - 1)
    return set(itertools.product(apis, isas, seeds, (False, True)))


def configuration_matrix(run: Path, manifest, formal: bool) -> dict:
    configs = json.loads((run / "resolved_configs.json").read_text())["configs"]
    require(
        len(configs) == len(expected_matrix(manifest.key, formal))
        and len({c["config_id"] for c in configs}) == len(configs),
        "configuration matrix incomplete",
    )
    require(
        {
            tuple(c["parameters"][k] for k in ("api", "isa", "starting_point", "native_timing"))
            for c in configs
        }
        == expected_matrix(manifest.key, formal),
        "API/ISA/seed/timer matrix differs",
    )
    for item in configs:
        params = item["parameters"]
        invalid = params["api"] == "LENGTH" and params["isa"] == "AVX2"
        require(
            item["status"] == ("SCHEMA_ERROR" if invalid else "PLANNED"),
            "configuration status differs",
        )
        require(
            set(params) == {"api", "isa", "starting_point", "native_timing"}, "hidden parameters"
        )
        expected = stable_id(
            "config",
            {
                "algorithm_id": manifest.algorithm_id,
                "parameters": params,
                "framework_parameters": item["framework_parameters"],
                "parameter_schema_version": "tscb.codec-parameters.v2",
            },
        )
        require(expected == item["config_id"], "ConfigID/default parameters differ")
    return {c["config_id"]: c["parameters"] for c in configs}


def source_and_runtime(registry: CodecRegistry, key: str) -> tuple:
    sdk = audit()
    manifest = registry.get(key)
    source = registry.sources.get(manifest.source_artifact_id)
    lock = json.loads((ROOT / "adapters/simdcomp/SOURCE_LOCK.json").read_text())
    require(
        source["identity"]["repository"] == lock["repository"]
        and source["identity"]["commit"] == lock["commit"]
        and source["build"]["source_closure"] == lock["files"]
        and source["identity"]["source_closure_sha256"]
        == hashlib.sha256(canonical_json_bytes(lock["files"])).hexdigest(),
        "registered source identity differs",
    )
    require(
        source["license"]["status"] == "RUN_ALLOWED"
        and source["license"]["spdx"] == "BSD-3-Clause",
        "registered license differs",
    )
    require(
        source["identity"]["patch_series"] == source["build"]["patches"]
        and len(source["build"]["patches"]) == 4
        and source["build"]["submodules"] == [],
        "registered patch/submodule identity differs",
    )
    for item in [*lock["files"], *source["build"]["patches"]]:
        require(sha(ROOT / item["path"]) == item["sha256"], "registered source/patch drift")
    card = validate_onboarding_card(
        json.loads((ROOT / f"registry/onboarding/{key}.json").read_text())
    )
    require(
        card["source_artifact_id"] == manifest.source_artifact_id, "onboarding identity differs"
    )
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
            (ROOT / f"build/adapters/simdcomp_u32/{build['kind']}/build-record.json").read_text()
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
                    {"role": f"SUPPORTING_COMPONENT_{i}", "sha256": sha(path)}
                    for i, path in enumerate(supports)
                ],
            ]
        )
    ).hexdigest()
    return manifest, source, runtime, sdk


def independent_frame(stream: bytes, params: dict, original: np.ndarray, key: str) -> dict:
    """Scalar decode of lane words; never call source kernels or the stage validator."""
    coding = "PLAIN" if key == KEYS[0] else "DELTA" if key == KEYS[1] else "FOR"
    require(len(stream) >= PREFIX.size + 48, "truncated complete stream")
    magic, length, digest = PREFIX.unpack_from(stream)
    require(magic == b"TSCBSCP1" and length <= 4096, "wrong stream prefix")
    header = stream[PREFIX.size : PREFIX.size + length]
    require(hashlib.sha256(header).digest() == digest, "descriptor checksum differs")
    info = json.loads(header)
    expected = {
        "schema_version": "tscb.simdcomp-container.v1",
        "algorithm": key,
        "track": "VALUE",
        "count": len(original),
        "parameters": {
            "api": params["api"],
            "isa": params["isa"],
            "starting_point": params["starting_point"],
            "coding": coding,
        },
        "buffer": {
            "dtype": "<u4",
            "shape": [len(original)],
            "logical_bits": original.nbytes * 8,
            "name": "value/000000",
        },
        "timestamp_unit": "NOT_APPLICABLE",
        "timestamp_epoch": "NOT_APPLICABLE",
        "value_units": ["count"],
        "codec_stages": (
            ["ORIGINAL_SIMDCOMP_D1_MODULAR32"]
            if coding == "DELTA"
            else ["ORIGINAL_SIMDCOMP_FIXED_FOR_MODULAR32"]
            if coding == "FOR"
            else []
        )
        + ["ORIGINAL_SIMDCOMP_UINT32_BITPACK"],
    }
    require(
        info == expected and header == canonical_json_bytes(expected), "descriptor semantics differ"
    )
    mode = (
        1
        if coding == "DELTA"
        else (3 if params["api"] == "FULL" else 2)
        if coding == "FOR"
        else (4 if params["isa"] == "AVX2" else 0)
    )
    block, seed = (256 if mode == 4 else 128), params["starting_point"]
    blocks = (len(original) + block - 1) // block
    frame = stream[PREFIX.size + length :]
    require(
        struct.unpack_from("<8s6IQ", frame)
        == (b"TSCBSBP1", len(original), seed, mode, block, blocks, 0, len(frame) - 48),
        "SBP1 count/seed/mode/geometry differs",
    )
    fnv = 14695981039346656037
    for byte in frame[:-8]:
        fnv = ((fnv ^ byte) * 1099511628211) % 2**64
    require(struct.unpack_from("<Q", frame, len(frame) - 8)[0] == fnv, "SBP1 checksum differs")
    at, previous, value_bits, payload_bytes, recovered, all_residuals = 40, seed, 0, 0, [], []
    for start in range(0, len(original), block):
        require(at + 8 <= len(frame) - 8, "truncated record")
        n, width, layout, size = struct.unpack_from("<HBBI", frame, at)
        expected_n = min(block, len(original) - start)
        expected_layout = 1 if mode in (1, 3) else 2 if mode == 4 and n == 256 else 0
        require(
            n == expected_n and width <= 32 and layout == expected_layout, "record geometry differs"
        )
        physical, lanes = (128 if layout == 1 else n), (8 if layout == 2 else 4)
        lane_words = ((physical + lanes - 1) // lanes * width + 31) // 32
        require(
            size == (physical * 4 if width == 32 else lane_words * lanes * 4)
            and at + 8 + size <= len(frame) - 8,
            "payload geometry differs",
        )
        packed = frame[at + 8 : at + 8 + size]
        if width == 32:
            values = list(struct.unpack("<" + "I" * physical, packed))
        else:
            lane_values = [
                sum(
                    int.from_bytes(
                        packed[(w * lanes + lane) * 4 : (w * lanes + lane + 1) * 4], "little"
                    )
                    << (w * 32)
                    for w in range(lane_words)
                )
                for lane in range(lanes)
            ]
            for lane, value in enumerate(lane_values):
                slots = len(range(lane, physical, lanes))
                require(value >> (slots * width) == 0, "nonzero unused lane bits")
            codes = [
                (lane_values[i % lanes] >> (i // lanes * width)) & ((1 << width) - 1)
                for i in range(physical)
            ]
            values, prev = [], previous
            for code in codes:
                prev = (
                    (prev + code) % 2**32
                    if mode == 1
                    else (seed + code) % 2**32
                    if mode in (2, 3)
                    else code
                )
                values.append(prev)
        codes, prev = [], previous
        for value in values:
            codes.append(
                (value - prev) % 2**32
                if mode == 1
                else (value - seed) % 2**32
                if mode in (2, 3)
                else value
            )
            prev = value
        require(max(codes, default=0).bit_length() == width, "nonminimal scalar width")
        require(values[:n] == original[start : start + n].tolist(), "scalar inverse differs")
        if layout == 1:
            require(
                values[n:] == [values[n - 1] if mode == 1 else seed] * (physical - n),
                "scalar padded reconstruction differs",
            )
        recovered.extend(values[:n])
        all_residuals.extend(codes[:n])
        previous, at = values[n - 1], at + 8 + size
        value_bits += n * width
        payload_bytes += size
    require(
        at == len(frame) - 8 and recovered == original.tolist(), "scalar trailing/inverse mismatch"
    )
    return {
        "value_bits": value_bits,
        "padding_bits": payload_bytes * 8 - value_bits,
        "metadata_bits": (length + 32 + blocks * 8) * 8,
        "container_bits": 160,
        "checksum_bits": 320,
        "payload_bytes": payload_bytes,
        "native_frame_bytes": len(frame),
        "block_size": block,
        "blocks": blocks,
        "residual_sha256": hashlib.sha256(
            np.array(all_residuals, dtype="<u4").tobytes()
        ).hexdigest(),
    }


def audit_common(run: Path, manifest, source: dict, runtime: str) -> tuple[list, list, dict]:
    codec_snapshot = json.loads((run / "codec_registry_snapshot.json").read_text())
    matched = [c for c in codec_snapshot["codecs"] if c["key"] == manifest.key]
    require(
        len(matched) == 1
        and matched[0]["algorithm_id"] == manifest.algorithm_id
        and matched[0]["manifest"] == manifest.document,
        "codec snapshot differs",
    )
    sources = json.loads((run / "source_registry_snapshot.json").read_text())["sources"]
    require(
        [s for s in sources if s["identity"] == source["identity"]] == [source],
        "source snapshot differs",
    )
    tasks, records = rows(run / "task_plan.jsonl"), rows(run / "run_components.jsonl")
    for layer in range(2, 6):
        require(bool(list(run.glob(f"layer{layer}-*.json"))), "layer artifact absent")
    for task in tasks:
        audit_stage_plan(task, manifest)
        require(
            task["algorithm_id"] == manifest.algorithm_id
            and task["execution"]["artifact_sha256"] == runtime
            and task["execution"]["source_artifact_id"] == manifest.source_artifact_id,
            "task runtime identity differs",
        )
    require(len({r["run_id"] for r in records}) == len(records), "duplicate attempts")
    report = json.loads((run / "report/report.json").read_text())
    for filename, digest in report["source_hashes"].items():
        require(sha(report_source_path(run, filename)) == digest, "report source artifact drift")
    for filename, digest in report["derived_artifact_hashes"].items():
        require(sha(run / filename) == digest, "derived report drift")
    require(
        report["task_count"] == len(tasks)
        and report["eligible_run_count"] == sum(r["eligibility"] for r in records),
        "report counts differ",
    )
    audit_raw_projection_and_coverage(run, tasks, records)
    return tasks, records, report


def audit_diagnostic(record: dict, task: dict, config_invalid: bool) -> None:
    status = "SCHEMA_ERROR" if config_invalid else "UNSUPPORTED"
    reason = "AVX2_SOURCE_HAS_NO_LENGTH_API" if config_invalid else "CAPABILITY_MISMATCH"
    require(
        all(record[k] == task[k] for k in ("algorithm_id", "dataset_id", "config_id", "track"))
        and record["execution_path_hash"] == task["execution"]["execution_path_hash"],
        "rejection task identity differs",
    )
    require(
        record["status"] == task["status"] == status
        and record["reason_code"] == task["reason_code"] == reason
        and record["record_kind"] == "DIAGNOSTIC"
        and record["eligibility"] is False,
        "rejection diagnostic differs",
    )
    require(
        all(
            record[k] is None
            for k in (
                "accounting",
                "bitstream_sha256",
                "correctness",
                "finalize_bytes",
                "input_sha256",
                "repetition_index",
                "resources",
                "timing",
                "workloads",
            )
        ),
        "unexecuted task has measured output",
    )
    preflight = record["diagnostics"]["preflight"]
    require(
        preflight["status"] == status
        and preflight["reason_code"] == reason
        and preflight["eligible_for_formal_repetitions"] is False
        and preflight["boundary"] is preflight["correctness"] is preflight["accounting"] is None,
        "rejection preflight fabricated execution",
    )
    if not config_invalid:
        require(
            task["execution"]["actual_isa"] == "NOT_EXECUTED"
            and task["compatibility"]["operations"] == []
            and task["compatibility"]["output_descriptor"] is None,
            "unsupported task claims execution/cast",
        )


def audit_supported(
    run: Path, manifest, source: dict, runtime: str, formal: bool, original: np.ndarray
) -> tuple[list, dict]:
    tasks, records, report = audit_common(run, manifest, source, runtime)
    params_by_id = configuration_matrix(run, manifest, formal)
    require(
        len(tasks) == len(params_by_id) and {t["config_id"] for t in tasks} == set(params_by_id),
        "task universe incomplete",
    )
    frozen = json.loads((run / "frozen_config.json").read_text())
    profile, repeats = frozen["profile"], (20 if formal else 1)
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
            "formal affinity/duration policy differs",
        )
    streams, valid_tasks = {}, []
    by_task = {t["task_id"]: t for t in tasks}
    require(all(r["task_id"] in by_task for r in records), "unclaimed attempts")
    for task in tasks:
        params, execution = params_by_id[task["config_id"]], task["execution"]
        observed = [r for r in records if r["task_id"] == task["task_id"]]
        invalid = params["api"] == "LENGTH" and params["isa"] == "AVX2"
        if invalid:
            require(len(observed) == 1, "schema rejection missing/duplicated")
            audit_diagnostic(observed[0], task, True)
            continue
        valid_tasks.append(task)
        require(
            len(observed) == repeats
            and {r["repetition_index"] for r in observed} == set(range(repeats)),
            "repetition universe incomplete",
        )
        require(
            task["status"] == execution["status"] == "PLANNED"
            and execution["actual_isa"] == params["isa"]
            and execution["requested_isa"] == params["isa"]
            and execution["fallback_used"] is False,
            "actual ISA/path differs",
        )
        if formal:
            require(
                execution["cpu_affinity"] == [0] and sum(r["eligibility"] for r in observed) >= 10,
                "actual affinity or eligible repetition count differs",
            )
        preflight = json.loads(
            (run / "preflight" / (task["task_id"].split(":")[-1] + ".json")).read_text()
        )
        require(
            preflight["status"] == "PASS"
            and preflight["eligible_for_formal_repetitions"]
            and preflight["boundary"]["passed"]
            and all(i["status"] == "PASS" for i in preflight["boundary"]["observations"]),
            "preflight/boundary evidence missing",
        )
        require(len({r["bitstream_sha256"] for r in observed}) == 1, "nondeterministic streams")
        stream = None
        for record in observed:
            path = run / "artifacts" / (record["run_id"].rsplit(":", 1)[-1] + ".bin")
            require(sha(path) == record["bitstream_sha256"], "repetition stream hash differs")
            stream = path.read_bytes() if stream is None else stream
        physical = independent_frame(stream, params, original, manifest.key)
        identity = (params["api"], params["isa"], params["starting_point"])
        require(
            identity not in streams or streams[identity] == observed[0]["bitstream_sha256"],
            "timer alters stream bytes",
        )
        streams[identity] = observed[0]["bitstream_sha256"]
        stage = preflight["diagnostics"].get("preprocess_stage_validation")
        if manifest.key in EXECUTOR_IDS:
            require(
                stage
                and stage["status"] == "PASS"
                and stage["executor_id"] == EXECUTOR_IDS[manifest.key]
                and stage["checked_stages"] == ["A", "B", "D"]
                and stage["inverse_validation"] == "BIT_EXACT"
                and stage["stage_A_wall_ns"] is stage["stage_B_wall_ns"] is None
                and stage["stage_A_emitted_residuals_sha256"] == physical["residual_sha256"]
                and stage["stage_B_payload_bytes"] == physical["payload_bytes"]
                and stage["stage_B_logical_value_bits"] == physical["value_bits"]
                and stage["stage_B_physical_padding_bits"] == physical["padding_bits"],
                "stage evidence differs",
            )
        else:
            require(
                task["preprocess"]["stages"] == [] and stage is None,
                "plain primitive has hidden stages",
            )
        alternate = dict(
            params,
            native_timing=False,
            starting_point=(2**32 - 1) ^ params["starting_point"] if manifest.key != KEYS[0] else 0,
        )
        if params["api"] in ("MASKED", "WITHOUTMASK"):
            alternate["api"] = "MASKED" if params["api"] == "WITHOUTMASK" else "WITHOUTMASK"
        session = create_adapter(ROOT, manifest).create_session(alternate)
        try:
            require(
                session.decompress(stream).buffers[0].array.tobytes() == original.tobytes(),
                "fresh independently configured decoder differs",
            )
        finally:
            session.close()
        for record in observed:
            require(
                record["execution_path_hash"] == execution["execution_path_hash"]
                and record["config_id"] == task["config_id"]
                and record["correctness"]["status"] == "PASS"
                and record["diagnostics"]["same_repetition_correctness_and_measurement"]
                and record["finalize_bytes"] == 0,
                "same-repetition correctness/runtime differs",
            )
            if record["status"] == "RESOURCE_PRESSURE":
                require(
                    formal
                    and not record["eligibility"]
                    and record["reason_code"] == "SWAP_OBSERVED_DURING_FORMAL_REPETITION"
                    and record["resources"]["swap_observed"],
                    "unexplained resource pressure",
                )
            else:
                require(
                    record["status"] == "PASS" and record["eligibility"] is formal,
                    "failed attempt admitted",
                )
            ledger, timing = record["accounting"], record["timing"]
            require(
                sum(ledger[k] for k in COMPONENTS)
                == ledger["serialized_bits"]
                == ledger["final_bits"]
                == len(stream) * 8
                and ledger["final_physical_bytes"] == len(stream)
                and ledger["canonical_raw_bits"] == original.nbytes * 8
                and ledger["external_side_information_bits"] == ledger["timestamp_bits"] == 0,
                "physical accounting does not close",
            )
            for component in (
                "value_bits",
                "padding_bits",
                "metadata_bits",
                "container_bits",
                "checksum_bits",
            ):
                require(
                    ledger[component] == physical[component],
                    "independent component billing differs",
                )
            require(
                timing["native_timing_enabled"] is params["native_timing"]
                and timing["native_input_bytes_per_iteration"] == original.nbytes,
                "native config/denominator differs",
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
                    <= timing[f"pipeline_{direction}_wall_ns"],
                    "timing boundaries invalid",
                )
                if params["native_timing"]:
                    require(
                        0
                        < timing[f"native_{direction}_wall_ns"]
                        <= timing[f"core_{direction}_wall_ns"]
                        and timing["native_timing_boundary"] == "CODEC_API_ONLY_V1"
                        and timing["native_timing_clock"] == "CLOCK_MONOTONIC",
                        "native timing invalid",
                    )
                else:
                    require(
                        timing[f"native_{direction}_wall_ns"] is None
                        and timing[f"native_{direction}_mb_per_second"] is None,
                        "disabled timer falsely measured",
                    )
            audit_telemetry(record, params, physical, original.nbytes, manifest.key)
    measured = [r for r in records if r["record_kind"] != "DIAGNOSTIC"]
    require(len(measured) == len(valid_tasks) * repeats, "extra measured attempts")
    require(
        {p.name for p in (run / "artifacts").glob("*.bin")}
        == {r["run_id"].rsplit(":", 1)[-1] + ".bin" for r in measured},
        "missing/unclaimed stream artifacts",
    )
    warmups = [json.loads(p.read_text()) for p in (run / "warmup").glob("*.json")]
    require(len(warmups) == len(valid_tasks), "warmup universe incomplete")
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
        require(report["summary_count"] == len(valid_tasks), "formal summary universe incomplete")
        audit_summary(run)
        for summary in report["summaries"]:
            accepted = [
                r for r in records if r["config_id"] == summary["config_id"] and r["eligibility"]
            ]
            require(
                len({r["execution_path_hash"] for r in accepted}) == 1
                and summary["execution_path_hash"] == accepted[0]["execution_path_hash"],
                "summary mixes paths",
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
            accepted.sort(key=lambda r: r["repetition_index"])
            require(
                summary["summary_id"]
                == stable_id("summary", {**group, "run_ids": [r["run_id"] for r in accepted]}),
                "summary identity differs",
            )
            audit_independent_statistics(summary, accepted, report["policy"])
    else:
        require(report["summary_count"] == 0, "qualification entered ranking")
    return records, streams


def audit_telemetry(record: dict, params: dict, physical: dict, raw: int, key: str) -> None:
    telemetry, timing = record["diagnostics"]["codec_telemetry"], record["timing"]
    require(
        telemetry["scope"] == "LAST_INNER_ITERATION"
        and telemetry["observed_iteration_index"] == timing["inner_iterations"] - 1,
        "telemetry scope differs",
    )
    block, blocks, payload = physical["block_size"], physical["blocks"], physical["payload_bytes"]
    count = raw // 4
    padded = key == KEYS[1] or key == KEYS[2] and params["api"] == "FULL"
    padding = (blocks * 128 - count) * 4 if padded else 0
    for direction in ("encode", "decode"):
        data = telemetry[direction]
        encode = direction == "encode"
        full = (
            ("avxpackwithoutmask" if params["api"] == "WITHOUTMASK" else "avxpack")
            if encode
            else "avxunpack"
        )
        tail = "simdpack_length" if encode else "simdunpack_length"
        if params["isa"] != "AVX2":
            if key == KEYS[1]:
                full = (
                    ("simdpackwithoutmaskd1" if params["api"] == "WITHOUTMASK" else "simdpackd1")
                    if encode
                    else "simdunpackd1"
                )
            elif key == KEYS[2]:
                full = ("simdpackFOR" if encode else "simdunpackFOR") + (
                    "_length" if params["api"] == "LENGTH" else ""
                )
            else:
                full = (
                    (
                        "simdpack_length"
                        if params["api"] == "LENGTH"
                        else "simdpackwithoutmask"
                        if params["api"] == "WITHOUTMASK"
                        else "simdpack"
                    )
                    if encode
                    else ("simdunpack_length" if params["api"] == "LENGTH" else "simdunpack")
                )
            tail = (
                ("simdpack_shortlength" if encode else "simdunpack_shortlength")
                if key == KEYS[0] and params["api"] != "LENGTH"
                else full
            )
        bound = 48 + blocks * (8 + block * 4)
        require(
            data["actual_full_api"] == full
            and data["actual_tail_api"] == tail
            and data["actual_isa"]
            == ("AVX2_WITH_SSE4_1_TAIL" if params["isa"] == "AVX2" else "SSE4_1")
            and data["blocks"] == blocks
            and data["full_calls"] == count // block
            and data["tail_calls"] == int(bool(count % block))
            and data["internal_padding_bytes"] == padding
            and data["external_padding_bytes"] == data["python_payload_copy_bytes"] == 0
            and data["native_payload_bytes"] == payload
            and data["padding_stream_bits"] == physical["padding_bits"]
            and data["native_raw_bytes"] == raw
            and data["native_staging_allocation_count"] == 2
            and data["native_staging_allocation_bytes"]
            == (bound + block * 8 if encode else max(raw, 1) + block * 8)
            and data["native_staging_input_copy_bytes"] == (raw if encode else payload)
            and data["native_staging_output_copy_bytes"]
            == (payload + physical["native_frame_bytes"] if encode else raw * 2)
            and data["included_in_native_api_timing"] is False,
            "actual source API/staging telemetry differs",
        )


def audit_unsupported(run: Path, manifest, source: dict, runtime: str) -> list:
    tasks, records, report = audit_common(run, manifest, source, runtime)
    configs = configuration_matrix(run, manifest, False)
    expected = set(itertools.product(configs, ("VALUE", "TIMESTAMP")))
    require(
        len(tasks) == len(records) == len(expected)
        and {(t["config_id"], t["track"]) for t in tasks} == expected
        and Counter(r["task_id"] for r in records) == Counter(t["task_id"] for t in tasks),
        "unsupported task universe incomplete",
    )
    by_task = {t["task_id"]: t for t in tasks}
    for record in records:
        task = by_task[record["task_id"]]
        params = configs[task["config_id"]]
        audit_diagnostic(record, task, params["api"] == "LENGTH" and params["isa"] == "AVX2")
        require(
            task["compatibility"]["input_descriptor"]["dtype_vector"]
            == (["<i8"] if task["track"] == "TIMESTAMP" else ["<f8"] * 7),
            "unsupported input changed dtype",
        )
    require(
        not list((run / "artifacts").glob("*.bin")) and not list((run / "warmup").glob("*.json")),
        "unsupported task produced stream/warmup",
    )
    require(report["summary_count"] == report["eligible_run_count"] == 0, "unsupported task ranked")
    return records


def audit_run_sets(key: str, names: list[str]) -> dict:
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest, source, runtime, sdk = source_and_runtime(registry, key)
    suffix = names[0].removeprefix(key + "-formal-20-")
    benchmark = json.loads(
        (ROOT / f"build/source-audits/simdcomp_benchmark_{suffix}.json").read_text()
    )
    require(
        benchmark["status"] == "RUNS_RECORDED_INDEPENDENT_AUDIT_PENDING"
        and benchmark["driver_sha256"] == sha(ROOT / "tools/qualify_simdcomp_benchmark.py")
        and benchmark["sdk_audit"] == sdk
        and benchmark["formal_requested"] is True,
        "benchmark execution evidence stale/incomplete",
    )
    closure = benchmark["actual_imported_python_closure"]
    benchmark_paths = {i["path"] for i in closure}
    require(
        len(benchmark_paths) == len(closure)
        and {
            "src/tscompbench/runner.py",
            "src/tscompbench/execution/preflight.py",
            "src/tscompbench/adapters/simdcomp.py",
            "src/tscompbench/preprocess/simdcomp.py",
            "src/tscompbench/statistics/engine.py",
            "src/tscompbench/reporting/generator.py",
        }
        <= benchmark_paths,
        "actual benchmark Python closure incomplete",
    )
    for item in closure:
        require(sha(ROOT / item["path"]) == item["sha256"], "actual benchmark source drift")
    require(len(benchmark["runs"]) == 9, "benchmark run universe incomplete")
    for name in names:
        entry = [r for r in benchmark["runs"] if r["run_set_id"] == name]
        require(
            len(entry) == 1
            and entry[0]["records_sha256"] == sha(ROOT / "runs" / name / "run_components.jsonl")
            and entry[0]["report_sha256"] == sha(ROOT / "runs" / name / "report/report.json"),
            "benchmark execution output differs",
        )
    fixture = ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz"
    dataset = json.loads((ROOT / "registry/datasets/streamvbyte_u32_uts.json").read_text())
    require(sha(fixture) == dataset["file"]["sha256"], "fixture drift")
    with np.load(fixture, allow_pickle=False) as archive:
        original = archive["values"]
    require(original.dtype.str == "<u4" and original.shape == (8193,), "fixture contract differs")
    collected, streams = [], []
    for index, name in enumerate(names[:2]):
        run = ROOT / "runs" / name
        canonical_paths = list((run / "datasets").glob("*/*.canonical.tscb"))
        require(len(canonical_paths) == 1, "Layer1 canonical artifact missing")
        canonical = read_canonical(canonical_paths[0], include_buffers=True)
        require(
            list(canonical.buffers.values()) == [original.tobytes()],
            "source/canonical bytes differ",
        )
        records, hashes = audit_supported(run, manifest, source, runtime, index == 0, original)
        collected.append(records)
        streams.append(hashes)
    require(
        all(streams[1].get(k) == v for k, v in streams[0].items()),
        "formal/qualification streams differ",
    )
    rejected = audit_unsupported(ROOT / "runs" / names[2], manifest, source, runtime)
    result = {
        "status": "PASS",
        "codec_key": key,
        "object_level": manifest.object_level.value,
        "algorithm_id": manifest.algorithm_id,
        "source_artifact_id": manifest.source_artifact_id,
        "runtime_digest": runtime,
        "formal_run": names[0],
        "qualification_run": names[1],
        "unsupported_run": names[2],
        "formal_attempts": len(collected[0]),
        "eligible_repetitions": sum(r["eligibility"] for r in collected[0]),
        "status_counts": dict(Counter(r["status"] for r in collected[0])),
        "qualification_attempts": len(collected[1]),
        "unsupported_diagnostics": len(rejected),
        "sdk_evidence": sdk,
        "scope": "UINT32_UTS_SOURCE_APIS_SSE4_1_AND_DECLARED_AVX2_ONLY",
        "full_logical_entry_qualified": False,
        "checked_int64_timestamp": "PENDING",
        "auditor_sha256": sha(Path(__file__)),
        "audit_dependencies": [
            {"path": p, "sha256": sha(ROOT / p)}
            for p in (
                "tools/audit_maskedvbyte_run.py",
                "tools/streamvbyte_audit_common.py",
                "tools/audit_simdcomp_sdk.py",
            )
        ],
        "formal_records_sha256": sha(ROOT / "runs" / names[0] / "run_components.jsonl"),
        "actual_imported_benchmark_python_file_count": len(benchmark_paths),
        "benchmark_driver_evidence_sha256": sha(
            ROOT / f"build/source-audits/simdcomp_benchmark_{suffix}.json"
        ),
    }
    (ROOT / f"build/source-audits/{key.replace('-', '_')}_five_layer_audit.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    return result


def audit_qualification_run_sets(key: str, qualification: str, unsupported: str) -> dict:
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest, source, runtime, sdk = source_and_runtime(registry, key)
    fixture = ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz"
    dataset = json.loads((ROOT / "registry/datasets/streamvbyte_u32_uts.json").read_text())
    require(sha(fixture) == dataset["file"]["sha256"], "original fixture drift")
    with np.load(fixture, allow_pickle=False) as archive:
        original = archive["values"]
    run = ROOT / "runs" / qualification
    canonical_paths = list((run / "datasets").glob("*/*.canonical.tscb"))
    require(len(canonical_paths) == 1, "Layer1 canonical artifact missing")
    canonical = read_canonical(canonical_paths[0], include_buffers=True)
    require(
        list(canonical.buffers.values()) == [original.tobytes()], "source/canonical bytes differ"
    )
    records, streams = audit_supported(run, manifest, source, runtime, False, original)
    rejected = audit_unsupported(ROOT / "runs" / unsupported, manifest, source, runtime)
    result = {
        "status": "PASS",
        "codec_key": key,
        "object_level": manifest.object_level.value,
        "algorithm_id": manifest.algorithm_id,
        "source_artifact_id": manifest.source_artifact_id,
        "runtime_digest": runtime,
        "qualification_run": qualification,
        "unsupported_run": unsupported,
        "qualification_attempts": len(records),
        "unsupported_diagnostics": len(rejected),
        "status_counts": dict(Counter(r["status"] for r in records)),
        "unsupported_status_counts": dict(Counter(r["status"] for r in rejected)),
        "distinct_streams": len(streams),
        "sdk_audit": sdk,
        "benchmark_five_layers": "QUALIFICATION_ONLY_FORMAL_AUDIT_PENDING",
        "full_logical_entry_qualified": False,
        "checked_int64_timestamp": "PENDING",
        "auditor_sha256": sha(Path(__file__)),
        "qualification_records_sha256": sha(run / "run_components.jsonl"),
        "audit_dependencies": [
            {"path": p, "sha256": sha(ROOT / p)}
            for p in (
                "tools/audit_maskedvbyte_run.py",
                "tools/streamvbyte_audit_common.py",
                "tools/audit_simdcomp_sdk.py",
            )
        ],
        "unsupported_records_sha256": sha(ROOT / "runs" / unsupported / "run_components.jsonl"),
    }
    output = ROOT / f"build/source-audits/{key.replace('-', '_')}_qualification_current_audit.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formal_run_set_id")
    parser.add_argument("qualification_run_set_id")
    parser.add_argument("--key", choices=KEYS, default=KEYS[0])
    parser.add_argument("--unsupported-run-set-id")
    parser.add_argument("--qualification-only", action="store_true")
    args = parser.parse_args()
    names = [
        args.formal_run_set_id,
        args.qualification_run_set_id,
        args.unsupported_run_set_id or f"{args.key}-unsupported-qualification-20261007-1",
    ]
    require(all(Path(name).name == name for name in names), "unsafe run set ID")
    try:
        result = (
            audit_qualification_run_sets(args.key, names[1], names[2])
            if args.qualification_only
            else audit_run_sets(args.key, names)
        )
    except Exception as error:
        output_name = (
            f"{args.key.replace('-', '_')}_qualification_current_audit.json"
            if args.qualification_only
            else f"{args.key.replace('-', '_')}_five_layer_audit.json"
        )
        (ROOT / "build/source-audits" / output_name).write_text(
            json.dumps(
                {
                    "status": "FAIL",
                    "codec_key": args.key,
                    "run_sets": names,
                    "error": str(error),
                    "auditor_sha256": sha(Path(__file__)),
                },
                indent=2,
            )
            + "\n"
        )
        raise
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
