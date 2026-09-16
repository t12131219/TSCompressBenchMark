import csv
import json
from dataclasses import replace
from pathlib import Path

from tscompbench.adapters import OracleAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import RunStatus
from tscompbench.datasets import DatasetRegistry
from tscompbench.datasets.canonical import read_canonical
from tscompbench.execution.preflight import preflight_task
from tscompbench.runner import execute_run_set, initialize_run_set, plan_run_set

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_layer3_executes_preflight_finalize_accounting_and_same_run_correctness(
    tmp_path,
) -> None:
    config = tmp_path / "layer3.toml"
    config.write_text(
        """schema_version = "2.0"
datasets = ["national_illness"]
algorithms = ["oracle-direct"]
tracks = ["VALUE"]
seed = 7

[data_preparation]
characterization_mode = "exact"
write_canonical = true

[profile]
threads = 1
processes = 1
timeout_seconds = 10
memory_limit_bytes = 1073741824

[sweep]
block_size = [8]
""",
        encoding="utf-8",
    )
    run_set = initialize_run_set(config, tmp_path / "runs", run_set_id="layer3")
    datasets = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    sources = SourceRegistry(PROJECT_ROOT / "registry" / "sources")
    codecs = CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources)

    results = execute_run_set(run_set, datasets, codecs)

    assert len(results) == 1
    assert results[0].preflight.eligible_for_formal_repetitions
    assert results[0].records[0].status.value == "PASS"
    assert results[0].records[0].eligibility is False  # harness oracle never ranks
    with (run_set.path / "runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert int(rows[0]["finalize_bytes"]) > 0
    assert int(rows[0]["final_bits"]) == int(rows[0]["serialized_bits"])
    evidence = json.loads((run_set.path / "run_components.jsonl").read_text())
    assert evidence["diagnostics"]["same_repetition_correctness_and_measurement"] is True
    assert evidence["timing"]["schema_version"] == "tscb.timing-observation.v2"
    assert evidence["timing"]["inner_iterations"] >= 1
    assert evidence["resources"]["schema_version"] == "tscb.resource-observation.v2"
    assert evidence["workloads"]["query"]["status"] == "NOT_REQUESTED"
    preflight = json.loads(next((run_set.path / "preflight").glob("*.json")).read_text())
    assert preflight["input_validation"]["timestamp_unit"] == "s"
    assert preflight["input_validation"]["timestamp_epoch"] == "UNIX"
    assert preflight["input_validation"]["value_units"] == [
        "percent",
        "percent",
        "count",
        "count",
        "count",
        "count",
        "count",
    ]
    assert (run_set.path / "layer3-execution.json").is_file()
    assert (run_set.path / "layer4-performance.json").is_file()
    assert len(list((run_set.path / "warmup").glob("*.json"))) == 1
    assert "LAYER_3_COMPLETED" in (run_set.path / "events.jsonl").read_text()
    assert "LAYER_4_COMPLETED" in (run_set.path / "events.jsonl").read_text()

    (run_set.path / "runs.csv").unlink()
    assert execute_run_set(run_set, datasets, codecs) == ()
    with (run_set.path / "runs.csv").open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 1


def test_preflight_fault_taxonomy_is_not_collapsed_into_generic_codec_failure(
    tmp_path,
) -> None:
    config = tmp_path / "faults.toml"
    config.write_text(
        """schema_version = "2.0"
datasets = ["national_illness"]
algorithms = ["oracle-direct", "oracle-lossy-adapter", "oracle-native-nd-only"]
tracks = ["VALUE"]

[data_preparation]
characterization_mode = "exact"
write_canonical = true

[profile]
timeout_seconds = 2
memory_limit_bytes = 1073741824

[sweep]
block_size = [8]
""",
        encoding="utf-8",
    )
    run_set = initialize_run_set(config, tmp_path / "runs", run_set_id="faults")
    datasets = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    sources = SourceRegistry(PROJECT_ROOT / "registry" / "sources")
    codecs = CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources)
    tasks = plan_run_set(run_set, datasets, codecs)
    by_algorithm = {item.algorithm_id: item for item in tasks}
    direct_manifest = codecs.get("oracle-direct")
    lossy_manifest = codecs.get("oracle-lossy-adapter")
    unsupported_manifest = codecs.get("oracle-native-nd-only")
    direct = by_algorithm[direct_manifest.algorithm_id]
    lossy = by_algorithm[lossy_manifest.algorithm_id]
    unsupported = by_algorithm[unsupported_manifest.algorithm_id]
    parameters = {
        item["config_id"]: item["parameters"]
        for item in json.loads(
            (run_set.path / "resolved_configs.json").read_text(encoding="utf-8")
        )["configs"]
    }
    artifact = read_canonical(
        next((run_set.path / "datasets").glob("*/*.canonical.tscb")),
        include_buffers=True,
    )

    def status(task, manifest, adapter):
        source = sources.get(manifest.source_artifact_id)
        result, _ = preflight_task(
            task,
            manifest,
            source,
            artifact,
            adapter,
            parameters[task.config_id],
        )
        return result.status

    adapter_contract = direct_manifest.document["adapter"]
    assert (
        status(
            direct,
            direct_manifest,
            OracleAdapter(mode="CAPACITY_LIE", manifest_adapter=adapter_contract),
        )
        is RunStatus.HARNESS_CAPACITY_ERROR
    )
    assert (
        status(
            direct,
            direct_manifest,
            OracleAdapter(mode="CORRUPT", manifest_adapter=adapter_contract),
        )
        is RunStatus.CORRECTNESS_FAIL
    )
    assert (
        status(
            direct,
            direct_manifest,
            OracleAdapter(mode="FALSE_DETERMINISM", manifest_adapter=adapter_contract),
        )
        is RunStatus.NONDETERMINISTIC
    )
    assert (
        status(
            direct,
            direct_manifest,
            OracleAdapter(mode="OOM", manifest_adapter=adapter_contract),
        )
        is RunStatus.OOM
    )
    timed_task = replace(
        direct,
        resource_limits={**direct.resource_limits, "timeout_seconds": 0.02},
    )
    assert (
        status(
            timed_task,
            direct_manifest,
            OracleAdapter(delay_seconds=0.2, manifest_adapter=adapter_contract),
        )
        is RunStatus.TIMEOUT
    )
    assert (
        status(
            lossy,
            lossy_manifest,
            OracleAdapter(
                mode="BOUND_VIOLATION",
                error_delta=1.0,
                manifest_adapter=lossy_manifest.document["adapter"],
            ),
        )
        is RunStatus.BOUND_VIOLATION
    )
    assert (
        status(
            unsupported,
            unsupported_manifest,
            OracleAdapter(manifest_adapter=unsupported_manifest.document["adapter"]),
        )
        is RunStatus.UNSUPPORTED
    )
