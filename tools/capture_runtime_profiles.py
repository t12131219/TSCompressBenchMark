#!/usr/bin/env python3
"""Capture actual production ELF mappings without changing build records."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.adapters.runtime_evidence import (  # noqa: E402
    capture_runtime_profile,
    verified_runtime_dependencies,
)
from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.ids import stable_id  # noqa: E402


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def registry(root: Path = ROOT) -> CodecRegistry:
    return CodecRegistry(root / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--capture", help=argparse.SUPPRESS)
    parser.add_argument("--validate", help=argparse.SUPPRESS)
    args = parser.parse_args()
    # The real factory eagerly imports NumPy and adapter support modules. Match
    # that production environment before capture or replay in a fresh child.
    import tscompbench.adapters.factory  # noqa: F401

    output = args.output_directory.resolve()
    if not output.is_relative_to(ROOT):
        raise SystemExit("output directory must be within the project")
    current = registry()
    if args.capture:
        manifest = current.get(args.capture)
        artifact = ROOT / manifest.document["adapter"]["artifact_path"]
        profile = capture_runtime_profile(ROOT, artifact, capture_driver=Path(__file__).resolve())
        write(output / "profiles" / (manifest.key + ".json"), profile)
        print(json.dumps({"codec": manifest.key, "status": "ACTUAL_LOAD_CAPTURE_PASS"}))
        return
    if args.validate:
        manifest = current.get(args.validate)
        artifact = ROOT / manifest.document["adapter"]["artifact_path"]
        adapter = copy.deepcopy(manifest.document["adapter"])
        profile_path = output / "profiles" / (manifest.key + ".json")
        adapter["runtime_profile"] = {
            "path": str(profile_path.relative_to(ROOT)),
            "sha256": digest(profile_path),
        }
        verified_runtime_dependencies(ROOT, artifact, adapter)
        import ctypes

        library = ctypes.CDLL(str(artifact))
        paths = verified_runtime_dependencies(ROOT, artifact, adapter, loaded=True)
        del library
        print(
            json.dumps(
                {
                    "codec": manifest.key,
                    "status": "FRESH_PROCESS_PRE_POST_LOAD_PASS",
                    "support_count": len(paths),
                }
            )
        )
        return
    output.mkdir(parents=True, exist_ok=False)
    manifests = [
        current.get(key)
        for key in current
        if current.get(key).document["identity"]["family"] != "HARNESS_ORACLE"
    ]
    before = {manifest.key: copy.deepcopy(manifest.document) for manifest in manifests}
    candidates = {}
    observations = []
    for manifest in manifests:
        for mode in ("--capture", "--validate"):
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--output-directory",
                str(output),
                mode,
                manifest.key,
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=120,
            )
            write(
                output
                / "logs"
                / (manifest.key + ("-capture.json" if mode == "--capture" else "-validate.json")),
                {
                    "command": command,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
            if result.returncode:
                raise SystemExit(f"runtime {mode} failed for {manifest.key}: {result.stderr}")
            observations.append(json.loads(result.stdout))
        profile_path = output / "profiles" / (manifest.key + ".json")
        candidate = copy.deepcopy(manifest.document)
        candidate["adapter"]["runtime_profile"] = {
            "path": str(profile_path.relative_to(ROOT)),
            "sha256": digest(profile_path),
        }
        candidates[manifest.key] = candidate
        write(output / "before/registry/codecs" / (manifest.key + ".json"), before[manifest.key])
        write(output / "candidate/registry/codecs" / (manifest.key + ".json"), candidate)
    # Validate a complete candidate registry, including unchanged harness codecs
    # and aliases. Only the newly captured runtime field is added to each codec.
    for path in (ROOT / "registry/codecs").rglob("*.json"):
        relative = path.relative_to(ROOT / "registry/codecs")
        destination = output / "candidate/registry/codecs" / relative
        if not destination.exists():
            value = json.loads(path.read_text())
            if relative.parts[0] == "aliases" and value["canonical_key"] in candidates:
                write(output / "before/registry/codecs" / relative, value)
                value["canonical_algorithm_id"] = stable_id(
                    "algorithm", candidates[value["canonical_key"]]
                )
            write(destination, value)
    proposed = registry(output / "candidate")
    if args.register:
        # Refuse a concurrent codec refresh instead of overwriting its fields.
        for key, document in before.items():
            if json.loads((ROOT / "registry/codecs" / (key + ".json")).read_text()) != document:
                raise SystemExit(f"concurrent registration changed {key}; staged evidence retained")
        for key, document in candidates.items():
            path = ROOT / "registry/codecs" / (key + ".json")
            temporary = path.with_suffix(".runtime-profile.tmp")
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(path)
        for path in (output / "candidate/registry/codecs/aliases").glob("*.json"):
            value = json.loads(path.read_text())
            target = ROOT / "registry/codecs/aliases" / path.name
            target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    receipt = {
        "status": "REGISTERED" if args.register else "CANDIDATE_VERIFIED",
        "scope": "ACTUAL_ELF_RUNTIME_SELECTION_ONLY_NOT_FULL_N1_OR_CODEC_PARITY",
        "profiles": len(candidates),
        "fresh_process_observations": observations,
        "identities": [
            {
                "codec": key,
                "previous_algorithm_id": current.get(key).algorithm_id,
                "current_algorithm_id": proposed.get(key).algorithm_id,
                "source_artifact_id_unchanged": current.get(key).source_artifact_id
                == proposed.get(key).source_artifact_id,
                "runtime_profile": value["adapter"]["runtime_profile"],
            }
            for key, value in candidates.items()
        ],
        "driver": {
            "path": str(Path(__file__).resolve().relative_to(ROOT)),
            "sha256": digest(Path(__file__)),
        },
    }
    write(output / "registration.json", receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "profiles": receipt["profiles"],
                "receipt": str(output / "registration.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
