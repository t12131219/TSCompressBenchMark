"""Register extensionless Dataset_Verify sources without overwriting v1 evidence.

Create a versioned rank-1 UTS view, source-domain fixtures selected from the
registered qualification templates, and the missing two-row boundaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
from verify_all_timing_scopes import select_template

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry, load_dataset
from tscompbench.datasets.canonical import read_canonical, write_canonical
from tscompbench.datasets.canonical_source import canonical_source_document
from tscompbench.datasets.models import CanonicalDataset, DatasetManifest, ValueBuffer, immutable
from tscompbench.ids import stable_id

ROOT = Path(__file__).resolve().parents[1]


def versioned_view(dataset):
    logical = deepcopy(dataset.logical_descriptor)
    if (
        logical["topology"] == "UTS"
        and len(dataset.values) == 1
        and dataset.values[0].array.ndim == 1
    ):
        logical["value_shape"] = [dataset.n_rows]
        logical["axes"] = ["time"]
    return replace(dataset, logical_descriptor=logical)


def synthetic(array, *, timestamp=None, key="boundary"):
    array = immutable(np.ascontiguousarray(array))
    shape = list(array.shape)
    is_uts = array.ndim == 1
    values = (
        ValueBuffer(
            "values",
            "values",
            array,
            "count" if array.dtype.kind in "iu" else "UNSPECIFIED",
            "synthetic",
            "values",
        ),
    )
    logical = {
        "schema_version": "tscb.logical-view.v2",
        "topology": "UTS"
        if is_uts
        else "SYNCHRONOUS_MTS"
        if array.ndim == 2
        else "NATIVE_ND_ARRAY",
        "axes": ["time"] + [f"axis{i}" for i in range(1, array.ndim)],
        "n_rows": shape[0],
        "timestamp": {
            "present": timestamp is not None,
            "origin": "NONE" if timestamp is None else "SYNTHETIC_EXPLICIT",
            "unit": "ms",
            "epoch": "UNIX",
            "order_policy": "PRESERVE",
        },
        "value_shape": shape,
        "value_columns": [values[0].descriptor()],
        "validity_shape": "NONE",
        "nan_is_null": False,
    }
    if timestamp is not None:
        timestamp = immutable(np.asarray(timestamp, dtype="<i8"))
    manifest = DatasetManifest(
        key,
        ROOT / "tools/prepare_dataset_verify_v3.py",
        ROOT / "tools/prepare_dataset_verify_v3.py",
        {"file": {"bytes": array.nbytes + (0 if timestamp is None else timestamp.nbytes)}},
        stable_id("dataset-verify-view-v3", {"key": key, "shape": shape, "dtype": array.dtype.str}),
    )
    physical = [
        {
            "view_id": "value-native-c",
            "layout": "ROW_MAJOR_CONTIG",
            "shape": shape,
            "endianness": "little",
            "dtype": array.dtype.str,
        }
    ]
    if timestamp is not None:
        physical.insert(
            0,
            {
                "view_id": "timestamp-row",
                "layout": "ROW_MAJOR_CONTIG",
                "dtype": "<i8",
                "shape": [shape[0]],
                "endianness": "little",
            },
        )
    return CanonicalDataset(
        manifest,
        timestamp,
        values,
        None,
        logical,
        tuple(physical),
        {"generator": "tools/prepare_dataset_verify_v3.py", "hidden_transforms": []},
    )


def prepare(root: Path, *, source_root: Path = ROOT / "Dataset_Verify"):
    root.mkdir(parents=True, exist_ok=True)
    manifests = root / "registry"
    manifests.mkdir(exist_ok=True)
    entries = []

    def register(path, key, group, original=None, split=None, license_info=None):
        doc = canonical_source_document(
            path,
            ROOT,
            key,
            split=split,
            license_info=license_info or {"spdx": "CC0-1.0", "status": "RUN_ALLOWED"},
        )
        target = manifests / f"{key}.json"
        if target.exists():
            if json.loads(target.read_text()) != doc:
                raise ValueError(f"refusing to overwrite changed verification manifest: {key}")
        else:
            target.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        entry = {
            "key": key,
            "group": group,
            "path": doc["file"]["path"],
            "original": original,
            "artifact_sha256": doc["file"]["sha256"],
            "content_sha256": doc["expected"]["semantic_content_sha256"],
            "shape": doc["expected"]["shape"],
            "n_rows": doc["expected"]["n_rows"],
        }
        entries.append(entry)
        return key

    index = json.loads((source_root / "index.json").read_text())
    # The old helper is used only to read its immutable v1 arrays, not to run codecs.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "dataset_verify_v1_fixtures", source_root / "fixtures.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    for i, entry in enumerate(index["entries"]):
        source = source_root / entry["path"]
        artifact = read_canonical(source, include_buffers=False)
        if artifact.sha256 != entry["file_sha256"]:
            raise ValueError(f"v1 artifact changed: {source}")
        if artifact.metadata["logical_descriptor"]["topology"] == "UTS":
            path = root / "data" / entry["path"].removeprefix("data/")
            if not path.exists():
                dataset = versioned_view(helper.load_fixture(entry["path"]))
                write_canonical(dataset, path)
        else:
            path = source
        key = "dv_" + hashlib.sha256(entry["path"].encode()).hexdigest()[:20]
        register(path, key, entry["generation_spec"]["group"], original=entry)
        if i % 100 == 0:
            print("registered", i, flush=True)
    # Dedicated legitimate input for each current codec; not invented histogram/audio semantics.
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    source_keys = {}
    codec_fixtures = {}
    for codec in codecs:
        if codec == "oracle-native-nd-only":
            key, path = "dv_native_nd", root / "special" / "native_nd"
            if not path.exists():
                write_canonical(
                    synthetic(np.arange(48, dtype="<f8").reshape(4, 3, 4), key=key), path
                )
            register(path, key, "native_nd")
        else:
            _, template = select_template(codec)
            source_key = template["datasets"][0]
            key = "dv_source_" + source_key
            if source_key not in source_keys:
                dataset = versioned_view(load_dataset(datasets.load(source_key)))
                path = root / "special" / source_key
                if not path.exists():
                    write_canonical(dataset, path)
                split = {
                    "reason": "Inherited registered source split",
                    **dataset.manifest.document["split"],
                }
                register(
                    path,
                    key,
                    "source_domain",
                    original={"source_key": source_key},
                    split=split,
                    license_info=dataset.manifest.document["license"],
                )
                source_keys[source_key] = key
        codec_fixtures[codec] = key
    for dtype in ("i1", "<i2", "<i4", "<i8", "u1", "<u2", "<u4", "<u8", "<f4", "<f8"):
        for m in (1, 8):
            for with_ts in (False, True):
                array = np.arange(2 * m, dtype=dtype).reshape((2,) if m == 1 else (2, m))
                key = f"dv_n2_{np.dtype(dtype).name}_m{m}_t{int(with_ts)}"
                path = root / "boundary_n2" / key
                if not path.exists():
                    write_canonical(
                        synthetic(array, timestamp=[0, 1000] if with_ts else None, key=key), path
                    )
                register(path, key, "boundary_n2")
    result = {
        "schema_version": "tscb.dataset-verify-index.v3",
        "policy": "new canonical identity; v1 untouched",
        "source_index_sha256": hashlib.sha256(
            (source_root / "index.json").read_bytes()
        ).hexdigest(),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "codec_fixtures": codec_fixtures,
        "entries": entries,
        "count": len(entries),
    }
    (root / "index.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print("PASS", len(entries), "sources", len(codec_fixtures), "codec fixtures", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "Dataset_Verify/v3")
    args = parser.parse_args()
    prepare(args.output.resolve())
