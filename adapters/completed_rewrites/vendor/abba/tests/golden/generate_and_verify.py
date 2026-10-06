#!/usr/bin/env python3
"""Generate or verify ABBA G2 vectors using the frozen executable oracle."""

import argparse
import json
import pathlib
import subprocess
import sys


CASES = [
    {"name": "readme-example", "request": {"operation": "transform", "values": [-1, 0.1, 1.3, 2, 1.9, 2.4, 1.8, 0.8, -0.5]}},
    {"name": "norm2-upstream", "request": {"operation": "transform", "config": {"compression_tol": 2.0, "digitization_tol": 2.0}, "values": [0, 2, 3, 2, 4, -1, 0, -1, 1, 0, -4, 0]}},
    {"name": "two-samples", "request": {"operation": "transform", "values": [1, 3]}},
    {"name": "flat", "request": {"operation": "transform", "values": [1, 1, 1, 1, 1, 1, 1, 1]}},
    {"name": "alternating", "request": {"operation": "transform", "values": [1, -1, 1, -1, 1, -1, 1, -1]}},
    {"name": "max-len", "request": {"operation": "transform", "config": {"max_len": 2}, "values": [0, 1, 2, 3, 4, 5, 6, 7]}},
    {"name": "zero-tolerance", "request": {"operation": "transform", "config": {"compression_tol": 0.0, "digitization_tol": 0.0, "max_k": 8}, "values": [0, 1, 4, 9, 16, 25]}},
    {"name": "digitize-upstream-scl0", "request": {"operation": "digitize", "config": {"min_k": 2}, "pieces": [[4, 4], [1, -5], [4, 1], [1, -4], [1, 4]]}},
    {"name": "symbol-population-tie", "request": {"operation": "digitize", "config": {"min_k": 2}, "pieces": [[1, 1], [50, 50], [100, 100], [2, 2], [51, 51], [3, 3]]}},
    {"name": "ties-to-even-quantization", "request": {"operation": "decode", "symbols": [0, 0, 0, 0, 0, 0, 0, 0], "centers": [[1.5, 1.0]], "first_value": 0.0}},
]


def run_oracle(script, cli, request):
    completed = subprocess.run(
        [sys.executable, str(script), "--ckmeans-cli", str(cli), "--request", json.dumps(request)],
        text=True, capture_output=True, check=True,
    )
    response = json.loads(completed.stdout)
    if not response["ok"]:
        raise RuntimeError(response["error"])
    return response["result"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", required=True, type=pathlib.Path)
    parser.add_argument("--ckmeans-cli", required=True, type=pathlib.Path)
    parser.add_argument("--vectors", required=True, type=pathlib.Path)
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()

    actual = {
        "schema_version": "tscb.abba-golden.v1",
        "source_commit": "614d56841cd2f1c2925cea4d2c2648a7b2ac791d",
        "canonical_profile": "ckmeans-scl0-norm2-v1",
        "vectors": [
            {**case, "expected": run_oracle(args.oracle, args.ckmeans_cli, case["request"])}
            for case in CASES
        ],
    }
    text = json.dumps(actual, indent=2, sort_keys=True) + "\n"
    if args.generate:
        args.vectors.write_text(text, encoding="utf-8")
        print("generated", len(CASES), "golden vectors")
        return
    expected = args.vectors.read_text(encoding="utf-8")
    if expected != text:
        raise SystemExit("golden vector mismatch")
    print("verified", len(CASES), "golden vectors")


if __name__ == "__main__":
    main()
