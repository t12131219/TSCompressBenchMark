from decimal import Decimal

import pytest

from tscompbench.configuration import ConfigurationError, load_experiment_config
from tscompbench.statistics import descriptive_statistics, pareto_front, rank_values
from tscompbench.statistics.engine import _auxiliary_timing_fields, _corpus_summaries


def test_descriptive_statistics_are_deterministic_and_not_fastest_only() -> None:
    first = descriptive_statistics(
        [10, 20, 30, 1000],
        bootstrap_samples=200,
        confidence_level=Decimal("0.95"),
        seed_material="group-a",
    )
    second = descriptive_statistics(
        [10, 20, 30, 1000],
        bootstrap_samples=200,
        confidence_level=Decimal("0.95"),
        seed_material="group-a",
    )
    assert first == second
    assert first["median"] == 25
    assert first["p25"] == 17.5
    assert first["p75"] == 272.5
    assert first["mean"] == 265
    assert first["ci_low"] <= first["median"] <= first["ci_high"]


def test_pareto_and_dense_ranking_keep_tradeoffs_explicit() -> None:
    candidates = {
        "compact": {"bits": 10.0, "time": 5.0},
        "fast": {"bits": 20.0, "time": 2.0},
        "dominated": {"bits": 25.0, "time": 6.0},
    }
    front, dominated_by = pareto_front(candidates, {"bits": "MIN", "time": "MIN"})
    assert front == {"compact", "fast"}
    assert set(dominated_by["dominated"]) == {"compact", "fast"}
    assert rank_values({"a": 4.0, "b": 4.0, "c": 2.0}, direction="MAX") == {
        "a": 1,
        "b": 1,
        "c": 2,
    }


def test_reporting_policy_is_frozen_in_experiment_configuration(tmp_path) -> None:
    path = tmp_path / "experiment.toml"
    path.write_text(
        """schema_version = "2.0"
datasets = ["national_illness"]

[reporting]
bootstrap_samples = 500
confidence_level = "0.90"
ranking_policy = "PER_METRIC_WITHIN_COMPARABILITY_GROUP"
tie_method = "DENSE_EXACT"
coverage_policy = "PUBLISH_SEPARATELY_NO_SCORE"
""",
        encoding="utf-8",
    )
    config = load_experiment_config(path)
    assert config.reporting.bootstrap_samples == 500
    assert config.canonical_document["reporting"]["confidence_level"] == "0.90"

    path.write_text(path.read_text(encoding="utf-8").replace("500", "99"), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="bootstrap_samples"):
        load_experiment_config(path)


@pytest.mark.parametrize("invalid", [None, -1, True, "17"])
def test_auxiliary_native_summary_does_not_publish_partial_totals(invalid):
    policy = {"bootstrap_samples": 200, "confidence_level": "0.95"}
    base = {
        "inner_iterations": 2, "canonical_bytes_per_iteration": 100,
        "codec_input_bytes_per_iteration": 120, "native_encode_wall_ns": 17,
        "native_decode_wall_ns": 19, "native_timing_enabled": True,
        "native_timing_boundary": "CODEC_API_ONLY_V1", "native_timing_clock": "CLOCK_MONOTONIC",
    }
    rows = [{"timing": base}, {"timing": {**base, "native_encode_wall_ns": invalid}}]
    result = _auxiliary_timing_fields(rows, policy, "test")
    assert result["native_encode_observation_count"] == 1
    assert result["native_encode_ns_median"] is None
    assert result["native_encode_mb_per_second_micro"] is None
    assert result["native_decode_observation_count"] == 2
    assert result["native_decode_ns_median"] == 9.5
    assert result["native_timing_boundary"] is None


def test_corpus_native_throughput_requires_every_dataset():
    base = {
        "algorithm_id": "a", "config_id": "c", "execution_path_hash": "e", "profile_id": "p",
        "semantic_comparability_key": "s", "execution_comparability_key": "x",
        "resource_profile_key": "r", "summary_id": "one", "dataset_id": "one",
        "canonical_raw_bits": 800, "final_bits": 400, "encode_ns_median": 100,
        "decode_ns_median": 50, "compression_factor": "2",
        "codec_input_bytes_per_iteration": 120, "native_encode_ns_median": 20,
        "native_decode_ns_median": 10,
    }
    second = {**base, "dataset_id": "two", "summary_id": "two",
              "codec_input_bytes_per_iteration": 240, "native_encode_ns_median": 40}
    result = _corpus_summaries([base, second])[0]
    assert float(result["micro_native_encode_mb_per_second"]) == 360 * 1000 / 60
    second["native_encode_ns_median"] = None
    assert _corpus_summaries([base, second])[0]["micro_native_encode_mb_per_second"] is None
