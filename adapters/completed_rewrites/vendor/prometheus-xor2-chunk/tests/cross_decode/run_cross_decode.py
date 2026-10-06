#!/usr/bin/env python3
# Copyright 2026 TSDataCompressBenchMark contributors.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import random
import subprocess
from pathlib import Path


STALE_NAN = 0x7FF0000000000002
MASK = (1 << 64) - 1


def signed(value: int) -> int:
    value &= MASK
    return value - (1 << 64) if value >= (1 << 63) else value


def samples_text(samples: list[tuple[int, int, int]]) -> str:
    return "".join(f"{st} {timestamp} {bits}\n" for st, timestamp, bits in samples)


def parse_samples(output: str) -> list[tuple[int, int, int]]:
    result = []
    for line in output.splitlines():
        if line.strip():
            st, timestamp, bits = line.split()
            result.append((int(st), int(timestamp), int(bits, 16)))
    return result


def run(executable: Path, mode: str, stdin: str, runner: Path | None = None) -> str:
    command = [str(executable), mode]
    if runner is not None:
        command.insert(0, str(runner))
    completed = subprocess.run(command, input=stdin, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{executable.name} {mode} failed ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def property_vectors() -> list[list[tuple[int, int, int]]]:
    generator = random.Random(0x20260928)
    vectors = []
    for trial in range(64):
        samples = []
        timestamp = generator.getrandbits(64)
        delta = generator.getrandbits(20)
        value = generator.getrandbits(64)
        st = 0
        for index in range(generator.randrange(160)):
            if index:
                delta = (delta + generator.randrange(-700_000, 700_001)) & MASK
                timestamp = (timestamp + delta) & MASK
                if generator.randrange(9) == 0:
                    value = STALE_NAN
                elif generator.randrange(4) != 0:
                    value ^= generator.getrandbits(18)
                else:
                    value = generator.getrandbits(64)
                if trial % 3 == 0 and index >= trial % 11:
                    st = signed((timestamp - generator.randrange(-200_000, 200_001)) & MASK)
            samples.append((st, signed(timestamp), value))
        vectors.append(samples)
    return vectors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpp-cli", type=Path, required=True)
    parser.add_argument("--go-oracle", type=Path, required=True)
    parser.add_argument("--cpp-runner", type=Path)
    parser.add_argument("--peer-cpp-cli", type=Path)
    parser.add_argument("--peer-cpp-runner", type=Path)
    args = parser.parse_args()

    golden_path = Path(__file__).resolve().parents[1] / "golden/xor2_chunk_vectors.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    cases = [
        [
            (
                int(sample["start_timestamp"]),
                int(sample["timestamp"]),
                int(sample["value_bits"], 16),
            )
            for sample in vector["samples"]
        ]
        for vector in golden
    ]
    expected_hex = [vector["expected_hex"] for vector in golden]

    for kind, vectors in (("golden", cases), ("property", property_vectors())):
        for index, samples in enumerate(vectors):
            source = samples_text(samples)
            cpp_encoded = run(args.cpp_cli, "encode", source, args.cpp_runner)
            go_encoded = run(args.go_oracle, "encode", source)
            if cpp_encoded != go_encoded:
                raise AssertionError(f"{kind} vector {index}: encoded bytes differ")
            if kind == "golden" and cpp_encoded != expected_hex[index]:
                raise AssertionError(f"golden vector {index}: frozen bytes differ")
            if parse_samples(run(args.go_oracle, "decode", cpp_encoded + "\n")) != samples:
                raise AssertionError(f"{kind} vector {index}: Go decode differs")
            if parse_samples(
                run(args.cpp_cli, "decode", go_encoded + "\n", args.cpp_runner)
            ) != samples:
                raise AssertionError(f"{kind} vector {index}: C++ decode differs")
            if args.peer_cpp_cli is not None:
                peer_encoded = run(
                    args.peer_cpp_cli, "encode", source, args.peer_cpp_runner
                )
                if peer_encoded != cpp_encoded:
                    raise AssertionError(f"{kind} vector {index}: ISA bytes differ")
                if parse_samples(
                    run(args.peer_cpp_cli, "decode", cpp_encoded + "\n", args.peer_cpp_runner)
                ) != samples:
                    raise AssertionError(f"{kind} vector {index}: peer decode differs")
                if parse_samples(
                    run(args.cpp_cli, "decode", peer_encoded + "\n", args.cpp_runner)
                ) != samples:
                    raise AssertionError(f"{kind} vector {index}: primary decode differs")

    suffix = " with bidirectional C++ ISA peers" if args.peer_cpp_cli else ""
    print(f"PASS: {len(golden)} golden and 64 property vectors{suffix}")


if __name__ == "__main__":
    main()
