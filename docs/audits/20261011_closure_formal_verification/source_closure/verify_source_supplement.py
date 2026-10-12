"""Verify recorded hash protocols, retained source locks and real-copy negatives.

No codec is loaded, executed or rebuilt. All expected digests remain the existing
recorded pins; mutations affect only temporary copies of the six-file Chimp source.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from audit_sources import ROOT, digest, ref, verify_manifest, write_new


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recovered-source-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("preserve existing evidence")
    if args.recovered_source_dir.exists():
        raise FileExistsError("preserve existing recovered sources")
    args.recovered_source_dir.mkdir(parents=True)
    parent = json.loads(args.source_report.read_text())
    if not parent["input_snapshot_unchanged"]:
        raise RuntimeError("source report snapshot drift")
    for reference in [parent["driver"], *parent["authority_reports"], *parent["inputs"]]:
        if digest(Path(reference["path"]).read_bytes()) != reference["sha256"]:
            raise RuntimeError("source report referenced input drift: " + reference["path"])
    source_rows = {x["codec_key"]: x for x in parent["rows"]}
    lock_path = ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json"
    lock = json.loads(lock_path.read_text())["algorithms"]["chimp"]["files"]
    source_root = ROOT / "adapters/rewrite_lossless/vendor/chimp"
    expected = {Path(x["path"]).relative_to(source_root.relative_to(ROOT)).as_posix(): x["sha256"] for x in lock}
    mutation_results = []
    with tempfile.TemporaryDirectory(prefix="tscb-real-source-negatives-") as directory:
        for name in ("BASELINE", "BYTE_MUTATION", "REMOVE", "ADD", "PATH_ESCAPE", "SYMLINK"):
            temporary = Path(directory) / name
            temporary.mkdir()
            for path in expected:
                target = temporary / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_root / path, target)
            pins = dict(expected)
            if name == "BYTE_MUTATION":
                target = temporary / "src/codec.cpp"
                target.write_bytes(target.read_bytes() + b"\n// audit byte mutation\n")
            elif name == "REMOVE":
                (temporary / "include/chimp.hpp").unlink()
            elif name == "ADD":
                (temporary / "src/undeclared.cpp").write_bytes(b"int undeclared = 1;\n")
            elif name == "PATH_ESCAPE":
                pins["../outside.cpp"] = digest(b"outside")
            elif name == "SYMLINK":
                (temporary / "include/chimp.hpp").unlink()
                (temporary / "include/chimp.hpp").symlink_to("../src/codec.cpp")
            result = verify_manifest(temporary, pins, exact=True)
            accepted = result["status"] == "PASS"
            mutation_results.append({"case": name, "real_source_root": str(source_root),
                                     "expectations_from": ref(lock_path), "verification": result,
                                     "status": "PASS" if accepted == (name == "BASELINE") else "FAIL"})
    protocols = []
    entropy_root = ROOT / "adapters/entropy_fse/vendor"
    entropy_paths = sorted((entropy_root / "lib").iterdir()) + [entropy_root / "LICENSE"]
    listing = b"".join((digest(path.read_bytes()) + "  " + path.relative_to(ROOT).as_posix() + "\n").encode()
                       for path in entropy_paths)
    entropy_sha = digest(listing)
    for key in ("fse", "huff0"):
        source = json.loads(Path(source_rows[key]["source_record"]["path"]).read_text())
        expected_sha = source["identity"]["source_closure_sha256"]
        protocols.append({"codec_key": key, "status": "PASS" if entropy_sha == expected_sha else "FAIL",
                          "declared_sha256": expected_sha, "observed_sha256": entropy_sha,
                          "file_count": len(entropy_paths),
                          "protocol": "SHA256_SHA256SUM_TEXT_SORTED_LIB_PATHS_THEN_LICENSE_WITH_REPOSITORY_RELATIVE_NAMES",
                          "existing_protocol_definition": ref(ROOT / "tests/adapters/test_entropy_fse.py"),
                          "scope": "EXISTING_16_FILE_NATIVE_SELECTED_CLOSURE_NOT_FULL_UPSTREAM_LIB_OR_REPOSITORY"})
    composition = json.loads(Path(source_rows["sprintz-fire-huff0"]["source_record"]["path"]).read_text())
    sprintz_proof = source_rows["sprintz-fire"]["registered_digest_observed"]
    protocols.append({"codec_key": "sprintz-fire-huff0",
                      "status": "PASS" if sprintz_proof == composition["identity"]["sprintz_source_closure_sha256"]
                      and entropy_sha == composition["identity"]["huff0_source_closure_sha256"] else "FAIL",
                      "sprintz_observed_sha256": sprintz_proof, "huff0_observed_sha256": entropy_sha,
                      "existing_protocol_definition": ref(ROOT / "tools/qualify_sprintz_fire_huff0.py"),
                      "scope": "EXISTING_TWO_SELECTED_COMPONENT_CLOSURES_NOT_FULL_UPSTREAM_CAPABILITY"})
    retained = []
    authorities = {Path(x["path"]).stem: json.loads(Path(x["path"]).read_text()) for x in parent["authority_reports"]}
    for key, name in (("fabba", "nla-group_fABBA"), ("deepzip", "mohit1997_DeepZip"), ("dzip", "mohit1997_DZip")):
        source_directory = ROOT / "Compression_Rewrite/Source" / key
        sha_path = source_directory / "SOURCE_FILES.sha256"
        expected = {}
        for line in sha_path.read_text().splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match or match[2] in expected:
                raise RuntimeError("malformed or duplicate existing source checksum")
            expected[match[2]] = match[1]
        git_files = {x["path"]: x["sha256"] for x in authorities[name]["files"] if x["kind"] == "blob"}
        mismatches = [x for x in expected if git_files.get(x) != expected[x]]
        snapshot = verify_manifest(source_directory / "upstream", expected, exact=True)
        recovered_root = args.recovered_source_dir / key
        recovered_root.mkdir()
        for relative, expected_sha in expected.items():
            if relative.startswith("/") or ".." in Path(relative).parts:
                raise RuntimeError("unsafe existing source path")
            authority = authorities[name]
            data = subprocess.run(["git", "--no-optional-locks", "-C", authority["repository_path"],
                                   "show", authority["commit"] + ":" + relative], check=True,
                                  capture_output=True, env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}).stdout
            if digest(data) != expected_sha:
                raise RuntimeError("exported original Git blob mismatches existing source checksum")
            target = recovered_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        recovered = verify_manifest(recovered_root, expected, exact=True)
        retained.append({"codec_key": key, "status": "PASS" if not mismatches and recovered["status"] == "PASS" else "FAIL",
                         "existing_checksum_file": ref(sha_path), "source_snapshot": snapshot,
                         "local_retained_snapshot_complete": snapshot["status"] == "PASS",
                         "local_retained_snapshot_modified": False,
                         "recovered_audit_source_directory": str(recovered_root.resolve()),
                         "recovered_audit_source_snapshot": recovered,
                         "independent_pinned_git_mismatches": mismatches,
                         "source_repository_file_count": len(git_files), "snapshot_file_count": len(expected),
                         "equals_full_primary_upstream_tree_paths": set(expected) == set(git_files),
                         "external_environment_and_dependencies_complete": False,
                         "training_or_source_semantic_parity_granted": False})
    links = []
    for name, authority in authorities.items():
        tracked = {x["path"] for x in authority["files"]}
        for relative in authority["symlinks"]:
            data = subprocess.run(["git", "--no-optional-locks", "-C", authority["repository_path"],
                                   "show", authority["commit"] + ":" + relative], check=True,
                                  capture_output=True, env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}).stdout
            target = data.decode()
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
            target_exists = resolved in tracked or any(x.startswith(resolved + "/") for x in tracked)
            links.append({"authority": name, "path": relative, "target_blob": target,
                          "blob_sha256": digest(data), "resolved_relative_target": resolved,
                          "target_in_tracked_primary_tree": target_exists,
                          "scope": "GIT_SYMLINK_BLOB_VERIFIED; NOT_DEREFERENCED_SOURCE_DEPENDENCY_PROOF"})
    report = {"schema_version": "tscb.source-closure-supplement.v2", "driver": ref(Path(__file__)),
              "source_report": ref(args.source_report), "parent_referenced_inputs_fresh": True,
              "actual_source_mutation_tests": mutation_results, "protocol_proofs": protocols,
              "retained_source_snapshots": retained,
              "authority_gitlink_count": sum(len(x["gitlinks"]) for x in authorities.values()),
              "symlink_blobs": links, "implicit_generated_dependency_closure_granted": False,
              "full_upstream_parity_granted": False, "formal_granted": False,
              "source_oracle_reexecuted": False, "production_files_modified": False}
    write_new(args.output, report)
    print(json.dumps({"actual_source_negatives": [x["status"] for x in mutation_results],
                      "protocol_proofs": [x["status"] for x in protocols],
                      "retained_snapshots": [(x["codec_key"], x["status"]) for x in retained],
                      "gitlinks": report["authority_gitlink_count"], "symlink_count": len(links)}, indent=2))
    raise SystemExit(any(x["status"] != "PASS" for x in [*mutation_results, *protocols, *retained]))


if __name__ == "__main__":
    main()
