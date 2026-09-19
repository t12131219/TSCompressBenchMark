"""Generate the declared unsigned 8-bit UTS fixture without numeric conversion."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def generate(output: Path) -> None:
    values = np.empty(2048, dtype=np.uint8)
    values[:512] = 0
    values[512:1024] = np.arange(512, dtype=np.uint16).astype(np.uint8)
    values[1024:1536] = 192
    values[1536:] = np.random.default_rng(20260919).integers(0, 256, 512, dtype=np.uint8)
    np.savez(output, values=values)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Generate the synthetic Sprintz u8 UTS fixture")
    parser.add_argument("--output", type=Path, default=root / "datasets/sprintz_u8_uts.npz")
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()
