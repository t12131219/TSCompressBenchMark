"""Refresh only current SDK consumption and preserve prior registry bytes for audit."""

from __future__ import annotations

import json
import argparse
from pathlib import Path

from audit_littleintpacker_sdk import audit, require, sdk_report_path, sha
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix", default="20261007-3")
    args = parser.parse_args()
    require(args.suffix and "/" not in args.suffix and ".." not in args.suffix, "invalid refresh suffix")
    current = audit()
    report = sdk_report_path()
    evidence = json.loads(report.read_text())
    out = ROOT / "build/source-audits" / f"littleintpacker-registry-refresh-{args.suffix}"
    require(not out.exists(), "preserve prior SDK registry refresh")
    out.mkdir(parents=True)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    staged = []
    for key in current["keys"]:
        codec = ROOT / f"registry/codecs/{key}.json"
        card_path = ROOT / f"registry/onboarding/{key}.json"
        document = json.loads(codec.read_text())
        document["adapter"]["python_source_closure"] = evidence["source_snapshot"]
        card = json.loads(card_path.read_text())
        card.pop("source_onboarding_id", None)
        tests = [t for t in card["upstream_tests"] if t["name"] == "direct_sdk"]
        require(len(tests) == 1, "direct SDK onboarding record missing/duplicated")
        tests[0].update(evidence=str(report.relative_to(ROOT)), log_sha256=sha(report), status="PASS")
        card = validate_onboarding_card(card)
        for target, value in ((codec, document), (card_path, card)):
            before = out / "before" / target.relative_to(ROOT)
            before.parent.mkdir(parents=True, exist_ok=True)
            before.write_bytes(target.read_bytes())
            candidate = out / target.relative_to(ROOT)
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            staged.append((target, candidate))
    proposed = CodecRegistry(out / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    identities = []
    for key in current["keys"]:
        old, new = registry.get(key), proposed.get(key)
        require(old.source_artifact_id == new.source_artifact_id, "SDK refresh changed source identity")
        identities.append({"key": key, "previous_algorithm_id": old.algorithm_id,
                           "current_algorithm_id": new.algorithm_id, "source_artifact_id": new.source_artifact_id})
    for target, candidate in staged:
        target.write_bytes(candidate.read_bytes())
    CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")).verify_all()
    record = {"status": "PASS", "keys": current["keys"], "sdk_evidence": current,
              "source_ids_preserved": True, "algorithm_identity_changes": identities,
              "full_logical_entries_qualified": False,
              "registry_files": [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p, _ in staged]}
    (out / "report.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "refreshed": current["keys"]}, indent=2))


if __name__ == "__main__":
    main()
