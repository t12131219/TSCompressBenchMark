#!/usr/bin/env python3
"""Run the frozen UCR source-vs-rewrite ABBA dataset plan."""

import argparse
import hashlib
import json
import math
import pathlib
import struct
import subprocess
import sys


CASES = [
    ("ucr2018:ECG5000:TEST:rows0-11", "UCRArchive_2018/ECG5000/ECG5000_TEST.tsv",
     "0192997dd1793880633bfb34ae3ad5129c09a8e0f210c469225451b92cdd8548",
     "436bade1ff860a6eeaaa23c8dd362fb6cb0f75a965c9da7a83f818db0b1e38b0"),
    ("ucr2018:Chinatown:TEST:rows0-11", "UCRArchive_2018/Chinatown/Chinatown_TEST.tsv",
     "9662e20a0ca8ca6a22f704103a36e16ccfb8dae23cccacdcb20e38ac9308efae",
     "952e675d509dcdacb0073653ae8013fecf64d122dacaa94d9671b7f6249203a0"),
    ("ucr2018:Coffee:TEST:rows0-11", "UCRArchive_2018/Coffee/Coffee_TEST.tsv",
     "07f25cedb9fd819a201e7de6abbdc444695b4b16ee70295010e401f18c38babd",
     "c8a94ca756470f8e5909b78df201b3255765c9e0565e99f7c427160170de5f06"),
]


def load_rows(path):
    rows = []
    with path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index >= 12:
                break
            values = [float(value) for value in line.rstrip().split("\t")[1:]]
            if len(values) < 2 or not all(math.isfinite(value) for value in values):
                raise ValueError("invalid dataset row")
            rows.append(values)
    if len(rows) != 12:
        raise ValueError("dataset does not contain 12 rows")
    return rows


def canonical_hash(rows):
    digest = hashlib.sha256()
    for row in rows:
        digest.update(struct.pack("<Q", len(row)))
        for value in row:
            digest.update(struct.pack("<d", value))
    return digest.hexdigest()


def run_oracle_batch(script, cli, requests):
    payload = "".join(json.dumps(request) + "\n" for request in requests)
    completed = subprocess.run(
        [sys.executable, str(script), "--ckmeans-cli", str(cli)],
        input=payload, text=True, capture_output=True, check=True,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
    if len(responses) != len(requests):
        raise RuntimeError("source oracle response count mismatch")
    results = []
    for response in responses:
        if not response["ok"]:
            raise RuntimeError(response["error"])
        results.append(response["result"])
    return results


def run_cpp(cli, values):
    payload = str(len(values)) + "\n" + " ".join(map(str, values)) + "\n"
    completed = subprocess.run(
        [str(cli), "--operation", "transform"], input=payload, text=True,
        capture_output=True, check=True,
    )
    response = json.loads(completed.stdout)
    if not response["ok"]:
        raise RuntimeError(response["error"])
    return response["result"]


def compare(reference, actual, path="result"):
    if isinstance(reference, dict):
        for key, value in reference.items():
            compare(value, actual[key], path + "." + key)
    elif isinstance(reference, list):
        if len(reference) != len(actual):
            raise AssertionError(path + " length mismatch")
        for index, (left, right) in enumerate(zip(reference, actual)):
            compare(left, right, "{}[{}]".format(path, index))
    elif isinstance(reference, int):
        if reference != actual:
            raise AssertionError(path + " integer mismatch")
    else:
        tolerance = 1e-10 + 1e-12 * abs(reference)
        if not math.isfinite(actual) or abs(reference - actual) > tolerance:
            raise AssertionError(path + " numeric mismatch")


def metrics(original, reconstructed):
    errors = [left - right for left, right in zip(original, reconstructed)]
    return {
        "rmse": math.sqrt(sum(value * value for value in errors) / len(errors)),
        "max_abs_error": max(abs(value) for value in errors),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpp-cli", required=True, type=pathlib.Path)
    parser.add_argument("--oracle", required=True, type=pathlib.Path)
    parser.add_argument("--ckmeans-cli", required=True, type=pathlib.Path)
    parser.add_argument("--datasets-root", required=True, type=pathlib.Path)
    parser.add_argument("--json-output", required=True, type=pathlib.Path)
    args = parser.parse_args()

    result = {
        "schema_version": "tscb.abba-dataset-result.v1",
        "algorithm_id": "abba",
        "profile": "ckmeans-scl0-norm2-v1",
        "cases": [],
        "summary": {"series": 0, "samples": 0, "final_bits": 0},
    }
    for dataset_id, relative, file_hash, input_hash in CASES:
        path = args.datasets_root / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != file_hash:
            raise RuntimeError("source hash mismatch for " + dataset_id)
        rows = load_rows(path)
        if canonical_hash(rows) != input_hash:
            raise RuntimeError("canonical input hash mismatch for " + dataset_id)
        requests = [{"operation": "transform", "values": row} for row in rows]
        source_results = run_oracle_batch(args.oracle, args.ckmeans_cli, requests)
        series_results = []
        for index, (row, source) in enumerate(zip(rows, source_results)):
            rewrite = run_cpp(args.cpp_cli, row)
            compare(source, rewrite, dataset_id + ":" + str(index))
            source_metrics = metrics(row, source["reconstructed"])
            rewrite_metrics = metrics(row, rewrite["reconstructed"])
            compare(source_metrics, rewrite_metrics, dataset_id + ":metrics")

            decoded = subprocess.run(
                [str(args.cpp_cli), "--operation", "decode-container"],
                input=rewrite["container_hex"] + "\n", text=True,
                capture_output=True, check=True,
            )
            decoded_values = json.loads(decoded.stdout)["result"]["reconstructed"]
            compare(rewrite["reconstructed"], decoded_values,
                    dataset_id + ":container")
            series_results.append({
                "row": index,
                "sample_count": len(row),
                "piece_count": len(rewrite["pieces"]),
                "center_count": len(rewrite["centers"]),
                "rmse": rewrite_metrics["rmse"],
                "max_abs_error": rewrite_metrics["max_abs_error"],
                "final_bits": rewrite["accounting"]["final_bits"],
                "status": "PASS",
            })
            result["summary"]["series"] += 1
            result["summary"]["samples"] += len(row)
            result["summary"]["final_bits"] += rewrite["accounting"]["final_bits"]
        result["cases"].append({
            "dataset_id": dataset_id,
            "canonical_input_sha256": input_hash,
            "series": series_results,
            "status": "PASS",
        })
    result["summary"]["status"] = "PASS"
    args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
    print("validated {series} series and {samples} samples".format(**result["summary"]))


if __name__ == "__main__":
    main()

