"""Audit authoritative LZSSE2 five-layer raw/report/source evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from tscompbench.adapters.lzsse2_raw import Lzsse2RawSession
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card

ROOT = Path(__file__).resolve().parents[1]


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formal_run_set_id")
    parser.add_argument("qualification_run_set_id")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(
            "/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/inikep_lzbench"
        ),
    )
    args = parser.parse_args()
    for name in (args.formal_run_set_id, args.qualification_run_set_id):
        if Path(name).name != name:
            raise ValueError("run set ID must be a single path component")
    run = ROOT / "runs" / args.formal_run_set_id
    qualification = ROOT / "runs" / args.qualification_run_set_id
    records = rows(run / "run_components.jsonl")
    assert len(records) == 10
    assert {r["repetition_index"] for r in records} == set(range(10))
    assert len({r["run_id"] for r in records}) == 10
    assert len({r["execution_path_hash"] for r in records}) == 1
    assert len({r["bitstream_sha256"] for r in records}) == 1
    components = [
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
    ]
    for record in records:
        assert record["status"] == record["correctness"]["status"] == "PASS"
        assert record["eligibility"]
        assert record["diagnostics"]["same_repetition_correctness_and_measurement"]
        timing = record["timing"]
        assert timing["selected_wall_ns"] >= 1_000_000_000
        assert timing["min_duration_satisfied"]
        assert timing["native_timing_boundary"] == "CODEC_API_ONLY_V1"
        assert timing["native_timing_clock"] == "CLOCK_MONOTONIC"
        for operation in ["encode", "decode"]:
            assert 0 < timing[f"native_{operation}_wall_ns"] <= timing[f"core_{operation}_wall_ns"]
            assert timing[f"core_{operation}_wall_ns"] <= timing[f"pipeline_{operation}_wall_ns"]
        ledger = record["accounting"]
        assert sum(ledger[k] for k in components) == ledger["serialized_bits"]
        assert ledger["final_bits"] == ledger["final_physical_bytes"] * 8
        assert ledger["external_side_information_bits"] == ledger["checksum_bits"] == 0
        assert ledger["canonical_raw_bits"] == 432768
        assert record["finalize_bytes"] == 0
    (task,) = rows(run / "task_plan.jsonl")
    assert task["execution"]["cpu_affinity"] == [0]
    assert task["execution"]["actual_isa"] == "SSE4_1"
    assert not task["execution"]["fallback_used"]
    preflight = json.loads(
        (run / "preflight" / (task["task_id"].split(":")[-1] + ".json")).read_text()
    )
    observations = preflight["boundary"]["observations"]
    assert len(observations) == 49 and all(x["status"] == "PASS" for x in observations)
    events = rows(run / "events.jsonl")
    (warmup,) = [e["payload"] for e in events if e["event_type"] == "TASK_WARMUP_COMPLETED"]
    assert warmup["completed_iterations"] >= 3 and warmup["elapsed_wall_ns"] >= 500_000_000
    qual = rows(qualification / "run_components.jsonl")
    assert len(qual) == 1 and qual[0]["status"] == "PASS" and qual[0]["eligibility"] is False
    card = validate_onboarding_card(
        json.loads((ROOT / "registry/onboarding/lzsse2-raw.json").read_text())
    )
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    assert card["source_artifact_id"] == registry.get("lzsse2-raw").source_artifact_id
    for build in card["builds"]:
        directory = ROOT / f"build/adapters/lzsse2_raw/{build['profile']}"
        binary = directory / "libtscb_lzsse2_raw.so"
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == build["artifact_sha256"]
        assert (
            json.loads((directory / "build-record.json").read_text())["compile_commands_sha256"]
            == build["compile_commands_sha256"]
        )
        command_bytes = (directory / "compile-command.json").read_bytes().removesuffix(b"\n")
        assert hashlib.sha256(command_bytes).hexdigest() == build["compile_commands_sha256"]
        command = json.loads(command_bytes)
        assert (
            hashlib.sha256((directory / "lzsse2.cpp").read_bytes()).hexdigest()
            == command["patched_translation_unit_sha256"]
        )
    vendor = ROOT / "adapters/lzsse2_raw/vendor/lzsse"
    original = args.source_root / "lz/lzsse"
    closure = hashlib.sha256()
    files = sorted(p for p in vendor.rglob("*") if p.is_file())
    assert len(files) == 5
    for file in files:
        assert file.read_bytes() == (original / file.relative_to(vendor)).read_bytes()
        closure.update(file.relative_to(vendor).as_posix().encode() + b"\0" + file.read_bytes())
    source = json.loads((ROOT / "registry/sources/lzsse2-raw-lzbench.artifact.json").read_text())
    assert closure.hexdigest() == source["identity"]["source_closure_sha256"]
    patch = ROOT / source["build"]["patches"][0]["path"]
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == source["identity"]["patch_sha256"]
    for test in card["upstream_tests"]:
        assert test["status"] == "PASS"
        assert (
            hashlib.sha256((ROOT / test["evidence"]).read_bytes()).hexdigest() == test["log_sha256"]
        )
    with (run / "summary.csv").open(newline="") as handle:
        summaries = list(csv.DictReader(handle))
    assert len(summaries) == 1
    (report,) = [e["payload"] for e in events if e["event_type"] == "LAYER_5_COMPLETED"]
    assert report["eligible_run_count"] == 10 and report["summary_count"] == 1
    stream_files = [
        p
        for p in run.rglob("*.bin")
        if hashlib.sha256(p.read_bytes()).hexdigest() == records[0]["bitstream_sha256"]
    ]
    assert stream_files, "the measured encoded object must be retained"
    header, payload = Lzsse2RawSession._parse_container(stream_files[0].read_bytes())
    decoded_bytes = sum(b["payload_bytes"] for b in header["buffers"])
    assert header["raw_storage"] == int(len(payload) == decoded_bytes)
    result = dict(
        status="PASS",
        formal_run=run.name,
        qualification_run=qualification.name,
        eligible_repetitions=10,
        boundary_observations=len(observations),
        warmup=warmup,
        selected_wall_ns_range=[
            min(r["timing"]["selected_wall_ns"] for r in records),
            max(r["timing"]["selected_wall_ns"] for r in records),
        ],
        accounting=records[0]["accounting"],
        report=report,
        summary=summaries[0],
        source_closure_sha256=closure.hexdigest(),
        patch_sha256=source["identity"]["patch_sha256"],
        combined_artifact_sha256=task["execution"]["artifact_sha256"],
        builds=card["builds"],
        raw_components_sha256=hashlib.sha256(
            (run / "run_components.jsonl").read_bytes()
        ).hexdigest(),
        raw_block_count=header["raw_storage"],
        raw_storage_bytes=len(payload) if header["raw_storage"] else 0,
        compressed_stream_bytes=len(payload),
        codec_input_bytes=decoded_bytes,
        cpu_affinity=task["execution"]["cpu_affinity"],
    )
    output = ROOT / "build/source-audits/lzsse2-final-audit-20260918.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
