"""Freeze a new source revision while preserving every comparison decision.

No codec is loaded and no previous qualification or performance result is
transferred. Changed method semantics require an independently designed bundle.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.comparison import (  # noqa: E402
    ComparisonContract,
    CorpusSpec,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    compile_group_plan,
    method_id,
    registered_source_closure_digest,
)
from tscompbench.comparison.analysis import AnalysisPolicy  # noqa: E402
from tscompbench.comparison.runner import load_comparison_bundle  # noqa: E402
from tscompbench.ids import canonical_json_bytes  # noqa: E402
from tscompbench.measurement.v32_protocol import MeasurementProtocol  # noqa: E402


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def registration_snapshot(root: Path) -> list[dict]:
    paths = [root / "registry/algorithm_scope.json"]
    for directory in ("codecs", "sources"):
        paths += sorted((root / "registry" / directory).glob("*.json"))
    return [{"path": str(p.relative_to(root)), "sha256": sha(p)} for p in paths]


def semantic_projection(document: dict) -> dict:
    """Retain all decisions except source pins, revision names and derived IDs."""
    result = copy.deepcopy(document)
    for section, fields in {
        "contract": ("revision",),
        "config_map": ("contract_id",),
        "expected_matrix": ("contract_id", "config_map_id"),
        "group": ("revision", "contract_id", "config_map_id", "expected_matrix_id"),
    }.items():
        for field in fields:
            result[section].pop(field)
    for member in result["group"]["members"]:
        for field in ("source_artifact_id", "source_closure_sha256"):
            member["implementation"].pop(field)
        member["shared_code_tags"] = [
            "SOURCE_ARTIFACT:BOUND" if tag.startswith("SOURCE_ARTIFACT:") else tag
            for tag in member["shared_code_tags"]
        ]
    for row in result["group"]["method_equivalence"]:
        row["evidence"] = [
            "SOURCE_ARTIFACT:BOUND" if tag.startswith("SOURCE_ARTIFACT:") else tag
            for tag in row["evidence"]
        ]
    return result


def rebind_document(root: Path, document: dict, revision: str) -> tuple[dict, dict]:
    """Return a newly planned bundle and proof; never mutate the supplied root."""
    root = root.resolve()
    if not isinstance(revision, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", revision
    ):
        raise ValueError("new revision must be a nonempty safe identifier")
    before = registration_snapshot(root)
    original = copy.deepcopy(document)
    contract = ComparisonContract.from_document(original["contract"])
    corpus = CorpusSpec.from_document(original["corpus"])
    configs = MethodConfigMap.from_document(original["config_map"])
    matrix = ExpectedOutcomeMatrix.from_document(original["expected_matrix"])
    group = GroupSpec.from_document(original["group"])
    protocol = MeasurementProtocol.from_document(original["protocol"])
    policy = AnalysisPolicy.from_document(original["analysis_policy"])
    if (
        original["contract"]["measurement_protocol_id"] != protocol.protocol_id
        or original["contract"]["analysis_policy_id"] != policy.id
        or original["config_map"]["contract_id"] != contract.id
        or original["expected_matrix"]["contract_id"] != contract.id
        or original["expected_matrix"]["corpus_id"] != corpus.id
        or original["expected_matrix"]["config_map_id"] != configs.id
        or original["group"]["contract_id"] != contract.id
        or original["group"]["corpus_id"] != corpus.id
        or original["group"]["config_map_id"] != configs.id
        or original["group"]["expected_matrix_id"] != matrix.id
    ):
        raise ValueError("base bundle identity chain differs")
    if revision in {original["contract"]["revision"], original["group"]["revision"]}:
        raise ValueError("preserve the old revision; an explicit new revision is required")
    registry = CodecRegistry(root / "registry/codecs", SourceRegistry(root / "registry/sources"))
    bundle = copy.deepcopy(original)
    changes, tags = [], {}
    for member in bundle["group"]["members"]:
        manifest = registry.get(member["codec_key"])
        codec = manifest.document
        expected_method = {
            "name": codec["identity"]["display_name"],
            "mechanism": codec["identity"]["family"],
            "variant": manifest.key,
            "semantic_version": "1",
            "definition_sha256": hashlib.sha256(
                canonical_json_bytes(
                    {
                        field: codec[field]
                        for field in ("classification", "semantics", "input", "lifecycle")
                    }
                )
            ).hexdigest(),
        }
        if member["method"] != expected_method:
            raise ValueError("method semantics changed; design a separate bundle: " + manifest.key)
        if member["implementation"]["method_id"] != method_id(expected_method):
            raise ValueError("method identity differs: " + manifest.key)
        old_source = member["implementation"]["source_artifact_id"]
        old_tag = "SOURCE_ARTIFACT:" + old_source
        new_tag = "SOURCE_ARTIFACT:" + manifest.source_artifact_id
        source_tags = [
            tag for tag in member["shared_code_tags"] if tag.startswith("SOURCE_ARTIFACT:")
        ]
        if source_tags != [old_tag]:
            raise ValueError("member source tag is missing or inconsistent: " + manifest.key)
        if old_tag in tags and tags[old_tag] != new_tag:
            raise ValueError("shared source split needs an independently designed equivalence")
        tags[old_tag] = new_tag
        current_closure = registered_source_closure_digest(registry, manifest.key)
        changes.append(
            {
                "member_id": member["member_id"],
                "codec_key": manifest.key,
                "algorithm_id": manifest.algorithm_id,
                "old_source_artifact_id": old_source,
                "current_source_artifact_id": manifest.source_artifact_id,
                "old_source_closure_sha256": member["implementation"]["source_closure_sha256"],
                "current_source_closure_sha256": current_closure,
                "method_id_preserved": method_id(expected_method),
            }
        )
        member["implementation"].update(
            source_artifact_id=manifest.source_artifact_id, source_closure_sha256=current_closure
        )
        member["shared_code_tags"] = [tags.get(tag, tag) for tag in member["shared_code_tags"]]
    for row in bundle["group"]["method_equivalence"]:
        for tag in row["evidence"]:
            if tag.startswith("SOURCE_ARTIFACT:") and tag not in tags:
                raise ValueError("equivalence evidence contains an unbound source tag")
        row["evidence"] = [tags.get(tag, tag) for tag in row["evidence"]]
    bundle["contract"]["revision"] = revision
    current_contract = ComparisonContract.from_document(bundle["contract"])
    bundle["config_map"]["contract_id"] = current_contract.id
    current_configs = MethodConfigMap.from_document(bundle["config_map"])
    bundle["expected_matrix"].update(
        contract_id=current_contract.id, config_map_id=current_configs.id
    )
    current_matrix = ExpectedOutcomeMatrix.from_document(bundle["expected_matrix"])
    bundle["group"].update(
        revision=revision,
        contract_id=current_contract.id,
        config_map_id=current_configs.id,
        expected_matrix_id=current_matrix.id,
    )
    current_group = GroupSpec.from_document(bundle["group"])
    if semantic_projection(bundle) != semantic_projection(original):
        raise ValueError("source migration changed a non-source comparison decision")
    plan = compile_group_plan(
        current_group,
        current_contract,
        corpus,
        current_configs,
        current_matrix,
        codec_registry=registry,
        active_codec_keys=set(
            json.loads((root / "registry/algorithm_scope.json").read_text())["registered_codecs"]
        ),
    )
    if before != registration_snapshot(root):
        raise ValueError("registration changed during source migration")
    proof = {
        "schema_version": "tscb.comparison-source-rebind.v1",
        "status": "PLANNED_SOURCE_REVISION_ONLY",
        "old_group_id": group.id,
        "current_group_id": current_group.id,
        "old_contract_id": contract.id,
        "current_contract_id": current_contract.id,
        "corpus_id_preserved": corpus.id,
        "non_source_decisions_preserved": True,
        "non_source_decisions_sha256": hashlib.sha256(
            canonical_json_bytes(semantic_projection(bundle))
        ).hexdigest(),
        "members": changes,
        "planned_denominators": plan.denominators,
        "registration_snapshot": before,
        "qualification_transferred": False,
        "formal_results_transferred": False,
        "full_parity_granted": False,
        "historical_evidence_rewritten": False,
    }
    return bundle, proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base-bundle", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    args = parser.parse_args()
    output, proof_path = args.output.resolve(), args.proof.resolve()
    base = args.base_bundle.resolve()
    if len({base, output, proof_path}) != 3 or output.exists() or proof_path.exists():
        raise FileExistsError("preserve prior bundles and proofs; use two distinct new outputs")
    base_hash = sha(base)
    bundle, proof = rebind_document(args.root, load_comparison_bundle(base), args.revision)
    if sha(base) != base_hash:
        raise ValueError("base bundle changed during source migration")
    if proof["registration_snapshot"] != registration_snapshot(args.root.resolve()):
        raise ValueError("registration changed before source migration publication")
    proof.update(
        base_bundle={"path": str(base), "sha256": base_hash},
        output_bundle={
            "path": str(output),
            "sha256": hashlib.sha256(canonical_json_bytes(bundle) + b"\n").hexdigest(),
        },
        driver={"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__))},
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(canonical_json_bytes(bundle) + b"\n")
    with proof_path.open("xb") as handle:
        handle.write(canonical_json_bytes(proof) + b"\n")
    print(json.dumps({"status": proof["status"], "group_id": proof["current_group_id"]}))


if __name__ == "__main__":
    main()
