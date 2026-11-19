"""Exact original-domain empirical quality policy for the first CORAD case."""
from fractions import Fraction
import math
import struct

from .assets import require

POLICY = {
    'schema':'bmk.corad-quality-policy/1', 'scope':'empirical_on_frozen_heldout_only',
    'calibration':'frozen_train_window_only', 'reference':'per_column_exact_arithmetic_mean_constant_predictor',
    'bounds':['training_reference_max_abs_error','training_reference_mean_squared_error'],
    'combine':'all_metrics_all_columns_inclusive', 'on_exceedance':'reject_quality_not_comparable',
    'units':{'pressure':'mbar','air_temperature':'degC','relative_humidity':'percentage_point'},
}


def _column(raw):
    require(0 < len(raw) <= 8192*8 and len(raw)%8 == 0, 'CORAD quality column extent differs')
    vals = [x for (x,) in struct.iter_unpack('<d',raw)]
    require(all(math.isfinite(x) for x in vals), 'CORAD quality column contains nonfinite values')
    return [Fraction(x) for x in vals]


def _errors(left, right):
    diffs = [abs(a-b) for a,b in zip(left,right,strict=True)]
    return max(diffs), sum(x*x for x in diffs)/len(diffs)


def calibrate(columns, data, policy):
    """The caller must supply only the frozen train partition, never codec output."""
    require(policy == POLICY and set(columns) == set(policy['units']) and len(columns) == len(policy['units']),
            'CORAD quality calibration policy or ordered columns differ')
    out = []
    for name,raw in zip(columns,data,strict=True):
        values = _column(raw)
        mean = sum(values)/len(values)
        maximum,mse = _errors(values,[mean]*len(values))
        out.append({'column':name,'unit':policy['units'][name],'reference_mean':str(mean),
                    'max_abs_error_limit':str(maximum),'mse_limit':str(mse)})
    return out


def assess(bounds, original, restored):
    rows = []
    for bound, a, b in zip(bounds,original,restored,strict=True):
        require(len(a) == len(b),'CORAD quality original/recovered column extents differ')
        maximum,mse = _errors(_column(a),_column(b))
        max_ok = maximum <= Fraction(bound['max_abs_error_limit'])
        rmse_ok = mse <= Fraction(bound['mse_limit'])  # Strictly monotone sqrt; no rounded boundary comparisons.
        rows.append({'column':bound['column'],'unit':bound['unit'],'max_abs_error_exact':str(maximum),'mse_exact':str(mse),
                     'max_abs_passed':max_ok,'rmse_passed':rmse_ok})
    require(bool(rows),'CORAD quality has no columns')
    return {'decision':'passed' if all(c['max_abs_passed'] and c['rmse_passed'] for c in rows) else 'quality_rejected',
            'columns':rows}
