from __future__ import annotations

import json
from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("track,expected", [("value", 6), ("system", 1)])
@pytest.mark.parametrize("timing_scope", ["CORE", "PIPELINE", "E2E"])
def test_requested_rewrites_through_five_layers(
    tmp_path: Path, track: str, expected: int, timing_scope: str
):
    template = ROOT / "configs/experiments" / f"requested-lossless-{track}-qualification.toml"
    config = tmp_path / f"{track}.toml"
    config.write_text(
        template.read_text()
        .replace('datasets = ["etth1", "exchange_rate", "weather"]', 'datasets = ["exchange_rate"]')
        .replace('timing_scope = "PIPELINE"', f'timing_scope = "{timing_scope}"')
    )
    run = initialize_run_set(config, tmp_path / "runs", run_set_id=f"rewrite-{track}-qualification")
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    results = execute_run_set(run, datasets, codecs)
    assert len(results) == expected
    assert all(result.preflight.eligible_for_formal_repetitions for result in results)
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(records) == expected
    for record in records:
        # System-wide swap may invalidate timing while codec correctness remains observable.
        assert record["status"] in {"PASS", "RESOURCE_PRESSURE"}
        if record["status"] == "RESOURCE_PRESSURE":
            assert record["reason_code"] == "SWAP_OBSERVED_DURING_FORMAL_REPETITION"
            assert record["resources"]["swap_observed"] is True
        assert record["correctness"]["status"] == "PASS"
        assert record["eligibility"] is False  # QUALIFICATION never enters formal rankings.
        accounting = record["accounting"]
        assert accounting["final_bits"] == accounting["final_physical_bytes"] * 8
        assert accounting["external_side_information_bits"] == 0
        assert accounting["metadata_bits"] > 0
        if track == "system":
            assert accounting["unallocated_shared_bits"] > 0
            assert accounting["timestamp_bits"] == accounting["value_bits"] == 0
        else:
            assert accounting["value_bits"] > 0
        timing = record["timing"]
        assert timing["timing_scope"] == timing_scope
        if timing_scope == "PIPELINE":
            assert timing["selected_encode_wall_ns"] == timing["pipeline_encode_wall_ns"]
        elif timing_scope == "CORE":
            assert timing["selected_encode_wall_ns"] == timing["core_encode_wall_ns"]
            assert timing["selected_decode_wall_ns"] == timing["core_decode_wall_ns"]
            assert timing["selected_wall_ns"] == (
                timing["core_encode_wall_ns"] + timing["core_decode_wall_ns"]
            )
        else:
            assert timing["selected_wall_ns"] == timing["e2e_wall_ns"]
        assert timing["native_encode_wall_ns"] is None
        assert timing["native_decode_wall_ns"] is None
        assert "DECOMPRESS_INDEPENDENT_CONTEXT" in record["diagnostics"]["lifecycle_trace"]
    report = report_run_set(run)
    assert report.task_count == expected
    for layer in [2, 3, 4, 5]:
        assert next(run.path.glob(f"layer{layer}-*.json"), None) is not None
    assert (report.report_directory / "report.json").is_file()
