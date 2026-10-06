"""Create small, declared inputs for complete five-layer codec qualification."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
UNITS = [
    "HISTOGRAM_ST_INT64_BITS",
    "HISTOGRAM_COUNT_BITS",
    "HISTOGRAM_ZERO_COUNT_BITS",
    "HISTOGRAM_SUM_BINARY64_BITS",
    "HISTOGRAM_ZERO_THRESHOLD_BINARY64_BITS",
    "HISTOGRAM_BUCKET_BITS",
]


def bits(value):
    return int(np.asarray(value, dtype="<f8").view("<u8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_manifest(doc, path, key):
    doc["key"] = key
    doc["display_name"] = "Synthetic completed-rewrite qualification: " + key
    doc["source"] = {
        "uri": "generated:tools/generate_completed_rewrite_fixtures.py@20261006",
        "retrieved_at": "2026-10-06",
        "notes": "Deterministic synthetic fixtures; no real-world corpus or performance claim",
    }
    doc["license"] = {"spdx": "CC0-1.0", "status": "RUN_ALLOWED"}
    doc["file"].update(
        path=str(path.relative_to(ROOT)), bytes=path.stat().st_size, sha256=sha(path)
    )
    doc["split"] = {
        "policy": "PER_OBJECT_ENCODING_OR_DECLARED_FROZEN_MODEL_NO_TEST_TUNING",
        "learned_eligible": True,
        "reason": (
            "Compression may fit per-object state; no external training or tuning on these fixtures"
        ),
    }
    (ROOT / "registry/datasets" / f"{key}.json").write_text(json.dumps(doc, indent=2) + "\n")


def csv_fixture(key, header, rows, units=None):
    path = ROOT / "fixtures/completed_rewrites" / f"{key}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", *header])
        for i, row in enumerate(rows):
            date = (datetime(2026, 1, 1) + timedelta(seconds=i * 10)).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([date, *row])
    doc = json.loads((ROOT / "registry/datasets/etth1.json").read_text())
    doc["file"]["header_bytes_sha256"] = hashlib.sha256(
        path.read_bytes().splitlines(keepends=True)[0]
    ).hexdigest()
    doc["expected"] = {"rows": len(rows), "columns": len(header) + 1}
    spec = doc["logical"]["value"]
    spec["column_selection"]["expected_count"] = len(header)
    spec["default_column"].update(entity="synthetic-record", dtype="<u8" if units else "<f8")
    if units:
        spec["overrides"] = {name: {"unit": unit} for name, unit in zip(header, units, strict=True)}
    save_manifest(doc, path, key)


def npz_fixture(key, values, unit):
    path = ROOT / "fixtures/completed_rewrites" / f"{key}.npz"
    np.savez(path, values=values)
    doc = json.loads((ROOT / "registry/datasets/sprintz_u8_uts.json").read_text())
    doc["logical"]["topology"] = "UTS" if values.ndim == 1 else "SYNCHRONOUS_MTS"
    doc["logical"]["axes"] = ["time"] if values.ndim == 1 else ["time", "channel"]
    doc["logical"]["value"]["array"].update(
        dtype=values.dtype.str, unit=unit, entity="synthetic-input"
    )
    doc["expected"] = {
        "shape": list(values.shape),
        "dtype": values.dtype.str,
        "array_keys": ["values"],
    }
    save_manifest(doc, path, key)


def main():
    (ROOT / "fixtures/completed_rewrites").mkdir(parents=True, exist_ok=True)
    rows = [
        [format(np.sin(i / 7) + j * 0.125 + np.cos(i / 11 + j) / 8, ".17g") for j in range(3)]
        for i in range(160)
    ]
    csv_fixture("rewrite_float_mts", ["channel0", "channel1", "channel2"], rows)
    npz_fixture(
        "rewrite_byte_uts",
        (np.arange(256, dtype=np.uint16) * 17 + np.arange(256) // 5).astype(np.uint8) % 4,
        "BYTE_SYMBOL",
    )
    t = np.arange(64, dtype=np.float64)
    audio = np.column_stack([0.1 * np.sin(t / 7), 0.1 * np.cos(t / 9)]).astype("<f4")
    npz_fixture("rewrite_audio_stereo", audio, "NORMALIZED_AUDIO_MINUS_HALF_TO_HALF")
    for floating in [False, True]:
        rows = []
        for i in range(16):
            count = i + 1
            zero = 0
            bucket = count
            if floating:
                count, zero, bucket = bits(float(count)), bits(0.0), bits(float(bucket))
            rows.append([0, count, zero, bits((i + 1) / 8), bits(0.0), bucket])
        csv_fixture(
            "rewrite_histogram_float" if floating else "rewrite_histogram_int",
            [
                "start_timestamp_bits",
                "count_bits",
                "zero_count_bits",
                "sum_bits",
                "zero_threshold_bits",
                "bucket_bits",
            ],
            rows,
            UNITS,
        )
    print("five qualification datasets generated and registered")


if __name__ == "__main__":
    main()
