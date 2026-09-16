#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TOOL_VERSION = "tscb-source-audit-v1"
SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "target",
    "dist",
}
VENDORED_MARKERS = {
    "third_party",
    "thirdparty",
    "3rdparty",
    "external",
    "extern",
    "vendor",
    "vendors",
}
BUILD_FILENAMES = {
    "CMakeLists.txt",
    "Makefile",
    "meson.build",
    "build.zig",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "setup.py",
    "pyproject.toml",
}
LANGUAGE_BY_SUFFIX = {
    ".c": "C",
    ".h": "C_OR_CPP_HEADER",
    ".cc": "CPP",
    ".cpp": "CPP",
    ".cxx": "CPP",
    ".hpp": "CPP_HEADER",
    ".hh": "CPP_HEADER",
    ".cu": "CUDA",
    ".cuh": "CUDA_HEADER",
    ".py": "PYTHON",
    ".pyx": "CYTHON",
    ".java": "JAVA",
    ".go": "GO",
    ".rs": "RUST",
    ".zig": "ZIG",
    ".m": "MATLAB_OR_OBJC",
    ".scala": "SCALA",
    ".kt": "KOTLIN",
    ".js": "JAVASCRIPT",
    ".ts": "TYPESCRIPT",
    ".sh": "SHELL",
}
LICENSE_PATTERN = re.compile(r"^(licen[cs]e|copying|notice|copyright)(\..*)?$", re.IGNORECASE)
BENCHMARK_PATTERN = re.compile(r"bench|benchmark|perf", re.IGNORECASE)
TEST_PATTERN = re.compile(r"(^|[_.-])test(s|ing)?([_.-]|$)", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def git(path: Path, *arguments: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", "-C", str(path), *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return completed.returncode, (completed.stdout or completed.stderr).strip()


def git_facts(path: Path) -> dict[str, Any]:
    rc, commit = git(path, "rev-parse", "HEAD")
    if rc != 0:
        return {"is_git_repository": False, "probe_error": commit}
    _, status = git(path, "status", "--porcelain=v1", "--untracked-files=all")
    _, shallow = git(path, "rev-parse", "--is-shallow-repository")
    _, remote = git(path, "remote", "get-url", "origin")
    submodule_rc, submodules = git(path, "submodule", "status", "--recursive")
    return {
        "is_git_repository": True,
        "commit": commit,
        "dirty": bool(status),
        "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "status_line_count": 0 if not status else len(status.splitlines()),
        "shallow": shallow == "true",
        "origin": remote if remote else "UNSPECIFIED",
        "submodules": [] if submodule_rc != 0 or not submodules else submodules.splitlines(),
    }


def scan_tree(path: Path) -> dict[str, Any]:
    languages: Counter[str] = Counter()
    total_files = 0
    total_bytes = 0
    vendored_files = 0
    build_entries: list[str] = []
    benchmark_evidence: list[str] = []
    test_evidence: list[str] = []
    license_evidence: list[str] = []
    readme_evidence: list[str] = []
    inventory_digest = hashlib.sha256()

    for current, directories, filenames in os.walk(path, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in SKIP_DIRECTORIES
            and not directory.startswith("cmake-build-")
            and directory != "build"
        )
        for filename in sorted(filenames):
            file_path = current_path / filename
            try:
                stat = file_path.lstat()
            except OSError:
                continue
            relative = file_path.relative_to(path).as_posix()
            total_files += 1
            total_bytes += stat.st_size
            inventory_digest.update(relative.encode("utf-8", errors="surrogateescape"))
            inventory_digest.update(b"\x00")
            inventory_digest.update(str(stat.st_size).encode("ascii"))
            inventory_digest.update(b"\n")
            parts_lower = {part.lower() for part in file_path.relative_to(path).parts[:-1]}
            if parts_lower & VENDORED_MARKERS:
                vendored_files += 1
            language = LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower())
            if language:
                languages[language] += 1
            if filename in BUILD_FILENAMES and len(file_path.relative_to(path).parts) <= 5:
                build_entries.append(relative)
            if LICENSE_PATTERN.match(filename) and len(file_path.relative_to(path).parts) <= 4:
                license_evidence.append(relative)
            if (
                filename.lower().startswith("readme")
                and len(file_path.relative_to(path).parts) <= 3
            ):
                readme_evidence.append(relative)
            evidence_text = relative.lower()
            if BENCHMARK_PATTERN.search(evidence_text):
                benchmark_evidence.append(relative)
            if TEST_PATTERN.search(evidence_text):
                test_evidence.append(relative)

    return {
        "file_count": total_files,
        "byte_count": total_bytes,
        "inventory_path_size_sha256": inventory_digest.hexdigest(),
        "language_file_counts": dict(sorted(languages.items())),
        "vendored_file_count": vendored_files,
        "build_entry_count": len(build_entries),
        "build_entries": build_entries[:100],
        "benchmark_evidence_count": len(benchmark_evidence),
        "benchmark_evidence": benchmark_evidence[:100],
        "test_evidence_count": len(test_evidence),
        "test_evidence": test_evidence[:100],
        "license_evidence": license_evidence[:100],
        "readme_evidence": readme_evidence[:50],
        "evidence_lists_truncated_at": 100,
    }


def source_artifact_id(repo: str, facts: dict[str, Any], tree: dict[str, Any]) -> str:
    identity = {
        "repo": repo,
        "commit": facts.get("commit", "UNAVAILABLE"),
        "dirty": facts.get("dirty", False),
        "status_sha256": facts.get("status_sha256"),
        "inventory_path_size_sha256": tree.get("inventory_path_size_sha256"),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"v2:source-artifact:sha256:{hashlib.sha256(encoded).hexdigest()}"


def audit(source_root: Path) -> dict[str, Any]:
    manifest_path = source_root / "manifest.json"
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repositories: list[dict[str, Any]] = []
    aggregate_languages: Counter[str] = Counter()
    aggregate_files = 0

    for repo, clone in sorted(source_manifest["clone_results"].items()):
        configured_path = clone.get("path")
        if not configured_path:
            repositories.append(
                {
                    "repo": repo,
                    "availability": clone.get("status", "UNAVAILABLE"),
                    "source_artifact_id": None,
                }
            )
            continue
        path = Path(configured_path)
        if not path.is_dir():
            repositories.append(
                {
                    "repo": repo,
                    "availability": "PATH_MISSING",
                    "configured_directory": path.name,
                    "source_artifact_id": None,
                }
            )
            continue
        facts = git_facts(path)
        tree = scan_tree(path)
        aggregate_files += tree["file_count"]
        aggregate_languages.update(tree["language_file_counts"])
        repositories.append(
            {
                "repo": repo,
                "availability": "AVAILABLE",
                "configured_directory": path.name,
                "clone_status": clone.get("status", "UNSPECIFIED"),
                "source_artifact_id": source_artifact_id(repo, facts, tree),
                "git": facts,
                "tree": tree,
            }
        )

    logical_entries = [
        {
            "sheet": entry.get("sheet"),
            "row": entry.get("row"),
            "group": entry.get("group"),
            "name": entry.get("name"),
            "folder": entry.get("folder"),
            "category": entry.get("category"),
            "source_url": entry.get("source_url"),
            "github_repo": entry.get("github_repo"),
        }
        for entry in source_manifest["entries"]
    ]
    available = sum(item["availability"] == "AVAILABLE" for item in repositories)
    clean = sum(
        item["availability"] == "AVAILABLE" and not item["git"].get("dirty", True)
        for item in repositories
    )
    return {
        "schema_version": "tscb.source-catalog.v2",
        "audit_tool_version": TOOL_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_manifest_sha256": sha256_file(manifest_path),
        "source_root_name": source_root.name,
        "policy": {
            "shared_source_tree_mutated": False,
            "generated_and_build_directories_excluded": sorted(SKIP_DIRECTORIES | {"build"}),
            "inventory_hash_scope": (
                "relative-path-and-size; git commit/status are authoritative source lock"
            ),
            "evidence_is_qualification": False,
        },
        "summary": {
            "logical_entry_count": len(logical_entries),
            "repository_entry_count": len(repositories),
            "available_repository_count": available,
            "clean_repository_count": clean,
            "scanned_file_count_excluding_generated_build_dirs": aggregate_files,
            "language_file_counts": dict(sorted(aggregate_languages.items())),
        },
        "repositories": repositories,
        "logical_entries": logical_entries,
    }


def write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary_name = handle.name
            json.dump(
                document, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = audit(args.source_root.resolve())
    write_json_atomic(args.output.resolve(), document)
    print(json.dumps(document["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
