"""Residual attribution preserves strict original-domain thresholds."""
from fractions import Fraction
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from audit_m3_corad_sparse_residual import above_bound


def test_rounded_ties_are_resolved_using_exact_f64_values():
    small = 2.0**-50
    original = np.array([[16.,16.,16.,-16.,-16.,17.,15.]])
    restored = np.array([[-small,0.,small,small,-small,0.,0.]])
    assert np.abs(original-restored)[0,:5].tolist() == [16.]*5
    assert above_bound(original,restored,Fraction(16)).tolist() == [[True,False,False,True,False,True,False]]


def test_rational_cutoff_between_binary64_values_is_not_rounded_up():
    source = np.array([[1.,1.,1.]])
    restored = np.array([[0.,2.0**-52,2.0**-51]])
    assert above_bound(source,restored,Fraction(1)-Fraction(1,2**53)).tolist() == [[True,False,False]]
