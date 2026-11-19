#!/usr/bin/env python3
"""Explicit, offline intake of the frozen Unique first-batch source archives.

The Unique checkout is not consulted by any other command. Published validation
JSON is provenance only; it never grants a benchmark qualification.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.assets import (ContractError, content_id, digest, load_json, local_file,  # noqa: E402
                           relative_parts, require, stream_digest)

FIRST_BATCH = (9, 11, 19, 85, 7, 31, 40, 39, 4, 29, 87, 80)
MANIFEST_SHA = "fff764c13d0ef2a0d33405c621b9fe0be7ce2c91930367e92b19787248e5e4f2"
CSV_SHA = "f5145a6e5848870265068fedc2417cd0f234f39c0ba7e71e3f44908551387a57"


def inspect_archive(path: Path, repository: str, source_manifest: dict) -> dict:
    expected = {}
    for record in source_manifest["files"]:
        name = record["path"]
        require(name not in expected, f"duplicate source manifest entry: {name}")
        expected[name] = record
    seen, files = set(), set()
    licenses, public_headers = [], []
    with tarfile.open(path, "r:gz") as tar:
        for member in tar:
            name = member.name
            parts = relative_parts(name)
            require(parts[0] == repository and name not in seen,
                    f"unexpected or duplicate archive member: {name}")
            seen.add(name)
            require(member.isdir() or member.isfile(), f"disallowed archive member type: {name}")
            if member.isdir():
                continue
            require(name in expected, f"undeclared archive member: {name}")
            payload = tar.extractfile(member)
            assert payload is not None
            with payload:
                require(stream_digest(payload) == expected[name]["sha256"],
                        f"archive member hash mismatch: {name}")
            require(member.mode & 0o777 == expected[name]["mode"] & 0o777,
                    f"archive member permissions mismatch: {name}")
            files.add(name)
            if (parts[1:2] == ("licenses",) or
                parts[-1].upper().startswith(("LICENSE", "LICENCE", "NOTICE", "COPYING", "COPYRIGHT"))):
                licenses.append(name)
            if len(parts) >= 3 and parts[1] == "include" and PurePosixPath(name).suffix in {".h", ".hpp"}:
                public_headers.append(name)
    require(files == expected.keys(), f"incomplete source manifest closure: {repository}")
    require(f"{repository}/CMakeLists.txt" in files, f"missing build entry: {repository}")
    return {"files": len(files), "license_members": sorted(licenses),
            "public_headers": sorted(public_headers),
            "build_entry": f"{repository}/CMakeLists.txt"}


def collect(unique: Path):
    selection_path = local_file(unique, "selected_compression_mine_fix_2.csv")
    manifest_path = local_file(unique, "SELECTION_MANIFEST.json")
    require(digest(selection_path) == CSV_SHA, "Unique CSV differs from frozen baseline")
    require(digest(manifest_path) == MANIFEST_SHA, "Unique manifest differs from frozen baseline")
    manifest = load_json(manifest_path)
    require(manifest["algorithm_count"] == 82 and manifest["repository_count"] == 29 and
            manifest["selection_sha256"] == CSV_SHA, "inconsistent frozen manifest")
    with selection_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    selected = {}
    for repo in manifest["repositories"]:
        for entry in repo["selections"]:
            number = int(entry["id"])
            require(number not in selected, f"duplicate selection {number}")
            selected[number] = repo, entry
    csv_rows = {int(row[0]): row for row in rows[1:] if row and row[0].isdigit() and any(row[1:4])}
    require(selected.keys() == csv_rows.keys(), "CSV/manifest selection coverage differs")
    sources, selections, copies = {}, [], {
        "catalog/selections/unique-v1.csv": selection_path,
        "catalog/selections/unique-v1.manifest.json": manifest_path,
    }
    for number in FIRST_BATCH:
        repo, entry = selected[number]
        name = repo["repository"]
        require(len(relative_parts(name)) == 1, f"invalid source ID: {name}")
        release = f"fix_Release/{name}/unique-v1"
        require(repo["release"] == release, f"unexpected release: {name}")
        row = csv_rows[number]
        require((row[1], row[3]) == (entry["algorithm"], entry["selection"]), f"selection mismatch: {number}")
        if name not in sources:
            archive = local_file(unique, repo["archive"])
            source_manifest_path = local_file(unique, repo["source_manifest"])
            validation_path = local_file(unique, release + "/validation.json")
            source_manifest = load_json(source_manifest_path)
            validation = load_json(validation_path)
            require(repo["archive"].startswith(release + "/") and
                    repo["source_manifest"] == release + "/source-manifest.json" and
                    source_manifest["archive"] == archive.name and
                    digest(archive) == repo["archive_sha256"] == source_manifest["sha256"] == validation["archive_sha256"],
                    f"release/archive evidence differs: {name}")
            archive_info = inspect_archive(archive, name, source_manifest)
            local_archive = f"third_party/archives/{archive.name}"
            evidence_dir = f"third_party/provenance/{name}"
            local_manifest = f"{evidence_dir}/source-manifest.json"
            local_validation = f"{evidence_dir}/unique-validation.json"
            copies.update({local_archive: archive, local_manifest: source_manifest_path,
                           local_validation: validation_path})
            sources[name] = {
                "origin_release": release,
                "archive": {"path": local_archive, "sha256": repo["archive_sha256"]},
                "source_manifest": {"path": local_manifest, "sha256": digest(source_manifest_path)},
                "historical_validation": {"path": local_validation, "sha256": digest(validation_path)},
                "selection_manifest_file_count": repo["file_count"],
                "selection_manifest_count_matches": repo["file_count"] == archive_info["files"],
                **archive_info,
            }
        field_hash = content_id(row[3])
        selections.append({"number": number, "algorithm": entry["algorithm"], "source_id": name,
                           "target": entry["target"], "selection_note": row[3],
                           "selection_field_sha256": field_hash,
                           "selection_id": content_id({"number": number, "csv_sha256": CSV_SHA,
                                                       "selection_field_sha256": field_hash})})
    require(len(sources) == 11, "unexpected first-batch source count")
    lock = {"schema": "bmk.sources/1", "source_family": "Unique_Selected_Compression_Rewrite",
            "release": "unique-v1", "source_evidence_level": "archive_verified_only",
            "selection_csv": {"path": "catalog/selections/unique-v1.csv", "sha256": CSV_SHA},
            "selection_manifest": {"path": "catalog/selections/unique-v1.manifest.json", "sha256": MANIFEST_SHA},
            "selections": selections, "sources": sources}
    return lock, copies


def publish(lock: dict, copies: dict[str, Path]) -> None:
    """Preflight conflicts, stage copies, and publish the lock last."""
    lock_path = "third_party/sources.lock.json"
    references = [lock["selection_csv"], lock["selection_manifest"]]
    for source in lock["sources"].values():
        references.extend(source[key] for key in ("archive", "source_manifest", "historical_validation"))
    hashes = {entry["path"]: entry["sha256"] for entry in references}
    require(hashes.keys() == copies.keys(), "copy set differs from frozen asset manifest")
    for name in copies:
        if (ROOT / name).exists() or (ROOT / name).is_symlink():
            require(digest(local_file(ROOT, name)) == hashes[name], f"refusing to overwrite {name}")
    if (ROOT / lock_path).exists() or (ROOT / lock_path).is_symlink():
        require(load_json(local_file(ROOT, lock_path)) == lock, f"refusing to overwrite {lock_path}")
    with tempfile.TemporaryDirectory(prefix=".import-unique-", dir=ROOT) as stage:
        staging = Path(stage)
        for name, source in copies.items():
            dest = staging / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            require(digest(dest) == hashes[name], f"source changed during copy: {name}")
        (staging / lock_path).write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name in [*copies, lock_path]:
            dest = ROOT / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            require(dest.parent.resolve().is_relative_to(ROOT), f"import destination escaped project: {name}")
            if not dest.exists():
                # Same-filesystem hard link publishes the finished file, without replacing an existing one.
                dest.hardlink_to(staging / name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-unique", required=True, type=Path)
    args = parser.parse_args()
    try:
        lock, copies = collect(args.from_unique)
        publish(lock, copies)
    except (ContractError, OSError, tarfile.TarError) as exc:
        print(f"source import rejected: {exc}", file=sys.stderr)
        return 2
    print(f"Imported {len(lock['selections'])} selections from {len(lock['sources'])} verified archives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
