from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from audit_m3_corad_zero_gate_shift import classify
from tsbench.assets import ContractError

GATE = {'constant_predictor':'0', 'max_abs_error':'0', 'mse':'0'}

@pytest.mark.parametrize('values,label,count', [([-0.,0.,0.,0.], 'same_as_train', 0),
                                              ([1.,1.,1.,1.], 'different_constant', 1),
                                              ([0.,1.,0.,0.,3.], 'variable', 1)])
def test_distinguishes_real_shift_outside_training_distribution(values, label, count):
    result = classify(np.zeros(8), np.array(values), GATE)
    assert result['classification'] == label
    assert result['complete_tricklets_not_recoverable_by_training_constant'] == count

def test_rejects_nonzero_or_falsely_constant_training_evidence():
    with pytest.raises(ContractError, match='nonempty train and development'):
        classify(np.zeros(8), np.ones(4), {**GATE, 'mse':'1'})
    with pytest.raises(ContractError, match='exact observed constant'):
        classify(np.arange(8), np.ones(4), GATE)
