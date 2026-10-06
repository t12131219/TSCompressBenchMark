"""Freeze completed standalone packages without modifying their implementations."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "abba",
    "fabba",
    "influxdb-tsm-adaptive-timestamp",
    "prometheus-xor2-chunk",
    "prometheus-histogram-st",
    "tristan",
    "corad",
    "deepzip",
    "dzip",
    "walloc-1d",
)


def sha(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def main():
    target = ROOT / "adapters/completed_rewrites"
    entries = {}
    for name in PACKAGES:
        source = ROOT / "Compression_Rewrite/ReWrite" / name
        manifest = (source / "PORT_MANIFEST.yaml").read_text()
        if "REWRITE_DONE" not in manifest or "BLOCKED" in manifest:
            raise RuntimeError(f"{name}: not a completed rewrite")
        destination = target / "vendor" / name
        files = []
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            if relative.parts[0] in {"validation", "release", "build", "reproduction"}:
                continue
            if "__pycache__" in relative.parts or ".git" in relative.parts:
                continue
            copied = destination / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            if copied.exists() and sha(copied) != sha(path):
                raise RuntimeError(f"frozen file changed: {copied}")
            if not copied.exists():
                shutil.copy2(path, copied)
            files.append(
                {
                    "path": str(copied.relative_to(ROOT)),
                    "sha256": sha(copied),
                    "original": str(path.relative_to(ROOT)),
                }
            )
        entries[name] = {"files": files, "port_manifest_sha256": sha(source / "PORT_MANIFEST.yaml")}
        provenance_source = ROOT / "Compression_Rewrite/Source" / name / "SOURCE_MANIFEST.yaml"
        if provenance_source.is_file():
            provenance = target / "provenance" / name / "SOURCE_MANIFEST.yaml"
            provenance.parent.mkdir(parents=True, exist_ok=True)
            if provenance.is_file() and sha(provenance) != sha(provenance_source):
                raise RuntimeError(f"frozen provenance drift: {provenance}")
            if not provenance.is_file():
                shutil.copy2(provenance_source, provenance)
            entries[name]["source_manifest"] = {
                "path": str(provenance.relative_to(ROOT)),
                "sha256": sha(provenance),
                "original": str(provenance_source.relative_to(ROOT)),
            }
    document = {"schema_version": "tscb.completed-rewrite-lock.v1", "packages": entries}
    (target / "FROZEN_SOURCES.json").write_text(json.dumps(document, indent=2) + "\n")
    print(json.dumps({name: len(entry["files"]) for name, entry in entries.items()}))


if __name__ == "__main__":
    main()
