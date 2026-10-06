#!/usr/bin/env python3
"""Stage-composed executable oracle for the frozen ABBA source closure."""

import argparse
import collections
import importlib.util
import json
import math
import pathlib
import subprocess
import sys

import numpy as np

sys.dont_write_bytecode = True


PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[2]
UPSTREAM_ROOT = PACKAGE_ROOT.parents[1] / "Source" / "abba" / "upstream"


def load_upstream_abba():
    spec = importlib.util.spec_from_file_location("frozen_abba", UPSTREAM_ROOT / "ABBA.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ABBA


ABBA = load_upstream_abba()


def config_from(request):
    config = request.get("config", {})
    return {
        "compression_tol": float(config.get("compression_tol", 0.1)),
        "digitization_tol": float(config.get("digitization_tol", 0.1)),
        "min_k": int(config.get("min_k", 1)),
        "max_k": int(config.get("max_k", 100)),
        "max_len": float(config.get("max_len", math.inf)),
    }


def make_abba(config):
    return ABBA(
        tol=[config["compression_tol"], config["digitization_tol"]],
        scl=0,
        min_k=config["min_k"],
        max_k=config["max_k"],
        max_len=config["max_len"],
        verbose=0,
        seed=True,
        norm=2,
        c_method="kmeans",
        weighted=False,
        symmetric=True,
    )


def run_ckmeans(cli, values, kmin, kmax, variance_bound):
    request = "{} {} {} {:.17g}\n{}\n".format(
        len(values), kmin, kmax, variance_bound,
        " ".join(format(float(value), ".17g") for value in values),
    )
    completed = subprocess.run(
        [str(cli)], input=request, text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError("CKmeans oracle failed: " + completed.stderr.strip())
    lines = completed.stdout.splitlines()
    if len(lines) != 3:
        raise RuntimeError("malformed CKmeans oracle response")
    k = int(lines[0])
    labels = [int(value) for value in lines[1].split()]
    centers = [float(value) for value in lines[2].split()]
    if len(labels) != len(values) or len(centers) != k:
        raise RuntimeError("incomplete CKmeans oracle response")
    return labels, centers


def digitize(abba, pieces, cli, config):
    data = np.array(pieces, dtype=float, copy=True)[:, 0:2]
    if len(data) < config["min_k"]:
        raise ValueError("Number of pieces less than min_k.")

    sample_count = 1.0 + float(np.sum(data[:, 0]))
    piece_count = float(len(data))
    scale = 0.20
    bound = (
        (6.0 * (sample_count - piece_count) / (sample_count * piece_count))
        * ((config["digitization_tol"] ** 2) / (scale ** 2))
    )
    inc_std = float(np.std(data[:, 1]))
    if inc_std <= np.finfo(float).eps:
        inc_std = 1.0
    normalized = data[:, 1] / inc_std
    if len(set(float(value) for value in normalized)) < config["min_k"]:
        raise ValueError("canonical profile forbids sklearn fallback")

    labels, normalized_centers = run_ckmeans(
        cli, normalized, config["min_k"], config["max_k"], bound
    )
    k = len(normalized_centers)
    centers = []
    for cluster in range(k):
        positions = [index for index, label in enumerate(labels) if label == cluster]
        centers.append([
            float(np.mean(data[positions, 0])),
            float(normalized_centers[cluster] * inc_std),
        ])

    counter = collections.Counter(labels)
    new_to_old = [item[0] for item in counter.most_common()]
    old_to_new = [0] * k
    for new_label, old_label in enumerate(new_to_old):
        old_to_new[old_label] = new_label
    symbols = [old_to_new[label] for label in labels]
    ordered_centers = [centers[old_label] for old_label in new_to_old]
    return {
        "variance_bound": float(bound),
        "labels_raw": labels,
        "centers_raw": centers,
        "symbols": symbols,
        "centers": ordered_centers,
    }


def decode(abba, symbols, centers, first_value):
    pieces = np.array([centers[symbol] for symbol in symbols], dtype=float)
    quantized = abba.quantize(pieces.copy())
    reconstructed = abba.inverse_compress(float(first_value), quantized)
    return {
        "quantized_pieces": quantized.tolist(),
        "reconstructed": [float(value) for value in reconstructed],
    }


def process(request, cli):
    config = config_from(request)
    abba = make_abba(config)
    operation = request.get("operation", "transform")

    if operation == "compress":
        values = np.asarray(request["values"], dtype=float)
        return {"pieces": abba.compress(values).tolist()}
    if operation == "digitize":
        result = digitize(abba, request["pieces"], cli, config)
        return result
    if operation == "decode":
        return decode(abba, request["symbols"], request["centers"], request["first_value"])
    if operation != "transform":
        raise ValueError("unknown operation")

    values = np.asarray(request["values"], dtype=float)
    if len(values) < 2 or not np.all(np.isfinite(values)):
        raise ValueError("transform requires at least two finite values")
    pieces = abba.compress(values)
    digitized = digitize(abba, pieces, cli, config)
    decoded = decode(abba, digitized["symbols"], digitized["centers"], values[0])
    return {
        "pieces": pieces.tolist(),
        **digitized,
        **decoded,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ckmeans-cli", required=True, type=pathlib.Path)
    parser.add_argument("--request", help="single JSON request; otherwise read JSON lines")
    args = parser.parse_args()

    requests = [args.request] if args.request is not None else sys.stdin
    for line in requests:
        if not str(line).strip():
            continue
        try:
            response = {"ok": True, "result": process(json.loads(line), args.ckmeans_cli)}
        except Exception as error:
            response = {"ok": False, "error": str(error)}
        print(json.dumps(response, allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
