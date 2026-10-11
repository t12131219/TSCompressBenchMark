import numpy as np

from tscompbench.comparison.analysis import AnalysisPolicy, _effect


def test_correlated_process_bootstrap_retains_pairing_and_reasonable_coverage():
    rng = np.random.default_rng(91827)
    policy = AnalysisPolicy(bootstrap_samples=800)
    for n in (8, 32):
        covered = 0
        for i in range(200):
            common = rng.normal(0, 0.15, n)
            a = np.exp(common + rng.normal(0, 0.08, n))
            b = np.exp(common + rng.normal(0, 0.08, n))
            effect = _effect(dict(enumerate(a)), dict(enumerate(b)), policy, 1, str(i))
            low, high = effect["confidence_interval"]
            covered += low <= 1 <= high
            assert effect["paired_blocks"] == n
            assert effect["resampling_unit"] == "SCHEDULE_BLOCK"
        assert 0.88 <= covered / 200 <= 0.995


def test_identical_and_sub_practical_effects_do_not_get_declared_winners():
    policy = AnalysisPolicy(bootstrap_samples=500)
    a = {str(k): 100.0 + k for k in range(8)}
    for multiplier in (1, 1.01):
        b = {k: v * multiplier for k, v in a.items()}
        effect = _effect(a, b, policy, 1, "small-effect")
        assert effect["status"] in {"WITHIN_REGISTERED_PRACTICAL_MARGIN", "INCONCLUSIVE"}
