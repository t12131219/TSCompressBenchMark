import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "v32_migration", ROOT / "tools/migrate_legacy_v32_analysis.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def legacy(tmp_path):
    run = tmp_path / "old"
    run.mkdir()
    row = {
        "schema_version": "tscb.run-record.v2",
        "run_id": "historical-run",
        "status": "PASS",
        "record_kind": "FORMAL_REPETITION",
        "eligibility": True,
        "correctness": {"status": "PASS"},
        "accounting": {
            "serialized_bits": 16,
            "external_side_information_bits": 8,
            "final_bits": 24,
        },
        "timing": {
            "selected_encode_wall_ns": 100,
            "selected_decode_wall_ns": 200,
            "inner_iterations": 1,
        },
        **{
            k: k
            for k in (
                "algorithm_id",
                "config_id",
                "dataset_id",
                "track",
                "execution_path_hash",
                "execution_comparability_key",
                "resource_profile_key",
            )
        },
    }
    (run / "run_components.jsonl").write_text(json.dumps(row) + "\n")
    (run / "runs.csv").write_bytes(b"original bytes,kept\n")
    return run, row


def test_migration_preserves_inputs_and_refuses_retroactive_design(tmp_path):
    run, _ = legacy(tmp_path)
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    result = module.migrate(run, tmp_path / "derived.json")
    assert result["described_records"] == result["fixed_records"] == 1
    assert result["v32_formal_eligible"] is False
    assert result["new_pairing_or_warmup_observations_generated"] is False
    assert result["code_sha256"] and result["dependency_sha256"]
    assert {p.name: p.read_bytes() for p in run.iterdir()} == before
    with pytest.raises(FileExistsError):
        module.migrate(run, tmp_path / "derived.json")
    with pytest.raises(ValueError, match="outside"):
        module.migrate(run, run / "derived.json")


def test_failed_and_ineligible_rows_remain_in_fixed_denominator(tmp_path):
    run, row = legacy(tmp_path)
    row["run_id"] = "failed"
    row["status"] = "FAIL"
    with (run / "run_components.jsonl").open("a") as handle:
        handle.write(json.dumps(row) + "\n")
    result = module.migrate(run, tmp_path / "derived.json")
    assert result["fixed_records"] == 2 and result["described_records"] == 1
    assert result["excluded_records"][0]["run_id"] == "failed"


def test_duplicate_or_interrupted_legacy_records_fail_closed(tmp_path):
    run, row = legacy(tmp_path)
    with (run / "run_components.jsonl").open("a") as handle:
        handle.write(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        module.migrate(run, tmp_path / "derived.json")
    (run / "run_components.jsonl").write_text(json.dumps(row))
    with pytest.raises(ValueError, match="interrupted"):
        module.migrate(run, tmp_path / "derived.json")
