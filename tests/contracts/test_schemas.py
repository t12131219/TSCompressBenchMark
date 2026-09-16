import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_versioned_json_schemas_are_valid_json_and_closed_at_root() -> None:
    schema_root = PROJECT_ROOT / "schemas" / "v2"
    paths = sorted(schema_root.glob("*.schema.json"))
    assert {path.name for path in paths} == {
        "canonical-artifact-metadata.schema.json",
        "accounting-ledger.schema.json",
        "benchmark-task.schema.json",
        "codec-manifest.schema.json",
        "compatibility-plan.schema.json",
        "comparability-keys.schema.json",
        "comparability-group.schema.json",
        "corpus-summary-record.schema.json",
        "coverage-record.schema.json",
        "dataset-characterization.schema.json",
        "dataset-manifest.schema.json",
        "execution-resolution.schema.json",
        "eligibility-record.schema.json",
        "experiment-config.schema.json",
        "measurement-policy.schema.json",
        "preprocess-plan.schema.json",
        "preflight-result.schema.json",
        "pareto-record.schema.json",
        "ranking-record.schema.json",
        "report.schema.json",
        "resolved-config.schema.json",
        "run-record.schema.json",
        "summary-record.schema.json",
        "source-artifact.schema.json",
        "source-onboarding.schema.json",
    }
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["additionalProperties"] is False
