"""Consume local standalone archives and verify their evidence and frozen API closure."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/rewrite_review/release-consumption"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name, label, command):
    result = subprocess.run(
        list(map(str, command)),
        capture_output=True,
        timeout=180,
        env=dict(os.environ, LC_ALL="C", SOURCE_DATE_EPOCH="0"),
    )
    log = OUT / f"{name}-{label}.log"
    log.write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, (name, label, log)
    return {
        "command": list(map(str, command)),
        "exit_code": result.returncode,
        "log": str(log.relative_to(ROOT)),
        "log_sha256": sha(log),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index_path = ROOT / "Compression_Rewrite/Release/requested-lossless-20261006/RELEASE_INDEX.json"
    index = json.loads(index_path.read_text())
    assert index["scope"] == "LOCAL_ONLY" and index["status"] == "REWRITE_DONE"
    cases = []
    for delivery in index["deliveries"]:
        name = delivery["algorithm"]
        archive = ROOT / delivery["archive"]["path"]
        assert sha(archive) == delivery["archive"]["sha256"]
        assert archive.stat().st_size == delivery["archive"]["bytes"]
        with tempfile.TemporaryDirectory(prefix=f"tscb-{name}-release-", dir="/tmp") as tmp:
            checkout = Path(tmp)
            with tarfile.open(archive, "r:gz") as bundle:
                assert all(member.isfile() for member in bundle.getmembers())
                assert not any("adapters/" in member.name for member in bundle.getmembers())
                bundle.extractall(checkout, filter="data")
            package = checkout / "ReWrite" / name
            source = checkout / "Source" / name
            assert sha(package / "PORT_MANIFEST.yaml") == delivery["manifest_sha256"]
            assert sha(package / "SBOM.json") == delivery["sbom_sha256"]
            manifest = yaml.safe_load((package / "PORT_MANIFEST.yaml").read_text())
            assert all(gate["status"] == "PASS" for gate in manifest["gates"].values())
            assert manifest["source"]["source_modified"] is False
            assert (
                sha((package / manifest["source"]["closure_manifest"]).resolve())
                == (manifest["source"]["closure_manifest_sha256"])
            )
            assert (
                sha(checkout / "USER_DECISIONS.md")
                == manifest["license"]["local_workflow_decision_sha256"]
            )
            for evidence in manifest["current_evidence"]:
                assert sha(package / evidence["path"]) == evidence["sha256"]
                assert json.loads((package / evidence["path"]).read_text())["status"] == "PASS"
            sbom = json.loads((package / "SBOM.json").read_text())
            for entry in sbom["files"]:
                assert sha(package / entry["path"]) == entry["sha256"], entry["path"]
            qualification = json.loads((package / "validation/current/report.json").read_text())
            for relative, digest in qualification["source_files"].items():
                assert sha(package / relative) == digest, (name, relative)
            lock = json.loads(
                (
                    source
                    / (
                        "ORIGINAL_API_CLOSURE.json"
                        if name == "prometheus-xor-chunk"
                        else "SOURCE_FILES.json"
                    )
                ).read_text()
            )
            for entry in lock.get("files", lock.get("source_files", [])):
                path = (
                    source / entry["path"]
                    if name == "prometheus-xor-chunk"
                    else (source / "upstream" / entry["path"])
                )
                assert sha(path) == entry["sha256"], (name, path)
            commands = []
            for artifact, digest in delivery["binary_artifacts"].items():
                assert sha(checkout / "bin" / artifact) == digest
                if artifact.endswith("preflight") or artifact == "prometheus_xor_chunk_tests":
                    commands.append(run(name, "binary-" + artifact, [checkout / "bin" / artifact]))
            build = checkout / "build"
            commands.append(
                run(
                    name,
                    "configure",
                    [
                        "cmake",
                        "-S",
                        package,
                        "-B",
                        build,
                        "-DCMAKE_BUILD_TYPE=Release",
                        "-DCMAKE_CXX_COMPILER=c++",
                    ],
                )
            )
            commands.append(run(name, "build", ["cmake", "--build", build, "-j2"]))
            commands.append(
                run(
                    name,
                    "preflight",
                    [
                        "ctest",
                        "--test-dir",
                        build,
                        "--output-on-failure",
                        "-R",
                        "(tests|preflight)$",
                    ],
                )
            )
            rebuilt = {artifact: sha(build / artifact) for artifact in delivery["binary_artifacts"]}
            assert rebuilt == delivery["binary_artifacts"], (name, "rebuild differs")
            cases.append(
                {
                    "algorithm": name,
                    "status": "PASS",
                    "archive_sha256": sha(archive),
                    "source_closure_files": len(lock.get("files", lock.get("source_files", []))),
                    "rebuilt_artifacts": rebuilt,
                    "commands": commands,
                }
            )
            print(name, "archive consumption PASS", flush=True)
    frozen_path = ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json"
    frozen = json.loads(frozen_path.read_text())
    for entry in frozen["algorithms"].values():
        for file in entry["files"]:
            assert sha(ROOT / file["path"]) == file["sha256"]
        origin = json.loads(
            (
                ROOT
                / "adapters/rewrite_lossless/vendor"
                / entry["package"]
                / "UPSTREAM_PROVENANCE.json"
            ).read_text()
        )
        package = ROOT / origin["standalone_origin"]
        assert sha(package / "PORT_MANIFEST.yaml") == origin["standalone_port_manifest_sha256"]
        assert sha(package / "SBOM.json") == origin["standalone_sbom_sha256"]
        for file in entry["files"]:
            path = Path(file["path"])
            relative = path.relative_to(Path("adapters/rewrite_lossless/vendor") / entry["package"])
            if relative.parts[0] in {"include", "src"}:
                assert sha(package / relative) == file["sha256"]
    report = {
        "status": "PASS",
        "scope": "LOCAL_ONLY",
        "archive_consumption": cases,
        "frozen_api_hashes": "PASS",
        "release_index_sha256": sha(index_path),
        "frozen_lock_sha256": sha(frozen_path),
        "driver_sha256": sha(Path(__file__)),
    }
    (ROOT / "docs/requested_lossless_release_consumption.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
