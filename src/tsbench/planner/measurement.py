"""Frozen measurement/qualification policy, separate from a timing result."""
from pathlib import Path

from ..assets import content_id, load_json, local_file
from ..contracts import load_contract
from .smoke_isolation import SUITE as ISOLATED_SUITE

POLICY = "configs/profiles/measurement_policy_v1.json"
PROFILE = "process_frame_preflight"
SNAPSHOT = "measurement-policy.schema.json"
TIMED_SUITE = "m1_lossless_candidate_v2"
FORMAL_TIMED_SUITE = "m1_lossless_formal_v1"
FULL_CORPUS_SUITE = "m1_lossless_full_corpus_preflight_v1"


def measurement_policy(root: Path) -> dict:
    policy = load_json(local_file(root, POLICY))
    schema = load_contract(root, "measurement-policy")
    schema.validate(policy, POLICY)
    return {"policy": policy, "schema_id": schema.document_id, "policy_id": content_id(policy)}


def timed(suite: dict) -> bool:
    return suite["id"] in {TIMED_SUITE, FORMAL_TIMED_SUITE, ISOLATED_SUITE, FULL_CORPUS_SUITE}


def process_binding(root: Path) -> dict:
    from ..assets import digest
    from ..supervisor import process
    return {**measurement_policy(root), "supervisor_sha256": digest(Path(process.__file__))}


def comparison_identity(plan: dict, source: dict) -> str:
    """Same-work identity for the bounded O-track diagnostic, not admission."""
    suite = plan["suite"]
    return content_id({"scope": plan["scope_id"], "mode": PROFILE,
                       "task": suite["task"], "quality": suite["quality"], "access": suite["access"],
                       "comparison_track": suite["comparison_track"], "canonical_input": source})
