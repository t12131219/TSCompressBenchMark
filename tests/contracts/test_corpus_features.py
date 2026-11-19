from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.analysis.corpus_features import _boundary_features, _fixtures, _pearson, _time, _value
from tsbench.corpus import BOUNDARY_GENERATOR, load_feature_policy


class CorpusFeatureTests(unittest.TestCase):
    def test_regular_axis_and_gap_count_preserve_order(self):
        self.assertTrue(_time(np.array([1, 3, 5]), 2, 4)["regular"])
        time = _time(np.array([-5, 0, 0, 8, 7]), 2, 4)
        self.assertEqual((time["negative"], time["duplicate_steps"], time["backward_steps"], time["large_gaps"]),
                         (1, 1, 1, 1))
        self.assertFalse(time["regular"])
        self.assertIsNone(_time(np.array([1, 3]), None, 4)["large_gaps"])

    def test_constant_trend_jump_period_and_sparsity_are_distinct(self):
        p = load_feature_policy(ROOT)[0]["thresholds"]
        self.assertEqual(_value(np.zeros(64), p, None)["traits"], ["constant", "sparse_zero"])
        x = np.arange(64, dtype=float)
        x[32:] += 1024
        profile = _value(x, p, None)
        self.assertEqual(profile["jump_count"], 1)
        self.assertEqual(profile["traits"], ["trend_indicator", "jump_indicator"])
        pattern = np.tile(np.array([0., 2., 1., 3.]), 32)
        self.assertIn("periodicity_indicator", _value(pattern, p, 4)["traits"])
        self.assertNotIn("periodicity_indicator", _value(pattern, p, None)["traits"])
        x[6] = np.nan
        self.assertEqual(_value(x, p, None)["finite_adjacent_deltas"], len(x) - 3)
        self.assertEqual(_value(np.full(8, 2.), p, None)["traits"], [])

    def test_pearson_preserves_pairing_and_rejects_constants(self):
        x = np.arange(64, dtype=float)
        self.assertEqual(_pearson(x, np.zeros_like(x), 32), (None, 64))
        self.assertEqual(_pearson(x[:31], x[:31], 32), (None, 31))
        y = -x
        y[1] = np.nan
        self.assertEqual(_pearson(x, y, 32), (-1_000_000, 63))
        self.assertEqual(_pearson(np.array([-1e308, 0., 1e308]), np.array([-3., 0., 3.]), 3), (1_000_000, 3))

    def test_synthetic_extrema_and_special_bits_are_read_from_fixtures(self):
        policy, _ = load_feature_policy(ROOT)
        _, (tv, floats, ints) = _fixtures(ROOT, policy)
        self.assertEqual((tv["time"]["negative"], tv["value_negative_zero"]), (1, 1))
        self.assertEqual((floats["nan"], floats["infinity"], floats["subnormal"]), (2, 2, 1))
        self.assertEqual((ints["min"], ints["max"]), (-(1 << 63), (1 << 63) - 1))

    def test_boundary_fixture_generation_and_decoded_semantics(self):
        policy, _ = load_feature_policy(ROOT)
        directory = (ROOT / policy["boundary_manifest"]).parent
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            subprocess.run([sys.executable, "-B", str(ROOT / BOUNDARY_GENERATOR), "--out", str(out)], cwd="/", check=True)
            self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()},
                             {p.name: p.read_bytes() for p in out.iterdir()})
        boundary, marks = _boundary_features(ROOT, policy)
        self.assertEqual(boundary["integer_extrema"]["u64"]["max"], 2**64 - 1)
        self.assertEqual(boundary["spatial_fields"]["tensor"]["shape"], [2, 3, 5])
        series = boundary["different_axes"][1]
        self.assertEqual((series["missing_rows"], series["valid_nan_rows"]), ([1, 3], [4]))
        self.assertIn(("structure", "different_lengths", "different-axes-object"), marks)
        self.assertIn(("numeric", "trend_indicator", "trend"), marks)
        self.assertFalse(any(axis == "domains" or axis == "size" for axis, _, _ in marks))
