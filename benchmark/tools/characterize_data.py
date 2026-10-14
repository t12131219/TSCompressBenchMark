"""Describe canonical inputs outside all codec/timing boundaries.

CSV decimal places are lexical properties of the frozen tokens, not a claim
about sensor precision. Timestamp arithmetic uses Python integers.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import csv
import hashlib
from math import gcd
from pathlib import Path

import numpy as np

from tsbench.data import array_descriptor, array_order, fingerprint, raw_bytes


MISSING_TOKENS = ('', 'NA', 'NaN', 'nan')


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _number(value):
    value = float(value)
    return value if np.isfinite(value) else None


def floating_column(array: np.ndarray) -> dict:
    """Population descriptors, computed only from finite input values."""
    a = np.asarray(array)
    finite = np.isfinite(a)
    f = a[finite].astype(np.float64)
    tiny = np.finfo(a.dtype).tiny
    result = {
        'count': int(a.size), 'finite_count': int(finite.sum()),
        'nan_count': int(np.isnan(a).sum()),
        'positive_infinity_count': int(np.isposinf(a).sum()),
        'negative_infinity_count': int(np.isneginf(a).sum()),
        'positive_zero_count': int(((a == 0) & ~np.signbit(a)).sum()),
        'negative_zero_count': int(((a == 0) & np.signbit(a)).sum()),
        'subnormal_count': int(((np.abs(a) > 0) & (np.abs(a) < tiny)).sum()),
        'finite_unique_numeric_values': int(np.unique(f).size),
        'finite_min': None, 'finite_max': None, 'finite_mean': None,
        'finite_population_std': None, 'finite_quantiles': None,
        'adjacent_finite_pairs': 0, 'adjacent_equal_pairs': 0,
        'adjacent_absolute_delta_median': None,
        'adjacent_absolute_delta_mean': None,
        'lag1_correlation': None,
        'linear_slope_per_row': None, 'linear_fit_residual_rmse': None,
    }
    with np.errstate(all='ignore'):
        if f.size:
            result.update(finite_min=_number(f.min()), finite_max=_number(f.max()),
                          finite_mean=_number(f.mean()), finite_population_std=_number(f.std(ddof=0)),
                          finite_quantiles={str(q): _number(v) for q, v in zip(
                              (0, .25, .5, .75, 1), np.quantile(f, (0, .25, .5, .75, 1)))})
        pairs = finite[1:] & finite[:-1]
        left, right = a[:-1][pairs].astype(np.float64), a[1:][pairs].astype(np.float64)
        result['adjacent_finite_pairs'] = int(pairs.sum())
        result['adjacent_equal_pairs'] = int((left == right).sum())
        if left.size:
            changes = np.abs(right - left)
            result['adjacent_absolute_delta_median'] = _number(np.median(changes))
            result['adjacent_absolute_delta_mean'] = _number(changes.mean())
        if left.size >= 2 and np.std(left) > 0 and np.std(right) > 0:
            result['lag1_correlation'] = _number(np.corrcoef(left, right)[0, 1])
        x = np.flatnonzero(finite).astype(np.float64)
        if x.size >= 2:
            centered = x - x.mean()
            slope = np.sum(centered * (f - f.mean())) / np.sum(centered**2)
            residual = f - (f.mean() + slope * centered)
            result['linear_slope_per_row'] = _number(slope)
            result['linear_fit_residual_rmse'] = _number(np.sqrt(np.mean(residual**2)))
    return result


def timestamps(array: np.ndarray, time_unit: str | None) -> dict:
    values = [int(x) for x in array]
    deltas = [b - a for a, b in zip(values, values[1:])]
    counts = Counter(deltas)
    mode = min(counts, key=lambda x: (-counts[x], x)) if counts else None
    scale = 0
    bias = min(values, default=0)
    for value in values:
        scale = gcd(scale, value - bias)
    return {
        'count': len(values), 'dtype': array.dtype.str, 'time_unit': time_unit,
        'first': values[0] if values else None, 'last': values[-1] if values else None,
        'minimum': min(values, default=None), 'maximum': max(values, default=None),
        'duplicate_occurrences_global': len(values) - len(set(values)),
        'adjacent_duplicates': counts.get(0, 0),
        'negative_deltas': sum(x < 0 for x in deltas),
        'strictly_increasing': all(x > 0 for x in deltas) if deltas else None,
        'nondecreasing': all(x >= 0 for x in deltas) if deltas else None,
        'delta_min': min(deltas, default=None), 'delta_max': max(deltas, default=None),
        'delta_mode': mode, 'delta_mode_count': counts[mode] if mode is not None else 0,
        'delta_distinct_count': len(counts),
        'deltas_unequal_to_mode': len(deltas) - (counts[mode] if mode is not None else 0),
        'delta_histogram': [{'delta': value, 'count': count} for value, count in sorted(counts.items())],
        'integer_affine_gcd': {'bias': bias, 'scale': scale or 1,
                               'normalized_maximum': (max(values, default=bias)-bias)//(scale or 1)},
        'interpretation': 'original order; Python integer subtraction; no sorting, deduplication or interpolation',
    }


def lexical_precision(tokens) -> dict:
    places = Counter()
    scientific = 0
    missing = 0
    nonfinite = 0
    negative_zero = 0
    count = 0
    for text in tokens:
        count += 1
        if text in MISSING_TOKENS:
            missing += 1
            continue
        try:
            decimal = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f'invalid decimal token: {text!r}') from exc
        if not decimal.is_finite():
            nonfinite += 1
            continue
        scientific += int('e' in text.lower())
        negative_zero += int(decimal.is_zero() and decimal.is_signed())
        places[max(0, -decimal.as_tuple().exponent)] += 1
    return {
        'token_count': count, 'missing_token_count': missing,
        'missing_token_rate': missing/count if count else None,
        'nonfinite_token_count': nonfinite, 'scientific_notation_count': scientific,
        'negative_zero_token_count': negative_zero,
        'decimal_places_histogram': {str(key): value for key, value in sorted(places.items())},
        'maximum_decimal_places': max(places, default=None),
        'scope': 'Decimal exponent of the frozen lexical token, including trailing zeros; not sensor or binary precision',
    }


def source_profile(catalog_entry: dict, corpus: Path, evaluation_start=2048, evaluation_stop=2560):
    """Verify exact source identity and strict field count before statistics."""
    expected = catalog_entry['file']
    path = (corpus / expected['name']).resolve(strict=True)
    digest = sha256(path)
    if digest != expected['sha256'] or path.stat().st_size != expected['bytes']:
        raise ValueError(f"{catalog_entry['id']}: frozen CSV identity drift")
    columns = expected['columns'][1:]
    tokens = {column: [] for column in columns}
    time_values = []
    epoch = datetime(1970, 1, 1)
    with path.open(newline='', encoding='utf-8', errors='strict') as stream:
        reader = csv.reader(stream, delimiter=',', quotechar='"', strict=True)
        if next(reader, None) != expected['columns']:
            raise ValueError(f"{catalog_entry['id']}: frozen header drift")
        for row_index, row in enumerate(reader):
            if len(row) != len(expected['columns']):
                raise ValueError(f"{catalog_entry['id']}: field count at row {row_index}")
            date = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            if date.strftime('%Y-%m-%d %H:%M:%S') != row[0]:
                raise ValueError(f"{catalog_entry['id']}: noncanonical timestamp token at row {row_index}")
            elapsed = date - epoch
            time_values.append((elapsed.days*86400 + elapsed.seconds)*1_000_000_000)
            for column, text in zip(columns, row[1:]):
                if text in MISSING_TOKENS or not np.isfinite(float(text)):
                    raise ValueError(f"{catalog_entry['id']}: missing/nonfinite {column}, row {row_index}")
                tokens[column].append(text)
    if len(time_values) != expected['rows'] or evaluation_stop > len(time_values):
        raise ValueError(f"{catalog_entry['id']}: frozen rows or evaluation bounds drift")
    if sha256(path) != digest:
        raise ValueError(f"{catalog_entry['id']}: source changed during characterization")
    axis = np.array(time_values, dtype='<i8')
    return {
        'id': catalog_entry['id'], 'path': str(path), 'sha256': digest,
        'bytes': path.stat().st_size, 'rows': len(time_values),
        'header': expected['columns'], 'value_dtype': '<f8',
        'timestamp_parser': '%Y-%m-%d %H:%M:%S; naive wall clock relative to 1970-01-01; no timezone conversion',
        'full_source_timestamp_profile': timestamps(axis, 'ns'),
        'evaluation_timestamp_profile': timestamps(axis[evaluation_start:evaluation_stop], 'ns'),
        'columns': {column: {
            'full_source_lexical_precision': lexical_precision(texts),
            'evaluation_lexical_precision': lexical_precision(texts[evaluation_start:evaluation_stop]),
            'full_source_binary64_profile': floating_column(np.array(texts, dtype='<f8')),
        } for column, texts in tokens.items()},
        'license': catalog_entry.get('license'), 'upstream': catalog_entry.get('upstream'),
        'acquisition': catalog_entry.get('acquisition'),
        'raw_data_redistributed': False,
    }


def object_profile(obj, dataset_id: str) -> dict:
    roles = obj.schema.get('roles', {})
    components = {}
    for name, array in obj.components.items():
        role = roles.get(name, name)
        record = {**array_descriptor(array), 'role': role, 'logical_bytes': array.nbytes,
                  'logical_bytes_sha256': hashlib.sha256(array.tobytes(order=array_order(array))).hexdigest()}
        if role == 'V' and array.dtype.kind == 'f':
            matrix = array[:, None] if array.ndim == 1 else array
            record['columns'] = {column: floating_column(matrix[:, index]) for index, column in enumerate(
                obj.schema.get('columns', [str(i) for i in range(matrix.shape[1])]))}
        elif role == 'T':
            record['timestamp_profile'] = timestamps(array, obj.schema.get('time_unit'))
        elif role == 'mask':
            record['missing_count'] = int((array == 0).sum())
            record['missing_rate'] = float((array == 0).mean()) if array.size else None
        components[name] = record
    return {'dataset_id': dataset_id, 'raw_object_id': fingerprint(obj), 'raw_bytes': raw_bytes(obj),
            'schema': dict(obj.schema), 'lineage': dict(obj.lineage), 'components': components,
            'validity_mask_present': any(roles.get(name, name) == 'mask' for name in obj.components),
            'missingness_policy': 'reject source missing tokens; no fabricated all-valid mask'}
