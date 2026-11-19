#!/usr/bin/env python3
"""Build the selected targets from verified archives; record source-build evidence only.

Run with a fresh output directory. No codec benchmarks or qualification are
performed. Isolation, if desired, must be established by the caller.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.api import check_sources  # noqa: E402
from tsbench.assets import ContractError, digest, relative_parts, require, verify_asset  # noqa: E402


def extract_archive(archive: Path, out: Path) -> None:
    seen = set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            target = out.joinpath(*relative_parts(member.name))
            require(member.name not in seen, f"duplicate archive member: {member.name}")
            seen.add(member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                require(member.isfile(), f"disallowed archive member: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = tar.extractfile(member)
                assert payload is not None
                with payload, target.open("xb") as stream:
                    shutil.copyfileobj(payload, stream)
                target.chmod(0o600 | member.mode & 0o100)


def capture(argv: list[str], logfile: Path, env: dict[str, str]) -> dict:
    print(f"{logfile.parent.name} {logfile.stem}", flush=True)
    start = time.monotonic_ns()
    with logfile.open("xb") as log:
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, env=env, check=False)
        except FileNotFoundError as exc:
            log.write(str(exc).encode("utf-8"))
            rc = None
        else:
            rc = result.returncode
    return {"argv": argv, "returncode": rc, "wall_ns": time.monotonic_ns() - start,
            "log": logfile.name, "log_sha256": digest(logfile)}


def machine_tool_versions(env: dict[str, str]) -> dict:
    rows = {}
    for program in ("cmake", "cc", "c++", "cargo", "rustc"):
        try:
            result = subprocess.run([program, "--version"], env=env, capture_output=True, text=True,
                                    check=False)
            rows[program] = {"returncode": result.returncode, "output": result.stdout.strip()}
        except OSError:
            rows[program] = {"returncode": None, "output": "tool not found"}
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--out", type=Path, required=True, help="new audit output directory")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    try:
        require(1 <= args.jobs <= 32, "jobs outside build audit bounds")
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=False)
        check = check_sources(ROOT)
        targets = {}
        for selection in check["selections"]:
            targets.setdefault(selection["source_id"], set()).add(selection["target"])
        cache = out / "empty-home"
        cache.mkdir()
        env = {"PATH": os.environ["PATH"], "HOME": str(cache), "CARGO_HOME": str(cache / "cargo"),
               "CARGO_NET_OFFLINE": "true", "LC_ALL": "C", "TZ": "UTC"}
        evidence = {"schema": "bmk.release-build-audit/1", "qualification_granted": False,
                    "sources_lock_id": check["sources_lock_id"], "tool_versions": machine_tool_versions(env),
                    "python": {"version": sys.version, "executable": sys.executable, "prefix": sys.prefix},
                    "network_namespace": os.readlink("/proc/self/ns/net"), "projects": []}
        for source_id, source in check["sources"].items():
            archive = verify_asset(ROOT, source["archive"])
            project = out / source_id
            project.mkdir()
            extract_archive(archive, project / "source")
            source_tree = project / "source" / source_id
            build = project / "cmake"
            configure = capture(["cmake", "-S", str(source_tree), "-B", str(build),
                                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                                 "-DFETCHCONTENT_FULLY_DISCONNECTED=ON"], project / "configure.log", env)
            compile = None
            if configure["returncode"] == 0:
                compile = capture(["cmake", "--build", str(build), "--parallel", str(args.jobs),
                                   "--target", *sorted(targets[source_id])], project / "compile.log", env)
            status = "configured_target_built" if compile and compile["returncode"] == 0 else "build_failed"
            products = [{"path": p.relative_to(project).as_posix(), "sha256": digest(p),
                         "bytes": p.stat().st_size} for p in sorted(build.rglob("*")) if p.is_file() and
                        (p.suffix in {".a", ".so"} or p.name in {"compile_commands.json", "link.txt"})]
            evidence["projects"].append({"source_id": source_id, "targets": sorted(targets[source_id]),
                "status": status, "archive": source["archive"], "configure": configure,
                "compile": compile, "products_and_command_logs": products})
            print(f"{source_id}: {status}", flush=True)
        (out / "audit.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
        return int(any(s["status"] != "configured_target_built" for s in evidence["projects"]))
    except (ContractError, OSError, tarfile.TarError) as exc:
        print(f"release build audit rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
