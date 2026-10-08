"""Independently audit original failures and corrected kernels; ABI remains pending."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "adapters/littleintpacker"
VENDOR = COMPONENT + "/vendor/littleintpacker"
PIN = "8777f574a5ab3c653881371819383c986292843c"
APIS = ("PACK32", "TURBO", "SC", "BMI2", "HORIZONTAL")
FILES = (
    "LICENSE",
    "README.md",
    "makefile",
    "include/bitpacking.h",
    "include/portability.h",
    "include/util.h",
    "src/bitpacking32.c",
    "src/turbobitpacking32.c",
    "src/scpacking32.c",
    "src/bmipacking32.c",
    "src/horizontalpacking32.c",
    "src/util.c",
    "tests/unit.c",
    "benchmarks/bitpackingbenchmark.c",
)
PROFILES = {
    "release": ["-O3", "-g", "-UNDEBUG"],
    "debug": ["-O0", "-g", "-UNDEBUG"],
    "sanitizer": [
        "-O1",
        "-g",
        "-UNDEBUG",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
        "-no-pie",
    ],
}
BASELINE = [
    "-march=x86-64",
    "-mno-avx",
    "-mno-avx2",
    "-mno-avx512f",
    "-fno-tree-vectorize",
    "-fno-tree-slp-vectorize",
]
SOURCES = {
    "bitpacking32.c": [],
    "turbobitpacking32.c": [],
    "scpacking32.c": [],
    "bmipacking32.c": ["-mavx2", "-mbmi2"],
    "horizontalpacking32.c": ["-mssse3", "-msse4.1"],
    "util.c": [],
}
MODES = (
    "exact-input",
    "exact-packed-output",
    "exact-decoded-output",
    "exact-packed-input",
    "invalid-width",
    "odd-width-multiple-blocks",
)
CHANGES = {
    "bitpacking32.c": (32, 528),
    "turbobitpacking32.c": (64, 272),
    "scpacking32.c": (64, 272),
    "bmipacking32.c": (64, 272),
}
AUDIT_PATH = "build/source-audits/littleintpacker_source_current_audit.json"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RuntimeError(reason)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unit_stdout() -> str:
    widths = "bit = " + "".join(f" {width} " for width in range(33)) + "\n"
    return (
        "".join(
            name + "\n" + widths
            for name in (
                "testshortpackhorizontal",
                "testshortpacksc",
                "testshortpackbmi",
                "testshortpack",
                "testshortpackturbo",
            )
        )
        + "All tests OK!\n"
    )


def matrix_stdout(patched: bool) -> str:
    return "".join(
        f"API_DONE {api} widths=33 lengths=23 patterns=5 cases=3795 "
        f"failures={0 if patched or api == 'HORIZONTAL' else 95}\n"
        for api in APIS
    ) + (
        f"MATRIX_DONE cases=18975 failures={0 if patched else 380} "
        "widths=33 lengths=23 patterns=5 apis=5\n"
    )


def audit(root: Path = ROOT) -> dict:
    def local(name: str) -> Path:
        path = Path(name)
        if path.is_absolute():
            return root / path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        require(".." not in path.parts, "evidence path escapes workspace")
        return root / path

    def check_file(item: dict, expected: str | None = None) -> None:
        if expected is not None:
            require(item["path"] == expected, "evidence path substituted: " + expected)
        path = local(item["path"])
        require(path.is_file(), "consumed file missing: " + item["path"])
        require(sha(path) == item["sha256"], "consumed file drift: " + item["path"])

    def closure(items: list[dict], expected: set[str]) -> None:
        require(
            len(items) == len(expected) and {item["path"] for item in items} == expected,
            "compiler dependency closure omitted or substituted",
        )
        for item in items:
            check_file(item)

    def deps(item: dict) -> set[str]:
        check_file(item)
        names = shlex.split(local(item["path"]).read_text().replace("\\\n", " ").split(":", 1)[1])
        return {
            str(Path(name).relative_to(ROOT)) if Path(name).is_relative_to(ROOT) else name
            for name in names
        }

    def pending(document: dict) -> None:
        require(document["full_logical_entries_qualified"] is False, "full entry claimed")
        require(
            all(
                document[key] == "PENDING"
                for key in (
                    "bounded_abi",
                    "python_sdk",
                    "benchmark_five_layers",
                )
            ),
            "source tests cannot qualify ABI/SDK/Benchmark",
        )

    source_path = "build/source-audits/littleintpacker_source_tests.json"
    patched_path = "build/source-audits/littleintpacker_patched_tests.json"
    original = json.loads(local(source_path).read_text())
    patched = json.loads(local(patched_path).read_text())
    lock = json.loads(local(COMPONENT + "/SOURCE_LOCK.json").read_text())
    patch_lock = json.loads(local(COMPONENT + "/PATCH_LOCK.json").read_text())
    require(
        original["status"] == "ORIGINAL_SOURCE_TESTS_EXECUTED_BOUNDED_ABI_PENDING",
        "original failure execution incomplete",
    )
    require(
        patched["status"] == "PATCHED_COMPLETE_UPSTREAM_AND_SOURCE_API_MATRIX_PASS",
        "patched execution incomplete",
    )
    for doc, driver in ((original, "source"), (patched, "patched")):
        pending(doc)
        check_file(doc["driver"], f"tools/qualify_littleintpacker_{driver}.py")
        check_file(doc["source_lock"], COMPONENT + "/SOURCE_LOCK.json")
        require(
            doc["leak_sanitizer"] == "NOT_QUALIFIED_DETECT_LEAKS_ZERO",
            "LeakSanitizer qualification claimed",
        )
    check_file(original["probe"], COMPONENT + "/tests/source_api_probe.c")
    check_file(patched["patch_lock"], COMPONENT + "/PATCH_LOCK.json")
    check_file(patched["original_report"], source_path)
    require(
        original["commit"] == lock["commit"] == PIN
        and lock["dirty"] is False
        and lock["submodules"] == []
        and original["source_repository_unmodified"] is True,
        "source pin/cleanliness differs",
    )
    require(
        lock["copy_policy"] == "TRACKED_PINNED_BYTES_NO_PATCH"
        and lock["repository"] == "https://github.com/fast-pack/LittleIntPacker"
        and lock["license"]
        == {"spdx": "Apache-2.0", "status": "RUN_ALLOWED", "file": VENDOR + "/LICENSE"},
        "source or license identity differs",
    )
    require(
        lock["logical_entries"]
        == [
            {"audit_index": 134, "name": "Fixed-width Bit Packing"},
            {"audit_index": 138, "name": "LittleIntPacker"},
        ],
        "workbook logical entries differ",
    )
    pending(lock)
    require(
        lock["freezer_sha256"] == sha(local("tools/freeze_littleintpacker_source.py")),
        "freezer drift",
    )
    require(
        lock["source_apis"]
        == dict(
            zip(
                APIS,
                (
                    ["pack32", "unpack32"],
                    ["turbopack32", "turbounpack32"],
                    ["scpack32", "scunpack32"],
                    ["bmipack32", "bmiunpack32"],
                    ["pack32", "horizontalunpack32"],
                ),
                strict=True,
            )
        ),
        "API coverage differs",
    )
    require(
        lock["upstream_unit"]
        == {
            "path": "tests/unit.c",
            "filtered": False,
            "api_pairs": list(APIS),
            "widths": list(range(33)),
            "lengths": list(range(513)),
            "trials_per_width": 100,
        },
        "upstream unit scope filtered",
    )
    require(
        lock["benchmark"]["timing_policy"]
        == "RDTSC_FASTEST_OF_50000_NOT_USED_FOR_FORMAL_STATISTICS",
        "upstream fastest-of timing treated as formal statistics",
    )
    require(
        len(lock["files"]) == len(FILES)
        and [item["upstream_path"] for item in lock["files"]] == list(FILES),
        "vendor file universe incomplete",
    )
    repository = (
        ROOT.parent / "Compression_Source_Code/Source_Code/_repos/fast-pack_LittleIntPacker"
    )

    def git(*args: str) -> bytes:
        return subprocess.run(
            ["git", "--no-optional-locks", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout

    require(
        git("rev-parse", "HEAD").decode().strip() == PIN
        and not git("status", "--porcelain")
        and not git("submodule", "status"),
        "current original repository changed",
    )
    for item in lock["files"]:
        check_file(item, VENDOR + "/" + item["upstream_path"])
        data = local(item["path"]).read_bytes()
        require(
            len(data) == item["bytes"] and data == git("show", f"{PIN}:{item['upstream_path']}"),
            "vendor differs from pinned upstream bytes",
        )

    check_file(patch_lock["patch"], COMPONENT + "/patches/0001-zero-width-and-word-access.patch")
    require(
        patch_lock["source_lock_sha256"] == sha(local(COMPONENT + "/SOURCE_LOCK.json"))
        and patch_lock["generator_sha256"] == sha(local("tools/prepare_littleintpacker_patch.py"))
        and patch_lock["original_source_modified"] is False
        and patch_lock["bounded_abi"] == patch_lock["benchmark_five_layers"] == "PENDING",
        "patch provenance/scope drift",
    )
    require(
        patched["original_failures_retained"] is True
        and patched["source_padding_required"] is True
        and patched["upstream_unit_filtered"] is False
        and patched["api_matrix_cases"] == 56925,
        "patch matrix/padding/failure retention misrepresented",
    )
    generated = "build/source-audits/littleintpacker-patched/generated"
    require(
        len(patched["generated_source_files"]) == len(FILES)
        and {i["path"] for i in patched["generated_source_files"]}
        == {generated + "/" + name for name in FILES},
        "generated source universe incomplete",
    )
    for item in patched["generated_source_files"]:
        check_file(item)
    require(
        len(patch_lock["changes"]) == 4
        and [i["upstream_path"] for i in patch_lock["changes"]]
        == ["src/" + name for name in CHANGES],
        "patch change universe differs",
    )
    for change in patch_lock["changes"]:
        name = Path(change["upstream_path"]).name
        bits, words = CHANGES[name]
        require(
            change["zero_width_fixes"] == 1
            and change["pointer_casts_removed"] == 64
            and change["word_loads"] == change["word_stores"] == words
            and change["word_bits"] == bits
            and change["original_sha256"] == sha(local(VENDOR + "/src/" + name))
            and change["patched_sha256"] == sha(local(generated + "/src/" + name)),
            "patch changed bytes/counts differ",
        )
    # Apply the recorded patch independently, without calling its generator.
    with tempfile.TemporaryDirectory(prefix="tscb-littleintpacker-audit-") as folder:
        directory = Path(folder)
        for name in FILES:
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(local(VENDOR + "/" + name).read_bytes())
        result = subprocess.run(
            [
                "/usr/bin/patch",
                "--batch",
                "--forward",
                "-p1",
                "-d",
                str(directory),
                "-i",
                str(local(patch_lock["patch"]["path"])),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        require(result.returncode == 0, "independent patch application failed")
        for name in FILES:
            require(
                (directory / name).read_bytes() == local(generated + "/" + name).read_bytes(),
                "generated source differs from actual patch: " + name,
            )

    closure_counts = {}
    failures = 0
    for kind, doc in (("source", original), ("patched", patched)):
        require(set(doc["profiles"]) == set(PROFILES), "build profile missing")
        expected_records = []

        def record(
            command: list[str],
            observed: dict | None = None,
            *,
            document: dict = doc,
            ledger: list = expected_records,
        ) -> dict:
            matches = [item for item in document["commands"] if item["command"] == command]
            require(len(matches) == 1, "raw command missing/duplicated or flags differ")
            found = matches[0]
            require(
                set(found) == {"command", "returncode", "stdout", "stderr"}
                and type(found["returncode"]) is int,
                "invalid command observation",
            )
            if observed is None:
                require(found["returncode"] == 0, "build or patch command failed")
            else:
                require(found == observed, "nested observation differs from raw command ledger")
            ledger.append(found)
            return found

        if kind == "patched":
            observation = record(
                [
                    "/usr/bin/patch",
                    "--batch",
                    "--forward",
                    "-p1",
                    "-d",
                    str(ROOT / generated),
                    "-i",
                    str(ROOT / patch_lock["patch"]["path"]),
                ]
            )
            require(
                observation["stdout"] == "".join(f"patching file src/{name}\n" for name in CHANGES)
                and observation["stderr"] == "",
                "actual patch application trace differs",
            )
        source_dir = VENDOR if kind == "source" else generated
        for profile, options in PROFILES.items():
            evidence = doc["profiles"][profile]
            build_dir = f"build/source-audits/littleintpacker-{kind}/{profile}"
            objects = []
            all_deps = set()
            require(len(evidence["builds"]) == len(SOURCES), "build object missing")
            for build, (name, isa) in zip(evidence["builds"], SOURCES.items(), strict=True):
                source = source_dir + "/src/" + name
                obj, dep = build_dir + "/" + name + ".o", build_dir + "/" + name + ".d"
                for field, filename in (("source", source), ("object", obj), ("dependency", dep)):
                    check_file(build[field], filename)
                command = [
                    "/usr/bin/gcc",
                    "-std=c99",
                    "-Wall",
                    "-Wextra",
                    *options,
                    *BASELINE,
                    *isa,
                    "-I",
                    str(ROOT / source_dir / "include"),
                    "-MD",
                    "-MF",
                    str(ROOT / dep),
                    "-c",
                    str(ROOT / source),
                    "-o",
                    str(ROOT / obj),
                ]
                require(build["command"] == command, "compiler options/ISA/source substituted")
                record(command)
                actual = deps(build["dependency"])
                require(source in actual, "actual compiled translation unit omitted")
                closure(build["compiler_closure"], actual)
                all_deps.update(actual)
                objects.append(str(ROOT / obj))
            require(set(evidence["executions"]) == {"unit", "api-probe"}, "unit/matrix omitted")
            for target, source in (
                ("unit", source_dir + "/tests/unit.c"),
                ("api-probe", COMPONENT + "/tests/source_api_probe.c"),
            ):
                executable = build_dir + "/" + target
                dep = executable + ".d"
                execution = evidence["executions"][target]
                check_file(execution["artifact"], executable)
                check_file(execution["dependency"], dep)
                record(
                    [
                        "/usr/bin/gcc",
                        "-std=c99",
                        *options,
                        *BASELINE,
                        "-I",
                        str(ROOT / source_dir / "include"),
                        "-MD",
                        "-MF",
                        str(ROOT / dep),
                        str(ROOT / source),
                        *objects,
                        "-o",
                        str(ROOT / executable),
                    ]
                )
                actual = deps(execution["dependency"])
                require(source in actual, "upstream unit/probe source absent from compiler closure")
                all_deps.update(actual)
                result = record([str(ROOT / executable)], execution["result"])
                if kind == "patched" or (profile != "sanitizer" and target == "unit"):
                    require(
                        execution["status"] == "PASS"
                        and result["returncode"] == 0
                        and result["stderr"] == ""
                        and result["stdout"]
                        == (unit_stdout() if target == "unit" else matrix_stdout(True)),
                        "complete successful upstream unit/API matrix absent",
                    )
                else:
                    require(
                        execution["status"] == "ORIGINAL_FAILURE_RETAINED",
                        "original failure relabeled as success",
                    )
                    if profile != "sanitizer":
                        expected_stderr = "".join(
                            f"INVERSE_FAIL {api} 0 {n} {pattern}\n"
                            for api in APIS[:4]
                            for n, pattern in [(15, p) for p in range(5)] + [(16, 0)]
                        )
                        require(
                            result["returncode"] == 12
                            and result["stdout"] == matrix_stdout(False)
                            and result["stderr"] == expected_stderr,
                            "original 380 zero-width failures removed/changed",
                        )
                    else:
                        filename = "scpacking32.c" if target == "unit" else "turbobitpacking32.c"
                        require(
                            result["returncode"] == 1
                            and "runtime error: store to misaligned address" in result["stderr"]
                            and source_dir + "/src/" + filename in result["stderr"]
                            and "All tests OK!" not in result["stdout"]
                            and "MATRIX_DONE" not in result["stdout"],
                            "original sanitizer failure trace removed/changed",
                        )
            probes = evidence["raw_probes" if kind == "source" else "alignment_probes"]
            modes = MODES if kind == "source" else (MODES[-1],)
            require(len(probes) == len(APIS) * len(modes), "raw probe universe incomplete")
            for probe, (index, api, mode) in zip(
                probes,
                ((i, api, mode) for i, api in enumerate(APIS) for mode in modes),
                strict=True,
            ):
                require(
                    probe["api"] == api and (kind == "patched" or probe["mode"] == mode),
                    "probe API/mode substituted",
                )
                result = record(
                    [str(ROOT / build_dir / "api-probe"), str(index), mode], probe["result"]
                )
                banner = f"RAW_UNSAFE_PROBE api={api} mode={mode}\n"
                unsafe = kind == "source" and (
                    mode != MODES[-1] or (profile == "sanitizer" and api in APIS[1:4])
                )
                if unsafe:
                    failures += 1
                    require(
                        probe["status"] == "ORIGINAL_FAILURE_RETAINED"
                        and result["returncode"] == (1 if profile == "sanitizer" else -11)
                        and result["stdout"] == ""
                        and result["stderr"].startswith(banner),
                        "original unsafe probe failure removed/changed",
                    )
                    if profile == "sanitizer":
                        require(
                            "AddressSanitizer" in result["stderr"]
                            or "runtime error:" in result["stderr"],
                            "original sanitizer probe diagnostic missing",
                        )
                else:
                    require(
                        probe["status"] == ("PASS" if kind == "patched" else "RAW_CALL_RETURNED")
                        and result["returncode"] == 0
                        and result["stderr"] == banner
                        and result["stdout"] == "RAW_PROBE_RETURNED_WITHOUT_DETECTED_FAILURE\n",
                        "odd-width probe incomplete",
                    )
            closure(evidence["compiler_closure"], all_deps)
            closure_counts[f"{kind}_{profile}"] = len(all_deps)
            if profile == "sanitizer":
                for target in ("unit", "api-probe"):
                    symbols = subprocess.run(
                        ["/usr/bin/nm", "-u", str(local(build_dir + "/" + target))],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=30,
                    ).stdout
                    require(
                        "__asan_init" in symbols and "__ubsan_handle" in symbols,
                        "actual executable lacks ASan/UBSan instrumentation",
                    )
        require(doc["commands"] == expected_records, "extra/missing/reordered raw commands")
    require(failures == 78, "original failure count differs")

    history_dir = "build/source-audits/littleintpacker-initial-zero-width-failure"
    history = json.loads(local(history_dir + "/report.json").read_text())
    require(
        history["status"] == "FAIL"
        and history["commit"] == PIN
        and history["commands"][-1]["returncode"] == 11
        and history["commands"][-1]["stderr"] == "INVERSE_FAIL PACK32 0 15 0\n",
        "initial failure history deleted/relabelled",
    )
    for field, name in (
        ("driver", "qualify_littleintpacker_source.py"),
        ("probe", "source_api_probe.c"),
        ("source_lock", "SOURCE_LOCK.json"),
    ):
        require(
            sha(local(history_dir + "/" + name)) == history[field]["sha256"],
            "initial failure source snapshot drift",
        )
    return {
        "status": "PASS",
        "qualification_scope": "SOURCE_AND_PATCHED_KERNELS_ONLY",
        "commit": PIN,
        "original_vendor_file_count": 14,
        "source_reports": [
            {"path": name, "sha256": sha(local(name))} for name in (source_path, patched_path)
        ],
        "original_unsafe_probe_count": failures,
        "original_zero_width_failures_per_profile": 380,
        "original_sanitizer_unit_and_matrix": "FAILURES_RETAINED",
        "patched_api_matrix_cases": 56925,
        "patched_alignment_probes": 15,
        "patched_full_upstream_profiles": list(PROFILES),
        "compiler_closure_counts": closure_counts,
        "source_padding_required": True,
        "leak_sanitizer": "NOT_QUALIFIED_DETECT_LEAKS_ZERO",
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entries_qualified": False,
        "initial_failure_report": {
            "path": history_dir + "/report.json",
            "sha256": sha(local(history_dir + "/report.json")),
        },
    }


if __name__ == "__main__":
    result = audit()
    result["auditor"] = {
        "path": "tools/audit_littleintpacker_source.py",
        "sha256": sha(Path(__file__)),
    }
    (ROOT / AUDIT_PATH).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
