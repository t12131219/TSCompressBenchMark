"""Generate deterministic development fixtures; these are not a real corpus."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def generate(output: Path, rows: int = 257, seed: int = 20261013) -> dict:
    if rows < 2:
        raise ValueError("rows must be >= 2")
    output.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t = np.arange(rows, dtype=np.float64)
    # Values with exact binary fractions exercise float codecs without silently
    # changing precision. The non-multiple length exercises native tail paths.
    values = np.column_stack((t / 8, (t % 32) / 4, (t % 7) / 2))
    arrays = {
        "float64": values,
        "float32": values.astype(np.float32),
        "int16": np.column_stack((np.arange(rows) % 128, np.arange(rows) % 17)).astype(np.int16),
        "uint8": (np.arange(rows) % 251).astype(np.uint8),
        "symbols4": (np.arange(rows) % 4).astype(np.uint8),
        "uint32": (np.arange(rows) % 1024).astype(np.uint32),
        "empty": np.empty(0, dtype=np.float64),
        "float_bits": np.array([
            0x0000000000000000, 0x8000000000000000, 0x7FF0000000000000,
            0xFFF0000000000000, 0x7FF8000000000001, 0x7FF8000000000011,
        ], dtype=np.uint64).view(np.float64),
        "noise64": rng.normal(size=(rows, 2)),
    }
    files = []
    for name, array in arrays.items():
        path = output / f"{name}.npy"
        np.save(path, array, allow_pickle=False)
        files.append({"path": path.name, "dtype": array.dtype.str,
                      "shape": list(array.shape), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    timestamps = np.arange(rows, dtype=np.int64) * 60_000_000_000
    if rows > 6:
        timestamps[5] = timestamps[4]  # Explicit duplicate; no sorting/deduplication.
    validity = np.ones(values.shape, dtype=np.uint8)
    validity[::19, 1] = 0
    records = output / "records.npz"
    np.savez(records, V=values, T=timestamps, mask=validity)
    files.append({"path": records.name, "sha256": hashlib.sha256(records.read_bytes()).hexdigest(),
                  "components": {"V": "<f8", "T": "<i8", "mask": "|u1"}})
    csv_path = output / "records.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp_ns", "x", "y", "z"])
        writer.writerows(zip(timestamps, *values.T))
    files.append({"path": csv_path.name, "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest()})
    manifest = {"schema": "tsbench.fixtures/1", "kind": "correctness_and_development_fixtures",
                "seed": seed, "rows": rows, "independent_sources": 0, "files": files}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "data")
    parser.add_argument("--rows", type=int, default=257)
    parser.add_argument("--seed", type=int, default=20261013)
    args = parser.parse_args()
    print(json.dumps(generate(args.output, args.rows, args.seed), indent=2))
