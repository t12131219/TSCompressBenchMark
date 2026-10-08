"""Audit original evidence, the exact RLE patch, all source matrices and complete unit reuse."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shlex
from pathlib import Path

from audit_fastpfor_simple_upstream import audit as audit_upstream
from freeze_fastpfor_simple_source import pinned, tracked

ROOT = Path(__file__).resolve().parents[1]
PIN = "2457e1ed1af35bbf7f4c509c863fa9797e637cb3"
COMPONENT = ROOT / "adapters/fastpfor_simple8b_rle"
DEFAULT_REPORT = ROOT / "build/source-audits/fastpfor-simple8b-rle-source-20261007-1/report.json"
PROFILE_FLAGS = {
    "release": ["-O3", "-DNDEBUG"],
    "debug": ["-O0", "-g", "-UNDEBUG"],
    "sanitizer": [
        "-O1",
        "-g",
        "-UNDEBUG",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
        "-fno-pie",
        "-no-pie",
    ],
}
UPSTREAM_FLAGS = ["-O3", "-g", "-UNDEBUG", "-march=x86-64", "-msse4.2", "-fno-tree-vectorize"]


def require(valid: bool, message: str) -> None:
    if not valid:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_identity(item: dict, expected: Path | None = None) -> Path:
    path = Path(item["path"])
    if not path.is_absolute():
        path = ROOT / path
    require(expected is None or path == expected, "source evidence artifact substituted")
    require(path.is_file() and sha(path) == item["sha256"], "source evidence drift: " + str(path))
    return path


def check_closure(build: dict) -> set[Path]:
    dep = check_identity(build["dependency_file"])
    paths = {
        Path(p).resolve()
        for p in shlex.split(dep.read_text().replace("\\\n", " ").split(":", 1)[1])
    }
    actual = build["compiler_closure"]
    require(len(actual) == len(paths), "source compiler dependency count differs")
    require({check_identity(item) for item in actual} == paths, "source compiler closure differs")
    return paths


def audit(report_path: Path = DEFAULT_REPORT) -> dict:
    report = json.loads(report_path.read_text())
    require(
        report["status"] == "PATCHED_RLE_SOURCE_MATRIX_AND_COMPLETE_RELEASE_UPSTREAM_PASS",
        "complete source execution absent",
    )
    require(
        report["scope"] == "PATCHED_RLE_VALID_UINT32_OBJECT_SOURCE_APIS_ONLY"
        and report["full_logical_entry_qualified"] is False
        and report["source_capacity_and_malformed_frames"] == "NOT_QUALIFIED_REQUIRE_BOUNDED_ABI",
        "source qualification scope expanded",
    )
    require(
        all(
            report[key] == "PENDING"
            for key in (
                "bounded_abi",
                "python_sdk",
                "benchmark_registration",
                "benchmark_five_layers",
            )
        ),
        "source matrix cannot qualify ABI/SDK/Benchmark",
    )
    require(
        report["leak_sanitizer"] == "NOT_QUALIFIED_DETECT_LEAKS_ZERO",
        "LeakSanitizer claim expanded",
    )
    require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,63}", report["run_id"]), "invalid run ID")
    out = ROOT / "build/source-audits" / ("fastpfor-simple8b-rle-source-" + report["run_id"])
    generated = out / "generated"
    check_identity(report["driver"], ROOT / "tools/qualify_fastpfor_simple8b_rle_source.py")
    require(sha(out / "driver.py") == report["driver"]["sha256"], "executed driver snapshot drift")
    dependency_names = {
        "freeze_fastpfor_simple8b_rle_source.py",
        "prepare_fastpfor_simple8b_rle_patch.py",
        "freeze_fastpfor_simple_source.py",
        "audit_fastpfor_simple_source.py",
        "audit_fastpfor_simple_upstream.py",
    }
    require(
        len(report["driver_dependencies"]) == len(dependency_names)
        and {Path(i["path"]).name for i in report["driver_dependencies"]} == dependency_names,
        "source driver dependency universe differs",
    )
    for item in report["driver_dependencies"]:
        check_identity(item, ROOT / "tools" / Path(item["path"]).name)
    matrix_source = COMPONENT / "tests/source_matrix.cpp"
    check_identity(report["matrix_source"], matrix_source)
    lock_path = check_identity(report["source_lock"], COMPONENT / "SOURCE_LOCK.json")
    lock = json.loads(lock_path.read_text())
    require(
        lock["repository"] == "https://github.com/fast-pack/FastPFOR"
        and lock["commit"] == PIN
        and lock["dirty"] is False
        and lock["submodules"] == []
        and lock["copy_policy"] == "TRACKED_PINNED_BYTES_EQUAL_NO_PATCH"
        and lock["license"]["spdx"] == "Apache-2.0"
        and lock["license"]["status"] == "RUN_ALLOWED"
        and lock["public_apis"] == ["Simple8b_RLE<false>", "Simple8b_RLE<true>"]
        and lock["logical_entries"] == [{"audit_index": 148, "name": "FastPFOR Simple8b_RLE"}]
        and lock["full_logical_entry_qualified"] is False,
        "workbook source identity or license differs",
    )
    require(
        sha(ROOT / "tools/freeze_fastpfor_simple8b_rle_source.py") == lock["freezer_sha256"],
        "source freezer drift",
    )
    repo = ROOT.parent / "Compression_Source_Code/Source_Code/_repos/fast-pack_FastPFOR"
    require(not pinned(repo, PIN), "unexpected original submodules")
    algorithm_files = {
        "LICENSE",
        "AUTHORS",
        "README.md",
        "headers/common.h",
        "headers/codecs.h",
        "headers/util.h",
        "headers/bitpacking.h",
        "headers/bitpackinghelpers.h",
        "headers/simple8b_rle.h",
    }
    reference_files = {
        "src/codecfactory.cpp",
        "src/unit.cpp",
        "src/inmemorybenchmark.cpp",
        "headers/cpubenchmark.h",
        "headers/deltautil.h",
        "unittest/test_simple8b.cpp",
        "CMakeLists.txt",
    }
    expected_files = {(name, "ORIGINAL_ALGORITHM") for name in algorithm_files} | {
        (name, "BENCHMARK_AND_TEST_REFERENCE") for name in reference_files
    }
    require(
        len(lock["files"]) == 16
        and {(item["upstream_path"], item["role"]) for item in lock["files"]} == expected_files,
        "source inventory incomplete",
    )
    for item in lock["files"]:
        directory = "vendor" if item["role"] == "ORIGINAL_ALGORITHM" else "references"
        local = check_identity(item, COMPONENT / directory / "fastpfor" / item["upstream_path"])
        require(
            local.read_bytes() == tracked(repo, PIN, item["upstream_path"])
            and local.stat().st_size == item["bytes"],
            "vendor differs from pinned Git bytes",
        )
    provenance_path = check_identity(
        lock["benchmark_comparison"],
        ROOT / "build/source-audits/fastpfor-simple8b-rle-provenance-2/report.json",
    )
    provenance = json.loads(provenance_path.read_text())
    require(
        provenance["status"] == "SOURCE_VARIANT_DIFFERENCES_RETAINED_NOT_QUALIFIED"
        and provenance["benchmark_copy_has_factory_entry"] is True
        and provenance["benchmark_copy_has_lzbench_rle_entry"] is False
        and provenance["source_safety"] == "NOT_QUALIFIED"
        and provenance["full_logical_entry_qualified"] is False,
        "benchmark source comparison missing or expanded",
    )
    require(
        sha(provenance_path.parent / "driver.py") == provenance["driver_sha256"]
        and sha(provenance_path.parent / "probe.cpp") == provenance["probe_sha256"],
        "executed provenance probe drift",
    )
    for item in provenance["commands"]:
        require(
            item["returncode"] == 0
            and json.loads((provenance_path.parent / (item["name"] + ".json")).read_text()) == item,
            "provenance raw command differs",
        )
    require(
        [item["label"] for item in provenance["sources"]] == ["workbook", "benchmark-copy"],
        "benchmark/source variant universe differs",
    )
    for item, dirname, commit in zip(
        provenance["sources"],
        ("fast-pack_FastPFOR", "sprintz-lzbench"),
        (PIN, "580c4f085381f31b1ad669525ed04e63cbc385f3"),
        strict=True,
    ):
        source_repo = repo.parent / dirname
        require(item["pin"] == commit, "benchmark reference pin differs")
        pinned(source_repo, commit)
        for file in item["files"]:
            snapshot = ROOT / file["snapshot"]
            require(
                sha(snapshot) == file["sha256"]
                and snapshot.read_bytes() == tracked(source_repo, commit, file["upstream_path"]),
                "benchmark reference snapshot differs",
            )
        base = provenance_path.parent / item["label"]
        require(
            sha(base / "encoder-probe") == item["binary_sha256"]
            and sha(base / "encoder-probe.d") == item["compiler_dependencies_sha256"],
            "benchmark parity binary/dependency drift",
        )
        execution = next(
            c for c in provenance["commands"] if c["name"] == item["label"] + "-execute"
        )
        require(
            item["observations"] == [json.loads(line) for line in execution["stdout"].splitlines()]
            and len(item["observations"]) == 9,
            "actual encoder parity outputs differ",
        )
    require(
        provenance["wire_differences"]
        == [
            {
                "value": 1048576,
                "count": 3,
                "workbook_words": ["f000000300100000"],
                "benchmark_copy_words": ["d004000000100000", "d000000000100000"],
            }
        ],
        "source variant decision lost sparse-value wire difference",
    )
    patch_path = check_identity(report["patch_lock"], COMPONENT / "PATCH_LOCK.json")
    patch_lock = json.loads(patch_path.read_text())
    require(
        patch_lock["source_lock_sha256"] == sha(lock_path)
        and patch_lock["selector_table_and_rle_selection_changed"] is False
        and patch_lock["original_source_modified"] is False
        and patch_lock["full_logical_entry_qualified"] is False
        and patch_lock["bounded_abi"] == patch_lock["benchmark_five_layers"] == "PENDING",
        "patch changed scope or source identity",
    )
    require(
        sha(ROOT / "tools/prepare_fastpfor_simple8b_rle_patch.py")
        == patch_lock["generator_sha256"],
        "patch generator drift",
    )
    source = (COMPONENT / "vendor/fastpfor/headers/simple8b_rle.h").read_text()
    expected = source
    for before, after in (
        (
            "      output[outPos++] = outVal;",
            "      memcpy(reinterpret_cast<unsigned char *>(output) +\n"
            "                 size_t(outPos++) * sizeof(uint64_t), &outVal, sizeof(outVal));",
        ),
        (
            "      uint64_t val = input[inPos++];",
            "      uint64_t val;\n"
            "      memcpy(&val, reinterpret_cast<const unsigned char *>(input) +\n"
            "                       size_t(inPos++) * sizeof(uint64_t), sizeof(val));",
        ),
        ("        for (; i < intNum; i += 8) {", "        for (; i + 8 <= intNum; i += 8) {"),
        ("    nvalue = count * 2;", "    nvalue = size_t(count) * 2 + (MarkLength ? 1 : 0);"),
    ):
        require(expected.count(before) == 1, "original correction pattern changed")
        expected = expected.replace(before, after)
    actual_patch = check_identity(
        patch_lock["patch"], COMPONENT / "patches/0001-complete-length-word-access-and-tail.patch"
    )
    expected_patch = "".join(
        difflib.unified_diff(
            source.splitlines(True),
            expected.splitlines(True),
            fromfile="a/headers/simple8b_rle.h",
            tofile="b/headers/simple8b_rle.h",
        )
    )
    require(
        actual_patch.read_text() == expected_patch
        and hashlib.sha256(source.encode()).hexdigest() == patch_lock["original_sha256"]
        and hashlib.sha256(expected.encode()).hexdigest() == patch_lock["patched_sha256"],
        "exact four-change patch differs",
    )
    require(
        len(report["generated_source_files"]) == 9
        and {check_identity(item) for item in report["generated_source_files"]}
        == {generated / name for name in algorithm_files},
        "generated source universe differs",
    )
    for name in algorithm_files:
        original = (COMPONENT / "vendor/fastpfor" / name).read_bytes()
        require(
            (generated / name).read_bytes()
            == (expected.encode() if name == "headers/simple8b_rle.h" else original),
            "generated source changed beyond patch",
        )

    failure_path = check_identity(
        report["original_failure_report"],
        ROOT / "build/source-audits/fastpfor-simple8b-rle-discovery/report.json",
    )
    failure = json.loads(failure_path.read_text())
    require(
        failure["status"] == "ORIGINAL_API_FAILURES_RETAINED_NOT_QUALIFIED"
        and failure["marked_return_length_omits_header"] is True
        and failure["zero_singleton_tail_words_overwritten"] == 7
        and failure["exact_output_asan"] == "HEAP_BUFFER_OVERFLOW",
        "original native failures not retained",
    )
    require(
        sha(ROOT / "tools/discover_fastpfor_simple8b_rle.py") == failure["driver_sha256"]
        and sha(failure_path.parent / "probe.cpp") == failure["probe_sha256"],
        "original failure probe drift",
    )
    for item in failure["commands"]:
        require(
            json.loads((failure_path.parent / (item["name"] + ".json")).read_text()) == item,
            "original failure raw log differs",
        )
    observations = {item["name"]: item for item in failure["commands"]}
    require(
        "returned_words=2 consumed_words=3" in observations["release-marked-padded"]["stdout"]
        and "tail_words_changed=7" in observations["release-unmarked-padded"]["stdout"]
        and observations["sanitizer-unmarked-exact"]["returncode"] != 0
        and "heap-buffer-overflow" in observations["sanitizer-unmarked-exact"]["stderr"],
        "original failures not backed by actual commands",
    )
    for item in failure["builds"]:
        require(
            sha(failure_path.parent / item["profile"]) == item["binary_sha256"],
            "original failure binary drift",
        )
    for item in failure["source_files"]:
        original = failure_path.parent / "original-source" / item["upstream_path"]
        require(
            sha(original) == item["sha256"]
            and original.read_bytes() == tracked(repo, PIN, item["upstream_path"]),
            "original failure source drift",
        )

    commands = report["commands"]
    names = ["apply-patch"]
    labels = [
        "original-release",
        "original-debug",
        "patched-release",
        "patched-debug",
        "patched-sanitizer",
    ]
    for label in labels:
        names += [label + "-compile", label + "-execute"]
    names += ["patched-full-factory-compile", "patched-full-unit-link", "patched-full-unit-execute"]
    require(
        [item["name"] for item in commands] == names
        and all(item["returncode"] == 0 for item in commands),
        "build/run universe incomplete",
    )
    command_map = {item["name"]: item for item in commands}
    for item in commands:
        require(
            json.loads((out / (item["name"] + ".json")).read_text()) == item,
            "source raw/nested log differs",
        )
        require(
            item["sanitizer_environment"]
            == {
                "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            },
            "sanitizer environment differs",
        )
    require(
        commands[0]["command"]
        == [
            "/usr/bin/patch",
            "--batch",
            "--forward",
            "-p1",
            "-d",
            str(generated),
            "-i",
            str(actual_patch),
        ],
        "actual patch application command differs",
    )
    require(
        [item["label"] for item in report["builds"]] == labels
        and [item["label"] for item in report["matrices"]] == labels,
        "three-profile/marked-unmarked matrix universe differs",
    )
    for label, build, matrix in zip(labels, report["builds"], report["matrices"], strict=True):
        original = label.startswith("original-")
        profile = label.split("-", 1)[1]
        headers = COMPONENT / "vendor/fastpfor/headers" if original else generated / "headers"
        exe = check_identity(build["executable"], out / label / "source-matrix")
        check_identity(build["dependency_file"], out / label / "source-matrix.d")
        flags = ["-std=c++17", "-march=x86-64", "-fno-tree-vectorize", *PROFILE_FLAGS[profile]]
        if original:
            flags.append("-DTSCB_ORIGINAL_RLE=1")
        command = [
            "/usr/bin/g++",
            *flags,
            "-I",
            str(headers),
            "-MD",
            "-MF",
            str(out / label / "source-matrix.d"),
            str(matrix_source),
            "-o",
            str(exe),
        ]
        require(
            build["command"] == command_map[label + "-compile"]["command"] == command,
            "source compiler/profile flags differ",
        )
        paths = check_closure(build)
        require(
            headers / "simple8b_rle.h" in paths and matrix_source in paths,
            "matrix did not consume the qualified RLE source",
        )
        if profile == "sanitizer":
            data = exe.read_bytes()
            require(
                b"__asan_init" in data and b"__ubsan_handle" in data,
                "sanitizer executable substituted",
            )
        require(
            command_map[label + "-execute"]["command"]
            == [str(exe)] + (["wire-only"] if original else []),
            "source invocation differs",
        )
        require(
            matrix["result"] == command_map[label + "-execute"], "matrix raw observation differs"
        )
        observation = {
            "status": "PASS",
            "cases": 70488,
            "guard_roundtrips": 0 if original else 1596,
            "selectors": 15,
            "wire_only": original,
        }
        require(
            matrix["observation"] == json.loads(matrix["result"]["stdout"]) == observation,
            "source matrix/guard/selector counts differ",
        )
    require(
        (
            report["original_wire_cases"],
            report["patched_roundtrip_cases"],
            report["patched_guard_roundtrips"],
        )
        == (140976, 211464, 4788),
        "source aggregate counts differ",
    )
    upstream = audit_upstream()
    original_report_path = check_identity(
        report["original_full_upstream"]["report"],
        ROOT / "build/source-audits/fastpfor_simple_upstream_tests.json",
    )
    require(report["original_full_upstream"]["audit"] == upstream, "original full unit audit drift")
    old = json.loads(original_report_path.read_text())
    require(
        old["result"]["stdout"].count("Simple8b_RLE encoding ... decoding ... ok!") == 5,
        "original full unit RLE executions absent",
    )
    require(
        lock["original_full_upstream_unit"]["report_sha256"] == sha(original_report_path)
        and lock["original_full_upstream_unit"]["lock_sha256"] == upstream["source_lock_sha256"],
        "source lock full-unit reuse differs",
    )
    vendor = ROOT / "adapters/fastpfor_simple/third_party/fastpfor_upstream_unit"
    factory = out / "patched-full-upstream/codecfactory.o"
    build = report["patched_factory_build"]
    check_identity(build["object"], factory)
    check_identity(build["dependency_file"], factory.with_suffix(".d"))
    command = [
        "/usr/bin/g++",
        "-std=c++11",
        *UPSTREAM_FLAGS,
        "-I",
        str(generated / "headers"),
        "-I",
        str(vendor / "headers"),
        "-MD",
        "-MF",
        str(factory.with_suffix(".d")),
        "-c",
        str(vendor / "src/codecfactory.cpp"),
        "-o",
        str(factory),
    ]
    require(
        build["command"] == command_map["patched-full-factory-compile"]["command"] == command,
        "full factory build flags/source differ",
    )
    paths = check_closure(build)
    require(
        generated / "headers/simple8b_rle.h" in paths
        and vendor / "headers/simple8b_rle.h" not in paths,
        "full factory used original RLE",
    )
    expected_reuse = [
        item
        for item in old["builds"]
        if not item["source"]["path"].endswith("/src/codecfactory.cpp")
    ]
    require(
        report["reused_upstream_objects"] == expected_reuse and len(expected_reuse) == 9,
        "complete unit object reuse differs",
    )
    objects = [
        str(factory)
        if item["source"]["path"].endswith("/src/codecfactory.cpp")
        else str(ROOT / item["object"]["path"])
        for item in old["builds"]
    ]
    exe = check_identity(
        report["patched_full_executable"], out / "patched-full-upstream/upstream-unit"
    )
    require(
        command_map["patched-full-unit-link"]["command"]
        == ["/usr/bin/g++", *UPSTREAM_FLAGS, *objects, "-o", str(exe)]
        and command_map["patched-full-unit-execute"]["command"] == [str(exe)],
        "full unfiltered unit link/run differs",
    )
    require(
        report["patched_full_result"] == command_map["patched-full-unit-execute"],
        "full unit raw observation differs",
    )
    stdout = report["patched_full_result"]["stdout"]
    require(
        re.findall(r"testing\.\.\. b = (\d+)", stdout) == [str(i) for i in range(29)]
        and re.findall(r"length = (\d+)", stdout) == [str(2**i) for i in (5, 10, 15, 20, 25)]
        and stdout.count("Simple8b_RLE encoding ... decoding ... ok!") == 5
        and stdout.endswith("testing...ok. Your code is good.\n"),
        "complete RLE unit incomplete",
    )
    return {
        "status": "PASS",
        "scope": report["scope"],
        "source_file_count": 16,
        "source_report": str(report_path),
        "source_report_sha256": sha(report_path),
        "patch_sha256": sha(actual_patch),
        "original_wire_cases": 140976,
        "patched_roundtrip_cases": 211464,
        "patched_guard_roundtrips": 4788,
        "original_and_patched_complete_factory_rle_zipf_cases": 10,
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    output = ROOT / "build/source-audits/fastpfor_simple8b_rle_source_current_audit.json"
    try:
        result = audit(args.report)
    except Exception as error:
        output.write_text(
            json.dumps(
                {"status": "FAIL", "error": str(error), "full_logical_entry_qualified": False},
                indent=2,
            )
            + "\n"
        )
        raise
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
