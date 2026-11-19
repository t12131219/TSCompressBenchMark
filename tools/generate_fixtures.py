#!/usr/bin/env python3
"""Generate deterministic internal fixture assets (no external data or Python packages)."""
from pathlib import Path
import json
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.assets import digest  # noqa: E402


def npy(descr, words):
    header = f"{{'descr': {descr!r}, 'fortran_order': False, 'shape': ({len(words)},), }}"
    header = header.encode("ascii")
    header += b" " * (-(len(header) + 11) % 64) + b"\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + b"".join(words)


def main():
    t = [-1003, 0, 7, 107, 1007, 1011, 1013, 2019, 2020]
    v = [0.0, -0.0, 1.5, 1.5, -2.0, 4.25, 4.5, 4.75, 8.0]
    joined = list(zip(t, v))
    payloads = {
        "t-v.csv": ("T,V\n" + "".join(f"{a},{b}\n" for a, b in joined)).encode("ascii"),
        "t-v.txt": ("T\tV\n" + "".join(f"{a}\t{b}\n" for a, b in joined)).encode("ascii"),
        "t.npy": npy("<i8", [struct.pack("<q", a) for a in t]),
        "v.npy": npy("<f8", [struct.pack("<d", b) for b in v]),
        "f64-bits.npy": npy("<f8", [struct.pack("<Q", b) for b in (
            0, 1 << 63, 1, 0x7FF0000000000000, 0xFFF0000000000000, 0x7FF8000000000011,
            0x7FF80000000000EF, 0x7FEFFFFFFFFFFFFF, 0xFFEFFFFFFFFFFFFF)]),
        "i64-edges.npy": npy("<i8", [struct.pack("<q", b) for b in (
            -(1 << 63), -(1 << 53) - 1, -1001, -1, 0, 1, (1 << 53) + 1, (1 << 63) - 1)]),
    }
    files = {}
    for name, data in payloads.items():
        path = ROOT / "datasets/fixtures" / name
        path.write_bytes(data)
        files[name] = {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "bytes": len(data)}
    manifest = {"schema": "bmk.fixtures/1", "generator_id": "m0-fixtures/v1",
                "provenance": "deterministic synthetic, generated in this project",
                "files": files,
                "objects": {
                    "tiny-tv": {"rows": len(joined), "columns": [
                        {"name": "T", "role": "timestamp", "dtype": "i64", "unit": "ns",
                         "epoch": "unix", "timezone": "UTC"},
                        {"name": "V", "role": "value", "dtype": "f64"}],
                        "formats": {"csv": ["t-v.csv"], "npy": ["t.npy", "v.npy"], "txt": ["t-v.txt"]}},
                    "f64-boundaries": {"rows": 9, "dtype": "f64", "formats": {"npy": ["f64-bits.npy"]}},
                    "i64-boundaries": {"rows": 8, "dtype": "i64", "formats": {"npy": ["i64-edges.npy"]}},
                }}
    (ROOT / "datasets/fixtures/manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
