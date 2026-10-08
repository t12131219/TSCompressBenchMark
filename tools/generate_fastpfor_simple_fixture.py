"""Generate an explicitly synthetic uint28-in-uint32 primitive qualification corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "fixtures/datasets/simple_uint28_uts.npz"
    output.parent.mkdir(parents=True, exist_ok=True)
    values = np.empty(8193, dtype="<u4")
    values[:2048] = 0
    values[2048:4096] = 2**28 - 1
    values[4096:6144] = np.resize(
        np.array(
            [1, 255, 256, 65535, 65536, 16777215, 16777216, 2**28 - 1],
            dtype="<u4",
        ),
        2048,
    )
    values[6144:] = np.random.default_rng(20261007).integers(0, 2**28, 2049, dtype="<u4")
    np.savez(output, values=values)
    manifest = {
        "schema_version": "tscb.dataset-manifest.v2",
        "key": "simple_uint28_uts",
        "display_name": "Synthetic uint28 domain in uint32 storage UTS for Simple9/16",
        "source": {
            "uri": "generated:tools/generate_fastpfor_simple_fixture.py@20261007",
            "retrieved_at": "2026-10-07",
            "notes": (
                "Synthetic uint32 values, not observed timestamps, rescaled epochs "
                "or a real-world ranking corpus"
            ),
        },
        "license": {"spdx": "CC0-1.0", "status": "RUN_ALLOWED"},
        "file": {
            "path": str(output.relative_to(root)),
            "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "format": "npz",
        },
        "parser": {
            "name": "numpy.npz",
            "version": "runtime-recorded",
            "allow_pickle": False,
            "array_key": "values",
            "expected_keys": ["values"],
        },
        "logical": {
            "topology": "UTS",
            "axes": ["time"],
            "timestamp": {
                "origin": "NONE",
                "reason": "Synthetic value-only primitive corpus has no timestamp values",
            },
            "value": {
                "kind": "NPZ_ARRAY",
                "array": {
                    "dtype": "<u4",
                    "unit": "count",
                    "entity": "synthetic-sequence",
                    "feature": "value",
                    "required_layout": "ROW_MAJOR_CONTIG",
                },
                "representation": "NATIVE_ND_PRESERVED",
            },
            "validity": {"shape": "NONE", "missing_tokens": [], "nan_is_null": False},
            "canonical": {"format_version": "tscb-canonical-v1", "byte_order": "little"},
        },
        "expected": {"shape": [8193], "dtype": "<u4", "array_keys": ["values"]},
        "split": {
            "policy": "UNSPECIFIED",
            "learned_eligible": False,
            "reason": "Synthetic non-learned primitive fixture",
        },
    }
    path = root / "registry/datasets/simple_uint28_uts.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(manifest["file"])


if __name__ == "__main__":
    main()
