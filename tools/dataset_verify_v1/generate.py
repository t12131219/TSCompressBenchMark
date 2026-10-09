"""Generate deterministic tscb-canonical-v1 fixtures directly as binary files."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from fixtures import PROJECT, ROOT
from tscompbench.datasets.canonical import write_canonical
from tscompbench.datasets.models import CanonicalDataset, DatasetManifest, ValueBuffer, immutable
from tscompbench.ids import canonical_json_bytes, stable_id

GENERATOR_VERSION = "dataset-verify-v1"
GENERATOR_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
BASE_SEED = 20261009
DTYPES = {
    "int8": "|i1", "int16": "<i2", "int32": "<i4", "int64": "<i8",
    "uint8": "|u1", "uint16": "<u2", "uint32": "<u4", "uint64": "<u8",
    "float32": "<f4", "float64": "<f8",
}
CATEGORIES = {
    "with_timestamp_univariate": (True, 1),
    "with_timestamp_multivariate": (True, 8),
    "without_timestamp_univariate": (False, 1),
    "without_timestamp_multivariate": (False, 8),
}
TIERS = {"4KiB": 4 * 1024, "64KiB": 64 * 1024,
         "1MiB": 1024**2, "16MiB": 16 * 1024**2}
PROFILES = ("constant", "slow", "periodic", "random")
EDGE_ROWS = (0, 1, 7, 8, 9, 31, 32, 33, 127, 128, 129, 1023, 1024, 1025)


def spec_for(category: str, dtype: str, *, group: str = "main", profile: str = "slow",
             tier: str = "64KiB", rows: int | None = None, channels: int | None = None,
             timestamp_mode: str = "regular") -> dict[str, Any]:
    has_timestamp, default_channels = CATEGORIES[category]
    m = channels if channels is not None else default_channels
    names = list(DTYPES) if dtype == "mixed10" else [dtype] * m
    if len(names) != m:
        raise ValueError("Mixed fixture must contain all 10 native dtypes")
    bytes_per_row = sum(np.dtype(DTYPES[name]).itemsize for name in names)
    bytes_per_row += 8 if has_timestamp else 0
    n = rows if rows is not None else max(1, TIERS[tier] // bytes_per_row)
    spec = {
        "category": category, "dtype": dtype, "value_dtypes": names,
        "group": group, "profile": profile, "tier": tier, "n_rows": n,
        "channels": m, "timestamp_mode": timestamp_mode if has_timestamp else "none",
        "target_payload_bytes": TIERS[tier] if rows is None else None,
    }
    digest = hashlib.sha256(canonical_json_bytes(spec)).digest()
    spec["seed"] = (BASE_SEED + int.from_bytes(digest[:8], "little")) % 2**64
    return spec


def all_specs() -> list[dict[str, Any]]:
    specs = []
    for category in CATEGORIES:
        for dtype in DTYPES:
            for tier in TIERS:
                for profile in PROFILES:
                    specs.append(spec_for(category, dtype, tier=tier, profile=profile))
            for n in EDGE_ROWS:
                specs.append(spec_for(category, dtype, group="length_extrema",
                                      profile="extrema", tier="explicit_rows", rows=n))
            if dtype.startswith("float"):
                specs.append(spec_for(category, dtype, group="ieee_special",
                                      profile="ieee_special", tier="explicit_rows", rows=129))
            if CATEGORIES[category][0]:
                for mode in ("irregular", "duplicates", "out_of_order"):
                    specs.append(spec_for(category, dtype, group="timestamp_cases",
                                          profile="periodic", timestamp_mode=mode))
            if CATEGORIES[category][1] > 1:
                for m in (2, 4, 16, 32):
                    specs.append(spec_for(category, dtype, group="channel_counts", channels=m))
        if CATEGORIES[category][1] > 1:
            for profile in PROFILES:
                specs.append(spec_for(category, "mixed10", group="mixed_dtypes",
                                      profile=profile, channels=10))
    return specs


def relative_path(spec: dict[str, Any]) -> Path:
    filename = (f"{spec['tier']}__{spec['profile']}__{spec['timestamp_mode']}"
                f"__n{spec['n_rows']}__c{spec['channels']}")
    return Path("data") / spec["category"] / spec["dtype"] / spec["group"] / filename


def value_array(dtype_name: str, n: int, channel: int, profile: str,
                seed: int) -> np.ndarray:
    dtype = np.dtype(DTYPES[dtype_name])
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, channel])))
    floating = dtype.kind == "f"
    if profile == "constant":
        scalar = (1.25 + channel / 4) if floating else (7 + channel)
        result = np.full(n, scalar, dtype=dtype)
    elif profile == "random":
        if floating:
            # Finite bounded values; special exponent/sign patterns have their own group.
            result = (rng.random(n, dtype=dtype.type) * 512 - 256).astype(dtype)
        else:
            info = np.iinfo(dtype)
            result = rng.integers(info.min, info.max, n, dtype=dtype, endpoint=True)
    elif profile in {"slow", "periodic"}:
        row = np.arange(n, dtype=np.int64)
        if profile == "slow":
            if floating:
                code = ((row // 4 + channel * 23) % 65536) - 32768
                result = (code / 256 + ((row + channel) % 7) / 1024).astype(dtype)
            else:
                code = ((row // 8 + channel * 11) % 128)
                if dtype.kind == "i":
                    code -= 64
                result = code.astype(dtype)
        else:
            code = np.abs(128 - ((row + channel * 17) % 256))
            if floating:
                result = ((code - 64) / 8).astype(dtype)
            else:
                if dtype.kind == "i":
                    code -= 64
                else:
                    # unsigned 8-bit data includes 128 but never wraps its dtype.
                    code = np.minimum(code, 128)
                result = code.astype(dtype)
    elif profile in {"extrema", "ieee_special"}:
        if not floating:
            info = np.iinfo(dtype)
            scalars = [info.min, info.min + 1, 0, 1, info.max // 2, info.max - 1, info.max]
            if dtype.kind == "i":
                scalars.insert(2, -1)
            bits = np.asarray(scalars, dtype=dtype)
        else:
            # Construct bits directly: preserve -0, subnormals and NaN payloads.
            patterns = {
                "float32": [0, 0x80000000, 1, 0x80000001, 0x007fffff, 0x00800000,
                            0x80800000, 0x3f800000, 0xbf800000, 0x3f800001,
                            0x7f7fffff, 0xff7fffff],
                "float64": [0, 0x8000000000000000, 1, 0x8000000000000001,
                            0x000fffffffffffff, 0x0010000000000000,
                            0x8010000000000000, 0x3ff0000000000000,
                            0xbff0000000000000, 0x3ff0000000000001,
                            0x7fefffffffffffff, 0xffefffffffffffff],
            }[dtype_name]
            if profile == "ieee_special":
                patterns += {
                    "float32": [0x7f800000, 0xff800000, 0x7fc00001, 0x7fc00123,
                                0x7f800001, 0xffc00042],
                    "float64": [0x7ff0000000000000, 0xfff0000000000000,
                                0x7ff8000000000001, 0x7ff8000000000123,
                                0x7ff0000000000001, 0xfff8000000000042],
                }[dtype_name]
            bits = np.asarray(patterns, dtype=f"<u{dtype.itemsize}").view(dtype)
        result = np.resize(np.roll(bits, channel), n).copy()
    else:
        raise ValueError(profile)
    return immutable(np.ascontiguousarray(result, dtype=dtype))


def timestamp_array(n: int, mode: str) -> np.ndarray | None:
    if mode == "none":
        return None
    row = np.arange(n, dtype="<i8")
    epoch_ms = 1704067200000  # 2024-01-01 UTC
    if mode == "irregular":
        steps = 700 + (row % 13) * 50
        values = epoch_ms + np.cumsum(steps) - (int(steps[0]) if n else 0)
    elif mode == "duplicates":
        steps = np.full(n, 1000, dtype="<i8")
        steps[7::7] = 0
        values = epoch_ms + np.cumsum(steps) - (int(steps[0]) if n else 0)
    elif mode in {"regular", "out_of_order"}:
        values = epoch_ms + row * 1000
        if mode == "out_of_order":
            left = np.arange(15, n - 1, 31)
            saved = values[left].copy()
            values[left] = values[left + 1]
            values[left + 1] = saved
    else:
        raise ValueError(mode)
    return immutable(np.ascontiguousarray(values, dtype="<i8"))


def make_dataset(spec: dict[str, Any]) -> CanonicalDataset:
    n, m = spec["n_rows"], spec["channels"]
    timestamp = timestamp_array(n, spec["timestamp_mode"])
    values = tuple(
        ValueBuffer(
            name=f"channel_{channel:03d}", display_name=f"Synthetic channel {channel}",
            array=value_array(dtype, n, channel, spec["profile"], spec["seed"]),
            unit="UNSPECIFIED" if dtype.startswith("float") else "count",
            entity="synthetic-verification", feature=f"channel_{channel:03d}",
        )
        for channel, dtype in enumerate(spec["value_dtypes"])
    )
    timestamp_spec = {
        "present": timestamp is not None,
        "origin": "SYNTHETIC_EXPLICIT" if timestamp is not None else "NONE",
    }
    if timestamp is not None:
        timestamp_spec.update(dtype="<i8", unit="ms", epoch="UNIX", order_policy="PRESERVE")
    logical = {
        "schema_version": "tscb.logical-view.v2",
        "topology": "UTS" if m == 1 else "SYNCHRONOUS_MTS",
        "axes": ["time"] if m == 1 else ["time", "channel"],
        "n_rows": n, "timestamp": timestamp_spec,
        "value_shape": [n, m], "value_columns": [value.descriptor() for value in values],
        "validity_shape": "NONE", "nan_is_null": False,
    }
    physical: list[dict[str, Any]] = []
    if timestamp is not None:
        physical.append({
            "view_id": "timestamp-row-major", "layout": "ROW_MAJOR_CONTIG",
            "dtype": "<i8", "shape": [n], "strides": [8], "endianness": "little",
        })
    physical.append({
        "view_id": "value-soa-columns", "layout": "SOA_COLUMNS",
        "dtype_vector": [value.array.dtype.str for value in values],
        "shape": [n, m], "endianness": "little",
    })
    manifest = DatasetManifest(
        key=relative_path(spec).name, path=ROOT / "index.json",
        source_path=ROOT / relative_path(spec),
        dataset_id=stable_id("dataset", {
            "generator_version": GENERATOR_VERSION,
            "generator_sha256": GENERATOR_SHA256, "spec": spec,
        }),
        document={
            "schema_version": "tscb.dataset-verify-manifest.v1",
            "file": {"format": "synthetic-direct-canonical", "bytes": 0},
            "source": {"uri": "generated:Dataset_Verify/generate.py", "seed": spec["seed"]},
            "logical": logical,
            "split": {"policy": "UNSPECIFIED", "learned_eligible": False},
        },
    )
    return CanonicalDataset(
        manifest=manifest, timestamp=timestamp, values=values, validity=None,
        logical_descriptor=logical, physical_descriptors=tuple(physical),
        loader_provenance={
            "loader": "Dataset_Verify.generate.make_dataset",
            "generator_version": GENERATOR_VERSION, "generator_sha256": GENERATOR_SHA256,
            "seed": spec["seed"], "python": platform.python_version(), "numpy": np.__version__,
            "source_file_exists": False, "hidden_transforms": [],
        },
    )


def write_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False,
                                    indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def generate(*, overwrite: bool = False) -> None:
    specs = all_specs()
    paths = [ROOT / relative_path(spec) for spec in specs]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate fixture paths")
    existing = [path for path in paths if path.exists()]
    if (existing or (ROOT / "index.json").exists()) and not overwrite:
        raise FileExistsError("Fixtures already exist; use --overwrite to regenerate deliberately")
    entries = []
    for number, spec in enumerate(specs, 1):
        dataset = make_dataset(spec)
        path = ROOT / relative_path(spec)
        artifact = write_canonical(dataset, path)
        entries.append({
            "path": path.relative_to(ROOT).as_posix(), "generation_spec": spec,
            "dataset_id": dataset.dataset_id, "file_sha256": artifact.sha256,
            "content_sha256": artifact.metadata["dataset_content_sha256"],
            "payload_bytes": dataset.canonical_raw_bits // 8,
            "file_bytes": path.stat().st_size,
            "buffer_count": len(dataset.named_arrays()),
            "available_tracks": ["VALUE", "TIMESTAMP", "SYSTEM"]
            if dataset.timestamp is not None else ["VALUE"],
            "edge_case": spec["group"] in {"length_extrema", "ieee_special", "timestamp_cases"},
        })
        if number % 100 == 0 or number == len(specs):
            print(f"Generated {number}/{len(specs)}", flush=True)
    write_json(ROOT / "index.json", {
        "schema_version": "tscb.dataset-verify-index.v1",
        "format": "tscb-canonical-v1", "generator_version": GENERATOR_VERSION,
        "generator_sha256": GENERATOR_SHA256, "base_seed": BASE_SEED,
        "python": platform.python_version(), "numpy": np.__version__,
        "numeric_types": DTYPES, "main_payload_tiers": TIERS,
        "main_profiles": list(PROFILES), "edge_row_counts": list(EDGE_ROWS),
        "total_files": len(entries),
        "total_file_bytes": sum(entry["file_bytes"] for entry in entries),
        "total_payload_bytes": sum(entry["payload_bytes"] for entry in entries),
        "counts_by_category": dict(Counter(spec["category"] for spec in specs)),
        "counts_by_group": dict(Counter(spec["group"] for spec in specs)),
        "split": {"policy": "UNSPECIFIED", "learned_eligible": False},
        "source_file_bytes_provenance_only": 0,
        "entries": entries,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="Regenerate known fixture paths")
    args = parser.parse_args()
    generate(overwrite=args.overwrite)
