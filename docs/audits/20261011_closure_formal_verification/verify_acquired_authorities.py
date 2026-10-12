"""Verify new exact-commit source acquisitions without rewriting prior source evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def file_ref(path):
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main():
    output = HERE / "upstream_authority_r3"
    if output.exists():
        raise FileExistsError("retain previous acquisition verification")
    output.mkdir()
    driver = HERE / "source_closure/audit_sources.py"
    spec = importlib.util.spec_from_file_location("source_audit", driver)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    audit.AUTHORITY_BASE = ROOT / "build/closure-formal-verification-20261011/upstream-authority-r2"
    names = {
        "elf": "386d69348e6c30475761d3519ee0bfe10ed473d3",
        "dipperstein-lzss": "65b6882ff1cc225f9c6fcd947def7b1adb21d578",
        "dipperstein-bitfile": "2e6132f75cbe16842a9ab81af7756ed9ac1cdbe0",
        "dipperstein-optlist": "c921d0f8f7b2fc3d454ba897a3bf04beecb6899a",
    }
    lock = ROOT / "adapters/rewrite_lossless/vendor/elf/UPSTREAM_PROVENANCE.json"
    source = ROOT / "registry/sources/lzss-dipperstein-c.artifact.json"
    original_refs = [file_ref(p) for p in (driver, lock, source)]
    trees = {}
    for name, commit in names.items():
        tree = audit.checked_git_tree(name + "/repository.git", commit)
        fsck = subprocess.run(
            ["git", "-C", tree["repository_path"], "fsck", "--full", "--no-reflogs"],
            capture_output=True,
            text=True,
        )
        tree.update(
            authority_kind="NEW_PUBLIC_HTTPS_EXACT_PIN_GIT_OBJECTS_NO_AUTHOR_SIGNATURE_CLAIM",
            fsck_exit_code=fsck.returncode,
            fsck_stdout=fsck.stdout,
            fsck_stderr=fsck.stderr,
        )
        if fsck.returncode:
            raise ValueError("Git object/tree/commit integrity failed")
        trees[name] = tree
        audit.write_new(output / (name + ".json"), tree)
    authority = {
        name: {row["path"]: row["sha256"] for row in tree["files"] if row["kind"] == "blob"}
        for name, tree in trees.items()
    }
    elf_lock = json.loads(lock.read_text())["source_lock"]
    elf_rows = [
        {
            "path": row["path"],
            "expected_sha256": row["sha256"],
            "authority_sha256": authority["elf"].get(row["path"]),
        }
        for row in elf_lock["files"]
    ]
    vendor = ROOT / "adapters/lzss_dipperstein/vendor/lzss"
    selected = {}
    for path in vendor.rglob("*"):
        if path.is_file():
            relative = path.relative_to(vendor).as_posix()
            name = "dipperstein-bitfile" if relative.startswith("bitfile/") else "dipperstein-lzss"
            upstream_path = (
                relative.removeprefix("bitfile/") if name.endswith("bitfile") else relative
            )
            selected[relative] = authority[name].get(upstream_path)
    missing = [path for path, value in selected.items() if value is None]
    vendor_check = audit.verify_manifest(
        vendor, {k: v for k, v in selected.items() if v is not None}, exact=True
    )
    links = trees["dipperstein-lzss"]["gitlinks"]
    required_bitfile = [row for row in links if row["path"] == "bitfile"]
    submodule_bound = required_bitfile == [
        {
            "path": "bitfile",
            "mode": "160000",
            "kind": "commit",
            "git_object_id": names["dipperstein-bitfile"],
        }
    ]
    all_gitlinks_verified = all(
        row["path"] in {"bitfile", "optlist"}
        and row["git_object_id"] == names["dipperstein-" + row["path"]]
        for row in links
    ) and all(not tree["gitlinks"] for name, tree in trees.items() if name != "dipperstein-lzss")
    stable = original_refs == [file_ref(p) for p in (driver, lock, source)]
    complete = (
        stable
        and submodule_bound
        and all_gitlinks_verified
        and not missing
        and vendor_check["status"] == "PASS"
    )
    complete = complete and all(
        row["expected_sha256"] == row["authority_sha256"] for row in elf_rows
    )
    document = {
        "status": "PASS_EXACT_PIN_SOURCE_AUTHORITIES" if complete else "SOURCE_AUTHORITY_HAS_GAPS",
        "authorities": [
            {
                "name": name,
                "commit": tree["commit"],
                "blobs": tree["file_count"],
                "bytes": tree["bytes"],
                "gitlinks": tree["gitlinks"],
                "symlinks": tree["symlinks"],
                "evidence": file_ref(output / (name + ".json")),
            }
            for name, tree in trees.items()
        ],
        "elf_old_lock_rows": elf_rows,
        "elf_complete_pinned_tree_verified": True,
        "dipperstein_selected_vendor": vendor_check,
        "vendor_paths_missing_in_authority": missing,
        "bitfile_gitlink_exact_commit_verified": submodule_bound,
        "all_source_gitlinks_exact_commits_verified": all_gitlinks_verified,
        "input_references": original_refs,
        "input_references_unchanged": stable,
        "driver": file_ref(Path(__file__)),
        "source_lock_or_old_snapshot_modified": False,
        "codec_executed": False,
        "full_N_G_CAP_granted": False,
        "transitive_external_dependencies_granted": False,
        "claim_boundary": (
            "Exact source trees and selected vendor bytes; no semantic/full dependency parity."
        ),
    }
    audit.write_new(output / "verification.json", document)
    print(
        json.dumps(
            {
                "status": document["status"],
                "elf_files": len(elf_rows),
                "vendor_status": vendor_check["status"],
                "submodule_bound": submodule_bound,
            }
        ),
        flush=True,
    )
    raise SystemExit(0 if complete else 1)


if __name__ == "__main__":
    main()
