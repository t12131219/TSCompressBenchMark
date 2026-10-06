#!/usr/bin/env python3
"""Generate or verify frozen fABBA G2 vectors."""

import argparse
import json
import pathlib
import subprocess
import sys

CASES = [
    {"name": "paper-shape", "request": {"values": [-1, 0.1, 1.3, 2, 1.9, 2.4, 1.8, 0.8, -0.5]}},
    {"name": "two-samples", "request": {"values": [1, 3]}},
    {"name": "flat", "request": {"values": [1, 1, 1, 1, 1, 1]}},
    {"name": "alternating", "request": {"values": [1, -1, 1, -1, 1, -1, 1]}},
    {"name": "max-len", "request": {"config": {"max_len": 2}, "values": [0, 1, 2, 3, 4, 5, 6]}},
    {"name": "zero-tolerance", "request": {"config": {"tol": 0, "alpha": 0}, "values": [0, 1, 4, 9, 16, 25]}},
    {"name": "digitize-tied-norms", "request": {"operation": "digitize", "pieces": [[1, 1], [1, -1], [2, 2], [2, -2]]}},
    {"name": "digitize-clusters", "request": {"operation": "digitize", "config": {"alpha": 0.5}, "pieces": [[4, 4], [1, -5], [4, 1], [1, -4], [1, 4]]}},
    {"name": "ties-to-even", "request": {"operation": "decode", "symbols": [0, 0, 0, 0, 0, 0, 0, 0], "centers": [[1.5, 1]], "first_value": 0}},
]


def run(script, request):
    completed = subprocess.run([sys.executable, str(script), "--request", json.dumps(request)],
                               text=True, capture_output=True, check=True)
    response = json.loads(completed.stdout)
    if not response["ok"]:
        raise RuntimeError(response["error"])
    return response["result"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", required=True, type=pathlib.Path)
    parser.add_argument("--vectors", required=True, type=pathlib.Path)
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    actual = {"schema_version": "tscb.fabba-golden.v1",
              "source_commit": "4066a5fc778f50f4bee1c41d8f3ab3ee4a3ff6ad",
              "canonical_profile": "stable-norm2-scl1-v1",
              "vectors": [{**case, "expected": run(args.oracle, case["request"])}
                          for case in CASES]}
    text = json.dumps(actual, indent=2, sort_keys=True) + "\n"
    if args.generate:
        args.vectors.write_text(text, encoding="utf-8")
        print("generated", len(CASES), "golden vectors")
    elif args.vectors.read_text(encoding="utf-8") != text:
        raise SystemExit("golden vector mismatch")
    else:
        print("verified", len(CASES), "golden vectors")


if __name__ == "__main__":
    main()
