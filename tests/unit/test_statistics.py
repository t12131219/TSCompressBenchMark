from decimal import Decimal

import pytest

from tscompbench.configuration import ConfigurationError, load_experiment_config
from tscompbench.statistics import descriptive_statistics, pareto_front, rank_values


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
