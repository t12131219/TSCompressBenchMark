from __future__ import annotations

import json
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[2]


def test_delta_varint_five_layer_qualification(tmp_path: Path) -> None:
    run = initialize_run_set(
        ROOT / "configs/experiments/delta-varint-qualification.toml",
        tmp_path / "runs",
        run_set_id="delta-varint-five-layer",
    )
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    codecs = CodecRegistry(
        ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")
    )
    results = execute_run_set(run, datasets, codecs)
    assert len(results) == 1
    assert results[0].preflight.eligible_for_formal_repetitions
    assert len(results[0].records) == 1
    record = results[0].records[0]
    assert record.status.value == "PASS"
    evidence = json.loads((run.path / "run_components.jsonl").read_text())
    assert evidence["accounting"]["timestamp_bits"] > 0
    assert evidence["accounting"]["final_bits"] == (
        evidence["accounting"]["final_physical_bytes"] * 8
    )
    assert evidence["finalize_bytes"] == 0
    assert evidence["correctness"]["status"] == "PASS"
    assert evidence["timing"]["native_encode_wall_ns"] > 0
    assert evidence["timing"]["native_decode_wall_ns"] > 0
    report = report_run_set(run)
    assert report.task_count == 1
    assert (report.report_directory / "report.json").is_file()
