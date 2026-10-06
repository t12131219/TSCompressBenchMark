#!/usr/bin/env python3
"""Stage-composed oracle for the frozen fABBA source closure."""

import argparse
import importlib.util
import json
import math
import pathlib
import sys

import numpy as np

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
UPSTREAM = ROOT.parents[1] / "Source" / "fabba" / "upstream" / "fABBA"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHAIN = load("frozen_fabba_chain", UPSTREAM / "chainApproximation.py")
AGG = load("frozen_fabba_agg", UPSTREAM / "fabba_agg.py")
INVERSE = load("frozen_fabba_inverse", UPSTREAM / "inverse_t.py")


def config_from(request):
    config = request.get("config", {})
    return {
        "tol": float(config.get("tol", 0.1)),
        "alpha": float(config.get("alpha", 0.1)),
        "scl": float(config.get("scl", 1.0)),
        "max_len": int(config.get("max_len", -1)),
    }


def digitize(pieces, config):
    raw = np.asarray(pieces, dtype=np.float64)[:, :2]
    source_std = np.std(raw, axis=0)
    std = np.where(source_std <= np.finfo(float).eps, 1.0, source_std)
    normalized = raw * np.array([config["scl"], 1.0]) / std
    norms = np.linalg.norm(normalized, ord=2, axis=1)
    order = np.lexsort((np.arange(len(raw), dtype=np.int64), norms))
    labels = np.full(len(raw), -1, dtype=np.int64)
    starts = []
    lab = 0
    for position, sp in enumerate(order):
        if labels[sp] >= 0:
            continue
        labels[sp] = lab
        starts.append(int(sp))
        for j in order[position:]:
            if labels[j] >= 0:
                continue
            delta = normalized[sp] - normalized[j]
            if float(np.inner(delta, delta)) <= config["alpha"] ** 2:
                labels[j] = lab
            elif norms[j] - norms[sp] > config["alpha"]:
                break
        lab += 1

    # For the upstream-defined domain, execute the frozen original aggregation
    # and require it to agree. Exact norm ties and zero-variance dimensions use
    # the two explicit profile stabilizations above.
    if (np.all(source_std > np.finfo(float).eps)
            and len(np.unique(norms)) == len(norms)):
        upstream_labels, upstream_starts = AGG.aggregate(
            normalized, "2-norm", config["alpha"])
        if not np.array_equal(labels, upstream_labels.astype(np.int64)):
            raise RuntimeError("frozen upstream aggregation divergence")
        upstream_indices = [int(item[0]) for item in upstream_starts]
        if starts != upstream_indices:
            raise RuntimeError("frozen upstream starting-point divergence")
    centers = [np.mean(raw[labels == cluster], axis=0).tolist()
               for cluster in range(lab)]
    return {
        "length_std": float(std[0]),
        "increment_std": float(std[1]),
        "sorted_indices": [int(value) for value in order],
        "starting_points": starts,
        "labels_raw": [int(value) for value in labels],
        "centers_raw": centers,
        "symbols": [int(value) for value in labels],
        "centers": centers,
    }


def decode(symbols, centers, first_value):
    expanded = np.asarray([centers[symbol] for symbol in symbols], dtype=float)
    quantized = INVERSE.quantize(expanded.copy())
    reconstructed = INVERSE.inv_compress(quantized, float(first_value))
    return {"quantized_pieces": quantized.tolist(),
            "reconstructed": [float(value) for value in reconstructed]}


def process(request):
    config = config_from(request)
    if not all(math.isfinite(config[key]) for key in ("tol", "alpha", "scl")):
        raise ValueError("configuration must be finite")
    operation = request.get("operation", "transform")
    if operation == "compress":
        return {"pieces": CHAIN.compress(np.asarray(request["values"], dtype=float),
                                          config["tol"], config["max_len"])}
    if operation == "digitize":
        return digitize(request["pieces"], config)
    if operation == "decode":
        return decode(request["symbols"], request["centers"], request["first_value"])
    if operation != "transform":
        raise ValueError("unknown operation")
    values = np.asarray(request["values"], dtype=float)
    if len(values) < 2 or not np.all(np.isfinite(values)):
        raise ValueError("transform requires at least two finite values")
    pieces = CHAIN.compress(values, config["tol"], config["max_len"])
    result = digitize(pieces, config)
    result.update(decode(result["symbols"], result["centers"], values[0]))
    return {"pieces": pieces, **result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request")
    args = parser.parse_args()
    requests = [args.request] if args.request is not None else sys.stdin
    for line in requests:
        if not str(line).strip():
            continue
        try:
            response = {"ok": True, "result": process(json.loads(line))}
        except Exception as error:
            response = {"ok": False, "error": str(error)}
        print(json.dumps(response, allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
