"""Freeze real, reproducible V3.2 CPU comparison bundles without running codecs.

Payloads live in ignored artifacts; committed source manifests/specifications
bind their exact content. Existing generated files are verified, never replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

# Direct invocation follows the repository's existing tools convention.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.adapters import adapter_artifacts  # noqa: E402
from tscompbench.codecs import (  # noqa: E402
    CodecRegistry,
    SourceRegistry,
    descriptor_from_dataset,
    negotiate,
)
from tscompbench.comparison import (  # noqa: E402
    ComparisonContract,
    CorpusSpec,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    compile_group_plan,
    method_id,
    registered_source_closure_digest,
)
from tscompbench.comparison.analysis import AnalysisPolicy  # noqa: E402
from tscompbench.contracts import BenchmarkTrack, CapabilityStatus  # noqa: E402
from tscompbench.datasets import DatasetRegistry, load_dataset  # noqa: E402
from tscompbench.datasets.canonical import (  # noqa: E402
    read_canonical,
    semantic_content_sha256,
    write_canonical,
)
from tscompbench.datasets.canonical_source import canonical_source_document  # noqa: E402
from tscompbench.datasets.models import (  # noqa: E402
    CanonicalDataset,
    DatasetManifest,
    ValueBuffer,
    immutable,
)
from tscompbench.datasets.prepare import load_preparation_result, prepare_dataset  # noqa: E402
from tscompbench.ids import canonical_json_bytes, stable_id  # noqa: E402
from tscompbench.measurement.v32_protocol import MeasurementProtocol  # noqa: E402
from tscompbench.planning.sweep import expand_sweep  # noqa: E402

GROUPS = {
    "byte": ("G-BYTE-LL", ("lz4-frame", "zstd-frame", "snappy-raw"), ()),
    "float": (
        "G-FLOAT-LL-F64",
        ("alp", "alp-rd", "chimp", "chimp128", "elf", "elf-plus", "elf-star", "self-star"),
        ("lz4-frame", "zstd-frame"),
    ),
    "int": (
        "G-INT-LL-I16",
        (
            "sprintz-delta",
            "sprintz-fire",
            "sprintz-fire-huff0",
            "neats-lossless-i64",
            "leats-lossless-i64",
        ),
        ("lz4-frame", "zstd-frame"),
    ),
    "abs": ("G-FLOAT-ABS", ("serf-qt", "serf-xor", "zfp-accuracy-1d"), ()),
    "quality": ("G-QUALITY", ("abba", "fabba"), ()),
    "model": ("G-BYTE-MODEL", ("deepzip", "dzip"), ("lz4-frame", "zstd-frame")),
    "entropy": ("G-BYTE-ENTROPY-LL", ("fse", "huff0", "lz4-frame", "zstd-frame"), ()),
    "u8": ("G-UINT8-LL", ("sprintz-delta-u8", "sprintz-fire-u8", "lz4-frame", "zstd-frame"), ()),
}
SOURCES = {
    "etth1": ("ETT_TRANSFORMER", "ETTh1_TRANSFORMER", "https://github.com/zhouhaoyi/ETDataset"),
    "weather": ("JENA_WEATHER", "JENA_WEATHER_STATION", "https://www.bgc-jena.mpg.de/wetter/"),
    "pems04": ("CALIFORNIA_PEMS", "PEMS04_DISTRICT", "https://pems.dot.ca.gov/"),
    "national_illness": (
        "CDC_ILI",
        "US_NATIONAL_ILI",
        "https://gis.cdc.gov/grasp/fluview/fluportaldashboard.html",
    ),
}
PATTERNS = ("constant", "linear", "periodic", "random")
QUALITY_POINTS = ("0.01", "0.1", "1")
BOUNDED_SOURCE_ROWS = 4096
BOUNDED_BYTE_LIMIT = 131072


def base4_symbols(payload: bytes) -> np.ndarray:
    """A declared symbol-stream task; no typed floating-object recovery claim."""
    octets = np.frombuffer(payload, dtype=np.uint8)
    symbols = ((octets[:, None] >> np.array([6, 4, 2, 0], dtype=np.uint8)) & 3).reshape(-1)
    rebuilt = ((symbols.reshape(-1, 4).astype(np.uint16) << [6, 4, 2, 0]).sum(axis=1)).astype("u1")
    if rebuilt.tobytes() != payload:
        raise ValueError("base4 serialization is not injective")
    return symbols


def configurations_for(manifest, group_key):
    defaults = {
        name: info["default"]
        for name, info in manifest.document["parameters"]["properties"].items()
        if "default" in info
    }
    points = (
        QUALITY_POINTS if group_key == "quality" and manifest.key in {"abba", "fabba"} else (None,)
    )
    configurations = []
    for point in points:
        parameters = dict(defaults)
        if group_key == "abs":
            parameters["error_bound"] = "0.001"
        if point is not None:
            if manifest.key == "abba":
                parameters.update(compression_tolerance=point, digitization_tolerance=point)
            else:
                parameters.update(tolerance=point, alpha=point)
        normalized = expand_sweep(
            manifest,
            {key: [value] for key, value in parameters.items()},
            framework_parameters={"benchmark_seed": 20261010},
        )[0]
        if normalized.status.value != "PLANNED":
            raise ValueError(f"frozen configuration is invalid: {manifest.key}")
        mode = manifest.loss_modes[0].value
        bounded = mode == "ERROR_BOUNDED_LOSSY"
        unbounded = mode == "UNBOUNDED_LOSSY"
        configurations.append(
            {
                "config_key": f"quality-tolerance-{point}"
                if point is not None
                else ("registered-default-abs0.001" if bounded else "registered-default"),
                "parameters": normalized.parameters,
                "framework_parameters": normalized.framework_parameters,
                "loss_mode": mode,
                "guarantee": {
                    "kind": "UNBOUNDED" if unbounded else "PROVEN_BOUND" if bounded else "LOSSLESS",
                    "metric": "MAXAE_V1" if bounded else None,
                    "threshold": "0.001" if bounded else None,
                    "unit": "ORIGINAL_VALUE_UNITS" if bounded or unbounded else "BITWISE",
                    "original_domain_total": not unbounded,
                },
            }
        )
    return configurations


def write_or_verify(path: Path, document: dict) -> None:
    payload = (
        json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    )
    if path.exists():
        if json.loads(path.read_text()) != document:
            raise ValueError(f"refusing to overwrite frozen artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)


def from_columns(
    key: str, columns: list[ValueBuffer], spec: dict, source_bytes: int
) -> CanonicalDataset:
    values = tuple(replace(c, array=immutable(np.ascontiguousarray(c.array))) for c in columns)
    n, m = values[0].array.size, len(values)
    logical = {
        "schema_version": "tscb.logical-view.v2",
        "topology": "UTS" if m == 1 else "SYNCHRONOUS_MTS",
        "axes": ["time"] if m == 1 else ["time", "feature"],
        "n_rows": n,
        "timestamp": {
            "present": False,
            "origin": "NONE",
            "unit": "NOT_APPLICABLE",
            "epoch": "NOT_APPLICABLE",
            "order_policy": "PRESERVE",
        },
        "value_shape": [n] if m == 1 else [n, m],
        "value_columns": [c.descriptor() for c in values],
        "validity_shape": "NONE",
        "nan_is_null": False,
    }
    manifest = DatasetManifest(
        key,
        Path(__file__),
        Path(__file__),
        {"file": {"bytes": source_bytes}},
        stable_id("comparison-derived-source", spec, version="v3"),
    )
    physical = tuple(
        {
            "view_id": f"value/{i:06d}",
            "layout": "ROW_MAJOR_CONTIG",
            "shape": [n],
            "dtype": c.array.dtype.str,
            "endianness": "little",
        }
        for i, c in enumerate(values)
    )
    return CanonicalDataset(
        manifest,
        None,
        values,
        None,
        logical,
        physical,
        {"generation_spec": spec, "hidden_transforms": []},
    )


def synthetic(
    key: str, dtype: str, pattern: str, *, seed: int, n: int, m: int
) -> tuple[CanonicalDataset, dict]:
    index = np.arange(n, dtype=np.int64)[:, None]
    channels = np.arange(m, dtype=np.int64)[None, :]
    if pattern == "constant":
        data = np.full((n, m), 10, dtype=np.int64) + channels
    elif pattern == "linear":
        data = index + channels + 10
    elif pattern == "periodic":
        data = index % 16 + channels + 10
    else:
        data = np.random.Generator(np.random.PCG64(seed)).integers(
            10, 256, size=(n, m), dtype=np.int64
        )
    if np.dtype(dtype).kind == "f":
        data = data / 16
    data = np.asarray(data, dtype=dtype)
    spec = {
        "kind": "SYNTHETIC",
        "pattern": pattern,
        "rng": "numpy.PCG64",
        "seed": seed,
        "n": n,
        "m": m,
        "dtype": dtype,
        "formula_version": "1",
        "floating_scale": "1/16" if data.dtype.kind == "f" else "1",
    }
    columns = [
        ValueBuffer(
            f"synthetic/{i:06d}",
            f"synthetic-{i}",
            data[:, i],
            "count" if data.dtype.kind in "iu" else "UNSPECIFIED",
            "synthetic",
            f"channel-{i}",
        )
        for i in range(m)
    ]
    return from_columns(key, columns, spec, data.nbytes), spec


class BundleBuilder:
    def __init__(self, payload_root: Path, cpus: list[int], *, revision: int = 3):
        self.payload_root = payload_root.resolve()
        self.manifests = ROOT / "registry/comparison_datasets/v32_20261010"
        self.datasets = DatasetRegistry(self.manifests, ROOT)
        self.originals = DatasetRegistry(ROOT / "registry/datasets", ROOT)
        self.codecs = CodecRegistry(
            ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")
        )
        self.active = set(
            json.loads((ROOT / "registry/algorithm_scope.json").read_text())["registered_codecs"]
        )
        self.cpus = cpus
        self.revision = f"20261010-v{revision}"
        self.revision_suffix = f"-v{revision}"
        self.protocol = MeasurementProtocol(
            profile="STEADY_PROCESS",
            outer_repetitions=8,
            encode_min_ns=50_000_000,
            decode_min_ns=50_000_000,
            max_trial_wall_ns=30_000_000_000,
            max_total_wall_ns=3_600_000_000_000,
            pilot_seed=20261010,
            thread_monitor_interval_ns=1_000_000,
        )
        self.policy = AnalysisPolicy()
        self.entries = {}
        self._original_cache = {}

    def original(self, key):
        if key not in self._original_cache:
            self._original_cache[key] = load_dataset(self.originals.load(key))
        return self._original_cache[key]

    def register(self, key, dataset, spec, *, source=None, split="TEST", proof=None):
        if key in self.entries:
            return self.entries[key]
        path = self.payload_root / "sources" / f"{key}.tscb"
        if path.exists():
            artifact = read_canonical(path, include_buffers=False)
            if (
                artifact.metadata["dataset_id"] != dataset.dataset_id
                or artifact.metadata["dataset_content_sha256"] != dataset.content_sha256()
            ):
                raise ValueError(f"derived canonical source changed: {key}")
        else:
            artifact = write_canonical(dataset, path)
        license_info = (
            source.manifest.document["license"]
            if source
            else {"spdx": "CC0-1.0", "status": "RUN_ALLOWED"}
        )
        doc = canonical_source_document(
            path,
            ROOT,
            key,
            split={
                "policy": split,
                "learned_eligible": False,
                "reason": (
                    "Frozen whole-object CPU comparison; "
                    "no learned split or source generalization claimed."
                ),
            },
            license_info=license_info,
        )
        doc["source"].update(
            uri=source.manifest.document["source"]["uri"] if source else "local:synthetic",
            retrieved_at=source.manifest.document["source"]["retrieved_at"]
            if source
            else "LOCAL_GENERATED",
            notes=json.dumps(
                {
                    "generation_spec": spec,
                    "source_manifest": str(source.manifest.path.relative_to(ROOT))
                    if source
                    else None,
                    "source_sha256": source.manifest.document["file"]["sha256"] if source else None,
                    "first_party_project_reference": SOURCES[source.manifest.key][2]
                    if source
                    else None,
                    "source_lineage_authentication": (
                        "LOCAL_MANIFEST_ONLY_NOT_EXTERNALLY_AUTHENTICATED"
                    )
                    if source
                    else "GENERATOR_FULL_SPEC",
                    "domain_proof": proof,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        write_or_verify(self.manifests / f"{key}.json", doc)
        output = self.payload_root / "prepared"
        if (output / key / "preparation-record.json").exists():
            prepared = load_preparation_result(self.datasets, key, output)
        else:
            prepared = prepare_dataset(self.datasets, key, output)
        prepared_artifact = read_canonical(prepared.canonical.path, include_buffers=False)
        entry = {
            "key": key,
            "dataset_id": prepared.dataset_id,
            "artifact_sha256": prepared.canonical.sha256,
            "logical_content_id": semantic_content_sha256(
                prepared_artifact.metadata, policy="tscb.dataset-content.v2"
            ),
            "source_transport_sha256": artifact.sha256,
            "generation_spec": spec,
            "domain_proof": proof,
            "logical_shape": dataset.logical_descriptor["value_shape"],
        }
        self.entries[key] = entry
        return entry

    def real_float(self, *, row_stop=8192):
        rows = []
        for source_key in ("etth1", "weather"):
            source = self.original(source_key)
            for m in (1, 4):
                key = f"v32_{source_key}_f64_{'uts' if m == 1 else 'mts'}"
                if row_stop != 8192:
                    key += f"_n{row_stop}"
                columns = [replace(c, array=c.array[:row_stop]) for c in source.values[:m]]
                arrays = [c.array for c in columns]
                if not all(
                    c.shape == (row_stop,) and c.dtype == np.dtype("<f8") and np.all(np.isfinite(c))
                    for c in arrays
                ):
                    raise ValueError("finite original f64 core predicate failed")
                spec = {
                    "kind": "REAL_VALUE_WINDOW",
                    "source_key": source_key,
                    "parent_dataset_id": source.dataset_id,
                    "parent_file_sha256": source.manifest.document["file"]["sha256"],
                    "row_start": 0,
                    "row_stop": row_stop,
                    "selected_columns": [c.name for c in columns],
                    "dtype_policy": "PRESERVE_ORIGINAL_F64",
                    "timestamp_policy": "VALUE_TRACK_SOURCE_TIMESTAMPS_OUTSIDE_OBJECT",
                }
                if row_stop != 8192:
                    spec.update(
                        window_selection_rule="PREDECLARED_CAPABILITY_BOUND_NO_RESULT_SELECTION",
                        source_manifest=str(source.manifest.path.relative_to(ROOT)),
                        domain_limit_bytes=BOUNDED_BYTE_LIMIT,
                        window_reason=(
                            "Existing FSE/Huff0 complete-object bound is 131072 bytes; "
                            "4096 rows x 4 original f64 columns fit without truncating output."
                        ),
                    )
                proof = {
                    "checked_values": sum(a.size for a in arrays),
                    "finite": True,
                    "original_dtype": "<f8",
                    "lossy_transform": False,
                    "minimum": [str(a.min()) for a in arrays],
                    "maximum": [str(a.max()) for a in arrays],
                }
                rows.append(
                    (
                        self.register(
                            key,
                            from_columns(
                                key, columns, spec, source.manifest.document["file"]["bytes"]
                            ),
                            spec,
                            source=source,
                            proof=proof,
                        ),
                        source,
                    )
                )
        return rows

    def real_u8(self):
        """Complete uint8 byte objects, derived before any codec/result observation."""
        rows = []
        for source_key in ("etth1", "weather"):
            source = self.original(source_key)
            for channels in (1, 4):
                selected = source.values[:channels]
                if len(selected) != channels or any(
                    column.array.ndim != 1
                    or column.array.size < BOUNDED_SOURCE_ROWS
                    or column.array.dtype != np.dtype("<f8")
                    for column in selected
                ):
                    raise ValueError("predeclared original f64 byte serialization domain failed")
                payload = b"".join(
                    column.array[:BOUNDED_SOURCE_ROWS].tobytes(order="C") for column in selected
                )
                data = np.frombuffer(payload, dtype="u1").copy()
                if data.size > BOUNDED_BYTE_LIMIT or data.tobytes() != payload:
                    raise ValueError(
                        "uint8 object exceeds the predeclared native complete-object domain"
                    )
                key = f"v32_{source_key}_u8_bytes_n{BOUNDED_SOURCE_ROWS}_c{channels}"
                spec = {
                    "kind": "REAL_SENSOR_F64_BYTES_TO_UINT8_OBJECT",
                    "source_key": source_key,
                    "parent_dataset_id": source.dataset_id,
                    "parent_file_sha256": source.manifest.document["file"]["sha256"],
                    "source_manifest": str(source.manifest.path.relative_to(ROOT)),
                    "row_start": 0,
                    "row_stop": BOUNDED_SOURCE_ROWS,
                    "selected_columns": [column.name for column in selected],
                    "serialization": "COLUMN_ORDER_ORIGINAL_LE_F64_BYTES_AS_UINT8_V1",
                    "source_payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "original_comparison_object": "UINT8_BYTE_STREAM",
                    "floating_object_recovery_claim": False,
                    "model_symbol_task": False,
                    "timestamp_policy": "SOURCE_TIMESTAMPS_OUTSIDE_UINT8_OBJECT",
                    "split_policy": "PREDECLARED_TEST_SOURCE_WINDOW_NO_RESULT_SELECTION",
                    "window_selection_rule": "PREDECLARED_CAPABILITY_BOUND_NO_RESULT_SELECTION",
                    "domain_limit_bytes": BOUNDED_BYTE_LIMIT,
                    "window_reason": (
                        "Existing Sprintz uint8 UTS max_n is 131072; "
                        "4096 rows x 4 source f64 columns serialize to at most 131072 bytes."
                    ),
                }
                proof = {
                    "original_dtype": "|u1",
                    "logical_rank": 1,
                    "logical_channels": 1,
                    "allowed_range": [0, 255],
                    "actual_minimum": int(data.min()),
                    "actual_maximum": int(data.max()),
                    "byte_count": int(data.size),
                    "source_byte_count": len(payload),
                    "injective_byte_serialization": True,
                    "source_column_boundaries_predeclared": True,
                    "lossy_transform": False,
                    "comparison_recovery_domain": "ORIGINAL_UINT8_BYTE_OBJECT_ONLY",
                }
                column = ValueBuffer(
                    "serialized-u8", "serialized-u8", data, "BYTE", source_key, "source-value-bytes"
                )
                rows.append(
                    (
                        self.register(
                            key,
                            from_columns(key, [column], spec, len(payload)),
                            spec,
                            source=source,
                            proof=proof,
                        ),
                        source,
                    )
                )
        return rows

    def u8_auxiliary(self):
        keys = []
        for pattern in PATTERNS:
            key = f"v32_qual_u8_bytes_{pattern}_m1"
            index = np.arange(257, dtype=np.uint64)
            data = (
                np.full(257, 255, dtype="u1")
                if pattern == "constant"
                else (index % 256).astype("u1")
                if pattern == "linear"
                else ((index // 3) % 256).astype("u1")
                if pattern == "periodic"
                else np.random.Generator(np.random.PCG64(20261010)).integers(
                    0, 256, 257, dtype="u1"
                )
            )
            spec = {
                "kind": "SYNTHETIC_UINT8_BYTE_OBJECT",
                "pattern": pattern,
                "seed": 20261010,
                "rng": "numpy.PCG64",
                "n": 257,
                "m": 1,
                "dtype": "|u1",
                "allowed_range": [0, 255],
                "formula_version": "1",
            }
            column = ValueBuffer("byte", "byte", data, "BYTE", "synthetic", "byte")
            self.register(
                key, from_columns(key, [column], spec, data.nbytes), spec, split="VALIDATION"
            )
            keys.append(key)
        key = "v32_dev_u8_bytes_random_m1"
        data = np.random.Generator(np.random.PCG64(20261011)).integers(0, 256, 1027, dtype="u1")
        spec = {
            "kind": "SYNTHETIC_UINT8_BYTE_OBJECT",
            "pattern": "random",
            "seed": 20261011,
            "rng": "numpy.PCG64",
            "n": 1027,
            "m": 1,
            "dtype": "|u1",
            "allowed_range": [0, 255],
            "formula_version": "1",
            "development_use": "PILOT_ONLY",
        }
        column = ValueBuffer("byte", "byte", data, "BYTE", "synthetic", "byte")
        self.register(key, from_columns(key, [column], spec, data.nbytes), spec, split="VALIDATION")
        return key, keys

    def real_int(self):
        rows = []
        for source_key in ("pems04", "national_illness"):
            source = self.original(source_key)
            if source_key == "pems04":
                all_values = source.values[0].array[:, :, 0]
                selected = [
                    ValueBuffer(
                        f"sensor/{i:06d}/feature/000000",
                        f"sensor-{i}-feature-0",
                        all_values[:, i],
                        "UNSPECIFIED",
                        f"PEMS04-sensor-{i}",
                        "feature-0",
                    )
                    for i in range(4)
                ]
            else:
                selected = [
                    c for c in source.values if c.display_name in {"AGE 0-4", "NUM. OF PROVIDERS"}
                ]
                if len(selected) != 2:
                    raise ValueError("expected named illness count columns are missing")
                all_values = np.column_stack([c.array for c in selected])
            valid = (
                np.all(np.isfinite(all_values))
                and np.all(all_values == np.trunc(all_values))
                and all_values.min() >= -32768
                and all_values.max() <= 32767
            )
            if not valid:
                raise ValueError(
                    "full-source integer/range proof failed; quantization is forbidden"
                )
            proof = {
                "full_source_selected_feature_values": int(all_values.size),
                "finite": True,
                "integral": True,
                "minimum": str(all_values.min()),
                "maximum": str(all_values.max()),
                "target_dtype": "<i2",
                "exact_round_trip": True,
                "lossy_transform": False,
            }
            for m in (1, len(selected)):
                key = f"v32_{source_key}_i16_{'uts' if m == 1 else 'mts'}"
                n = min(8192, source.n_rows)
                columns = []
                for c in selected[:m]:
                    before = c.array[:n]
                    after = np.asarray(before, dtype="<i2")
                    if not np.array_equal(after.astype(before.dtype), before):
                        raise ValueError("integer narrowing changed original numeric values")
                    columns.append(replace(c, array=after))
                spec = {
                    "kind": "REAL_INTEGER_VALUE_WINDOW",
                    "source_key": source_key,
                    "parent_dataset_id": source.dataset_id,
                    "parent_file_sha256": source.manifest.document["file"]["sha256"],
                    "row_start": 0,
                    "row_stop": n,
                    "selected_columns": [c.name for c in columns],
                    "source_feature": "FEATURE_AXIS_0"
                    if source_key == "pems04"
                    else "NAMED_COUNT_COLUMNS",
                    "dtype_policy": "PROVED_EXACT_I16_NUMERIC_REPRESENTATION_NO_QUANTIZATION",
                    "timestamp_policy": "VALUE_TRACK_SOURCE_TIMESTAMPS_OUTSIDE_OBJECT",
                }
                rows.append(
                    (
                        self.register(
                            key,
                            from_columns(
                                key, columns, spec, source.manifest.document["file"]["bytes"]
                            ),
                            spec,
                            source=source,
                            proof=proof,
                        ),
                        source,
                    )
                )
        return rows

    def auxiliary(self, dtype):
        label = "i16" if np.dtype(dtype).kind == "i" else "f64"
        keys = []
        for pattern in PATTERNS:
            for m in (1, 4):
                key = f"v32_qual_{label}_{pattern}_m{m}"
                dataset, spec = synthetic(key, dtype, pattern, seed=20261010, n=257, m=m)
                self.register(key, dataset, spec, split="VALIDATION")
                keys.append(key)
        key = f"v32_dev_{label}_random_m3"
        dataset, spec = synthetic(key, dtype, "random", seed=20261011, n=1027, m=3)
        self.register(key, dataset, spec, split="VALIDATION")
        return key, keys

    def real_model_symbols(self):
        rows = []
        for source_key in ("etth1", "weather"):
            source = self.original(source_key)
            for channels in (1, 4):
                selected = source.values[:channels]
                n = min(32, source.n_rows)
                payload = b"".join(
                    np.asarray(column.array[:n], dtype="<f8").tobytes() for column in selected
                )
                symbols = base4_symbols(payload)
                key = f"v32_{source_key}_base4_n32_c{channels}"
                spec = {
                    "kind": "REAL_SENSOR_BYTES_TO_BASE4_SYMBOL_STREAM",
                    "source_key": source_key,
                    "parent_dataset_id": source.dataset_id,
                    "parent_file_sha256": source.manifest.document["file"]["sha256"],
                    "row_start": 0,
                    "row_stop": n,
                    "selected_columns": [column.name for column in selected],
                    "serialization": "COLUMN_ORDER_LE_F64_BYTES_THEN_MSB_FIRST_2BIT_DIGITS_V1",
                    "source_payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "original_comparison_object": "UINT8_BASE4_SYMBOL_STREAM",
                    "floating_object_recovery_claim": False,
                    "timestamp_policy": "SOURCE_TIMESTAMPS_OUTSIDE_SYMBOL_OBJECT",
                    "split_policy": "PREDECLARED_TEST_SOURCE_WINDOW_NO_MODEL_FITTING_OR_SELECTION",
                }
                proof = {
                    "alphabet": [0, 1, 2, 3],
                    "actual_minimum": int(symbols.min()),
                    "actual_maximum": int(symbols.max()),
                    "injective_byte_serialization": True,
                    "original_dtype": "|u1",
                    "symbol_count": int(symbols.size),
                    "source_byte_count": len(payload),
                    "lossy_transform": False,
                    "model_training_provenance": "UNKNOWN_FOR_FROZEN_DEEPZIP_MODEL_NOT_INFERRED",
                    "dzip_initial_model": "DECLARED_SEEDED_UNTRAINED_ALPHABET_PER_OBJECT",
                }
                column = ValueBuffer(
                    "base4-symbol",
                    "base4-symbol",
                    symbols,
                    "BASE4_SYMBOL",
                    source_key,
                    "serialized-value-symbol",
                )
                rows.append(
                    (
                        self.register(
                            key,
                            from_columns(key, [column], spec, len(payload)),
                            spec,
                            source=source,
                            proof=proof,
                        ),
                        source,
                    )
                )
        return rows

    def model_auxiliary(self):
        keys = []
        for pattern in PATTERNS:
            key = f"v32_qual_base4_{pattern}_m1"
            index = np.arange(129, dtype=np.int64)
            data = (
                np.zeros(129, dtype="u1")
                if pattern == "constant"
                else (
                    (index % 4).astype("u1")
                    if pattern == "linear"
                    else (
                        ((index // 3) % 4).astype("u1")
                        if pattern == "periodic"
                        else np.random.Generator(np.random.PCG64(20261010)).integers(
                            0, 4, 129, dtype="u1"
                        )
                    )
                )
            )
            spec = {
                "kind": "SYNTHETIC_BASE4_SYMBOL_STREAM",
                "pattern": pattern,
                "seed": 20261010,
                "rng": "numpy.PCG64",
                "n": 129,
                "m": 1,
                "dtype": "|u1",
                "alphabet": [0, 1, 2, 3],
                "formula_version": "1",
            }
            column = ValueBuffer("symbol", "symbol", data, "BASE4_SYMBOL", "synthetic", "symbol")
            self.register(
                key, from_columns(key, [column], spec, data.nbytes), spec, split="VALIDATION"
            )
            keys.append(key)
        key = "v32_dev_base4_random_m1"
        data = np.random.Generator(np.random.PCG64(20261011)).integers(0, 4, 257, dtype="u1")
        spec = {
            "kind": "SYNTHETIC_BASE4_SYMBOL_STREAM",
            "pattern": "random",
            "seed": 20261011,
            "rng": "numpy.PCG64",
            "n": 257,
            "m": 1,
            "dtype": "|u1",
            "alphabet": [0, 1, 2, 3],
            "formula_version": "1",
            "development_use": "PILOT_ONLY_NO_MODEL_TRAINING",
        }
        column = ValueBuffer("symbol", "symbol", data, "BASE4_SYMBOL", "synthetic", "symbol")
        self.register(key, from_columns(key, [column], spec, data.nbytes), spec, split="VALIDATION")
        return key, keys

    def build(self, group_key):
        name, core, references = GROUPS[group_key]
        model, quality = group_key == "model", group_key == "quality"
        if len(self.cpus) != (3 if model else 1):
            raise ValueError("model comparison freezes three CPUs/threads; other groups freeze one")
        if model:
            real = self.real_model_symbols()
            dev, qualification = self.model_auxiliary()
        elif group_key == "u8":
            real = self.real_u8()
            dev, qualification = self.u8_auxiliary()
        else:
            real = (
                self.real_int()
                if group_key == "int"
                else self.real_float(
                    row_stop=BOUNDED_SOURCE_ROWS if group_key == "entropy" else 8192
                )
            )
            dev, qualification = self.auxiliary("<i2" if group_key == "int" else "<f8")
        protocol = (
            replace(
                self.protocol,
                max_trial_wall_ns=900_000_000_000,
                max_total_wall_ns=7_200_000_000_000,
                max_inner_iterations=8,
                outer_repetitions=4,
                min_outer_repetitions=4,
                pilot_repetitions=3,
            )
            if model
            else self.protocol
        )
        fixed = group_key == "abs"
        selection = {
            "kind": "FULL_GRID" if quality else "FROZEN_DEFAULT",
            "max_configs_per_method": 3 if quality else 1,
            "selection_dataset_ids": [],
            "objective": None,
            "tie_break": "LEXICAL_CONFIG_KEY",
            "selection_cost_policy": "PREDECLARED_NO_TEST_SELECTION",
        }
        contract = ComparisonContract.from_document(
            {
                "schema_version": "tscb.comparison-contract.v1",
                "name": name,
                "revision": self.revision,
                "research_question": (
                    "Complete uint8 base4 symbol streams derived from declared real sensor bytes: "
                    "lossless storage and independent-object PIPELINE time, "
                    "equal three-thread budgets, model state included; no floating-object "
                    "or unseen-source generalization claim."
                    if model
                    else "Original f64 VALUE objects: empirical per-channel RMSE/MaxAE, finalized "
                    "storage and independent-object PIPELINE time on a frozen three-point "
                    "unbounded-quality grid; no fixed-error guarantee."
                    if quality
                    else "Complete original uint8 byte objects serialized from predeclared "
                    "source f64 bytes: lossless finalized storage and independent-object "
                    "PIPELINE time under equal single-worker CPU budgets; no original-floating "
                    "recovery, model-symbol or unseen-source generalization claim."
                    if group_key == "u8"
                    else "Complete original VALUE objects: finalized storage and "
                    "independent-object PIPELINE time under equal CPU budgets on this fixed corpus."
                ),
                "estimand": {
                    "population": "FIXED_CORPUS",
                    "outcome": "FINAL_BITS_AND_PIPELINE_WALL_NS",
                    "aggregation": "RAW_BITS_WEIGHTED_AND_PAIRED_DATASET",
                    "weight_unit": "RAW_BITS",
                },
                "mode": "COMPLETE_OBJECT",
                "track": "VALUE",
                "recovery": {
                    "mode": "APPROX_GRID" if fixed or quality else "EXACT_GRID",
                    "null_semantics": "BITWISE",
                    "coordinate_policy": "PRESERVE_ORIGINAL_GRID",
                },
                "fidelity": {
                    "kind": "QUALITY_CURVE" if quality else "FIXED_ERROR" if fixed else "LOSSLESS",
                    "error_metric": "MAXAE_V1" if fixed else None,
                    "threshold": "0.001" if fixed else None,
                    "unit": "ORIGINAL_VALUE_UNITS" if fixed or quality else "BITWISE",
                    "quality_metrics": ["RMSE_V1", "MAXAE_V1"] if quality else [],
                },
                "cost_boundary": "SCHEMA_BOUND_OBJECT",
                "timing_boundary": "PIPELINE",
                "workload": "WHOLE_OBJECT",
                "state": "INDEPENDENT_OBJECT",
                "resources": {
                    "device": "CPU",
                    "threads": 3 if model else 1,
                    "processes": 1,
                    "memory_limit_bytes": 8_589_934_592 if model else 2_147_483_648,
                    "isa_policy": "ANY_AVAILABLE",
                    "allowed_isa": [],
                    "machine_policy_id": stable_id(
                        "machine-budget",
                        {
                            "host": platform.node(),
                            "machine": platform.machine(),
                            "cpu_affinity": self.cpus,
                            "threads": 3 if model else 1,
                            "processes": 1,
                            "memory_limit_bytes": 8_589_934_592 if model else 2_147_483_648,
                        },
                        version="v3",
                    ),
                },
                "selection_policy": selection,
                "measurement_protocol_id": protocol.protocol_id,
                "analysis_policy_id": self.policy.id,
            }
        )
        corpus_rows = []
        for entry, original in real:
            family, entity, _ = SOURCES[original.manifest.key]
            source = {
                "family": family,
                "entity": entity,
                "independence_unit": original.manifest.key,
                "evidence": [
                    f"LOCAL_SOURCE_MANIFEST:{original.manifest.path.relative_to(ROOT)}",
                    f"RAW_SHA256:{original.manifest.document['file']['sha256']}",
                    "COLUMNS_AND_WINDOWS_OF_ONE_SOURCE_ARE_ONE_INDEPENDENCE_UNIT",
                    "PROJECT_REFERENCE_DOES_NOT_AUTHENTICATE_LOCAL_FILE_LINEAGE",
                ],
            }
            corpus_rows.append(
                {
                    "dataset_id": entry["dataset_id"],
                    "logical_content_id": entry["logical_content_id"],
                    "artifact_sha256": entry["artifact_sha256"],
                    "role": "CORE",
                    "source_kind": "REAL",
                    "source": source,
                    "parents": [
                        {
                            "dataset_id": original.dataset_id,
                            "source_kind": "REAL",
                            "family": family,
                            "entity": entity,
                            "independence_unit": original.manifest.key,
                        }
                    ],
                    "derivation": "SERIALIZATION" if model or group_key == "u8" else "WINDOW",
                    "split": "TEST",
                    "weight": "1",
                    "domain_evidence": [
                        f"GENERATION_SPEC:{self.manifests.relative_to(ROOT)}/{entry['key']}.json",
                        "PROVED_EXACT_NUMERIC_I16_NO_QUANTIZATION"
                        if group_key == "int"
                        else "BASE4_SYMBOL_STREAM_TASK_NOT_ORIGINAL_F64_OBJECT"
                        if model
                        else "UINT8_BYTE_OBJECT_TASK_NOT_ORIGINAL_FLOAT_OR_BASE4_SYMBOL_TASK"
                        if group_key == "u8"
                        else "ORIGINAL_FINITE_F64_VALUES_UNCHANGED",
                    ],
                }
            )
        corpus = CorpusSpec.from_document(
            {
                "schema_version": "tscb.corpus-spec.v1",
                "content_identity_policy": "tscb.dataset-content.v2",
                "name": name + "-real-core",
                "revision": self.revision,
                "selection_rule": (
                    "Predeclared first 32 rows, first 1 and 4 source columns serialized as "
                    "column-major little-endian f64 bytes then MSB-first base4 symbols. "
                    "Comparison original is the UTS uint8 symbol stream; "
                    "no result-dependent selection."
                    if model
                    else "Predeclared first 4096 source rows, first 1 and 4 source columns. "
                    "The 4-column f64 window is 131072 bytes, within the registered FSE/Huff0 "
                    "and Sprintz uint8 complete-object bounds. Original f64 objects for entropy; "
                    "column-order original little-endian f64 bytes as one-dimensional uint8 "
                    "objects for u8; no result-dependent selection."
                    if group_key in {"entropy", "u8"}
                    else "Predeclared first 8192 rows (or complete shorter source), "
                    "first 4 original float/sensor channels or 2 named illness count fields, "
                    "and first-channel UTS; no result-dependent selection."
                ),
                "sampling_design": (
                    "Fixed local sensor source corpus, two source families; related symbol "
                    "streams remain one independence unit. Synthetic pilot/qualification "
                    "objects are disjoint. DeepZip frozen model training overlap is UNKNOWN; "
                    "no learning, tuning, test selection or generalization claim."
                    if model
                    else "Fixed local source corpus, two source families; related UTS/MTS "
                    "windows remain the same independence unit. Exact integer "
                    "representation defines the original typed i16 task, "
                    "never a lossy cast route."
                ),
                "exclusion_rule": (
                    "The prior 8192-row four-column object exceeds the registered 131072-byte "
                    "domain and is excluded before measurement; the fixed 4096-row windows "
                    "are used for every member. "
                    if group_key in {"entropy", "u8"}
                    else ""
                )
                + (
                    "No post-result exclusions; all promised members/configs "
                    "remain in the fixed matrix."
                ),
                "datasets": corpus_rows,
            }
        )
        members, config_members, equivalence, build_evidence = [], [], [], {}
        for key in (*core, *references):
            if key not in self.active or key not in self.codecs.keys():
                raise ValueError(f"requested core/reference codec is outside active scope: {key}")
            manifest = self.codecs.get(key)
            method_definition = {
                "name": manifest.document["identity"]["display_name"],
                "mechanism": manifest.document["identity"]["family"],
                "variant": key,
                "semantic_version": "1",
                "definition_sha256": hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "classification": manifest.document["classification"],
                            "semantics": manifest.document["semantics"],
                            "input": manifest.document["input"],
                            "lifecycle": manifest.document["lifecycle"],
                        }
                    )
                ).hexdigest(),
            }
            source = self.codecs.sources.get(manifest.source_artifact_id)
            tags = [f"SOURCE_ARTIFACT:{manifest.source_artifact_id}"]
            members.append(
                {
                    "member_id": key,
                    "codec_key": key,
                    "role": "CORE" if key in core else "REFERENCE",
                    "method": method_definition,
                    "implementation": {
                        "method_id": method_id(method_definition),
                        "source_artifact_id": manifest.source_artifact_id,
                        "source_closure_sha256": registered_source_closure_digest(self.codecs, key),
                        "implementation_variant": "REGISTERED_SOURCE_CPU",
                    },
                    "allowed_paths": ["SOURCE_REJECT_RAW"]
                    if key == "alp"
                    else [
                        "DIRECT",
                        "EXACT_WIDEN",
                        "BYTE_SERIALIZATION",
                        "COLUMN_INDEPENDENT",
                        "JOINT",
                    ],
                    "shared_code_tags": tags,
                }
            )
            equivalence.append(
                {
                    "class_id": key,
                    "members": [key],
                    "basis": (
                        "Distinct frozen mechanism/variant; forced ALP/ALP-RD and "
                        "predictor/entropy variants disclosed as variants, "
                        "never aliases or best-of selection."
                    ),
                    "evidence": manifest.document["identity"]["citations"]
                    + [
                        f"SOURCE_ARTIFACT:{source['source_artifact_id']}",
                        f"MANIFEST:registry/codecs/{key}.json",
                    ],
                }
            )
            config_members.append(
                {
                    "member_id": key,
                    "configs": configurations_for(manifest, group_key),
                }
            )
            artifact, supporting = adapter_artifacts(ROOT, manifest)
            paths = (artifact, *supporting)
            build_evidence[key] = {
                "files": [
                    {
                        "path": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()
                        if p.is_file()
                        else None,
                    }
                    for p in paths
                ],
                "available": all(p.is_file() for p in paths),
            }
        configs = MethodConfigMap.from_document(
            {
                "schema_version": "tscb.method-config-map.v1",
                "contract_id": contract.id,
                "selection_policy": selection,
                "members": config_members,
            }
        )
        expected_rows = []
        for entry, _ in real:
            dataset = load_dataset(self.datasets.load(entry["key"]))
            descriptor = descriptor_from_dataset(dataset, BenchmarkTrack.VALUE)
            for member in config_members:
                key = member["member_id"]
                for config in member["configs"]:
                    compat = negotiate(
                        self.codecs.get(key), descriptor, parameters=config["parameters"]
                    )
                    if compat.status is CapabilityStatus.UNSUPPORTED:
                        raise ValueError(
                            f"predeclared real core is not structurally legal: "
                            f"{key}/{entry['key']}: {compat.reason_code}"
                        )
                    expected_rows.append(
                        {
                            "dataset_id": entry["dataset_id"],
                            "member_id": key,
                            "config_key": config["config_key"],
                            "expected": {
                                "outcome": "PASS",
                                "reason": (
                                    "SOURCE_DOMAIN_STRUCTURALLY_LEGAL_REQUIRES_REAL_QUALIFICATION"
                                ),
                                "origin": "TASK",
                                "stage": "COMPLETE_RECOVERY",
                                "evidence": [
                                    f"MANIFEST:registry/codecs/{key}.json",
                                    f"SOURCE_DOMAIN_PROOF:{self.manifests.relative_to(ROOT)}/{entry['key']}.json",
                                    "STRUCTURAL_NEGOTIATION_IS_NOT_OBSERVED_CORRECTNESS",
                                ],
                            },
                        }
                    )
        expected = ExpectedOutcomeMatrix.from_document(
            {
                "schema_version": "tscb.expected-outcome-matrix.v1",
                "contract_id": contract.id,
                "corpus_id": corpus.id,
                "config_map_id": configs.id,
                "entries": expected_rows,
            }
        )
        group = GroupSpec.from_document(
            {
                "schema_version": "tscb.group-spec.v1",
                "name": name,
                "revision": self.revision,
                "contract_id": contract.id,
                "corpus_id": corpus.id,
                "config_map_id": configs.id,
                "expected_matrix_id": expected.id,
                "scope": "CORE_COMPARISON",
                "minimum_distinct_methods": 2,
                "minimum_independent_real_sources": 2,
                "completion_policy": "ALL_CORE_LEGAL_CONFIGS_AND_EXPECTED_TERMINALS",
                "members": members,
                "method_equivalence": equivalence,
            }
        )
        plan = compile_group_plan(
            group,
            contract,
            corpus,
            configs,
            expected,
            codec_registry=self.codecs,
            active_codec_keys=self.active,
        )
        bundle = {
            "schema_version": "tscb.comparison-bundle.v1",
            "contract": contract.to_document(),
            "corpus": corpus.to_document(),
            "group": group.to_document(),
            "config_map": configs.to_document(),
            "expected_matrix": expected.to_document(),
            "protocol": protocol.to_document(),
            "analysis_policy": self.policy.to_document(),
            "dataset_bindings": {entry["dataset_id"]: entry["key"] for entry, _ in real},
            "cpu_affinity": self.cpus,
            "seed": 20261010,
            "development_dataset": dev,
            "qualification_datasets": qualification,
        }
        target = (
            ROOT / "configs/comparisons" / f"{name.lower()}-v32-20261010{self.revision_suffix}.json"
        )
        write_or_verify(target, bundle)
        write_or_verify(
            self.payload_root / "plans" / f"{name}{self.revision_suffix}.json", plan.to_document()
        )
        write_or_verify(
            self.payload_root / "provenance" / f"{name}{self.revision_suffix}.json",
            {
                "schema_version": "tscb.comparison-build-provenance.v1",
                "bundle_sha256": hashlib.sha256(canonical_json_bytes(bundle)).hexdigest(),
                "planned_cell_count": len(plan.cells),
                "denominators": plan.denominators,
                "build_artifacts": build_evidence,
                "datasets": [entry for entry, _ in real],
                "development_dataset": self.entries[dev],
                "qualification_datasets": [self.entries[k] for k in qualification],
                "scientific_scope": {
                    "quality_grid": list(QUALITY_POINTS) if quality else [],
                    "quality_guarantee": "EMPIRICAL_ORIGINAL_DOMAIN_RMSE_MAXAE_NO_FIXED_BOUND"
                    if quality
                    else "LOSSLESS",
                    "model_original_object": "UINT8_BASE4_SYMBOL_STREAM" if model else None,
                    **(
                        {
                            "comparison_object": "ORIGINAL_F64_VALUE_OBJECT"
                            if group_key == "entropy"
                            else "UINT8_BYTE_STREAM",
                            "predeclared_source_rows": BOUNDED_SOURCE_ROWS,
                            "registered_complete_object_limit_bytes": BOUNDED_BYTE_LIMIT,
                            "floating_recovery_claim": group_key == "entropy",
                            "model_symbol_task": False,
                        }
                        if group_key in {"entropy", "u8"}
                        else {}
                    ),
                    "training_overlap": "UNKNOWN_FOR_FROZEN_DEEPZIP_MODEL_NO_GENERALIZATION_CLAIM"
                    if model
                    else "NOT_APPLICABLE",
                    "model_provenance": {
                        key: {
                            "parameters": config_members[index]["configs"],
                            "frozen_models": self.codecs.get(key)
                            .document["adapter"]
                            .get("models", {}),
                            "source_artifact_id": self.codecs.get(key).source_artifact_id,
                            "accounting": (
                                "COMPLETE_EMBEDDED_NATIVE_MODEL_FRAMES_COUNTED_IN_VALUE_BITS"
                            )
                            if key in {"deepzip", "dzip"}
                            else "NOT_APPLICABLE",
                            "separate_model_bucket": (
                                "NOT_ALLOCATED_BY_CURRENT_OPAQUE_FRAME_INSPECTOR"
                            )
                            if key in {"deepzip", "dzip"}
                            else "NOT_APPLICABLE",
                        }
                        for index, key in enumerate((*core, *references))
                    }
                    if model
                    else {},
                    "failure_policy": "KEEP_ALL_FROZEN_CONFIG_AND_CORPUS_CELLS",
                },
            },
        )
        return {
            "group": name,
            "bundle": str(target.relative_to(ROOT)),
            "cells": len(plan.cells),
            "denominators": plan.denominators,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--groups", nargs="+", choices=GROUPS, default=["byte", "float", "int", "abs"]
    )
    parser.add_argument(
        "--payload-root", type=Path, default=ROOT / "artifacts/comparisons/v32_20261010"
    )
    parser.add_argument("--cpu-affinity", nargs="+", type=int)
    parser.add_argument(
        "--revision",
        type=int,
        default=3,
        help="New immutable bundle revision (>=2); revision 1 remains historical evidence.",
    )
    args = parser.parse_args()
    allowed = sorted(os.sched_getaffinity(0))
    cpus = args.cpu_affinity or allowed[: 3 if args.groups == ["model"] else 1]
    if len(cpus) != len(set(cpus)) or not set(cpus) <= set(allowed):
        parser.error("CPU affinity must contain unique available logical CPUs")
    if "model" in args.groups and len(args.groups) != 1:
        parser.error("freeze the model group separately with its three-thread budget")
    if len(cpus) != (3 if args.groups == ["model"] else 1):
        parser.error("model group requires three available CPUs; other groups require one")
    if not args.payload_root.resolve().is_relative_to(ROOT):
        parser.error("canonical payloads must stay inside the project root")
    if not 2 <= args.revision <= 999:
        parser.error("new bundle revisions must be between 2 and 999")
    builder = BundleBuilder(args.payload_root, cpus, revision=args.revision)
    for group in args.groups:
        print(json.dumps(builder.build(group), ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
