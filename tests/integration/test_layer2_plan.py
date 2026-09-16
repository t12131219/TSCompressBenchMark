import json
from collections import Counter
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import initialize_run_set, plan_run_set

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_layer2_plan_consumes_layer1_artifacts_and_keeps_all_capability_states(
    tmp_path,
) -> None:
    config = PROJECT_ROOT / "configs" / "experiments" / "capability-configuration-smoke.toml"
    run_set = initialize_run_set(config, tmp_path / "runs", run_set_id="layer2")
    datasets = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    sources = SourceRegistry(PROJECT_ROOT / "registry" / "sources")
    codecs = CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources)
    tasks = plan_run_set(run_set, datasets, codecs)

    assert len(tasks) == 8
    counts = Counter(item.compatibility.status.value for item in tasks)
    assert counts == {
        "DIRECT_SUPPORTED": 2,
        "ADAPTER_LOSSLESS": 2,
        "ADAPTER_LOSSY": 2,
        "UNSUPPORTED": 2,
    }
    assert Counter(item.status.value for item in tasks) == {
        "PLANNED": 4,
        "ADAPTER_LOSSY_ROUTED": 2,
        "UNSUPPORTED": 2,
    }
    assert len({item.task_id for item in tasks}) == len(tasks)
    assert all(
        item.comparability.execution_document["semantic_key"] == item.comparability.semantic_key
        for item in tasks
    )
    assert all(
        item.comparability.resource_document["execution_key"] == item.comparability.execution_key
        for item in tasks
    )
    assert all(
        item.comparability.execution_document["measurement_mode"] == "QUALIFICATION"
        and item.comparability.execution_document["iteration_semantics"] == "INDEPENDENT_OBJECT"
        and item.comparability.execution_document["repetitions"] == 1
        for item in tasks
    )
    summary = json.loads((run_set.path / "layer2-plan.json").read_text())
    assert summary["source_logical_entry_count"] == 221
    assert (run_set.path / "task_plan.jsonl").is_file()
    assert "LAYER_2_COMPLETED" in (run_set.path / "events.jsonl").read_text()
