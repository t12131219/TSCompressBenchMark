"""Independently recheck SIMDComp's current tested source, original failures and patches."""

from __future__ import annotations

import hashlib
import itertools
import json
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("release", "debug", "sanitizer")
MODES = ("plain", "d1", "for", "query-d1", "query-for", "set-plain", "set-d1", "set-for")
COUNTS = {
    "plain": (11088, 0),
    "d1": (396, 0),
    "for": (11088, 0),
    "query-d1": (594, 248754),
    "query-for": (594, 235884),
    "set-plain": (4224, 0),
    "set-d1": (4224, 0),
    "set-for": (4224, 0),
}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def dependency_paths(path: Path, directory: Path) -> set[Path]:
    filenames = shlex.split(path.read_text().replace("\\\n", " ").split(":", 1)[1])
    return {
        (Path(name) if Path(name).is_absolute() else directory / name).resolve()
        for name in filenames
    }


def audit(root: Path = ROOT) -> dict:
    # Reports preserve the exact original command paths. Map workspace files for
    # independent-copy drift tests; external compiler/runtime headers stay absolute.
    def local(filename: str) -> Path:
        path = Path(filename)
        if path.is_relative_to(ROOT):
            return root / path.relative_to(ROOT)
        return path if path.is_absolute() else root / path

    def check_file(item: dict, reason: str) -> None:
        require(sha(local(item["path"])) == item["sha256"], reason)

    adapter = root / "adapters/simdcomp"
    lock_path = adapter / "SOURCE_LOCK.json"
    lock = read(lock_path)
    require(
        lock["repository"] == "https://github.com/lemire/simdcomp"
        and lock["commit"] == "d5301778fe5045ca8099252de5a6ed8016a287df"
        and lock["license"]["spdx"] == "BSD-3-Clause"
        and lock["license"]["status"] == "RUN_ALLOWED"
        and not lock["dirty"]
        and lock["submodules"] == [],
        "source identity/license differs",
    )
    require(
        len(lock["files"]) == len({f["path"] for f in lock["files"]}) == 27,
        "original vendor universe incomplete",
    )
    require(
        sha(root / "tools/freeze_simdcomp_source.py") == lock["freezer_sha256"], "freezer drift"
    )
    for item in lock["files"]:
        check_file(item, "original vendor drift")
    upstreams, guards = {}, {}
    dependency_counts = {}
    for kind in ("original", "patched"):
        path = root / f"build/source-audits/simdcomp-upstream-{kind}-tests.json"
        upstream = read(path)
        upstreams[kind] = upstream
        require(
            upstream["status"] == "PASS"
            and upstream["source_kind"] == kind
            and upstream["source_lock_sha256"] == sha(lock_path)
            and upstream["files"] == lock["files"]
            and upstream["benchmark_adapter_qualification"] == "NOT_CLAIMED"
            and upstream["actual_isa"] == "SSE4_1_SSSE3_NO_AVX"
            and upstream["source_repository_modified"] is False,
            "upstream admission stale",
        )
        check_file(upstream["driver"], "upstream driver drift")
        require(
            len(upstream["tests"]) == 9
            and {(t["profile"], t["test_kind"]) for t in upstream["tests"]}
            == set(itertools.product(PROFILES, ("unit", "unit_chars", "example"))),
            "upstream test matrix incomplete",
        )
        require(
            len(upstream["builds"]) == 3
            and {b["profile"] for b in upstream["builds"]} == set(PROFILES),
            "upstream builds incomplete",
        )
        for build in upstream["builds"]:
            check_file(build["compile_commands"], "actual compile commands drift")
            commands = read(local(build["compile_commands"]["path"]))
            require(
                commands == build["commands"] and len(commands) == 11,
                "compile target universe differs",
            )
            for command in commands:
                flags = shlex.split(command["command"])
                require(
                    all(
                        flag in flags
                        for flag in ("-march=x86-64", "-msse4.1", "-mno-avx", "-UNDEBUG")
                    )
                    and "-DNDEBUG" not in flags
                    and "-march=native" not in flags,
                    "actual ISA/assertion flags differ",
                )
                if build["profile"] == "sanitizer":
                    require(
                        "-fsanitize=address,undefined" in flags
                        and "-fno-sanitize-recover=all" in flags,
                        "sanitizer instrumentation missing",
                    )
            closure = build["compiled_source_closure"]
            require(closure and build["objects"], "actual compiler closure missing")
            for item in [*closure, *build["objects"], build["library"]]:
                check_file(item, "compiled library/object/input drift")
            directory = local(build["library"]["path"]).parent
            actual = set().union(
                *(dependency_paths(d, directory) for d in directory.rglob("*.o.d"))
            )
            require(
                actual == {local(item["path"]).resolve() for item in closure},
                "actual compiler dependency universe differs",
            )
            dependency_counts[kind + "/" + build["profile"]] = len(closure)
        for test in upstream["tests"]:
            require(
                test["status"] == "PASS" and test["returncode"] == 0, "upstream tests did not pass"
            )
            check_file(test["executable"], "upstream executable drift")
            require(
                test["command"] == [test["executable"]["path"]], "upstream program command differs"
            )
            require(
                any(
                    all(c[k] == test[k] for k in ("command", "returncode", "stdout", "stderr"))
                    for c in upstream["commands"]
                ),
                "upstream command observation missing",
            )
            if test["test_kind"] == "unit":
                require("All tests OK!" in test["stdout"], "upstream unit success marker missing")
            if test["test_kind"] == "unit_chars":
                require(
                    "Code looks good." in test["stdout"], "upstream uint32 success marker missing"
                )
        guard_path = root / f"build/source-audits/simdcomp-source-{kind}-guards.json"
        guards[kind] = report = read(guard_path)
        require(
            report["source_kind"] == kind
            and report["source_lock_sha256"] == sha(lock_path)
            and report["upstream_report"]["sha256"] == sha(path)
            and report["actual_isa"] == upstream["actual_isa"]
            and report["benchmark_adapter_qualification"] == "NOT_CLAIMED",
            "guard provenance differs",
        )
        check_file(report["driver"], "guard driver drift")
        check_file(report["guard"], "independent guard drift")
        require(
            len(report["tests"]) == 24
            and {(t["profile"], t["mode"]) for t in report["tests"]}
            == set(itertools.product(PROFILES, MODES)),
            "public API matrix incomplete",
        )
        require(
            len(report["builds"]) == 3
            and {b["profile"] for b in report["builds"]} == set(PROFILES),
            "guard build matrix incomplete",
        )
        for build in report["builds"]:
            upstream_build = next(b for b in upstream["builds"] if b["profile"] == build["profile"])
            require(
                build["library"]["sha256"] == upstream_build["library"]["sha256"],
                "guard linked a different library",
            )
            for item in [build["library"], build["executable"], *build["compiled_source_closure"]]:
                check_file(item, "guard executable/dependency drift")
            executable = local(build["executable"]["path"])
            actual = dependency_paths(executable.parent / "source-guard.d", executable.parent)
            require(
                actual
                == {local(item["path"]).resolve() for item in build["compiled_source_closure"]},
                "actual guard dependency universe differs",
            )
            compile_observations = [
                command
                for command in report["commands"]
                if command["command"][-2:] == ["-o", build["executable"]["path"]]
            ]
            require(len(compile_observations) == 1, "guard compile observation missing")
            compilation = compile_observations[0]
            flags = compilation["command"]
            require(
                compilation["returncode"] == 0
                and all(
                    flag in flags
                    for flag in ("-march=x86-64", "-msse4.1", "-mno-avx", "-UNDEBUG", "-MD")
                )
                and build["library"]["path"] in flags
                and report["guard"]["path"] in flags,
                "guard ISA/source/library compile flags differ",
            )
            if build["profile"] == "sanitizer":
                require(
                    "-fsanitize=address,undefined" in flags
                    and "-fno-sanitize-recover=all" in flags,
                    "guard sanitizer instrumentation missing",
                )
        for test in report["tests"]:
            failed = kind == "original" and (
                test["mode"] in ("query-d1", "query-for", "set-d1", "set-for")
                or test["mode"] == "set-plain"
                and test["profile"] == "sanitizer"
            )
            require(
                test["status"] == ("FAIL" if failed else "PASS")
                and (test["returncode"] != 0 if failed else test["returncode"] == 0),
                "original failure or patched success misreported",
            )
            build = next(b for b in report["builds"] if b["profile"] == test["profile"])
            require(
                test["command"] == [build["executable"]["path"], test["mode"]],
                "guard command differs",
            )
            require(
                any(
                    all(c[k] == test[k] for k in ("command", "returncode", "stdout", "stderr"))
                    for c in report["commands"]
                ),
                "guard command observation missing",
            )
            if not failed:
                cases, calls = COUNTS[test["mode"]]
                expected = (
                    f"SIMDComp source {test['mode']} cases PASS: {cases}; "
                    f"query calls: {calls}; exact guard pages; scalar wire\n"
                )
                require(
                    test["stdout"] == expected,
                    "scalar/guard/query coverage differs",
                )
            elif test["mode"] == "query-d1":
                require(
                    "width=32 count=0: search lower bound position" in test["stderr"],
                    "original empty-search failure missing",
                )
            elif test["mode"] == "query-for":
                require(test["returncode"] in (-11, -6), "original protected read did not fail")
                if test["profile"] == "sanitizer":
                    require(
                        "AddressSanitizer" in test["stderr"]
                        and "simdselectFOR" in test["stderr"]
                        and "READ memory access" in test["stderr"],
                        "original guard-page read evidence missing",
                    )
            elif test["profile"] == "sanitizer":
                require(
                    "shift exponent 32" in test["stderr"] and "simdfastset" in test["stderr"],
                    "original width32 UB evidence missing",
                )
            else:
                require(
                    "width=32 count=128: mutation scalar wire differs" in test["stderr"],
                    "original absolute mutation failure missing",
                )
        require(
            report["status"] == ("OBSERVED_FAILURES" if kind == "original" else "PASS")
            and report["failed_test_count"] == (13 if kind == "original" else 0),
            "source outcome misreported",
        )
    patches = upstreams["patched"]["patches"]
    require(
        len(patches) == 3 and not upstreams["original"]["patches"], "explicit patch series differs"
    )
    for patch in patches:
        check_file(patch, "patch drift")
    # Replay on a fresh independent copy, then compare every frozen file. Never
    # trust that the source labeled 'patched' was produced by the saved series.
    with tempfile.TemporaryDirectory(prefix="tscb-simdcomp-patch-") as directory:
        scratch = Path(directory)
        for item in lock["files"]:
            target = scratch / item["upstream_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local(item["path"]), target)
        for patch in patches:
            command = subprocess.run(
                [
                    "patch",
                    "--batch",
                    "--forward",
                    "-p1",
                    "-d",
                    str(scratch),
                    "-i",
                    str(local(patch["path"])),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            require(command.returncode == 0, "patch series cannot reproduce tested source")
        changed = set()
        for item in lock["files"]:
            tested = (
                root
                / "build/source-audits/simdcomp-upstream/patched-source"
                / item["upstream_path"]
            )
            require(
                sha(tested) == sha(scratch / item["upstream_path"]),
                "tested patch source not reproducible",
            )
            if sha(tested) != item["sha256"]:
                changed.add(item["upstream_path"])
        require(
            changed
            == {
                "src/simdbitpacking.c",
                "src/simdfor.c",
                "src/simdpackedsearch.c",
                "src/simdintegratedbitpacking.c",
            },
            "patch changed unexpected source",
        )
    return {
        "status": "PASS",
        "qualification_scope": "PATCHED_SSE4_1_PUBLIC_SOURCE_APIS_ONLY",
        "source_lock_sha256": sha(lock_path),
        "original_failures_retained": 13,
        "guard_cases_per_profile": {key: value[0] for key, value in COUNTS.items()},
        "query_calls_per_profile": sum(value[1] for value in COUNTS.values()),
        "actual_compiled_dependency_counts": dependency_counts,
        "patches": patches,
        "reports": {
            path.name: sha(path)
            for path in (root / "build/source-audits").glob("simdcomp-*-*.json")
            if path.name != "simdcomp-source-current-audit.json"
        },
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
        "logical_entry_index": 137,
        "platform": "LINUX_X86_64_SSE4_1_SSSE3",
        "leak_detection": "DISABLED",
        "remaining_isa_profiles": ["AVX2", "AVX512_HARDWARE_UNAVAILABLE", "ARM_UNTESTED"],
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    output = ROOT / "build/source-audits/simdcomp-source-current-audit.json"
    try:
        result = audit()
    except Exception as error:
        output.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
