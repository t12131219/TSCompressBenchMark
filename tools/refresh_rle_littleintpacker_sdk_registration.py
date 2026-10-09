"""Consume independently audited, fresh SDK reports without rewriting old evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from audit_fastpfor_simple8b_rle_sdk import audit as audit_rle
from audit_littleintpacker_sdk import audit as audit_lip

from tscompbench.adapters import create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card

ROOT = Path(__file__).resolve().parents[1]
LIP_KEYS = (
    "littleintpacker-pack32-u32",
    "littleintpacker-turbo-u32",
    "littleintpacker-sc-u32",
    "littleintpacker-bmi2-u32",
    "littleintpacker-horizontal-u32",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh(suffix, rle_report, lip_report):
    if not suffix or Path(suffix).name != suffix or ".." in suffix:
        raise ValueError("invalid refresh suffix")
    output = ROOT / "build/source-audits" / f"rle-littleintpacker-sdk-refresh-{suffix}"
    if output.exists():
        raise FileExistsError("preserve prior SDK registry refresh")
    reports = {
        "fastpfor-simple8b-rle-u32": (
            rle_report,
            audit_rle(rle_report),
            "direct_python_sdk_466_tests",
        ),
        **{key: (lip_report, audit_lip(ROOT, lip_report), "direct_sdk") for key in LIP_KEYS},
    }
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    staged = []
    identities = []
    for key, (path, audit, test_name) in reports.items():
        assert audit["status"] == "PASS"
        path.relative_to(ROOT)
        evidence = json.loads(path.read_text())
        for item in evidence["source_snapshot"]:
            assert sha(ROOT / item["path"]) == item["sha256"], "SDK dependency drift"
        codec_path = ROOT / "registry/codecs" / f"{key}.json"
        card_path = ROOT / "registry/onboarding" / f"{key}.json"
        original = json.loads(codec_path.read_text())
        codec = copy.deepcopy(original)
        codec["adapter"]["python_source_closure"] = evidence["source_snapshot"]
        restored = copy.deepcopy(codec)
        restored["adapter"]["python_source_closure"] = original["adapter"]["python_source_closure"]
        assert restored == original, "SDK refresh changed algorithm contract"
        card = json.loads(card_path.read_text())
        card.pop("source_onboarding_id", None)
        tests = [t for t in card["upstream_tests"] if t["name"] == test_name]
        assert len(tests) == 1, "direct SDK record missing or duplicated"
        tests[0].update(evidence=str(path.relative_to(ROOT)), log_sha256=sha(path), status="PASS")
        card = validate_onboarding_card(card)
        staged.extend(((codec_path, codec), (card_path, card)))
        identities.append(
            {
                "key": key,
                "previous_algorithm_id": registry.get(key).algorithm_id,
                "source_artifact_id": registry.get(key).source_artifact_id,
            }
        )
    output.mkdir(parents=True)
    for path, value in staged:
        for directory, data in (
            ("before", path.read_bytes()),
            ("candidate", (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()),
        ):
            target = output / directory / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    proposed = CodecRegistry(
        output / "candidate/registry/codecs", SourceRegistry(ROOT / "registry/sources")
    )
    for item in identities:
        manifest = proposed.get(item["key"])
        assert manifest.source_artifact_id == item["source_artifact_id"]
        item["current_algorithm_id"] = manifest.algorithm_id
    try:
        for path, _ in staged:
            path.write_bytes((output / "candidate" / path.relative_to(ROOT)).read_bytes())
        current = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
        current.verify_all()
        for key in reports:
            create_adapter(ROOT, current.get(key)).create_session({}).close()
    except Exception as error:
        for path, _ in staged:
            path.write_bytes((output / "before" / path.relative_to(ROOT)).read_bytes())
        (output / "report.json").write_text(
            json.dumps({"status": "FAIL", "rolled_back": True, "error": str(error)}, indent=2)
            + "\n"
        )
        raise
    result = {
        "status": "PASS",
        "source_ids_preserved": True,
        "identities": identities,
        "scope": "AUDITED_SDK_EXECUTION_CLOSURE_REFRESH_NOT_FORMAL_PERFORMANCE",
        "sdk_reports": [
            {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in (rle_report, lip_report)
        ],
    }
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix", required=True)
    parser.add_argument("--rle-report", type=Path, required=True)
    parser.add_argument("--littleintpacker-report", type=Path, required=True)
    args = parser.parse_args()
    refresh(args.suffix, args.rle_report.resolve(), args.littleintpacker_report.resolve())
