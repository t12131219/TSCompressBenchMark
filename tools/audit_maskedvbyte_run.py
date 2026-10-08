"""Audit MaskedVByte five-layer artifacts using scalar LEB128 and modular D1."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import random
import statistics
import struct
from collections import Counter
from decimal import Decimal
from pathlib import Path

import numpy as np
from audit_maskedvbyte_sdk import audit, require, sha
from streamvbyte_audit_common import audit_run_provenance, audit_summary

from tscompbench.adapters.factory import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.datasets.canonical import read_canonical
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.preprocess.maskedvbyte import EXECUTOR_ID

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("maskedvbyte-u32", "delta-maskedvbyte-u32")
PREFIX = struct.Struct("<8sI32s")
COMPONENTS = (
    "timestamp_bits",
    "value_bits",
    "shared_bits",
    "unallocated_shared_bits",
    "metadata_bits",
    "validity_bits",
    "dictionary_bits",
    "model_bits",
    "index_bits",
    "checkpoint_bits",
    "checksum_bits",
    "padding_bits",
    "container_bits",
)


def expected_matrix(key: str) -> set[tuple]:
    seeds = (0,) if key == KEYS[0] else (0, 1, 2**31, 2**32 - 1)
    return set(itertools.product(("COUNT", "COMPRESSED_SIZE"), seeds, (False, True)))


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def report_source_path(run: Path, filename: str) -> Path:
    # The report labels current Python implementation hashes separately from
    # files stored in the run directory. Verify both against their actual owners.
    if filename.startswith("implementation/"):
        return ROOT / "src/tscompbench" / filename.removeprefix("implementation/")
    return run / filename


def audit_raw_projection_and_coverage(run: Path, tasks: list[dict], records: list[dict]) -> None:
    with (run / "runs.csv").open(newline="") as file:
        projection = list(csv.DictReader(file))
    require(len(projection) == len(records), "raw CSV dropped attempts")
    for flat, record in zip(projection, records, strict=True):
        for field in (
            "run_id",
            "task_id",
            "dataset_id",
            "algorithm_id",
            "config_id",
            "execution_path_hash",
            "status",
            "reason_code",
            "eligibility",
            "record_kind",
            "repetition_index",
            "bitstream_sha256",
            "finalize_bytes",
        ):
            value = record[field]
            require(flat[field] == ("" if value is None else str(value)), "raw CSV identity drift")
        for group, fields in (
            (
                "accounting",
                (
                    "canonical_raw_bits",
                    "serialized_bits",
                    "final_bits",
                    "final_physical_bytes",
                    "external_side_information_bits",
                ),
            ),
            (
                "timing",
                (
                    "inner_iterations",
                    "selected_encode_wall_ns",
                    "selected_decode_wall_ns",
                    "core_encode_wall_ns",
                    "core_decode_wall_ns",
                    "pipeline_encode_wall_ns",
                    "pipeline_decode_wall_ns",
                    "native_encode_wall_ns",
                    "native_decode_wall_ns",
                ),
            ),
        ):
            for field in fields:
                value = (record[group] or {}).get(field)
                require(flat[field] == ("" if value is None else str(value)), "raw CSV value drift")
    report = json.loads((run / "report/report.json").read_text())
    coverage = report["coverage"]
    require(
        len(coverage) == len(tasks)
        and {item["task_id"] for item in coverage} == {task["task_id"] for task in tasks},
        "coverage dropped or duplicated tasks",
    )
    for item in coverage:
        attempts = [record for record in records if record["task_id"] == item["task_id"]]
        require(
            item["record_count"] == len(attempts)
            and set(item["run_ids"]) == {r["run_id"] for r in attempts}
            and item["status_counts"] == dict(Counter(r["status"] for r in attempts)),
            "coverage does not describe the actual attempt universe",
        )


def audit_independent_statistics(summary: dict, accepted: list[dict], policy: dict) -> None:
    accepted.sort(key=lambda record: record["repetition_index"])
    for prefix in (
        "core_encode",
        "core_decode",
        "pipeline_encode",
        "pipeline_decode",
        "native_encode",
        "native_decode",
    ):
        field = prefix + "_wall_ns"
        values = [record["timing"][field] for record in accepted]
        names = ("mean", "median", "p25", "p75", "sd", "cv", "ci_low", "ci_high")
        if any(value is None for value in values):
            require(
                all(summary[prefix + "_ns_" + name] is None for name in names)
                and summary[prefix + "_observation_count"] == 0
                and summary[prefix + "_mb_per_second_micro"] is None,
                "null native summary fabricated",
            )
            continue
        per_object = [
            value / record["timing"]["inner_iterations"]
            for value, record in zip(values, accepted, strict=True)
        ]
        mean, sd = statistics.mean(per_object), statistics.stdev(per_object)
        seed = hashlib.sha256((summary["summary_id"] + ":" + prefix + "_ns").encode()).digest()
        generator = random.Random(int.from_bytes(seed[:8], "big"))
        medians = [
            statistics.median(generator.choices(per_object, k=len(per_object)))
            for _ in range(policy["bootstrap_samples"])
        ]
        alpha = (Decimal(1) - Decimal(policy["confidence_level"])) / 2
        expected = {
            "mean": mean,
            "median": statistics.median(per_object),
            "sd": sd,
            "p25": float(np.quantile(per_object, 0.25)),
            "p75": float(np.quantile(per_object, 0.75)),
            "cv": sd / abs(mean),
            "ci_low": float(np.quantile(medians, float(alpha))),
            "ci_high": float(np.quantile(medians, float(1 - alpha))),
        }
        for name, value in expected.items():
            require(
                math.isclose(summary[prefix + "_ns_" + name], value, rel_tol=1e-12),
                "independently recomputed summary differs: " + prefix + "/" + name,
            )
        rate = (
            sum(
                r["timing"]["canonical_bytes_per_iteration"] * r["timing"]["inner_iterations"]
                for r in accepted
            )
            * 1000
            / sum(values)
        )
        require(
            summary[prefix + "_observation_count"] == len(accepted)
            and math.isclose(float(summary[prefix + "_mb_per_second_micro"]), rate, rel_tol=1e-12),
            "micro throughput is not total bytes / total time",
        )


def source_and_runtime(registry: CodecRegistry, key: str) -> tuple:
    native = audit()
    manifest = registry.get(key)
    source = registry.sources.get(manifest.source_artifact_id)
    require(
        source["identity"]["repository"] == "https://github.com/fast-pack/MaskedVByte"
        and source["identity"]["commit"] == "e2298b7a28002e08f3f74755353b7229bfe6475b",
        "registered source identity differs",
    )
    closure = source["build"]["source_closure"]
    require(
        hashlib.sha256(canonical_json_bytes(closure)).hexdigest()
        == source["identity"]["source_closure_sha256"],
        "source closure identity differs",
    )
    for item in closure:
        require(sha(ROOT / item["path"]) == item["sha256"], "registered source drift")
    require(source["build"]["submodules"] == [], "unexpected source submodule")
    require(
        source["identity"]["patch_series"] == source["build"]["patches"],
        "source identity/build patch mismatch",
    )
    for patch in source["identity"]["patch_series"]:
        require(sha(ROOT / patch["path"]) == patch["sha256"], "registered patch drift")
    require(
        source["license"]["status"] == "RUN_ALLOWED" and source["license"]["spdx"] == "Apache-2.0",
        "registered license differs",
    )
    card = validate_onboarding_card(
        json.loads((ROOT / f"registry/onboarding/{key}.json").read_text())
    )
    require(
        card["source_artifact_id"] == manifest.source_artifact_id, "onboarding identity differs"
    )
    for test in card["upstream_tests"]:
        require(
            test["status"] == "PASS" and sha(ROOT / test["evidence"]) == test["log_sha256"],
            "onboarding test evidence stale",
        )
    require(len(card["builds"]) == 3, "onboarding build matrix incomplete")
    for item in card["builds"]:
        record = json.loads(
            (ROOT / f"build/adapters/maskedvbyte_u32/{item['kind']}/build-record.json").read_text()
        )
        require(
            item["artifact_sha256"] == record["artifact_sha256"]
            and item["compile_commands_sha256"] == record["compile_commands_sha256"],
            "onboarding build stale",
        )
    artifact, supports = adapter_artifacts(ROOT, manifest)
    runtime = hashlib.sha256(
        canonical_json_bytes(
            [
                {"role": "PRIMARY_ADAPTER", "sha256": sha(artifact)},
                *[
                    {"role": f"SUPPORTING_COMPONENT_{index}", "sha256": sha(path)}
                    for index, path in enumerate(supports)
                ],
            ]
        )
    ).hexdigest()
    return manifest, source, runtime, native


def configuration_matrix(run: Path, manifest) -> dict[str, dict]:
    document = json.loads((run / "resolved_configs.json").read_text())
    configs = document["configs"]
    require(
        len(configs) == len(expected_matrix(manifest.key))
        and len({item["config_id"] for item in configs}) == len(configs),
        "configuration matrix incomplete",
    )
    require(
        {
            (
                item["parameters"]["decoder_api"],
                item["parameters"]["starting_point"],
                item["parameters"]["native_timing"],
            )
            for item in configs
        }
        == expected_matrix(manifest.key),
        "mode/seed/timer matrix differs",
    )
    for item in configs:
        require(
            item["status"] == "PLANNED" and item["parameters"]["isa"] == "SSE4_1",
            "invalid configuration was used",
        )
        expected = stable_id(
            "config",
            {
                "algorithm_id": manifest.algorithm_id,
                "parameters": item["parameters"],
                "framework_parameters": item["framework_parameters"],
                "parameter_schema_version": "tscb.codec-parameters.v2",
            },
        )
        require(expected == item["config_id"], "ConfigID/default parameter mismatch")
    return {item["config_id"]: item["parameters"] for item in configs}


def scalar_payload(original: np.ndarray, delta: bool, seed: int) -> bytes:
    output = bytearray()
    previous = seed
    for item in original:
        number = (int(item) - previous) % 2**32 if delta else int(item)
        previous = int(item)
        while number >= 128:
            output.append((number & 127) | 128)
            number >>= 7
        output.append(number)
    return bytes(output)


def audit_stage_plan(task: dict, manifest) -> None:
    declared = [
        dict(stage, enabled=True) for stage in manifest.document["semantics"]["preprocess_stages"]
    ]
    require(
        task["preprocess"]
        == {
            "schema_version": "tscb.preprocess-plan.v2",
            "stages": declared,
            "preprocess_plan_id": stable_id("preprocess-plan", declared),
            "semantic_class": manifest.document["semantics"]["preprocess_class"],
        },
        "declared stage plan differs",
    )


def independent_frame(stream: bytes, params: dict, original: np.ndarray, key: str) -> dict:
    """Inspect actual bytes without invoking the codec or its stage validator."""
    delta = key == KEYS[1]
    require(len(stream) >= PREFIX.size + 40, "truncated complete object")
    magic, length, digest = PREFIX.unpack_from(stream)
    require(magic == b"TSCBMVP1" and length <= 4096, "wrong complete object prefix")
    descriptor = stream[PREFIX.size : PREFIX.size + length]
    require(hashlib.sha256(descriptor).digest() == digest, "descriptor checksum differs")
    info = json.loads(descriptor)
    expected = {
        "schema_version": "tscb.maskedvbyte-container.v1",
        "algorithm": key,
        "track": "VALUE",
        "count": len(original),
        "buffer": {
            "dtype": "<u4",
            "logical_bits": original.nbytes * 8,
            "name": "value/000000",
            "shape": [len(original)],
        },
        "parameters": {
            "coding": "DELTA" if delta else "PLAIN",
            "starting_point": params["starting_point"],
        },
        "codec_stages": (["ORIGINAL_MASKEDVBYTE_D1_MODULAR32"] if delta else [])
        + ["ORIGINAL_MASKEDVBYTE_LEB128_UINT32"],
        "timestamp_unit": "NOT_APPLICABLE",
        "timestamp_epoch": "NOT_APPLICABLE",
        "value_units": ["count"],
    }
    if delta:
        expected["pipeline_executor_id"] = EXECUTOR_ID
    require(
        info == expected and descriptor == canonical_json_bytes(expected),
        "descriptor identity/semantics differ",
    )
    frame = stream[PREFIX.size + length :]
    require(len(frame) >= 40, "native frame truncated")
    header = struct.unpack_from("<8sIIIIQ", frame)
    require(
        header
        == (b"TSCBMVB1", len(original), params["starting_point"], int(delta), 0, len(frame) - 40),
        "MVB1 identity/count/seed differs",
    )
    checksum = 14695981039346656037
    for byte in frame[:-8]:
        checksum = ((checksum ^ byte) * 1099511628211) % 2**64
    require(struct.unpack_from("<Q", frame, len(frame) - 8)[0] == checksum, "MVB1 checksum differs")
    payload = frame[32:-8]
    require(
        payload == scalar_payload(original, delta, params["starting_point"]),
        "actual payload differs from independent scalar LEB128/D1 oracle",
    )
    recovered, at, previous = [], 0, params["starting_point"]
    for _ in range(len(original)):
        value = 0
        for width in range(5):
            require(at < len(payload), "truncated scalar LEB128")
            byte = payload[at]
            at += 1
            require(width != 4 or byte <= 15, "scalar LEB128 overflow")
            value |= (byte & 127) << (7 * width)
            if byte < 128:
                require(width == 0 or byte != 0, "noncanonical scalar LEB128")
                break
        else:
            raise RuntimeError("unterminated scalar LEB128")
        previous = (previous + value) % 2**32 if delta else value
        recovered.append(previous)
    require(
        at == len(payload) and recovered == original.tolist(), "independent scalar inverse differs"
    )
    return {
        "value_bits": len(payload) * 8,
        "metadata_bits": (length + 24) * 8,
        "container_bits": 160,
        "checksum_bits": 320,
    }


def audit_supported(
    run: Path, manifest, source: dict, runtime: str, formal: bool, original: np.ndarray
) -> tuple[list[dict], dict]:
    audit_run_provenance(run, manifest, source, runtime)
    params_by_id = configuration_matrix(run, manifest)
    tasks = rows(run / "task_plan.jsonl")
    records = rows(run / "run_components.jsonl")
    config_count = len(params_by_id)
    expected_count = config_count * (20 if formal else 1)
    require(
        len(tasks) == config_count
        and len(records) == expected_count
        and len({record["run_id"] for record in records}) == expected_count,
        "task/repetition universe incomplete",
    )
    frozen = json.loads((run / "frozen_config.json").read_text())
    profile = frozen["profile"]
    require(
        profile["repetitions"] == (20 if formal else 1)
        and profile["measurement_mode"] == ("FORMAL" if formal else "QUALIFICATION")
        and profile["timing_scope"] == "PIPELINE"
        and profile["threads"] == profile["processes"] == 1,
        "measurement profile differs from preplanned policy",
    )
    if formal:
        require(
            profile["warmup_min_count"] >= 3
            and float(profile["warmup_min_seconds"]) >= 0.5
            and float(profile["min_repetition_seconds"]) >= 1
            and profile["cpu_affinity"] == [0],
            "formal time/affinity policy differs",
        )
    paths = list((run / "artifacts").glob("*.bin"))
    require(
        {path.name for path in paths}
        == {record["run_id"].rsplit(":", 1)[-1] + ".bin" for record in records},
        "a repetition artifact is missing or unclaimed",
    )
    for record in records:
        path = run / "artifacts" / (record["run_id"].rsplit(":", 1)[-1] + ".bin")
        require(sha(path) == record["bitstream_sha256"], "repetition artifact hash differs")
    streams = {sha(path): path for path in paths}
    require(
        len(streams) == (1 if manifest.key == KEYS[0] else 4), "serialized seed objects missing"
    )
    params_to_stream = {}
    for task in tasks:
        audit_stage_plan(task, manifest)
        params = params_by_id[task["config_id"]]
        observed = [record for record in records if record["task_id"] == task["task_id"]]
        require(
            len(observed) == (20 if formal else 1)
            and {record["repetition_index"] for record in observed}
            == set(range(20 if formal else 1)),
            "repetitions missing or selectively supplemented",
        )
        execution = task["execution"]
        require(
            execution["threads"] == execution["processes"] == 1
            and execution["actual_isa"] == "SSE4_1"
            and not execution["fallback_used"],
            "actual execution differs",
        )
        if formal:
            require(execution["cpu_affinity"] == [0], "actual CPU affinity differs")
            require(
                sum(record["eligibility"] for record in observed) >= 10,
                "too few eligible formal repetitions",
            )
        preflight = json.loads(
            (run / "preflight" / (task["task_id"].split(":")[-1] + ".json")).read_text()
        )
        require(
            preflight["status"] == "PASS"
            and preflight["eligible_for_formal_repetitions"]
            and preflight["boundary"]["passed"]
            and all(item["status"] == "PASS" for item in preflight["boundary"]["observations"]),
            "preflight/full boundary qualification missing",
        )
        stage = preflight["diagnostics"].get("preprocess_stage_validation")
        if manifest.key == KEYS[1]:
            require(
                [item["stage_slot"] for item in task["preprocess"]["stages"]] == ["A", "B", "D"]
                and all(item["enabled"] for item in task["preprocess"]["stages"])
                and isinstance(stage, dict)
                and stage["status"] == "PASS"
                and stage["executor_id"] == EXECUTOR_ID
                and stage["checked_stages"] == ["A", "B", "D"]
                and stage["inverse_validation"] == "BIT_EXACT"
                and stage["stage_A_wall_ns"] is stage["stage_B_wall_ns"] is None
                and stage["stage_timing_reason"] == "SOURCE_API_FUSES_A_AND_B",
                "P2 stage identity/inverse evidence absent",
            )
        else:
            require(task["preprocess"]["stages"] == [], "plain primitive has hidden delta")
        require(
            len({record["bitstream_sha256"] for record in observed}) == 1,
            "non-deterministic stream",
        )
        stream_hash = observed[0]["bitstream_sha256"]
        require(stream_hash in streams, "actual bitstream artifact missing")
        stream = streams[stream_hash].read_bytes()
        physical = independent_frame(stream, params, original, manifest.key)
        session = create_adapter(ROOT, manifest).create_session(
            {
                "decoder_api": "COMPRESSED_SIZE" if params["decoder_api"] == "COUNT" else "COUNT",
                "starting_point": (2**32 - 1) ^ params["starting_point"]
                if manifest.key == KEYS[1]
                else 0,
            }
        )
        try:
            require(
                session.decompress(stream).buffers[0].array.tobytes() == original.tobytes(),
                "fresh independently configured decoder differs",
            )
        finally:
            session.close()
        identity = params["starting_point"]
        require(
            identity not in params_to_stream or params_to_stream[identity] == stream_hash,
            "decoder/timing switches change stream bytes",
        )
        params_to_stream[identity] = stream_hash
        for record in observed:
            require(
                record["execution_path_hash"] == execution["execution_path_hash"]
                and record["correctness"]["status"] == "PASS"
                and record["diagnostics"]["same_repetition_correctness_and_measurement"]
                and record["finalize_bytes"] == 0,
                "run correctness/execution mismatch",
            )
            if record["status"] == "RESOURCE_PRESSURE":
                require(
                    formal
                    and not record["eligibility"]
                    and record["reason_code"] == "SWAP_OBSERVED_DURING_FORMAL_REPETITION"
                    and record["resources"]["swap_observed"]
                    and record["resources"]["swap_observation_scope"] == "SYSTEM_VMSTAT",
                    "unexplained pressure attempt",
                )
            else:
                require(
                    record["status"] == "PASS" and record["eligibility"] is formal,
                    "unsupported or failed attempt incorrectly qualified",
                )
            ledger = record["accounting"]
            require(
                sum(ledger[key] for key in COMPONENTS)
                == ledger["serialized_bits"]
                == ledger["final_bits"]
                == len(stream) * 8
                and ledger["final_physical_bytes"] == len(stream)
                and ledger["canonical_raw_bits"] == original.nbytes * 8
                and ledger["timestamp_bits"]
                == ledger["padding_bits"]
                == ledger["external_side_information_bits"]
                == 0,
                "physical accounting does not close",
            )
            for key, value in physical.items():
                require(ledger[key] == value, "independent component accounting differs")
            timing = record["timing"]
            require(
                timing["native_timing_enabled"] is params["native_timing"], "timer ConfigID differs"
            )
            if formal:
                require(
                    timing["selected_encode_wall_ns"] >= 1_000_000_000
                    and timing["selected_decode_wall_ns"] >= 1_000_000_000
                    and timing["min_duration_satisfied"],
                    "formal repetition duration insufficient",
                )
            require(
                timing["native_input_bytes_per_iteration"] == original.nbytes,
                "native denominator differs",
            )
            for direction in ("encode", "decode"):
                require(
                    0
                    < timing[f"core_{direction}_wall_ns"]
                    <= timing[f"pipeline_{direction}_wall_ns"],
                    "CORE/PIPELINE time boundary invalid",
                )
                native_time = timing[f"native_{direction}_wall_ns"]
                if params["native_timing"]:
                    require(
                        0 < native_time <= timing[f"core_{direction}_wall_ns"]
                        and timing["native_timing_boundary"] == "CODEC_API_ONLY_V1"
                        and timing["native_timing_clock"] == "CLOCK_MONOTONIC",
                        "native timer invalid",
                    )
                else:
                    require(
                        native_time is None and timing[f"native_{direction}_mb_per_second"] is None,
                        "disabled timer falsely measured",
                    )
            telemetry = record["diagnostics"]["codec_telemetry"]
            require(
                telemetry["scope"] == "LAST_INNER_ITERATION"
                and telemetry["observed_iteration_index"] == timing["inner_iterations"] - 1,
                "telemetry scope wrong",
            )
            for direction in ("encode", "decode"):
                value = telemetry[direction]
                delta = manifest.key == KEYS[1]
                payload_bytes = physical["value_bits"] // 8
                api = (
                    "vbyte_encode"
                    if direction == "encode"
                    else (
                        "masked_vbyte_decode"
                        if params["decoder_api"] == "COUNT"
                        else "masked_vbyte_decode_fromcompressedsize"
                    )
                )
                if delta:
                    api += "_delta"
                require(
                    value["actual_original_api"] == api
                    and value["coding"] == ("DELTA" if delta else "PLAIN")
                    and value["decoder_api"] == params["decoder_api"]
                    and value["internal_padding_bytes"] == value["python_payload_copy_bytes"] == 0
                    and value["native_raw_bytes"] == original.nbytes
                    and value["native_payload_bytes"] == payload_bytes
                    and value["native_staging_allocation_bytes"]
                    == original.nbytes + (payload_bytes if direction == "encode" else 0)
                    and value["native_staging_allocation_count"]
                    == (2 if direction == "encode" else 1)
                    and value["native_staging_input_copy_bytes"]
                    == (original.nbytes if direction == "encode" else 0)
                    and value["native_staging_output_copy_bytes"]
                    == (payload_bytes if direction == "encode" else original.nbytes)
                    and value["included_in_native_api_timing"] is False,
                    "original API/staging/copy telemetry differs",
                )
    warmups = [json.loads(path.read_text()) for path in (run / "warmup").glob("*.json")]
    require(len(warmups) == config_count, "warmup universe incomplete")
    if formal:
        require(
            all(
                item["threshold_satisfied"]
                and item["completed_iterations"] >= 3
                and item["elapsed_wall_ns"] >= 500_000_000
                for item in warmups
            ),
            "warmup insufficient",
        )
    report = json.loads((run / "report/report.json").read_text())
    for filename, digest in report["source_hashes"].items():
        require(sha(report_source_path(run, filename)) == digest, "report source artifact drift")
    require(
        report["task_count"] == config_count
        and report["eligible_run_count"] == sum(r["eligibility"] for r in records)
        and report["summary_count"] == (config_count if formal else 0),
        "report counts differ",
    )
    audit_raw_projection_and_coverage(run, tasks, records)
    if formal:
        audit_summary(run)
        for summary in report["summaries"]:
            accepted = [
                r for r in records if r["config_id"] == summary["config_id"] and r["eligibility"]
            ]
            accepted.sort(key=lambda record: record["repetition_index"])
            require(
                len({r["execution_path_hash"] for r in accepted}) == 1
                and summary["execution_path_hash"] == accepted[0]["execution_path_hash"],
                "summary mixes or invents execution paths",
            )
            group = {
                field: summary[field]
                for field in (
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
                == stable_id(
                    "summary",
                    {
                        **group,
                        "run_ids": [r["run_id"] for r in accepted],
                    },
                ),
                "summary identity differs from actual repetitions",
            )
            audit_independent_statistics(summary, accepted, report["policy"])
    return records, params_to_stream


def audit_unsupported(run: Path, manifest, source: dict, runtime: str) -> list[dict]:
    """Capability rejections retain provenance but must never claim execution."""
    codec_snapshot = json.loads((run / "codec_registry_snapshot.json").read_text())
    matches = [item for item in codec_snapshot["codecs"] if item["key"] == manifest.key]
    require(
        len(matches) == 1
        and matches[0]["algorithm_id"] == manifest.algorithm_id
        and matches[0]["manifest"] == manifest.document,
        "unsupported codec snapshot differs",
    )
    source_snapshot = json.loads((run / "source_registry_snapshot.json").read_text())
    matches = [
        item for item in source_snapshot["sources"] if item["identity"] == source["identity"]
    ]
    require(matches == [source], "unsupported source snapshot differs")
    params_by_id = configuration_matrix(run, manifest)
    tasks = rows(run / "task_plan.jsonl")
    diagnostics = rows(run / "run_components.jsonl")
    expected = set(itertools.product(params_by_id, ("VALUE", "TIMESTAMP")))
    require(
        len(tasks) == len(diagnostics) == len(expected)
        and {(task["config_id"], task["track"]) for task in tasks} == expected
        and len({task["task_id"] for task in tasks}) == len(expected)
        and len({record["run_id"] for record in diagnostics}) == len(expected)
        and Counter(record["task_id"] for record in diagnostics)
        == Counter(task["task_id"] for task in tasks),
        "unsupported task/configuration universe incomplete",
    )
    by_task = {task["task_id"]: task for task in tasks}
    for record in diagnostics:
        task = by_task[record["task_id"]]
        audit_stage_plan(task, manifest)
        execution = task["execution"]
        compatibility = task["compatibility"]
        require(
            task["algorithm_id"] == record["algorithm_id"] == manifest.algorithm_id
            and task["dataset_id"] == record["dataset_id"]
            and task["config_id"] == record["config_id"]
            and task["track"] == record["track"]
            and execution["source_artifact_id"] == manifest.source_artifact_id
            and execution["artifact_sha256"] == runtime
            and record["execution_path_hash"] == execution["execution_path_hash"],
            "unsupported task/runtime identity differs",
        )
        require(
            task["status"]
            == execution["status"]
            == compatibility["status"]
            == record["status"]
            == "UNSUPPORTED"
            and task["reason_code"]
            == execution["reason_code"]
            == compatibility["reason_code"]
            == record["reason_code"]
            == "CAPABILITY_MISMATCH"
            and execution["actual_isa"] == "NOT_EXECUTED"
            and execution["requested_isa"] == "SSE4_1"
            and execution["fallback_used"] is False
            and task["comparability"]["execution_document"]["actual_isa"] == "NOT_EXECUTED"
            and record["record_kind"] == "DIAGNOSTIC"
            and record["eligibility"] is False,
            "capability rejection falsely claims execution",
        )
        require(
            compatibility["operations"] == []
            and compatibility["output_descriptor"] is None
            and compatibility["input_descriptor"]["dtype_vector"]
            == (["<i8"] if task["track"] == "TIMESTAMP" else ["<f8"] * 7),
            "unsupported input silently converted",
        )
        require(
            all(
                record[field] is None
                for field in (
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
            preflight["status"] == "UNSUPPORTED"
            and preflight["reason_code"] == "CAPABILITY_MISMATCH"
            and preflight["eligible_for_formal_repetitions"] is False
            and preflight["boundary"]
            is preflight["correctness"]
            is preflight["accounting"]
            is None,
            "unsupported preflight fabricated a successful check",
        )
    require(not list((run / "artifacts").glob("*.bin")), "unsupported task emitted a stream")
    require(not list((run / "warmup").glob("*.json")), "unsupported task was warmed up")
    for layer in range(2, 6):
        require(bool(list(run.glob(f"layer{layer}-*.json"))), "unsupported layer evidence absent")
    report = json.loads((run / "report/report.json").read_text())
    for filename, digest in report["source_hashes"].items():
        require(
            sha(report_source_path(run, filename)) == digest,
            "unsupported report source artifact drift",
        )
    require(
        report["task_count"] == len(expected)
        and report["eligible_run_count"] == report["summary_count"] == 0
        and report["summaries"] == []
        and report["source_hashes"]["run_components.jsonl"] == sha(run / "run_components.jsonl"),
        "unsupported report dropped tasks or admitted diagnostics",
    )
    for filename, digest in report["derived_artifact_hashes"].items():
        require(sha(run / filename) == digest, "unsupported derived report drift")
    audit_raw_projection_and_coverage(run, tasks, diagnostics)
    return diagnostics


def audit_run_sets(key: str, names: list[str]) -> dict:
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest, source, runtime, sdk = source_and_runtime(registry, key)
    fixture = ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz"
    dataset = json.loads((ROOT / "registry/datasets/streamvbyte_u32_uts.json").read_text())
    require(sha(fixture) == dataset["file"]["sha256"], "original fixture drift")
    with np.load(fixture, allow_pickle=False) as archive:
        original = archive["values"]
    require(original.dtype.str == "<u4" and len(original) == 8193, "fixture contract differs")
    records_by_run, hashes_by_run = [], []
    for index, name in enumerate(names[:2]):
        run = ROOT / "runs" / name
        canonical_paths = list((run / "datasets").glob("*/*.canonical.tscb"))
        require(len(canonical_paths) == 1, "Layer1 canonical artifact absent")
        canonical = read_canonical(canonical_paths[0], include_buffers=True)
        require(
            list(canonical.buffers.values()) == [original.tobytes()],
            "Layer1 source/canonical bytes differ",
        )
        records, hashes = audit_supported(run, manifest, source, runtime, index == 0, original)
        records_by_run.append(records)
        hashes_by_run.append(hashes)
    require(hashes_by_run[0] == hashes_by_run[1], "qualification/formal objects differ")
    diagnostics = audit_unsupported(ROOT / "runs" / names[2], manifest, source, runtime)
    formal = records_by_run[0]
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
        "formal_attempts": len(formal),
        "eligible_repetitions": sum(r["eligibility"] for r in formal),
        "resource_pressure_attempts": sum(r["status"] == "RESOURCE_PRESSURE" for r in formal),
        "qualification_attempts": len(records_by_run[1]),
        "unsupported_diagnostics": len(diagnostics),
        "configurations": len(expected_matrix(key)),
        "unique_seed_streams": len(hashes_by_run[0]),
        "status_counts": dict(Counter(r["status"] for r in formal)),
        "sdk_evidence": sdk,
        "supported_fixture": "SYNTHETIC_FULL_RANGE_UINT32_UTS",
        "scope": "ORIGINAL_LEB128_PLAIN"
        if key == KEYS[0]
        else "ORIGINAL_FUSED_MODULAR32_D1_LEB128_FOUR_EDGE_SEEDS",
        "int64_timestamp_qualification": "NOT_CLAIMED",
        "full_logical_entry_qualified": False,
        "raw_components_sha256": sha(ROOT / "runs" / names[0] / "run_components.jsonl"),
        "auditor_sha256": sha(Path(__file__)),
        "audit_dependencies": [
            {
                "path": "tools/streamvbyte_audit_common.py",
                "sha256": sha(ROOT / "tools/streamvbyte_audit_common.py"),
            },
            {
                "path": "tools/audit_maskedvbyte_sdk.py",
                "sha256": sha(ROOT / "tools/audit_maskedvbyte_sdk.py"),
            },
        ],
    }
    output = ROOT / f"build/source-audits/{key}-five-layer-audit.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formal_run_set_id")
    parser.add_argument("qualification_run_set_id")
    parser.add_argument("--key", choices=KEYS, default=KEYS[0])
    parser.add_argument("--unsupported-run-set-id")
    args = parser.parse_args()
    key = args.key
    names = [
        args.formal_run_set_id,
        args.qualification_run_set_id,
        args.unsupported_run_set_id or f"{key}-unsupported-qualification-20261007-2",
    ]
    require(all(Path(name).name == name for name in names), "unsafe run set ID")
    try:
        result = audit_run_sets(key, names)
    except Exception as error:
        path = ROOT / f"build/source-audits/{key}-five-layer-audit.json"
        path.write_text(
            json.dumps(
                {
                    "status": "FAIL",
                    "codec_key": key,
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
