#!/usr/bin/env python3
"""Frozen source-oracle versus canonical fABBA differential validation."""

import argparse
import json
import math
import pathlib
import random
import subprocess
import sys


def config_args(request):
    config = request.get("config", {})
    return ["--tol", str(config.get("tol", 0.1)),
            "--alpha", str(config.get("alpha", 0.1)),
            "--scl", str(config.get("scl", 1.0)),
            "--max-len", str(config.get("max_len", -1))]


def cpp_input(request):
    operation = request.get("operation", "transform")
    if operation in ("transform", "compress"):
        values = request["values"]
        return str(len(values)) + "\n" + " ".join(map(str, values)) + "\n"
    if operation == "digitize":
        pieces = request["pieces"]
        return str(len(pieces)) + "\n" + " ".join(
            "{} {}".format(piece[0], piece[1]) for piece in pieces) + "\n"
    symbols, centers = request["symbols"], request["centers"]
    return "{} {} {}\n{}\n{}\n".format(
        request["first_value"], len(symbols), len(centers),
        " ".join("{} {}".format(*center) for center in centers),
        " ".join(map(str, symbols)))


def run_cpp(cli, request):
    completed = subprocess.run([str(cli), "--operation",
                                request.get("operation", "transform"),
                                *config_args(request)], input=cpp_input(request),
                               text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError("C++ CLI failed: " + completed.stdout + completed.stderr)
    response = json.loads(completed.stdout)
    if not response["ok"]:
        raise RuntimeError(response["error"])
    return response["result"]


def run_oracle(script, requests):
    payload = "".join(json.dumps(request) + "\n" for request in requests)
    completed = subprocess.run([sys.executable, str(script)], input=payload,
                               text=True, capture_output=True, check=True)
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
    if len(responses) != len(requests):
        raise RuntimeError("oracle response count mismatch")
    for response in responses:
        if not response["ok"]:
            raise RuntimeError(response["error"])
    return [response["result"] for response in responses]


def compare(reference, actual, path="result"):
    if isinstance(reference, dict):
        for key, value in reference.items(): compare(value, actual[key], path + "." + key)
    elif isinstance(reference, list):
        if len(reference) != len(actual): raise AssertionError(path + " length mismatch")
        for index, (left, right) in enumerate(zip(reference, actual)):
            compare(left, right, "{}[{}]".format(path, index))
    elif isinstance(reference, int):
        if reference != actual: raise AssertionError(path + " integer mismatch")
    else:
        tolerance = 1e-10 + 1e-12 * abs(reference)
        if not math.isfinite(actual) or abs(reference - actual) > tolerance:
            raise AssertionError("{}: {} != {}".format(path, reference, actual))


def property_requests():
    generator = random.Random(20260928)
    requests = []
    for case in range(64):
        count = 2 + (case * 17) % 79
        values = []
        current = float(case % 7) - 3.0
        for index in range(count):
            if case % 4 == 0: current += generator.uniform(-1.0, 1.0)
            elif case % 4 == 1: current = math.sin(index * 0.17 + case) * (1 + case % 5)
            elif case % 4 == 2: current += ((index % 5) - 2) * 0.125
            else: current = (index // 3) * 0.5 + generator.uniform(-0.02, 0.02)
            values.append(current)
        requests.append({"values": values, "config": {
            "tol": [0.0, 0.03, 0.1, 0.5][case % 4],
            "alpha": [0.0, 0.05, 0.1, 0.3][(case // 4) % 4],
            "scl": [0.5, 1.0, 2.0][case % 3],
            "max_len": [-1, 2, 5, 13][(case // 8) % 4]}})
    return requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpp-cli", required=True, type=pathlib.Path)
    parser.add_argument("--oracle", required=True, type=pathlib.Path)
    parser.add_argument("--vectors", required=True, type=pathlib.Path)
    args = parser.parse_args()
    frozen = json.loads(args.vectors.read_text(encoding="utf-8"))["vectors"]
    requests = [item["request"] for item in frozen] + property_requests()
    references = run_oracle(args.oracle, requests)
    for index, (request, reference) in enumerate(zip(requests, references)):
        actual = run_cpp(args.cpp_cli, request)
        compare(reference, actual, "case[{}]".format(index))
        if request.get("operation", "transform") == "transform":
            decoded = subprocess.run([str(args.cpp_cli), "--operation", "decode-container"],
                                     input=actual["container_hex"] + "\n", text=True,
                                     capture_output=True, check=True)
            compare(actual["reconstructed"],
                    json.loads(decoded.stdout)["result"]["reconstructed"],
                    "case[{}].container".format(index))
    print("verified {} golden and 64 property vectors".format(len(frozen)))


if __name__ == "__main__":
    main()
