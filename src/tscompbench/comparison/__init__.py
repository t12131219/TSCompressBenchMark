"""Versioned comparison specifications, frozen planning and public projections."""

from .analysis_extensions import augment_analysis
from .models import (
    ComparisonContract,
    CorpusSpec,
    ExecutionJob,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    TaskSpec,
    admit_fidelity,
    implementation_id,
    method_id,
)
from .planning import (
    ComparisonPlan,
    PlannedComparisonCell,
    compile_group_plan,
    registered_source_closure_digest,
    validate_job_for_cell,
)
from .projection import PublicProjection, public_projection
from .report_renderer import render_comparison_report
from .schema import ComparisonSpecError

__all__ = [
    "ComparisonContract",
    "ComparisonPlan",
    "ComparisonSpecError",
    "CorpusSpec",
    "ExecutionJob",
    "ExpectedOutcomeMatrix",
    "GroupSpec",
    "MethodConfigMap",
    "PlannedComparisonCell",
    "PublicProjection",
    "TaskSpec",
    "admit_fidelity",
    "augment_analysis",
    "compile_group_plan",
    "implementation_id",
    "method_id",
    "public_projection",
    "registered_source_closure_digest",
    "render_comparison_report",
    "validate_job_for_cell",
]
