"""Audit actual five-layer runs against current source and independent D1 math."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import statistics
import struct
from collections import Counter
from pathlib import Path

import numpy as np
from audit_fast_differential_native import audit, require, sha
from streamvbyte_audit_common import audit_run_provenance, audit_summary, formal_direction_durations_satisfied

from tscompbench.adapters.factory import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.datasets.canonical import read_canonical
from tscompbench.ids import canonical_json_bytes, stable_id

ROOT = Path(__file__).resolve().parents[1]
KEY = "fast-differential-u32"
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
MATRIX = set(itertools.product(("DISTINCT", "INPLACE"), (0, 1, 2**31, 2**32 - 1), (False, True)))


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def report_source_path(run: Path, filename: str) -> Path:
    # The report labels current Python implementation hashes separately from
    # files stored in the run directory. Verify both against their actual owners.
    if filename.startswith("implementation/"):
        return ROOT / "src/tscompbench" / filename.removeprefix("implementation/")
    return run / filename


def source_and_runtime(registry: CodecRegistry) -> tuple:
    native = audit()
    manifest = registry.get(KEY)
    source = registry.sources.get(manifest.source_artifact_id)
    require(
        source["identity"]["repository"] == "https://github.com/lemire/FastDifferentialCoding"
        and source["identity"]["commit"] == "714a9febba97ffb6b574c7a41cf1142090558727",
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
    require(
        source["license"]["status"] == "RUN_ALLOWED" and source["license"]["spdx"] == "Apache-2.0",
        "registered license differs",
    )
    card = validate_onboarding_card(
        json.loads((ROOT / f"registry/onboarding/{KEY}.json").read_text())
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
            (
                ROOT / f"build/adapters/fast_differential_u32/{item['kind']}/build-record.json"
            ).read_text()
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
        len(configs) == 16 and len({item["config_id"] for item in configs}) == 16,
        "configuration matrix incomplete",
    )
    require(
        {
            (
                item["parameters"]["api_mode"],
                item["parameters"]["starting_point"],
                item["parameters"]["native_timing"],
            )
            for item in configs
        }
        == MATRIX,
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


def independent_frame(stream: bytes, params: dict, original: np.ndarray) -> dict:
    require(len(stream) >= PREFIX.size, "truncated complete object")
    magic, length, digest = PREFIX.unpack_from(stream)
    require(magic == b"TSCBFDP1" and length <= 4096, "wrong complete object prefix")
    descriptor = stream[PREFIX.size : PREFIX.size + length]
    require(hashlib.sha256(descriptor).digest() == digest, "descriptor checksum differs")
    info = json.loads(descriptor)
    require(descriptor == canonical_json_bytes(info), "descriptor is not canonical JSON")
    expected_params = {key: params[key] for key in ("api_mode", "isa", "starting_point")}
    require(
        info["parameters"] == expected_params
        and info["count"] == len(original)
        and info["buffer"]["dtype"] == "<u4"
        and info["buffer"]["shape"] == [len(original)],
        "descriptor geometry/parameters differ",
    )
    payload = stream[PREFIX.size + length :]
    require(len(payload) == 32 + original.nbytes, "actual physical frame length differs")
    header = struct.unpack_from("<8sIIII", payload)
    require(
        header
        == (
            b"TSCBFDC1",
            len(original),
            params["starting_point"],
            int(params["api_mode"] == "INPLACE"),
            0,
        ),
        "FDC1 identity differs",
    )
    checksum = 14695981039346656037
    for value in payload[:-8]:
        checksum = ((checksum ^ value) * 1099511628211) % 2**64
    require(
        struct.unpack_from("<Q", payload, len(payload) - 8)[0] == checksum, "FDC1 checksum differs"
    )
    words = np.frombuffer(payload[24:-8], dtype="<u4")
    previous = params["starting_point"]
    for index, value in enumerate(original):
        require(
            int(words[index]) == (int(value) - previous) % 2**32,
            "actual word differs from independent D1 oracle",
        )
        previous = (previous + int(words[index])) % 2**32
        require(previous == int(value), "independent modular prefix sum differs")
    return {
        "value_bits": original.nbytes * 8,
        "metadata_bits": (length + 16) * 8,
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
    expected_count = 320 if formal else 16
    require(
        len(tasks) == 16
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
    require(len(streams) == 8, "serialized mode/seed objects missing")
    params_to_stream = {}
    for task in tasks:
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
        require(
            len({record["bitstream_sha256"] for record in observed}) == 1,
            "non-deterministic stream",
        )
        stream_hash = observed[0]["bitstream_sha256"]
        require(stream_hash in streams, "actual bitstream artifact missing")
        stream = streams[stream_hash].read_bytes()
        physical = independent_frame(stream, params, original)
        session = create_adapter(ROOT, manifest).create_session(
            {
                "api_mode": "INPLACE" if params["api_mode"] == "DISTINCT" else "DISTINCT",
                "starting_point": (2**32 - 1) ^ params["starting_point"],
            }
        )
        try:
            require(
                session.decompress(stream).buffers[0].array.tobytes() == original.tobytes(),
                "fresh independently configured decoder differs",
            )
        finally:
            session.close()
        identity = (params["api_mode"], params["starting_point"])
        require(
            identity not in params_to_stream or params_to_stream[identity] == stream_hash,
            "native timing switch changes stream bytes",
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
                    formal_direction_durations_satisfied(timing),
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
                require(
                    value["api_mode"] == params["api_mode"]
                    and value["internal_padding_bytes"] == 0
                    and value["native_staging_allocation_bytes"]
                    == 4 * len(original) * (1 if params["api_mode"] == "INPLACE" else 2)
                    and value["native_staging_input_copy_bytes"] == original.nbytes
                    and value["native_staging_output_copy_bytes"] == original.nbytes,
                    "mode/copy/allocation telemetry differs",
                )
    warmups = [json.loads(path.read_text()) for path in (run / "warmup").glob("*.json")]
    require(len(warmups) == 16, "warmup universe incomplete")
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
        report["task_count"] == 16
        and report["eligible_run_count"] == sum(r["eligibility"] for r in records)
        and report["summary_count"] == (16 if formal else 0),
        "report counts differ",
    )
    if formal:
        audit_summary(run)
        for summary in report["summaries"]:
            accepted = [
                r for r in records if r["config_id"] == summary["config_id"] and r["eligibility"]
            ]
            for prefix in ("pipeline_encode", "pipeline_decode", "native_encode", "native_decode"):
                field = prefix + "_wall_ns"
                values = [r["timing"][field] for r in accepted]
                if any(value is None for value in values):
                    require(
                        all(
                            summary[prefix + suffix] is None
                            for suffix in (
                                "_ns_mean",
                                "_ns_median",
                                "_ns_sd",
                                "_mb_per_second_micro",
                            )
                        )
                        and summary[prefix + "_observation_count"] == 0,
                        "null native summary fabricated",
                    )
                else:
                    per_object = [
                        value / r["timing"]["inner_iterations"]
                        for value, r in zip(values, accepted, strict=True)
                    ]
                    for suffix, result in (
                        ("mean", statistics.mean(per_object)),
                        ("median", statistics.median(per_object)),
                        ("sd", statistics.stdev(per_object)),
                    ):
                        require(
                            math.isclose(summary[prefix + "_ns_" + suffix], result, rel_tol=1e-12),
                            "independently recomputed summary differs",
                        )
                    rate = (
                        sum(original.nbytes * r["timing"]["inner_iterations"] for r in accepted)
                        * 1000
                        / sum(values)
                    )
                    require(
                        math.isclose(
                            float(summary[prefix + "_mb_per_second_micro"]), rate, rel_tol=1e-12
                        ),
                        "micro throughput is not total bytes / total time",
                    )
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
        len(tasks) == len(diagnostics) == len(expected) == 32
        and {(task["config_id"], task["track"]) for task in tasks} == expected
        and len({task["task_id"] for task in tasks}) == 32
        and len({record["run_id"] for record in diagnostics}) == 32
        and Counter(record["task_id"] for record in diagnostics)
        == Counter(task["task_id"] for task in tasks),
        "unsupported task/configuration universe incomplete",
    )
    by_task = {task["task_id"]: task for task in tasks}
    for record in diagnostics:
        task = by_task[record["task_id"]]
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
            and task["preprocess"]["stages"] == []
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
        report["task_count"] == 32
        and report["eligible_run_count"] == report["summary_count"] == 0
        and report["summaries"] == []
        and report["source_hashes"]["run_components.jsonl"] == sha(run / "run_components.jsonl"),
        "unsupported report dropped tasks or admitted diagnostics",
    )
    for filename, digest in report["derived_artifact_hashes"].items():
        require(sha(run / filename) == digest, "unsupported derived report drift")
    return diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formal_run_set_id")
    parser.add_argument("qualification_run_set_id")
    parser.add_argument(
        "--unsupported-run-set-id",
        default="fast-differential-u32-unsupported-qualification-20261007-1",
    )
    args = parser.parse_args()
    names = [args.formal_run_set_id, args.qualification_run_set_id, args.unsupported_run_set_id]
    require(all(Path(name).name == name for name in names), "unsafe run set ID")
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest, source, runtime, native = source_and_runtime(registry)
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
    unsupported = ROOT / "runs" / names[2]
    diagnostics = audit_unsupported(unsupported, manifest, source, runtime)
    formal = records_by_run[0]
    result = {
        "status": "PASS",
        "codec_key": KEY,
        "object_level": "P0_PRIMITIVE",
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
        "configurations": 16,
        "unique_mode_seed_streams": len(hashes_by_run[0]),
        "status_counts": dict(Counter(r["status"] for r in formal)),
        "native_evidence": native,
        "supported_fixture": "SYNTHETIC_FULL_RANGE_UINT32_UTS",
        "scope": "FOUR_ORIGINAL_D1_APIS_BOTH_MODES_FOUR_EDGE_SEEDS_NATIVE_TIMER_ON_OFF",
        "int64_timestamp_or_backend_pipeline_qualification": "NOT_CLAIMED",
        "full_logical_entry_qualified": False,
        "raw_components_sha256": sha(ROOT / "runs" / names[0] / "run_components.jsonl"),
        "auditor_sha256": sha(Path(__file__)),
    }
    output = ROOT / "build/source-audits/fast-differential-u32-five-layer-audit.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        path = ROOT / "build/source-audits/fast-differential-u32-five-layer-audit.json"
        path.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
