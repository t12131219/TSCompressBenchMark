#!/usr/bin/env python3
"""Prepare and verify an unmodified source tree for a local plugin build."""
from pathlib import Path
import sys

from probe_release_builds import ROOT, extract_archive
from tsbench.api import check_sources
from tsbench.assets import digest, load_json, require, verify_asset


def prepare(source_id: str, out: Path) -> None:
    source = check_sources(ROOT, source_ids={source_id})["sources"][source_id]
    archive = verify_asset(ROOT, source["archive"])
    manifest = load_json(verify_asset(ROOT, source["source_manifest"]))
    if not out.exists():
        out.mkdir(parents=True, exist_ok=False)
        extract_archive(archive, out)
    require(out.is_dir() and not out.is_symlink(), "expected dedicated source extraction directory")
    entries = sorted(out.rglob("*"))
    require(not any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in entries),
            "disallowed member in build source tree")
    actual = {p.relative_to(out).as_posix(): digest(p) for p in entries if p.is_file()}
    require(actual == {member["path"]: member["sha256"] for member in manifest["files"]},
            "prepared source tree differs from its lock; use a fresh build directory")


if __name__ == "__main__":
    prepare(sys.argv[1], Path(sys.argv[2]))
