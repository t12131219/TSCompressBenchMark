#!/usr/bin/env python3
"""Regenerate §6.5 synthetic boundary assets into a fresh directory (stdlib only)."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import struct

GENERATOR = "corpus-boundaries/v1"
PREFIX = "datasets/fixtures/corpus-boundaries-v1"
SEED = 0xB91ACD31


def npy(dtype: str, shape: tuple[int, ...], payload: bytes) -> bytes:
    header = f"{{'descr': {dtype!r}, 'fortran_order': False, 'shape': {shape}, }}".encode("ascii")
    header += b" " * (-(len(header) + 11) % 64) + b"\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + payload


def packed(format_char, values):
    return b"".join(struct.pack("<" + format_char, x) for x in values)


def xorshift32(n: int):
    # Generated pseudorandom stress input, not an estimate of noise in real data.
    x = SEED
    for _ in range(n):
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        yield (x >> 16) - 32768


def generate(out: Path):
    if not out.is_dir() or any(out.iterdir()):
        raise ValueError("boundary fixture output must be an existing empty directory")
    files = {}

    def save(name, dtype, shape, char, values):
        words = packed(char, values)
        assert len(words) == math.prod(shape) * struct.calcsize("<" + char)
        data = npy(dtype, shape, words)
        path = out / (name + ".npy")
        with path.open("xb") as stream:
            stream.write(data)
        files[name] = {"path": f"{PREFIX}/{path.name}", "sha256": hashlib.sha256(data).hexdigest(),
                       "bytes": len(data), "dtype": dtype, "shape": list(shape)}

    integers = []
    for width, signed, unsigned in ((1, "b", "B"), (2, "h", "H"), (4, "i", "I"), (8, "q", "Q")):
        endian = "|" if width == 1 else "<"
        sign = 1 << (8 * width - 1)
        for letter, char, values in (("i", signed, (-sign, -sign + 1, -1, 0, 1, sign - 2, sign - 1)),
                                     ("u", unsigned, (0, 1, sign - 1, sign, sign + 1, 2 * sign - 2, 2 * sign - 1))):
            name = f"{letter}{8 * width}-extrema"
            save(name, f"{endian}{letter}{width}", (7,), char, values)
            integers.append(name)
    save("f32-special", "<f4", (9,), "I", (0, 0x80000000, 1, 0x7F800000, 0xFF800000,
         0x7FC00011, 0x7FC000EF, 0x7F7FFFFF, 0xFF7FFFFF))
    save("axis-a", "<i8", (64,), "q", range(-10, 54))
    save("axis-b", "<i8", (6,), "q", (-20, -18, -18, -16, 0, 2))
    save("trend", "<f8", (64,), "d", (x * 0.5 for x in range(64)))
    # Invalid cells deliberately have nonzero, finite storage words; neither a
    # zero nor a NaN in the values defines a validity bit.
    save("masked", "<f8", (6,), "Q", (0, 0x4000000000000000, 1 << 63, 0x4010000000000000,
                                     0x7FF8000000000042, 0x4018000000000000))
    save("validity", "|b1", (6,), "?", (True, False, True, False, True, True))
    save("matrix", "<f4", (3, 5), "f", (row * 16 + col + 0.5 for row in range(3) for col in range(5)))
    save("tensor", "<f8", (2, 3, 5), "d", (z * 128 + row * 16 + col + 0.25
         for z in range(2) for row in range(3) for col in range(5)))
    save("noise", "<f4", (256,), "f", (x / 32768 for x in xorshift32(256)))
    manifest = {"schema": "bmk.corpus-boundary-fixtures/1", "generator_id": GENERATOR,
                "noise": {"generator": "xorshift32_high16_centered_q15_v1", "seed": SEED, "file": "noise"},
                "files": files, "integer_extrema": integers,
                "different_axes": [{"axis": "axis-a", "values": "trend", "nominal_step_ns": 1},
                                   {"axis": "axis-b", "values": "masked", "nominal_step_ns": 2, "validity": "validity"}],
                "timestamp_semantics": {"unit": "ns", "epoch": "unix", "timezone": "UTC"},
                "spatial_fields": ["matrix", "tensor"], "float_special": "f32-special"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    cli.add_argument("--out", type=Path, required=True)
    args = cli.parse_args()
    try:
        generate(args.out)
    except (OSError, ValueError) as exc:
        cli.error(str(exc))
