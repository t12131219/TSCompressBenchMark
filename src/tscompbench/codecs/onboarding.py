from __future__ import annotations

from typing import Any

from tscompbench.contracts import LicenseStatus, ObjectLevel
from tscompbench.ids import stable_id

from .models import CodecContractError

_REQUIRED = {
    "schema_version",
    "source_artifact_id",
    "repository",
    "commit",
    "dirty",
    "submodules",
    "implementation_files",
    "public_api_files",
    "benchmark_files",
    "test_files",
    "license_files",
    "third_party_dependencies",
    "object_level_candidates",
    "input_contract",
    "output_contract",
    "lifecycle_contract",
    "stream_components",
    "upstream_tests",
    "builds",
    "license_decision",
    "known_limitations",
    "unsupported_reason_codes",
}


def validate_onboarding_card(document: dict[str, Any]) -> dict[str, Any]:
    """Validate the mandatory source-admission evidence before adapter authoring."""

    missing = _REQUIRED - set(document)
    unknown = set(document) - _REQUIRED - {"source_onboarding_id"}
    if missing or unknown:
        raise CodecContractError(
            f"source onboarding fields mismatch: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
    if document["schema_version"] != "tscb.source-onboarding.v2":
        raise CodecContractError("unsupported source onboarding schema")
    if document["dirty"] is not False:
        raise CodecContractError("source onboarding requires a clean or explicitly patched source")
    for level in document["object_level_candidates"]:
        ObjectLevel(level)
    license_status = LicenseStatus(document["license_decision"]["status"])
    if license_status is LicenseStatus.BLOCKED:
        raise CodecContractError("license-blocked source cannot proceed to adapter authoring")
    if not document["implementation_files"] or not document["public_api_files"]:
        raise CodecContractError(
            "source onboarding must locate implementation and public API files"
        )
    lifecycle = document["lifecycle_contract"]
    required_lifecycle = {"output_bound", "return_length", "error_codes", "finalize", "reset"}
    if required_lifecycle - set(lifecycle):
        raise CodecContractError("source lifecycle evidence is incomplete")
    if not document["builds"] or any(
        "artifact_sha256" not in build or "compile_commands_sha256" not in build
        for build in document["builds"]
    ):
        raise CodecContractError("source onboarding requires hashed build evidence")
    identity = {key: document[key] for key in sorted(_REQUIRED)}
    result = dict(document)
    source_onboarding_id = stable_id("source-onboarding", identity)
    recorded = result.get("source_onboarding_id")
    if recorded is not None and recorded != source_onboarding_id:
        raise CodecContractError("recorded SourceOnboardingID does not match card content")
    result["source_onboarding_id"] = source_onboarding_id
    return result
