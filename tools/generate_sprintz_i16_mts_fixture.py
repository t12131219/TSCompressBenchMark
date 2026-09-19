"""Generate the declared signed 16-bit synchronous MTS Sprintz fixture."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def generate(output: Path) -> None:
    rows = 4096
    index = np.arange(rows, dtype=np.int32)
    values = np.empty((rows, 4), dtype="<i2")
    values[:, 0] = ((index % 1024) - 512).astype(np.int16)
    values[:, 1] = np.where((index // 256) % 2, 1200, -1200).astype(np.int16)
    values[:, 2] = (3000 * np.sin(index / 32.0)).astype(np.int16)
    values[:, 3] = np.random.default_rng(20260919).integers(
        -32768, 32768, rows, dtype=np.int16
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(output, values=values)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Generate the synthetic Sprintz int16 synchronous MTS fixture"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "datasets/sprintz_i16_mts.npz",
    )
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()
