"""Read-only current registration and evidence audit; writes only a new audit JSON."""
from __future__ import annotations

import hashlib
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from qualify_v32_active_entries import source_evidence, validate_frozen
from tscompbench.adapters.factory import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry


def digest(path):
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("current_checks.json"))
    args = parser.parse_args()
    scope = json.loads((ROOT / "registry/algorithm_scope.json").read_text())
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    active = set(scope["registered_codecs"])
    entries = []
    for key in registry.keys():
        manifest = registry.get(key)
        if manifest.document["identity"]["family"] == "HARNESS_ORACLE":
            continue
        adapter = manifest.document["adapter"]
        artifact = ROOT / adapter["artifact_path"]
        row = {
            "key": key, "scope": "ACTIVE" if key in active else "RETAINED_OUT_OF_SCOPE",
            "algorithm_id": manifest.algorithm_id,
            "source_artifact_id": manifest.source_artifact_id,
            "factory": adapter["factory"],
            "implementation_class": manifest.implementation_class.value,
            "object_level": manifest.object_level.value,
            "artifact": str(artifact.relative_to(ROOT)),
            "artifact_sha256": digest(artifact),
        }
        try:
            primary, support = adapter_artifacts(ROOT, manifest)
            row["factory_dependencies"] = {"status": "RESOLVED", "support_count": len(support)}
            row["missing_support"] = [str(path) for path in support if not path.is_file()]
            instance = create_adapter(ROOT, manifest)
            row["load"] = {"status": "PASS", "adapter_class": type(instance).__name__}
        except Exception as error:
            row["load"] = {"status": "FAIL", "type": type(error).__name__, "reason": str(error)}
        evidence = source_evidence(ROOT, registry.sources.get(manifest.source_artifact_id))
        row["source_evidence"] = evidence
        profiles = []
        for profile in ("release", "debug", "sanitizer"):
            record_path = artifact.parent.parent / profile / "build-record.json"
            if not record_path.is_file():
                continue
            record = json.loads(record_path.read_text())
            declared_artifact = record.get("artifact", adapter["artifact_path"])
            binary = Path(declared_artifact)
            if not binary.is_absolute():
                binary = ROOT / binary
            files = []
            for field in ("source_files", "source_closure", "binding_sources", "runtime_dependencies",
                          "compiled_source_closure", "objects", "patches", "generated_source_files"):
                for item in record.get(field, []):
                    if not isinstance(item, dict) or "path" not in item or "sha256" not in item:
                        continue
                    path = Path(item["path"])
                    if not path.is_absolute():
                        path = ROOT / path
                    actual = digest(path)
                    files.append({"field": field, "path": item["path"],
                                  "expected": item["sha256"], "actual": actual,
                                  "status": "MATCH" if actual == item["sha256"] else "MISSING" if actual is None else "MISMATCH"})
            expected = record.get("artifact_sha256")
            actual = digest(binary)
            profiles.append({"profile": profile, "record": str(record_path.relative_to(ROOT)),
                             "record_sha256": digest(record_path),
                             "artifact_hash_status": "MATCH" if actual == expected and actual else "MISSING" if actual is None else "MISMATCH",
                             "checked_entry_counts": dict(Counter(item["status"] for item in files)),
                             "issues": [item for item in files if item["status"] != "MATCH"]})
        row["build_profiles"] = profiles
        entries.append(row)
        print(key, row["scope"], row["load"]["status"], evidence["closure_status"], flush=True)
    evidence_root = ROOT / "build/v32-evidence-20261010/current-r2"
    plan = json.loads((evidence_root / "active33/plan.json").read_text())
    try:
        validate_frozen(plan, ROOT)
        frozen = {"status": "PASS", "plan_id": plan["plan_id"], "entries": len(plan["entries"])}
    except Exception as error:
        frozen = {"status": "FAIL", "type": type(error).__name__, "reason": str(error)}
    summary = json.loads((evidence_root / "active33/summary.json").read_text())
    document = {
        "schema_version": "tscb.rewrite-native-current-audit.v1", "date": "2026-10-11",
        "method": "Current manifests, factory load, source/hash and build-record inspection; frozen evidence validation. No performance remeasurement or source parity inferred from these checks.",
        "scope_counts": dict(Counter(row["scope"] for row in entries)),
        "load_counts": dict(Counter((row["scope"], row["load"]["status"]).__str__() for row in entries)),
        "frozen_active33": frozen, "historical_active33_summary": summary, "entries": entries,
    }
    output = args.output.resolve()
    with output.open("x") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"output": str(output), "scope_counts": document["scope_counts"],
                      "load_counts": document["load_counts"], "frozen": frozen}, ensure_ascii=False))


if __name__ == "__main__":
    main()
