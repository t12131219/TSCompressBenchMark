#!/usr/bin/env python3
"""Validate fABBA partitioned compression against the frozen source stage."""

import argparse
import importlib.util
import json
import pathlib
import subprocess

import numpy as np


def load_chain(source_root):
    path = source_root / "fABBA" / "chainApproximation.py"
    spec = importlib.util.spec_from_file_location("capability_fabba_chain", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpp-cli", required=True, type=pathlib.Path)
    parser.add_argument("--source-root", required=True, type=pathlib.Path)
    args = parser.parse_args()
    chain = load_chain(args.source_root)
    generator = np.random.RandomState(20260928)
    for case in range(32):
        count = 128 + case
        partition = 2 + case % 7
        threads = 1 + case % 4
        values = np.cumsum(generator.normal(size=count))
        interval = count // partition
        expected = [chain.compress(values[i * interval:(i + 1) * interval], 0.1, -1)
                    for i in range(partition)]
        command = [str(args.cpp_cli), "--operation", "parallel-compress",
                   "--tol", "0.1", "--alpha", "0.1", "--scl", "1",
                   "--max-len", "-1", "--partition", str(partition),
                   "--threads", str(threads)]
        request = str(count) + " " + " ".join(format(float(v), ".17g") for v in values) + "\n"
        completed = subprocess.run(command, input=request, text=True,
                                   capture_output=True, check=False)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)["result"]
        actual = result["partitions"]
        execution = result["execution"]
        expected_threads = min(threads, partition)
        if execution != {
                "partitions_requested": partition,
                "partitions_used": partition,
                "threads_requested": threads,
                "threads_used": expected_threads,
                "samples_per_partition": interval,
                "samples_consumed": interval * partition,
                "samples_discarded": count - interval * partition}:
            raise AssertionError(f"case {case}: execution evidence mismatch: {execution}")
        if len(actual) != len(expected):
            raise AssertionError(f"case {case}: partition count mismatch")
        for index, (left, right) in enumerate(zip(actual, expected)):
            if not np.allclose(np.asarray(left), np.asarray(right), rtol=1e-10, atol=1e-10):
                raise AssertionError(f"case {case}, partition {index}: source mismatch")
        repeated = subprocess.run(command, input=request, text=True,
                                  capture_output=True, check=True).stdout
        if repeated != completed.stdout:
            raise AssertionError(f"case {case}: parallel result is nondeterministic")
    print("fABBA partitioned capability validation passed: 32 cases")


if __name__ == "__main__":
    main()
