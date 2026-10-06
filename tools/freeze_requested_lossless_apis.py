"Freeze accepted standalone APIs into separate Benchmark adapter snapshots."

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.ids import stable_id

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "chimp": (1, "chimp"),
    "chimp128": (2, "chimp"),
    "elf-plus": (3, "elf-plus"),
    "self-star": (4, "self-star"),
    "prometheus-xor-chunk": (5, "prometheus-xor-chunk"),
    "elf": (6, "elf"),
    "elf-star": (7, "elf-star"),
}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dump(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def main():
    base = ROOT / "adapters/rewrite_lossless"
    lock = {"schema_version": 1, "algorithms": {}}
    done = set()
    for name, (kind, pkg) in PACKAGES.items():
        package = ROOT / "Compression_Rewrite/ReWrite" / pkg
        dest = base / "vendor" / pkg
        source = ROOT / "Compression_Rewrite/Source" / pkg
        if pkg not in done:
            dest.mkdir(parents=True, exist_ok=True)
            for folder in ["include", "src", "LICENSES"]:
                shutil.copytree(package / folder, dest / folder, dirs_exist_ok=True)
            shutil.copy2(package / "contract.md", dest / "contract.md")
            if (dest / "PORT_MANIFEST.yaml").exists():
                (dest / "PORT_MANIFEST.yaml").unlink()
            source_lock = source / (
                "ORIGINAL_API_CLOSURE.json"
                if pkg == "prometheus-xor-chunk"
                else "SOURCE_FILES.json"
            )
            qualification = json.loads((package / "validation/current/report.json").read_text())
            assert qualification["status"] == "PASS"
            upstream_lock = json.loads(source_lock.read_text())
            license = (
                "Apache-2.0"
                if pkg == "chimp"
                else "Apache-2.0 AND BSD-3-Clause"
                if pkg == "prometheus-xor-chunk"
                else "NOASSERTION"
            )
            origin = {
                "package": pkg,
                "standalone_api_version": 1,
                "standalone_origin": str(package.relative_to(ROOT)),
                "source_lock": upstream_lock,
                "source_lock_sha256": sha(source_lock),
                "standalone_port_manifest_sha256": sha(package / "PORT_MANIFEST.yaml"),
                "standalone_sbom_sha256": sha(package / "SBOM.json"),
                "current_qualification": {
                    "status": "PASS",
                    "report_sha256": sha(package / "validation/current/report.json"),
                    "declared_platforms": qualification["declared_platforms"],
                    "security_scope": qualification["security_scope"],
                    "reproducibility": qualification["reproducibility"],
                    "artifacts": qualification["artifacts"],
                },
                "license": {
                    "spdx": license,
                    "local_workflow_only": license == "NOASSERTION",
                    "decision_sha256": sha(ROOT / "Compression_Rewrite/USER_DECISIONS.md"),
                    "external_publication_authorized": False,
                },
            }
            dump(dest / "UPSTREAM_PROVENANCE.json", origin)
            if license == "NOASSERTION":
                shutil.copy2(
                    ROOT / "Compression_Rewrite/USER_DECISIONS.md",
                    dest / "LOCAL_WORKFLOW_DECISIONS.md",
                )
            (dest / "README.md").write_text(
                "# Frozen "
                + pkg
                + (
                    " standalone API\n\nExact include/src snapshot of the independe"
                    "ntly qualified rewrite. UPSTREAM_PROVENANCE.json records sou"
                    "rce closure, current qualification and originating standalon"
                    "e package. The Benchmark wrapper is authored separately in ."
                    "./../native. Changes require explicit refreezing and qualifi"
                    "cation.\n\n"
                )
                + (
                    (
                        "NOASSERTION is retained. User permits local audit/run/rewrit"
                        "e only; no external publication.\n"
                    )
                    if license == "NOASSERTION"
                    else "Original license terms and notices are retained.\n"
                )
            )
            done.add(pkg)
        files = [
            {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
            for p in sorted(dest.rglob("*"))
            if p.is_file()
        ]
        units = [str(p.relative_to(dest)) for p in sorted((dest / "src").rglob("*.cpp"))]
        entry = {"kind": kind, "package": pkg, "translation_units": units, "files": files}
        lock["algorithms"][name] = entry
        source_doc = json.loads(
            (ROOT / "registry/sources" / (name + "-rewrite.artifact.json")).read_text()
        )
        source_doc["identity"]["api_files"] = files
        source_doc["build"]["translation_units"] = units
        source_doc["license"]["status"] = (
            "RUN_ALLOWED"
            if pkg in ["chimp", "prometheus-xor-chunk"]
            else "REDISTRIBUTION_RESTRICTED"
        )
        source_doc["license"]["redistribution"] = (
            "ORIGINAL_LICENSE_TERMS_APPLY"
            if pkg in ["chimp", "prometheus-xor-chunk"]
            else (
                "NO_EXTERNAL_PUBLICATION; user-authorized local run/rewrite; unknown upstream grant"
            )
        )
        source_doc["license"]["files"] = [
            f["path"]
            for f in files
            if "/LICENSES/" in f["path"] or f["path"].endswith("LOCAL_WORKFLOW_DECISIONS.md")
        ]
        dump(ROOT / "registry/sources" / (name + "-rewrite.artifact.json"), source_doc)
        doc = json.loads((ROOT / "registry/codecs" / (name + ".json")).read_text())
        doc["identity"]["source_artifact_id"] = stable_id("source-artifact", source_doc["identity"])
        dump(ROOT / "registry/codecs" / (name + ".json"), doc)
    dump(base / "FROZEN_APIS.json", lock)
    # Refresh alias identities before loading the registry, which rejects stale aliases.
    target = json.loads((ROOT / "registry/codecs/prometheus-xor-chunk.json").read_text())
    for name in ["gorilla", "delta-of-delta", "second-order-difference"]:
        dump(
            ROOT / "registry/codecs/aliases" / (name + ".json"),
            {
                "schema_version": "tscb.codec-alias.v2",
                "key": name,
                "canonical_key": target["key"],
                "canonical_algorithm_id": stable_id("algorithm", target),
                "source_artifact_id": target["identity"]["source_artifact_id"],
                "mapping_kind": "SPREADSHEET_SOURCE_MAPPING_NOT_NEW_CODEC",
                "evidence": [
                    (
                        "Compression_Rewrite_Algorithm_List_v1.0.xlsx, SHA256 961ae06"
                        "a62a45abf68b6947e396db7553b2251334131e21914599f52455ed243: r"
                        "equested Gorilla and Delta-of-Delta rows select Prometheus t"
                        "imestamp/value joint chunk source."
                    ),
                    (
                        "Frozen Prometheus commit 8374d30cb3fe705773bbac72d7015eba174"
                        "80557: xorAppender.Append uses timestamp second differences "
                        "and value XOR in one stream."
                    ),
                    (
                        "Standalone original-public-api/report.json compares unmodifi"
                        "ed NewXORChunk / Appender / FromData / Iterator APIs with al"
                        "l real rows and columns."
                    ),
                ],
                "limitations": [
                    (
                        "Measures complete paired int64 timestamp/binary64 value chun"
                        "ks on SYSTEM/S0; it does not isolate a timestamp-only or val"
                        "ue-only bitstream."
                    ),
                    (
                        "All three aliases share the same AlgorithmID and canonical c"
                        "onfigurations and do not add ranked algorithms."
                    ),
                    (
                        "Standalone compressed bytes remain opaque shared T/V bytes; "
                        "wrapper overhead is accounted exactly."
                    ),
                ],
            },
        )
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    print("frozen", len(lock["algorithms"]), "canonical registry codecs", len(registry))


if __name__ == "__main__":
    main()
