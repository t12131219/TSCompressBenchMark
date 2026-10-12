"""Independent read-only review of acquired Git source authorities, without codecs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = ROOT / "docs/audits/20261011_closure_formal_verification"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        input=data, capture_output=True,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0"},
    )
    require(result.returncode == 0, "Git verification failed: " + result.stderr.decode(errors="replace"))
    return result.stdout


def inspect(repo: Path, commit: str, expected: dict) -> tuple[dict, dict[str, bytes]]:
    require(git(repo, "rev-parse", commit + "^{commit}").decode().strip() == commit,
            "commit pin mismatch")
    root_tree = git(repo, "rev-parse", commit + "^{tree}").decode().strip()
    rows = []
    for raw in git(repo, "ls-tree", "-rtz", commit).split(b"\0"):
        if raw:
            meta, path = raw.split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            rows.append({"path": path.decode(), "mode": mode, "kind": kind, "git_object_id": oid})
    objects = {commit: "commit", root_tree: "tree"}
    objects.update({row["git_object_id"]: row["kind"] for row in rows if row["kind"] != "commit"})
    raw_objects = git(repo, "cat-file", "--batch", data=("\n".join(objects) + "\n").encode())
    position, contents = 0, {}
    for oid, kind in objects.items():
        newline = raw_objects.index(b"\n", position)
        header_oid, header_kind, raw_size = raw_objects[position:newline].decode().split()
        size = int(raw_size)
        body = raw_objects[newline + 1:newline + 1 + size]
        require(header_oid == oid and header_kind == kind and len(body) == size,
                "Git batch object identity mismatch")
        require(raw_objects[newline + 1 + size:newline + 2 + size] == b"\n", "truncated object")
        algorithm = hashlib.sha1 if len(oid) == 40 else hashlib.sha256
        require(algorithm(kind.encode() + b" " + str(size).encode() + b"\0" + body).hexdigest() == oid,
                "Git object hash mismatch")
        contents[oid] = body
        position = newline + 2 + size
    require(position == len(raw_objects), "unexpected trailing Git batch data")
    blob_rows, blob_contents = [], {}
    for row in rows:
        if row["kind"] == "blob":
            body = contents[row["git_object_id"]]
            blob_contents[row["path"]] = body
            blob_rows.append({**row, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                              "object_integrity": "PASS"})
    links = [row for row in rows if row["kind"] == "commit"]
    non_tree = sorted(blob_rows + links, key=lambda row: row["path"])
    require(non_tree == sorted(expected["files"], key=lambda row: row["path"]),
            "independent pinned inventory differs from acquired evidence")
    require(root_tree == expected["root_tree_id"], "root tree differs from evidence")
    require(commit == expected["commit"], "evidence commit differs from independent pin")
    symlinks = [row["path"] for row in rows if row["mode"] == "120000"]
    require(not symlinks, "resolved symlink closure is outside this review")
    fsck = git(repo, "fsck", "--full", "--no-reflogs", "--no-dangling")
    summary = {
        "repository": str(repo), "commit": commit, "root_tree_id": root_tree,
        "objects_rehashed_by_kind": dict(Counter(objects.values())),
        "blobs": len(blob_rows), "bytes": sum(row["bytes"] for row in blob_rows),
        "exact_inventory_matches_report": True, "symlinks": symlinks, "gitlinks": links,
        "git_fsck_exit_code": 0, "git_fsck_stdout": fsck.decode(errors="replace"),
        "status": "PASS",
    }
    require(summary["blobs"] == expected["file_count"] and summary["bytes"] == expected["bytes"],
            "declared blob denominator mismatch")
    return summary, blob_contents


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "retain previous review evidence")
    verification_path = AUDIT / "upstream_authority_r3/verification.json"
    verification = json.loads(verification_path.read_text())
    lock_path = ROOT / "adapters/rewrite_lossless/vendor/elf/UPSTREAM_PROVENANCE.json"
    source_path = ROOT / "registry/sources/lzss-dipperstein-c.artifact.json"
    lock = json.loads(lock_path.read_text())["source_lock"]
    identity = json.loads(source_path.read_text())["identity"]
    evidence_paths = [ROOT / row["evidence"]["path"] for row in verification["authorities"]]
    references = [verification_path, lock_path, source_path, Path(__file__).resolve()]
    references += evidence_paths + [ROOT / verification["driver"]["path"]]
    references += [ROOT / row["path"] for row in verification["input_references"]]
    references += [AUDIT / "source_closure/final_index.json", AUDIT / "formal_static_review/final_index-r3.json"]
    before = [ref(path) for path in references]
    for row in verification["authorities"]:
        require(sha(ROOT / row["evidence"]["path"]) == row["evidence"]["sha256"], "evidence SHA mismatch")
    for row in verification["input_references"] + [verification["driver"]]:
        require(sha(ROOT / row["path"]) == row["sha256"], "input or driver SHA mismatch")
    base = ROOT / "build/closure-formal-verification-20261011/upstream-authority-r2"
    pins = {"elf": lock["commit"], "dipperstein-lzss": identity["commit"],
            "dipperstein-bitfile": identity["dependency"]["commit"]}
    summaries, blobs = {}, {}
    for name in ("elf", "dipperstein-lzss", "dipperstein-bitfile", "dipperstein-optlist"):
        if name == "dipperstein-optlist":
            link = next(row for row in summaries["dipperstein-lzss"]["gitlinks"] if row["path"] == "optlist")
            pins[name] = link["git_object_id"]
        expected = json.loads((AUDIT / "upstream_authority_r3" / (name + ".json")).read_text())
        summaries[name], blobs[name] = inspect(base / name / "repository.git", pins[name], expected)
    links = summaries["dipperstein-lzss"]["gitlinks"]
    require({row["path"]: row["git_object_id"] for row in links} ==
            {"bitfile": pins["dipperstein-bitfile"], "optlist": pins["dipperstein-optlist"]},
            "root source submodule pin set mismatch")
    require(all(not value["gitlinks"] for name, value in summaries.items() if name != "dipperstein-lzss"),
            "unreviewed recursive source gitlink")
    require(len(lock["files"]) == 20 and len({row["path"] for row in lock["files"]}) == 20,
            "Elf original selected lock denominator mismatch")
    require(all(hashlib.sha256(blobs["elf"][row["path"]]).hexdigest() == row["sha256"]
                for row in lock["files"]), "Elf original selected lock byte mismatch")
    vendor = ROOT / "adapters/lzss_dipperstein/vendor/lzss"
    vendor_files = []
    registered_digest = hashlib.sha256()
    for path in sorted(vendor.rglob("*")):
        require(not path.is_symlink(), "vendor symlink is outside declared selected closure")
        if not path.is_file():
            continue
        require("__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"},
                "unexpected cache file in selected source closure")
        relative, data = path.relative_to(vendor).as_posix(), path.read_bytes()
        authority_name = "dipperstein-bitfile" if relative.startswith("bitfile/") else "dipperstein-lzss"
        authority_path = relative.removeprefix("bitfile/") if authority_name.endswith("bitfile") else relative
        require(data == blobs[authority_name].get(authority_path), "selected vendor byte differs from pinned authority")
        registered_digest.update(relative.encode() + b"\0" + data)
        vendor_files.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest()})
    require(len(vendor_files) == identity["source_closure_file_count"] == 12, "registered vendor count mismatch")
    require(registered_digest.hexdigest() == identity["source_closure_sha256"], "existing registered selected digest mismatch")
    after = [ref(path) for path in references]
    require(before == after, "reviewed inputs or old indexes changed during review")
    report = {
        "schema_version": "tscb.independent-acquired-authority-review.v1",
        "status": "PASS_EXACT_PIN_SOURCE_AUTHORITY_GAPS_RESOLVED",
        "independent_driver": ref(Path(__file__).resolve()),
        "references": before, "references_unchanged": True,
        "authorities": summaries, "all_recursive_source_gitlinks_exact_commits_verified": True,
        "elf_original_selected_lock_count": 20, "elf_original_selected_lock_bytes_match": True,
        "dipperstein_registered_selected_digest": {
            "status": "PASS", "registered_sha256": identity["source_closure_sha256"],
            "observed_sha256": registered_digest.hexdigest(), "file_count": len(vendor_files),
            "protocol": "RELATIVE_PATH_NUL_FILE_BYTES_V1_PYTHON_PATH_COMPONENT_ORDER",
            "files": vendor_files,
        },
        "acquisition_driver_review": {
            "actual_vendor_path_set_is_enumerated_from_observed_vendor": True,
            "selected_byte_expectations_come_from_independent_pinned_git": True,
            "set_completeness_requires_registered_digest_or_explicit_external_manifest": True,
            "independent_review_checked_original_registered_digest_and_denominator": True,
        },
        "missing_old_elf_tree_gap_resolved": True,
        "missing_dipperstein_independent_source_authority_gap_resolved": True,
        "old_source_and_formal_static_indexes_not_modified": True,
        "codec_loaded": False, "production_modules_imported": False,
        "build_or_performance_executed": False, "network_used_by_review": False,
        "upstream_author_signature_verified": False,
        "external_dependency_toolchain_closure_granted": False,
        "semantic_differential_parity_granted": False,
        "full_N_G_CAP_or_FORMAL_granted": False,
        "claim_boundary": "Full pinned tracked main/submodule source trees and registered selected vendor bytes only.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "blobs": sum(s["blobs"] for s in summaries.values()),
                      "bytes": sum(s["bytes"] for s in summaries.values()),
                      "authorities": len(summaries), "selected_vendor_count": len(vendor_files)}))


if __name__ == "__main__":
    main()
