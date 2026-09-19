import json
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[2]


def test_lzss_five_layer_qualification_and_append_only_resume(tmp_path):
    config = ROOT / "configs/experiments/lzss-raw-qualification.toml"
    run = initialize_run_set(config, tmp_path / "runs", run_set_id="lzss-five-layer")
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    results = execute_run_set(run, datasets, codecs)
    assert len(results) == 1 and results[0].preflight.eligible_for_formal_repetitions
    record = results[0].records[0]
    assert record.status.value == "PASS"
    assert record.eligibility is False  # Qualification must not become formal performance evidence.
    raw = (run.path / "run_components.jsonl").read_bytes()
    evidence = json.loads(raw)
    assert evidence["diagnostics"]["same_repetition_correctness_and_measurement"]
    ledger = evidence["accounting"]
    assert ledger["final_bits"] == ledger["final_physical_bytes"] * 8
    assert evidence["finalize_bytes"] == 0
    assert evidence["timing"]["native_encode_wall_ns"] > 0
    assert evidence["timing"]["native_decode_wall_ns"] > 0
    report = report_run_set(run)
    assert report.task_count == 1 and report.eligible_run_count == 0
    assert (report.report_directory / "report.html").is_file()
    assert execute_run_set(run, datasets, codecs) == ()
    assert (run.path / "run_components.jsonl").read_bytes() == raw
    again = report_run_set(run)
    assert again.report_id == report.report_id
