"""Compare two pinned RLE encoders; this does not qualify source safety or integration."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOS = ROOT.parent / "Compression_Source_Code/Source_Code/_repos"
OUT = ROOT / "build/source-audits/fastpfor-simple8b-rle-provenance-2"
SOURCES = (
    ("workbook", "fast-pack_FastPFOR", "2457e1ed1af35bbf7f4c509c863fa9797e637cb3", "headers"),
    ("benchmark-copy", "sprintz-lzbench", "580c4f085381f31b1ad669525ed04e63cbc385f3", "fastpfor"),
)
PROBE = r"""
#include "simple8b_rle.h"
#include <cstdio>
#include <vector>
int main() {
    const uint32_t values[] = {0, 1U << 20, (1U << 21) - 1};
    const uint32_t counts[] = {3, 30, 60};
    for (uint32_t value : values) for (uint32_t count : counts) {
        const std::vector<uint32_t> input(count, value);
        std::vector<uint64_t> output(count, 0);
        const auto words = FastPForLib::Simple8b_Codec::Compress(
            input.data(), 0, count, output.data(), 0);
        std::printf("{\"value\":%u,\"count\":%u,\"words\":[", value, count);
        for (int i = 0; i < words; ++i)
            std::printf("%s\"%016llx\"", i ? "," : "",
                        static_cast<unsigned long long>(output[i]));
        std::puts("]}");
    }
}
"""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preserve previous provenance evidence")
    OUT.mkdir(parents=True)
    (OUT / "driver.py").write_bytes(Path(__file__).read_bytes())
    report = {
        "status": "RUNNING",
        "scope": "NINE_CONSTANT_INPUT_ENCODER_PARITY_PROBES_ONLY",
        "audit_index": 148,
        "driver_sha256": sha(Path(__file__).read_bytes()),
        "source_safety": "NOT_QUALIFIED",
        "upstream_self_tests": "NOT_EXECUTED_BY_THIS_REVIEW",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
        "commands": [],
        "sources": [],
    }

    def save() -> None:
        (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(command: list[str], name: str) -> bytes:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=60)
        entry = {
            "name": name,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout.decode(),
            "stderr": result.stderr.decode(),
        }
        report["commands"].append(entry)
        (OUT / (name + ".json")).write_text(json.dumps(entry, indent=2) + "\n")
        save()
        result.check_returncode()
        return result.stdout

    def pinned_file(repo: Path, pin: str, name: str, target: Path) -> dict:
        data = (repo / name).read_bytes()
        tracked = run(
            ["git", "--no-optional-locks", "-C", str(repo), "show", pin + ":" + name],
            target.relative_to(OUT).as_posix().replace("/", "__") + "-git-bytes",
        )
        if tracked != data:
            raise RuntimeError("working file differs from pinned bytes: " + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"upstream_path": name, "snapshot": str(target.relative_to(ROOT)),
                "sha256": sha(data), "bytes": len(data)}

    try:
        probe = OUT / "probe.cpp"
        probe.write_text(PROBE)
        report["probe_sha256"] = sha(probe.read_bytes())
        for label, dirname, pin, prefix in SOURCES:
            repo = REPOS / dirname
            git = ["git", "--no-optional-locks", "-C", str(repo)]
            if run(git + ["rev-parse", "HEAD"], label + "-pin").decode().strip() != pin:
                raise RuntimeError("repository pin changed")
            if run(git + ["status", "--porcelain"], label + "-clean"):
                raise RuntimeError("repository is dirty")
            run(git + ["submodule", "status"], label + "-submodules")
            source = {"label": label, "repository_path": str(repo), "pin": pin, "files": []}
            report["sources"].append(source)
            for filename in ("common.h", "codecs.h", "util.h", "bitpacking.h",
                             "bitpackinghelpers.h", "simple8b_rle.h"):
                source["files"].append(pinned_file(
                    repo, pin, prefix + "/" + filename, OUT / label / "include" / filename))
            references = (
                ("LICENSE", "src/codecfactory.cpp", "src/unit.cpp", "src/inmemorybenchmark.cpp",
                 "unittest/test_simple8b.cpp", "CMakeLists.txt")
                if label == "workbook" else
                ("fastpfor/codecfactory.h", "_lzbench/compressors.cpp",
                 "_lzbench/compressors.h", "_lzbench/lzbench.h")
            )
            for name in references:
                source["files"].append(
                    pinned_file(repo, pin, name, OUT / label / "reference" / name)
                )
            binary = OUT / label / "encoder-probe"
            run(["taskset", "-c", "2", "g++", "-std=c++17", "-O2", "-DNDEBUG",
                 "-march=x86-64", "-fno-tree-vectorize", "-MD", "-MF",
                 str(binary) + ".d", "-I" + str(OUT / label / "include"),
                 str(probe), "-o", str(binary)], label + "-compile")
            source["binary_sha256"] = sha(binary.read_bytes())
            source["compiler_dependencies_sha256"] = sha(Path(str(binary) + ".d").read_bytes())
            output = run(["taskset", "-c", "2", str(binary)], label + "-execute")
            source["observations"] = [json.loads(line) for line in output.decode().splitlines()]
        workbook, reference = report["sources"]
        pairs = list(zip(workbook["observations"], reference["observations"], strict=True))
        if len(pairs) != 9 or any(
            (a["value"], a["count"]) != (b["value"], b["count"]) for a, b in pairs
        ):
            raise RuntimeError("probe input universe mismatch")
        differences = [{"value": a["value"], "count": a["count"],
                        "workbook_words": a["words"], "benchmark_copy_words": b["words"]}
                       for a, b in pairs if a["words"] != b["words"]]
        sparse = next(d for d in differences if d["value"] == 1 << 20 and d["count"] == 3)
        if (
            sparse["workbook_words"] != ["f000000300100000"]
            or len(sparse["benchmark_copy_words"]) != 2
        ):
            raise RuntimeError("expected sparse-input selector difference not observed")
        reference_dir = OUT / "benchmark-copy/reference"
        factory = (reference_dir / "fastpfor/codecfactory.h").read_text()
        if not re.search(r'map\["simple8b_rle"\].*Simple8b_RLE<true>', factory):
            raise RuntimeError("reference factory RLE registration changed")
        for name in ("compressors.cpp", "compressors.h", "lzbench.h"):
            text = (reference_dir / "_lzbench" / name).read_text()
            if not re.search(r'\bsimple8b\b', text) or re.search(r'\bsimple8b_rle\b', text):
                raise RuntimeError("reference standalone benchmark mapping changed: " + name)
        diff = "".join(difflib.unified_diff(
            (OUT / "benchmark-copy/include/simple8b_rle.h").read_text().splitlines(True),
            (OUT / "workbook/include/simple8b_rle.h").read_text().splitlines(True),
            fromfile="sprintz-lzbench/fastpfor/simple8b_rle.h",
            tofile="FastPFOR/headers/simple8b_rle.h"))
        (OUT / "source.diff").write_text(diff)
        report.update(
            status="SOURCE_VARIANT_DIFFERENCES_RETAINED_NOT_QUALIFIED",
            wire_differences=differences,
            source_diff_sha256=sha(diff.encode()),
            earlier_failed_attempt="build/source-audits/fastpfor-simple8b-rle-provenance/report.json",
            benchmark_copy_has_factory_entry=True,
            benchmark_copy_has_lzbench_rle_entry=False,
            selection="WORKBOOK_FASTPFOR_PIN_RETAINED_BENCHMARK_COPY_REFERENCE_ONLY",
        )
        print(json.dumps({"status": report["status"], "cases_per_encoder": 9,
                          "wire_difference_count": len(differences), "sparse_example": sparse}))
    except Exception as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
