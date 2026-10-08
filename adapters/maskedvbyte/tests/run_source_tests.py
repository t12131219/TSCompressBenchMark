"""Capture original failures and qualify separately patched public APIs, before ABI admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/maskedvbyte"
VENDOR = ADAPTER / "vendor/MaskedVByte"
OUT = ROOT / "build/source-audits/maskedvbyte-source"
ENV = dict(
    os.environ,
    ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
    UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
)
PROFILES = {
    "release": ["-O3"],
    "debug": ["-O0", "-g"],
    "sanitizer": [
        "-O1",
        "-g",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
        "-fno-pie",
    ],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-kind", choices=("original", "patched", "both"), default="original"
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = ROOT / f"build/source-audits/maskedvbyte-source-{args.source_kind}-tests.json"
    evidence = {
        "status": "RUNNING",
        "source_kind": args.source_kind,
        "commands": [],
        "tests": [],
        "builds": [],
    }

    def save() -> None:
        report.write_text(json.dumps(evidence, indent=2) + "\n")

    def run(command: list[str], *, must_pass: bool = True) -> dict:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, timeout=120, env=ENV
        )
        item = {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        evidence["commands"].append(item)
        save()
        if must_pass and result.returncode:
            raise RuntimeError("qualification command failed: " + shlex.join(command))
        return item

    save()
    try:
        if platform.machine() != "x86_64" or "sse4_1" not in Path("/proc/cpuinfo").read_text():
            raise RuntimeError("this qualification requires actual Linux x86_64/SSE4.1")
        lock_path = ADAPTER / "SOURCE_LOCK.json"
        lock = json.loads(lock_path.read_text())
        original = ROOT.parent / "Compression_Source_Code/Source_Code/_repos/fast-pack_MaskedVByte"
        assert (
            run(["git", "-C", str(original), "rev-parse", "HEAD"])["stdout"].strip()
            == lock["commit"]
        )
        assert not run(["git", "-C", str(original), "status", "--porcelain"])["stdout"].strip()
        assert not run(["git", "-C", str(original), "submodule", "status"])["stdout"].strip()
        for item in lock["files"]:
            path = ROOT / item["path"]
            assert sha(path) == item["sha256"] == sha(original / path.relative_to(VENDOR))
        kinds = ("original", "patched") if args.source_kind == "both" else (args.source_kind,)
        patches = sorted((ADAPTER / "patches").glob("*.patch"))
        if "patched" in kinds:
            assert patches, "patched qualification requires an explicit recorded patch"
        evidence.update(
            source_lock_sha256=sha(lock_path),
            driver_sha256=sha(Path(__file__)),
            guard_sha256=sha(ADAPTER / "tests/source_guard.c"),
            source_files=lock["files"],
            patches=[identity(path) for path in patches],
            source_repository_unmodified=True,
            platform="LINUX_X86_64_SSE4_1",
            leak_detection="DISABLED",
            benchmark_adapter_qualification="NOT_CLAIMED",
        )
        for kind in kinds:
            source = VENDOR
            if kind == "patched":
                source = OUT / "patched"
                source.mkdir(exist_ok=True)
                shutil.copytree(VENDOR, source, dirs_exist_ok=True)
                for patch in patches:
                    run(
                        [
                            "patch",
                            "--batch",
                            "--forward",
                            "-p1",
                            "-d",
                            str(source),
                            "-i",
                            str(patch),
                        ]
                    )
            for profile, options in PROFILES.items():
                directory = OUT / kind / profile
                directory.mkdir(parents=True, exist_ok=True)
                compiler = "clang" if profile == "sanitizer" else "cc"
                flags = [
                    "-std=c11",
                    "-msse4.1",
                    "-mno-avx",
                    "-mno-avx2",
                    "-Wall",
                    "-Wextra",
                    *options,
                    "-I",
                    str(source / "include"),
                ]
                closure, objects = set(), []
                files = [
                    source / "src/varintencode.c",
                    source / "src/varintdecode.c",
                    VENDOR / "tests/unit.c",
                    ADAPTER / "tests/source_guard.c",
                ]
                for index, path in enumerate(files):
                    obj, dep = directory / f"tu{index}.o", directory / f"tu{index}.d"
                    run([compiler, *flags, "-MD", "-MF", str(dep), "-c", str(path), "-o", str(obj)])
                    dependencies = shlex.split(
                        dep.read_text().replace("\\\n", " ").split(":", 1)[1]
                    )
                    closure.update(Path(name).resolve() for name in dependencies)
                    objects.append(obj)
                for test_kind, obj, extra in (
                    ("upstream", objects[2], []),
                    ("decode_guard", objects[3], []),
                    ("query_guard", objects[3], ["query"]),
                ):
                    executable = directory / test_kind
                    run(
                        [
                            compiler,
                            *options,
                            *(["-no-pie"] if profile == "sanitizer" else []),
                            str(obj),
                            *(str(path) for path in objects[:2]),
                            "-o",
                            str(executable),
                        ]
                    )
                    observed = run([str(executable), *extra], must_pass=False)
                    evidence["tests"].append(
                        {
                            "source_kind": kind,
                            "profile": profile,
                            "test_kind": test_kind,
                            "executable": identity(executable),
                            "test_sha256": sha(files[2] if test_kind == "upstream" else files[3]),
                            "status": "PASS" if observed["returncode"] == 0 else "FAIL",
                            **observed,
                        }
                    )
                    save()
                    print(kind, profile, test_kind, evidence["tests"][-1]["status"], flush=True)
                evidence["builds"].append(
                    {
                        "source_kind": kind,
                        "profile": profile,
                        "compiler": run([compiler, "--version"])["stdout"].splitlines()[0],
                        "source_translation_units": [identity(path) for path in files[:2]],
                        "compiled_source_closure": [identity(path) for path in sorted(closure)],
                        "objects": [identity(path) for path in objects],
                    }
                )
                save()
        failed = [test for test in evidence["tests"] if test["status"] != "PASS"]
        qualified = not failed
        if args.source_kind == "both":
            qualified = all(
                test["source_kind"] == "original"
                and test["profile"] == "sanitizer"
                and "runtime error:" in test["stderr"]
                and "left shift" in test["stderr"]
                for test in failed
            )
        evidence.update(
            status="PASS" if qualified else "FAIL",
            failed_test_count=len(failed),
            qualification_scope="PUBLIC_API_SOURCE_TESTS_ONLY_NOT_BOUNDED_ABI_OR_FIVE_LAYERS",
        )
        save()
        if not qualified:
            raise RuntimeError("source test failures retained; source is not qualified")
    except Exception as error:
        evidence.update(status="FAIL", error=str(error))
        save()
        raise


if __name__ == "__main__":
    main()
