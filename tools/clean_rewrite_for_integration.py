"""Plan and apply source-only cleanup within one explicit, user-scoped directory.

Keep runtime models and build/test inputs. Archive small historical documents
outside that directory; delete only the inventoried, unchanged candidate files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tarfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "Compression_Rewrite"
AUDIT = PROJECT / "docs/rewrite_cleanup/20261006-integration"
PLAN = AUDIT / "cleanup_plan.json"
RESULT = AUDIT / "cleanup_result.json"
CODE = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".cu",
    ".cuh",
    ".py",
    ".go",
    ".java",
    ".rs",
    ".m",
    ".i",
    ".swig",
    ".sh",
    ".cmake",
    ".map",
    ".in",
    ".s",
    ".S",
    ".asm",
    ".f",
    ".f90",
    ".zig",
}
TOP_KEEP = {
    "CMakeLists.txt",
    "README.md",
    "PORT_MANIFEST.yaml",
    "NATIVE_CAPABILITY_MATRIX.yaml",
    "contract.md",
    "contract_v1.md",
    "ALGORITHM_CONTRACT.md",
    "format.md",
    "frame_contract.md",
    "model_schema.json",
    "MODEL_MANIFEST.json",
    "DEPENDENCY_LOCK.json",
    "DEPENDENCY_SUPPLEMENT.json",
    "CPU_DEPENDENCY.json",
    "CPU_DEPENDENCY.patch",
    "DEPENDENCY_PATCHES.json",
    "DEPENDENCY_PORTABILITY.patch",
    "MKLDNN_DEPENDENCIES.json",
    "NATIVE_DEPENDENCIES.json",
    "NOTICE",
    "NOTICE.md",
}
SOURCE_TOP = {
    "SOURCE_MANIFEST.yaml",
    "SOURCE_FILES.json",
    "SOURCE_FILES.sha256",
    "TOOLCHAIN_MANIFEST.yaml",
    "MODEL_MANIFEST.yaml",
    "LICENSE_INVENTORY.json",
    "oracle-requirements.txt",
}
CACHES = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache", "CMakeFiles"}
COPY_ASSETS = {
    "Source/terracodec-tec-tt/models/tec-tt-l2a-lambda20.tctw": (
        "ReWrite/terracodec-tec-tt/models/tec-tt-l2a-lambda20.tctw"
    ),
    "Source/terracodec-tec-tt/models/tec-tt-l1c-lambda20.tctw": (
        "ReWrite/terracodec-tec-tt/models/tec-tt-l1c-lambda20.tctw"
    ),
    "Source/terracodec-tec-tt/models/tec-tt-l2a-lambda20.json": (
        "ReWrite/terracodec-tec-tt/models/tec-tt-l2a-lambda20.json"
    ),
    "Source/terracodec-tec-tt/models/tec-tt-l1c-lambda20.json": (
        "ReWrite/terracodec-tec-tt/models/tec-tt-l1c-lambda20.json"
    ),
    "ReWrite/walloc-1d/validation/source-cpu-v3/stereo_5x.wlm": (
        "ReWrite/walloc-1d/models/stereo_5x.wlm"
    ),
    "ReWrite/walloc-1d/validation/source-cpu-v3/stereo_20x.wlm": (
        "ReWrite/walloc-1d/models/stereo_20x.wlm"
    ),
    "ReWrite/prometheus-histogram-st/validation/public_api_oracle.txt": (
        "ReWrite/prometheus-histogram-st/tests/fixtures/public_api_oracle.txt"
    ),
    "ReWrite/dzip/validation/source-oracle/alphabet-1/bootstrap.dzn": (
        "ReWrite/dzip/tests/fixtures/alphabet-1/bootstrap.dzn"
    ),
    "ReWrite/dzip/validation/source-oracle/alphabet-2/bootstrap.dzn": (
        "ReWrite/dzip/tests/fixtures/alphabet-2/bootstrap.dzn"
    ),
}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory():
    entries = {}
    for directory, dirs, files in os.walk(ROOT, followlinks=False):
        for name in [*files, *(d for d in dirs if (Path(directory) / d).is_symlink())]:
            path = Path(directory) / name
            info = path.lstat()
            assert stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode), path
            entries[str(path.relative_to(ROOT))] = dict(
                bytes=info.st_size,
                blocks=info.st_blocks * 512,
                device=info.st_dev,
                inode=info.st_ino,
                mtime_ns=info.st_mtime_ns,
                symlink=os.readlink(path) if path.is_symlink() else None,
            )
    return entries


def allocated():
    return int(subprocess.check_output(["du", "-s", "-B1", str(ROOT)], text=True).split()[0])


def retained(relative, info):
    path = Path(relative)
    parts = path.parts
    if any(part in CACHES for part in parts):
        return False
    if parts[0] == "ReWrite" and len(parts) >= 3:
        local = parts[2:]
        if len(local) == 1:
            return local[0] in TOP_KEEP or path.suffix == ".patch"
        if local[0] in {"src", "include", "third_party", "LICENSES"}:
            return True
        if local[0] == "tests":
            return path.suffix not in {".log", ".pyc", ".o", ".a", ".so"}
        if local[0] == "tools":
            return path.suffix in {".c", ".cpp", ".cc", ".cu", ".hpp", ".h"}
    if parts[0] == "Source" and len(parts) >= 3:
        local = parts[2:]
        if len(local) == 1:
            return local[0] in SOURCE_TOP
        if local[0] in {"LICENSES", "PATCHES", "reference_licenses"}:
            return True
        if local[0] == "upstream":
            if any(
                p.lower()
                in {"data", "datasets", "trained_models", "checkpoints", "models", "golden"}
                for p in local[1:-1]
            ):
                return False
            return (
                path.suffix in CODE
                or path.name
                in {
                    "CMakeLists.txt",
                    "Makefile",
                    "LICENSE",
                    "LICENCE",
                    "COPYING",
                    "NOTICE",
                    "requirements.txt",
                    "pyproject.toml",
                    "setup.cfg",
                    "go.mod",
                    "go.sum",
                }
                or (
                    path.suffix in {".json", ".yaml", ".yml", ".toml"}
                    and info["bytes"] < 1024 * 1024
                )
            )
    return relative == "USER_DECISIONS.md"


def safe(relative):
    path = ROOT / relative
    assert not Path(relative).is_absolute() and ".." not in Path(relative).parts
    assert path.parent.resolve().is_relative_to(ROOT.resolve()), relative
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    assert ROOT.resolve() == Path(
        "/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite"
    )
    assert not ROOT.is_symlink()
    assert not subprocess.check_output(
        ["git", "ls-files", "--", "Compression_Rewrite"], cwd=PROJECT
    )
    AUDIT.mkdir(parents=True, exist_ok=True)
    if not args.apply:
        assert not PLAN.exists(), "Preserve the previous cleanup plan"
        entries = inventory()
        keep = {
            r: {**i, "sha256": sha(safe(r)) if i["symlink"] is None else None}
            for r, i in entries.items()
            if retained(r, i)
        }
        for r, info in keep.items():
            if info["symlink"] is not None:
                target = safe(r).resolve()
                assert target.is_file() and target.is_relative_to(ROOT)
                assert str(target.relative_to(ROOT)) in keep, f"Retained link loses target: {r}"
        assets = dict(COPY_ASSETS)
        for path in sorted((ROOT / "Source/deepzip/golden/locked").glob("*/*.dzm")):
            if path.stem != "biGRU":
                assets[str(path.relative_to(ROOT))] = f"ReWrite/deepzip/models/{path.name}"
        transferred = []
        for origin, destination in assets.items():
            src, dst = safe(origin), safe(destination)
            assert src.is_file() and not src.is_symlink() and not dst.exists(), origin
            transferred.append(
                dict(
                    source=origin,
                    destination=destination,
                    bytes=src.stat().st_size,
                    sha256=sha(src),
                )
            )
        candidates = {r: i for r, i in entries.items() if r not in keep}
        # Small text evidence and orchestration scripts are recoverable from
        # this metadata archive; bulk arrays/checkpoints/builds are excluded.
        archive = [
            r
            for r, i in entries.items()
            if i["symlink"] is None
            and i["bytes"] <= 4 * 1024 * 1024
            and Path(r).suffix
            in {".md", ".json", ".yaml", ".yml", ".log", ".sha256", ".py", ".go", ".java", ".xlsx"}
            and not any(p in CACHES for p in Path(r).parts)
            and "third_party" not in Path(r).parts
            and "upstream" not in Path(r).parts
        ]
        plan = dict(
            root=str(ROOT),
            generated_at_utc=datetime.now(UTC).isoformat(),
            before_allocated_bytes=allocated(),
            keep=keep,
            delete=candidates,
            transfers=transferred,
            archive_metadata=archive,
            policy=(
                "Keep integration source/build/test/licenses/runtime models; "
                "historical text archived outside root. "
                "Deleted large outputs and packages are not backed up "
                "and cannot be recovered from the metadata archive."
            ),
        )
        PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                dict(
                    status="PLANNED",
                    before_gib=plan["before_allocated_bytes"] / 1024**3,
                    keep_files=len(keep),
                    delete_files=len(candidates),
                    archive_files=len(archive),
                    runtime_and_fixture_bytes=sum(t["bytes"] for t in transferred),
                    categories=dict(Counter("/".join(Path(r).parts[:2]) for r in candidates)),
                )
            )
        )
        return
    assert not RESULT.exists(), "Cleanup has already run"
    plan = json.loads(PLAN.read_text())
    assert plan["root"] == str(ROOT)
    expected = {
        **plan["delete"],
        **{r: {k: v for k, v in i.items() if k != "sha256"} for r, i in plan["keep"].items()},
    }
    assert inventory() == expected, "Files changed since the cleanup plan; do not delete"
    archive_path = AUDIT / "historical_metadata.tar.gz"
    assert not archive_path.exists()
    archive_hashes = {}
    with tarfile.open(archive_path, "w:gz") as archive:
        for relative in plan["archive_metadata"]:
            archive_hashes[relative] = sha(safe(relative))
            archive.add(safe(relative), arcname=relative, recursive=False)
    with tarfile.open(archive_path) as archive:
        for relative, digest in archive_hashes.items():
            assert hashlib.sha256(archive.extractfile(relative).read()).hexdigest() == digest
    for item in plan["transfers"]:
        src, dst = safe(item["source"]), safe(item["destination"])
        assert sha(src) == item["sha256"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Preserve immutable contents via hardlink; never chmod shared assets.
        os.link(src, dst)
        assert sha(dst) == item["sha256"]
    for r, info in plan["keep"].items():
        if info["sha256"]:
            assert sha(safe(r)) == info["sha256"], r
    (AUDIT / "archive_inventory.json").write_text(json.dumps(archive_hashes, indent=2) + "\n")
    for relative, info in plan["delete"].items():
        path = safe(relative)
        current = path.lstat()
        assert (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) == (
            info["device"],
            info["inode"],
            info["bytes"],
            info["mtime_ns"],
        ), relative
        path.unlink()
    for directory, _, _ in os.walk(ROOT, topdown=False, followlinks=False):
        path = Path(directory)
        if path != ROOT and not any(path.iterdir()):
            path.rmdir()
    for relative, info in plan["keep"].items():
        if info["sha256"]:
            assert sha(safe(relative)) == info["sha256"], relative
    for item in plan["transfers"]:
        assert sha(safe(item["destination"])) == item["sha256"]
    after = allocated()
    result = dict(
        status="PASS",
        before_allocated_bytes=plan["before_allocated_bytes"],
        after_allocated_bytes=after,
        root_freed_bytes=plan["before_allocated_bytes"] - after,
        archive=str(archive_path.relative_to(PROJECT)),
        archive_sha256=sha(archive_path),
        archive_allocated_bytes=archive_path.stat().st_blocks * 512,
        deleted_files=len(plan["delete"]),
        kept_files=len(plan["keep"]),
        assets=plan["transfers"],
        retained_hashes_verified=True,
        historical_release_audits_replayable=False,
    )
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
