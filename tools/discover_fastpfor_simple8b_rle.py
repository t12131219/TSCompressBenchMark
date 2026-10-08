"""Retain narrow original-API failure discovery; this grants no integration qualification."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "Compression_Source_Code/Source_Code/_repos/fast-pack_FastPFOR"
PIN = "2457e1ed1af35bbf7f4c509c863fa9797e637cb3"
OUT = ROOT / "build/source-audits/fastpfor-simple8b-rle-discovery"
PROBE = r"""
#include "simple8b_rle.h"
#include <cstdio>
#include <cstring>
#include <memory>

template<bool Marked>
int probe(bool exact) {
    FastPForLib::Simple8b_RLE<Marked> codec;
    const uint32_t input[] = {0};
    alignas(16) uint32_t encoded[64];
    std::memset(encoded, 0xa5, sizeof(encoded));
    size_t words = 64;
    codec.encodeArray(input, 1, encoded, words);
    std::unique_ptr<uint32_t[]> decoded(new uint32_t[exact ? 1 : 16]);
    for (unsigned i = 0; i < (exact ? 1U : 16U); ++i) decoded[i] = 0xa5a5a5a5U;
    size_t count = 1;
    const auto* consumed = codec.decodeArray(encoded, words, decoded.get(), count);
    unsigned changed = 0;
    if (!exact) for (unsigned i = 1; i < 16; ++i) changed += decoded[i] != 0xa5a5a5a5U;
    const auto used = static_cast<size_t>(consumed - encoded);
    std::printf("marked=%d returned_words=%zu consumed_words=%zu decoded_count=%zu "
                "value_match=%d tail_words_changed=%u\n", Marked, words, used, count,
                decoded[0] == input[0], changed);
    return (used == words && changed == 0 && decoded[0] == input[0]) ? 0 : 2;
}
int main(int argc, char** argv) {
    const bool marked = argc > 1 && std::strcmp(argv[1], "marked") == 0;
    const bool exact = argc > 2 && std::strcmp(argv[2], "exact") == 0;
    return marked ? probe<true>(exact) : probe<false>(exact);
}
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preserve prior original-API discovery evidence")
    OUT.mkdir(parents=True)
    path = OUT / "probe.cpp"
    path.write_text(PROBE)
    report = {
        "status": "RUNNING",
        "qualification_scope": "ORIGINAL_API_N1_ZERO_DISCOVERY_ONLY",
        "logical_entry": {"audit_index": 148, "name": "FastPFOR Simple8b_RLE"},
        "repository": "https://github.com/fast-pack/FastPFOR",
        "pin": PIN,
        "driver_sha256": sha(Path(__file__)),
        "probe_sha256": sha(path),
        "commands": [],
        "builds": [],
        "source_files": [],
        "source_safety": "NOT_QUALIFIED",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
    }

    def save() -> None:
        (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(command: list[str], name: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="print_stacktrace=1"),
        )
        entry = {
            "name": name,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        report["commands"].append(entry)
        (OUT / (name + ".json")).write_text(json.dumps(entry, indent=2) + "\n")
        save()
        return result

    save()
    try:
        if run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], "source-pin").stdout.strip() != PIN:
            raise RuntimeError("source pin differs")
        if run(["git", "-C", str(SOURCE), "status", "--porcelain"], "source-clean").stdout.strip():
            raise RuntimeError("original source repository dirty")
        for name in (
            "headers/simple8b_rle.h",
            "headers/common.h",
            "headers/codecs.h",
            "headers/util.h",
            "src/codecfactory.cpp",
            "src/unit.cpp",
            "src/inmemorybenchmark.cpp",
            "LICENSE",
        ):
            source = SOURCE / name
            copy = OUT / "original-source" / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(source.read_bytes())
            report["source_files"].append({"upstream_path": name, "sha256": sha(source)})
        for profile, flags in (
            ("release", ["-O2", "-DNDEBUG"]),
            ("debug", ["-O0", "-g"]),
            (
                "sanitizer",
                [
                    "-O1",
                    "-g",
                    "-fsanitize=address,undefined",
                    "-fno-omit-frame-pointer",
                    "-fno-sanitize-recover=all",
                ],
            ),
        ):
            binary = OUT / profile
            command = [
                "g++",
                "-std=c++17",
                "-march=x86-64",
                "-fno-tree-vectorize",
                *flags,
                "-I" + str(SOURCE / "headers"),
                str(path),
                "-o",
                str(binary),
            ]
            if run(command, "build-" + profile).returncode:
                raise RuntimeError("original probe compilation failed")
            report["builds"].append({"profile": profile, "binary_sha256": sha(binary)})
            for marked in ("unmarked", "marked"):
                run([str(binary), marked, "padded"], profile + "-" + marked + "-padded")
            if profile == "sanitizer":
                run([str(binary), "unmarked", "exact"], "sanitizer-unmarked-exact")
        observations = {entry["name"]: entry for entry in report["commands"]}
        release = observations["release-marked-padded"]
        if "returned_words=2 consumed_words=3" not in release["stdout"]:
            raise RuntimeError("marked return-length discrepancy not observed")
        if "tail_words_changed=7" not in observations["release-unmarked-padded"]["stdout"]:
            raise RuntimeError("unrolled tail overwrite not observed")
        if "heap-buffer-overflow" not in observations["sanitizer-unmarked-exact"]["stderr"]:
            raise RuntimeError("exact-output ASan failure not observed")
        report.update(
            status="ORIGINAL_API_FAILURES_RETAINED_NOT_QUALIFIED",
            marked_return_length_omits_header=True,
            zero_singleton_tail_words_overwritten=7,
            exact_output_asan="HEAP_BUFFER_OVERFLOW",
            leak_sanitizer="NOT_QUALIFIED_DETECT_LEAKS_ZERO",
        )
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "status",
                        "marked_return_length_omits_header",
                        "zero_singleton_tail_words_overwritten",
                        "exact_output_asan",
                    )
                }
            )
        )
    except Exception as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
