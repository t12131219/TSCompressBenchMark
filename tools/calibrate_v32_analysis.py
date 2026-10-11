#!/usr/bin/env python3
"""Simulate paired process noise; this calibration is not performance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.comparison.analysis import AnalysisPolicy, _effect  # noqa: E402
from tscompbench.ids import canonical_json_bytes  # noqa: E402


def simulate(*, experiments=400, bootstrap_samples=1000, seed=20261010):
    rng = np.random.default_rng(seed)
    policy = AnalysisPolicy(bootstrap_samples=bootstrap_samples)
    scenarios = []
    for n in (8, 32):
        for shared_sigma, individual_sigma in ((0.15, 0.08), (0.5, 0.25)):
            covered = decisions = precise = 0
            for i in range(experiments):
                shared = rng.normal(0, shared_sigma, n)
                a = np.exp(shared + rng.normal(0, individual_sigma, n))
                b = np.exp(shared + rng.normal(0, individual_sigma, n))
                effect = _effect(
                    dict(enumerate(a)),
                    dict(enumerate(b)),
                    replace(policy, seed=seed + i),
                    1,
                    f"calibration-{n}-{shared_sigma}-{i}",
                )
                low, high = effect["confidence_interval"]
                covered += low <= 1 <= high
                decisions += effect["status"] in {"FIRST_MEMBER_FASTER", "SECOND_MEMBER_FASTER"}
                precise += effect["precision_achieved"]
            scenarios.append(
                {
                    "independent_schedule_blocks": n,
                    "shared_log_noise_sigma": str(shared_sigma),
                    "method_log_noise_sigma": str(individual_sigma),
                    "experiments": experiments,
                    "truth": "RATIO_OF_POPULATION_MEANS_1",
                    "empirical_coverage": str(covered / experiments),
                    "false_winner_fraction": str(decisions / experiments),
                    "precision_achieved_fraction": str(precise / experiments),
                    "coverage_monte_carlo_standard_error": str(
                        np.sqrt((covered / experiments) * (1 - covered / experiments) / experiments)
                    ),
                }
            )
    return {
        "schema_version": "tscb.analysis-simulation-calibration.v1",
        "seed": seed,
        "rng": "numpy.PCG64",
        "policy": policy.to_document(),
        "scenarios": scenarios,
        "scope": "FINITE_LOGNORMAL_PAIRED_PROCESS_MODELS_NOT_A_UNIVERSAL_COVERAGE_GUARANTEE",
        "correlation_unit": "SHARED_NOISE_PER_SCHEDULE_BLOCK",
        "source_population_inference": False,
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "analysis_sha256": hashlib.sha256(
            (ROOT / "src/tscompbench/comparison/analysis.py").read_bytes()
        ).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--experiments", type=int, default=400)
    args = parser.parse_args()
    if args.experiments < 100:
        parser.error("at least 100 independent simulation experiments are required")
    result = simulate(experiments=args.experiments)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(canonical_json_bytes(result) + b"\n")
    print(json.dumps(result["scenarios"]))


if __name__ == "__main__":
    main()
