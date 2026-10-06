#!/usr/bin/env python3
# Copyright 2026 TSDataCompressBenchMark contributors.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    path: str
    timestamp_format: str
    source_hash: str
    rows: int


DATASETS = (
    Dataset("ett:ETTh1:OT", "ETTh1.csv", "%Y-%m-%d %H:%M:%S",
            "f18de3ad269cef59bb07b5438d79bb3042d3be49bdeecf01c1cd6d29695ee066", 17420),
    Dataset("ett:exchange_rate:OT", "exchange_rate.csv", "%Y/%m/%d %H:%M",
            "48b4d9d3d508f5104162e85b9a6042e3557fde11aa9f2944eba8c0d0efc89842", 7588),
    Dataset("ett:national_illness:OT", "national_illness.csv", "%Y-%m-%d %H:%M:%S",
            "93601f64d2566dc796ca4305adad8b8560c2db1a1ff04543c3bd813a7263570a", 966),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(root: Path, dataset: Dataset) -> tuple[list[tuple[int, int, int]], bytes, bytes]:
    path = root / dataset.path
    source = path.read_bytes()
    if sha256(source) != dataset.source_hash:
        raise RuntimeError(f"{dataset.path}: source hash differs from frozen plan")
    samples = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or "date" not in reader.fieldnames or "OT" not in reader.fieldnames:
            raise RuntimeError(f"{dataset.path}: required date/OT columns are absent")
        for row_number, row in enumerate(reader, start=2):
            try:
                parsed = datetime.strptime(row["date"], dataset.timestamp_format).replace(tzinfo=timezone.utc)
                timestamp = int(parsed.timestamp()) * 1000
                bits = struct.unpack(">Q", struct.pack(">d", float(row["OT"])))[0]
            except (TypeError, ValueError) as error:
                raise RuntimeError(f"{dataset.path}:{row_number}: {error}") from error
            samples.append((0, timestamp, bits))
    if len(samples) != dataset.rows:
        raise RuntimeError(f"{dataset.path}: got {len(samples)} rows, expected {dataset.rows}")
    binary = b"".join(struct.pack(">qqQ", *sample) for sample in samples)
    text = "".join(f"{st} {timestamp} {bits}\n" for st, timestamp, bits in samples).encode("ascii")
    return samples, binary, text


def run(executable: Path, mode: str, stdin: bytes, runner: Path | None = None) -> bytes:
    command = [str(executable), mode]
    if runner is not None:
        command.insert(0, str(runner))
    result = subprocess.run(command, input=stdin, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{executable.name} {mode} failed: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout.strip()


def parse(output: bytes) -> list[tuple[int, int, int]]:
    samples = []
    for line in output.decode("ascii").splitlines():
        if line.strip():
            st, timestamp, bits = line.split()
            samples.append((int(st), int(timestamp), int(bits, 16)))
    return samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpp-cli", required=True, type=Path)
    parser.add_argument("--go-oracle", required=True, type=Path)
    parser.add_argument("--cpp-runner", type=Path)
    parser.add_argument("--datasets-root", required=True, type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    cases = []
    for dataset in DATASETS:
        samples, canonical_binary, canonical_text = load(args.datasets_root, dataset)
        go_encoded = run(args.go_oracle, "encode", canonical_text)
        cpp_encoded = run(args.cpp_cli, "encode", canonical_text, args.cpp_runner)
        if go_encoded != cpp_encoded:
            raise AssertionError(f"{dataset.dataset_id}: physical bytes differ")
        decoded = (
            parse(run(args.go_oracle, "decode", go_encoded + b"\n")),
            parse(run(args.cpp_cli, "decode", cpp_encoded + b"\n", args.cpp_runner)),
            parse(run(args.go_oracle, "decode", cpp_encoded + b"\n")),
            parse(run(args.cpp_cli, "decode", go_encoded + b"\n", args.cpp_runner)),
        )
        if any(path != samples for path in decoded):
            raise AssertionError(f"{dataset.dataset_id}: self/cross decode differs")
        encoded = bytes.fromhex(go_encoded.decode("ascii"))
        raw_bits = len(samples) * 192
        final_bits = len(encoded) * 8
        cases.append({
            "dataset_id": dataset.dataset_id,
            "relative_path": dataset.path,
            "source_file_sha256": dataset.source_hash,
            "selected_columns": ["date", "OT"],
            "start_timestamp_policy": "constant signed int64 zero",
            "timestamp_policy": "parse as UTC signed int64 Unix milliseconds",
            "value_policy": "parse as IEEE-754 binary64 and preserve uint64 bits",
            "shape": [len(samples), 3],
            "row_range": [0, len(samples)],
            "canonical_record_encoding": "big-endian int64 ST, int64 timestamp, uint64 value bits",
            "canonical_input_sha256": sha256(canonical_binary),
            "canonical_text_sha256": sha256(canonical_text),
            "config_sha256": sha256(b"prometheus-xor2-chunk:EncXOR2:ST=0:one-chunk:v1\n"),
            "sample_count": len(samples),
            "canonical_raw_bits": raw_bits,
            "serialized_bits": final_bits,
            "external_side_information_bits": 0,
            "final_bits": final_bits,
            "compression_factor": raw_bits / final_bits,
            "source_encoded_sha256": sha256(encoded),
            "rewrite_encoded_sha256": sha256(encoded),
            "byte_identical": True,
            "source_self_decode": "PASS",
            "rewrite_self_decode": "PASS",
            "source_decodes_rewrite": "PASS",
            "rewrite_decodes_source": "PASS",
            "result": "PASS",
        })

    report = {
        "schema_version": "prometheus-xor2-dataset-validation.v1",
        "algorithm_id": "prometheus-xor2-chunk",
        "implementation_id": "prometheus-xor2-chunk-canonical-cpp",
        "compatibility_target": "CROSS_DECODE",
        "source_oracle": args.go_oracle.name,
        "cpp_cli": args.cpp_cli.name,
        "cpp_runner": args.cpp_runner.name if args.cpp_runner else None,
        "datasets_root": "datasets/",
        "selected_case_count": len(cases),
        "all_cases_passed": all(case["result"] == "PASS" for case in cases),
        "cases": cases,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_output:
        args.json_output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
