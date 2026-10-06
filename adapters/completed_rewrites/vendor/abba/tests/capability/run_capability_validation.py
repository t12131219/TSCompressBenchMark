#!/usr/bin/env python3
"""Validate ABBA alternate clustering capabilities against the frozen source."""

import argparse
import importlib.util
import json
import pathlib
import subprocess
import warnings

import numpy as np


def load_abba(source_root):
    spec = importlib.util.spec_from_file_location("capability_abba", source_root / "ABBA.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ABBA


def native(cli, values, method, scl, norm, weighted, symmetric):
    args = [str(cli), "--operation", "transform", "--compression-tol", "0.15",
            "--digitization-tol", "0.25", "--min-k", "1", "--max-k", "8",
            "--scl", str(scl), "--norm", str(norm), "--clustering", method,
            "--weighted", str(int(weighted)), "--symmetric", str(int(symmetric))]
    request = str(len(values)) + " " + " ".join(format(float(v), ".17g") for v in values) + "\n"
    completed = subprocess.run(args, input=request, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    return json.loads(completed.stdout)["result"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpp-cli", required=True, type=pathlib.Path)
    parser.add_argument("--source-root", required=True, type=pathlib.Path)
    args = parser.parse_args()
    ABBA = load_abba(args.source_root)
    generator = np.random.RandomState(20260928)
    cases = []
    for weighted in (False, True):
        for symmetric in (False, True):
            for norm in (1, 2):
                cases.extend(("incremental", 0.0, norm, weighted, symmetric) for _ in range(4))
    cases.extend(("kmeans", scl, 2, False, True)
                 for scl in (0.5, 1.0, 2.0, float("inf")) for _ in range(8))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for index, (method, scl, norm, weighted, symmetric) in enumerate(cases):
            values = np.cumsum(generator.normal(size=40))
            source = ABBA(tol=[0.15, 0.25], scl=scl, min_k=1, max_k=8,
                          verbose=0, seed=True, norm=norm, c_method=method,
                          weighted=weighted, symmetric=symmetric)
            pieces = source.compress(values)
            string, centers = source.digitize(pieces)
            result = native(args.cpp_cli, values, method, scl, norm, weighted, symmetric)
            symbols = [ord(value) - ord("a") for value in string]
            if symbols != result["symbols"]:
                raise AssertionError(f"case {index}: symbol mismatch")
            if not np.allclose(centers, np.asarray(result["centers"]), rtol=1e-10, atol=1e-10):
                raise AssertionError(f"case {index}: center mismatch")
    print(f"ABBA alternate capability validation passed: {len(cases)} cases")


if __name__ == "__main__":
    main()
