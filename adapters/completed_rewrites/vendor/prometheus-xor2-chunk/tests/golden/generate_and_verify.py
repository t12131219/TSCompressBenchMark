#!/usr/bin/env python3
"""Generate or verify deterministic Prometheus XOR2 golden chunks."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


STALE_NAN = 0x7FF0000000000002
U64_MASK = (1 << 64) - 1


def sample(st: int, timestamp: int, value_bits: int) -> dict[str, object]:
    return {
        "start_timestamp": st,
        "timestamp": timestamp,
        "value_bits": f"0x{value_bits & U64_MASK:016x}",
    }


def vectors() -> list[dict[str, object]]:
    forced_st = [
        sample(0, 1_000 + index * 10, 0x3FF0000000000000)
        for index in range(129)
    ]
    return [
        {"name": "empty", "samples": []},
        {
            "name": "single_no_st",
            "samples": [sample(0, -1, 0x8000000000000000)],
        },
        {
            "name": "first_st_known",
            "samples": [sample(900, 1_000, 0x3FF0000000000000)],
        },
        {
            "name": "unchanged_joint_zero",
            "samples": [
                sample(0, 1_000, 0x3FF0000000000000),
                sample(0, 1_010, 0x3FF0000000000000),
                sample(0, 1_020, 0x3FF0000000000000),
                sample(0, 1_030, 0x3FF0000000000000),
            ],
        },
        {
            "name": "dod_13_bit_boundaries",
            "samples": [
                sample(0, 0, 0),
                sample(0, 10_000, 0),
                sample(0, 24_095, 0),  # dod = +4095.
                sample(0, 34_094, 0),  # dod = -4096.
            ],
        },
        {
            "name": "dod_20_bit_boundaries",
            "samples": [
                sample(0, 0, 0),
                sample(0, 1_000_000, 0),
                sample(0, 2_524_287, 0),  # dod = +524287.
                sample(0, 3_524_286, 0),  # dod = -524288.
            ],
        },
        {
            "name": "dod_64_bit_escape",
            "samples": [
                sample(0, 0, 0),
                sample(0, 1, 0),
                sample(0, 524_290, 0),  # dod = +524288.
                sample(0, 524_290 + 524_289 + (1 << 40), 0),
            ],
        },
        {
            "name": "value_windows_new_and_reused",
            "samples": [
                sample(0, 1_000, 0x3FF0000000000000),
                sample(0, 1_010, 0x3FF0000000000001),
                sample(0, 1_020, 0x3FF0000000000003),
                sample(0, 1_031, 0x3FF0000000000002),
                sample(0, 1_042, 0x4000000000000000),
            ],
        },
        {
            "name": "exact_stale_marker_preserves_baseline",
            "samples": [
                sample(0, 1_000, 0x3FF0000000000000),
                sample(0, 1_010, 0x3FF0000000000001),
                sample(0, 1_020, STALE_NAN),
                sample(0, 1_030, 0x3FF0000000000001),
                sample(0, 1_041, STALE_NAN),
                sample(0, 1_052, 0x3FF0000000000003),
            ],
        },
        {
            "name": "st_starts_at_sample_one",
            "samples": [
                sample(0, 1_000, 0x3FF0000000000000),
                sample(950, 1_010, 0x3FF0000000000000),
                sample(960, 1_020, 0x3FF0000000000000),
                sample(969, 1_030, 0x3FF0000000000000),
            ],
        },
        {
            "name": "st_later_change_and_varbit_buckets",
            "samples": [
                sample(0, 10_000, 0),
                sample(0, 10_010, 0),
                sample(0, 10_020, 0),
                sample(9_900, 10_030, 0),
                sample(9_911, 10_040, 0),
                sample(9_950, 10_050, 0),
                sample(10_500, 10_060, 0),
                sample(-200_000, 10_070, 0),
                sample(1 << 40, 10_080, 0),
            ],
        },
        {
            "name": "timestamp_modulo_wrap",
            "samples": [
                sample(0, (1 << 63) - 3, 1),
                sample(0, -(1 << 63) + 3, 2),
                sample(0, -(1 << 63) + 8, 3),
            ],
        },
        {
            "name": "index_127_forces_st_payload",
            "samples": forced_st,
        },
    ]


def oracle_input(samples: list[dict[str, object]]) -> str:
    return "".join(
        f"{entry['start_timestamp']} {entry['timestamp']} "
        f"{int(str(entry['value_bits']), 16)}\n"
        for entry in samples
    )


def run_oracle(oracle: Path, mode: str, data: str) -> str:
    result = subprocess.run(
        [str(oracle), mode],
        input=data,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"oracle {mode} failed with {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def decoded_records(output: str) -> list[tuple[int, int, int]]:
    if not output:
        return []
    records = []
    for line in output.splitlines():
        st_text, timestamp_text, bits_text = line.split("\t")
        records.append((int(st_text), int(timestamp_text), int(bits_text, 16)))
    return records


def expected_records(samples: list[dict[str, object]]) -> list[tuple[int, int, int]]:
    return [
        (
            int(entry["start_timestamp"]),
            int(entry["timestamp"]),
            int(str(entry["value_bits"]), 16),
        )
        for entry in samples
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", required=True, type=Path)
    parser.add_argument(
        "--vectors",
        type=Path,
        default=Path(__file__).with_name("xor2_chunk_vectors.json"),
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    generated = vectors()
    for vector in generated:
        samples = vector["samples"]
        encoded = run_oracle(args.oracle, "encode", oracle_input(samples))
        decoded = decoded_records(run_oracle(args.oracle, "decode", encoded + "\n"))
        if decoded != expected_records(samples):
            raise RuntimeError(f"oracle round-trip mismatch for {vector['name']}")
        vector["expected_hex"] = encoded

    if args.write:
        args.vectors.write_text(json.dumps(generated, indent=2) + "\n", encoding="utf-8")
    else:
        frozen = json.loads(args.vectors.read_text(encoding="utf-8"))
        if frozen != generated:
            raise RuntimeError("frozen XOR2 vectors differ from oracle output")

    print(f"PASS: {len(generated)} XOR2 golden vectors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
