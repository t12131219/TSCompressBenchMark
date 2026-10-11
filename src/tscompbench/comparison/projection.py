from __future__ import annotations

from dataclasses import dataclass

from tscompbench.ids import canonical_json_bytes, stable_id

from .models import ComparisonContract, ExecutionJob, TaskSpec, admit_fidelity
from .schema import ComparisonSpecError


@dataclass(frozen=True)
class PublicProjection:
    key: str
    serialized: bytes
    disclosure_bytes: bytes

    @property
    def document(self) -> dict:
        import json

        return json.loads(self.serialized)

    @property
    def disclosures(self) -> dict:
        import json

        return json.loads(self.disclosure_bytes)


def public_projection(
    contract: ComparisonContract, task: TaskSpec, job: ExecutionJob
) -> PublicProjection:
    """Compare completed original-object tasks while retaining execution identity.

    This is admission to a comparison cell. Observed correctness, cost closure,
    recovery and formal measurement qualification remain executor obligations.
    """
    c, t, j = contract.to_document(), task.to_document(), job.to_document()
    if j["task_spec_id"] != task.id or j["original_content_id"] != t["logical_content_id"]:
        raise ComparisonSpecError("execution job does not bind this original task/content")
    if t["logical_schema"]["track"] != c["track"]:
        raise ComparisonSpecError("comparison track differs from original task")
    for field in ("recovery", "fidelity", "cost_boundary", "workload", "state"):
        if t[field] != c[field]:
            raise ComparisonSpecError(f"comparison task differs in {field}")
    if j["state"] != c["state"] or j["timing_boundary"] != c["timing_boundary"]:
        raise ComparisonSpecError("execution state/timing differs from comparison boundary")
    if j["resources"] != c["resources"]:
        raise ComparisonSpecError("execution resource/machine policy differs from frozen budget")
    resources = c["resources"]
    if resources["allowed_isa"] and j["actual_isa"] not in resources["allowed_isa"]:
        raise ComparisonSpecError("actual ISA is outside permitted machine policy")
    admit_fidelity(c["fidelity"], j)
    projection = {
        "schema_version": "tscb.public-comparison-projection.v1",
        "contract_id": contract.id,
        "dataset_id": t["dataset_id"],
        "logical_content_id": t["logical_content_id"],
        "logical_schema": t["logical_schema"],
        "track": c["track"],
        "recovery": c["recovery"],
        "fidelity": c["fidelity"],
        "cost_boundary": c["cost_boundary"],
        "workload": c["workload"],
        "state": c["state"],
        "timing_boundary": c["timing_boundary"],
        "resources": resources,
        "measurement_protocol_id": c["measurement_protocol_id"],
        "analysis_policy_id": c["analysis_policy_id"],
        "selection_policy": c["selection_policy"],
    }
    if c["mode"] == "COMMON_NATIVE_API":
        projection.update(
            actual_input_id=j["actual_input_id"], actual_input_schema_id=j["actual_input_schema_id"]
        )
    if resources["isa_policy"] == "FIXED":
        projection["actual_isa"] = j["actual_isa"]
    disclosures = {
        "execution_job_id": job.id,
        **{
            key: j[key]
            for key in (
                "member_id",
                "method_id",
                "implementation_id",
                "algorithm_id",
                "config_id",
                "recipe_id",
                "view_id",
                "execution_path_hash",
                "source_artifact_id",
                "build_id",
                "runtime_id",
                "actual_input_id",
                "actual_input_schema_id",
                "path",
                "backend",
                "actual_isa",
                "loss_mode",
                "guarantee",
            )
        },
        "ranking_policy": c["fidelity"]["kind"],
        "fixed_error_guarantee_ranking_eligible": c["fidelity"]["kind"] == "FIXED_ERROR",
    }
    return PublicProjection(
        stable_id("public-comparison-projection", projection, version="v3"),
        canonical_json_bytes(projection),
        canonical_json_bytes(disclosures),
    )
