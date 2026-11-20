"""Native ZFP real-corpus units: reversible fields and fixed-rate array windows."""
from hashlib import sha256
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import numpy as np

from ..assets import canonical_bytes, parse_json, require
from ..planner.zfp_execution import THREAD_ENV

MAX_ARRAY_ROWS = 4096
ARRAY_LAYOUT = {'profile': 'zfp_f64_array_mutation_v1', 'min_rows': 8, 'max_rows': MAX_ARRAY_ROWS,
                'requested_rate': 18, 'expected_effective_rate': 32,
                'quality': {'absolute_floor': 1e-5, 'relative_to_expected': 1e-6}}
PROFILES = {'serial': (0, 1, 0), 'omp1': (1, 1, 64), 'omp2': (1, 2, 64)}


def array_windows(contract, cols, rows):
    """Expand only locked, balanced spans; do not re-segment or include gaps."""
    require(contract['layout'] == ARRAY_LAYOUT and contract['row_coordinates'] == 'absolute_zero_based_half_open',
            'ZFP array layout differs from the frozen profile')
    overrides = {g['value_column_index']: g for g in contract['column_overrides']}
    require(len(overrides) == len(contract['column_overrides']) and all(0 <= k < cols for k in overrides),
            'invalid ZFP array column overrides')
    for col in range(cols):
        group = overrides.get(col, contract['default_column'])
        spans = sorted([(x['rows'], True, x) for x in group['accepted_spans']] +
                       [(x['rows'], False, x) for x in group['excluded_spans']], key=lambda x: x[0])
        cursor = 0
        for (start, end), accepted, spec in spans:
            require(start == cursor and start < end <= rows, 'ZFP array span has a gap or overlap')
            cursor = end
            if not accepted:
                continue
            count, base, extras = (spec[k] for k in ('windows', 'base_rows', 'first_windows_with_one_extra_row'))
            require(count > 0 and 0 <= extras < count and end - start == base * count + extras and
                    8 <= base <= base + bool(extras) <= MAX_ARRAY_ROWS,
                    'invalid ZFP array balanced window geometry')
            for i in range(count):
                stop = start + base + (i < extras)
                yield col, start, stop
                start = stop
        require(cursor == rows, 'ZFP array column does not close at the planned end')


def _call(control, folder, *args):
    proc = subprocess.run([str(control), *map(str, args)], cwd=folder,
                          env={'LC_ALL': 'C', **THREAD_ENV}, capture_output=True, text=True, timeout=30)
    require(proc.returncode == 0 and not proc.stderr, f'ZFP {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}')
    return parse_json(proc.stdout, 'ZFP native corpus control')


def _f64(raw):
    return np.frombuffer(raw, dtype='<f8')


def _ref(raw):
    return {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}


def _field_record(n, length, profile):
    execution, threads, blocks = PROFILES[profile]
    return {'rows': n, 'frame_bytes': length, 'execution': execution, 'configured_threads': threads,
            'chunk_blocks': blocks, 'decode_execution': 0}


def _reopen(control, work, operation, wire, n):
    # A new process receives only a local wire file and the declared row count.
    # This is a detached corpus preflight, not a Bubblewrap qualification run.
    with TemporaryDirectory(prefix='zfp-reopen-', dir=work) as tmp:
        folder = Path(tmp)
        (folder / 'wire').write_bytes(wire)
        observed = _call(control, folder, operation, n, 'wire')
        require({p.name for p in folder.iterdir()} == {'wire', 'values'}, 'ZFP reopen output closure differs')
        return (folder / 'values').read_bytes(), observed


def field_unit(control, work, raw, *, openmp=False):
    """Run each declared profile on the very same full-column bytes."""
    require(0 < len(raw) <= 1 << 20 and len(raw) % 8 == 0, 'invalid ZFP field input span')
    n = len(raw) // 8
    profiles, products = {}, {}
    for policy in (PROFILES if openmp else ('serial',)):
        with TemporaryDirectory(prefix='zfp-field-', dir=work) as tmp:
            folder = Path(tmp)
            (folder / 'input').write_bytes(raw)
            encoded = _call(control, folder, 'field-encode', n, 'input', policy)
            wire = (folder / 'frame').read_bytes()
        require(len(wire) > 0 and len(wire) % 8 == 0 and encoded == _field_record(n, len(wire), policy),
                'ZFP field payload extent or active encoder policy differs')
        restored, decoded = _reopen(control, work, 'field-restore', wire, n)
        require(restored == raw and decoded == _field_record(n, len(wire), 'serial'),
                'ZFP full-field detached restore differs in bits or policy')
        metadata = canonical_bytes({'format': 'zfp-raw-reversible-v1', 'type': 'f64', 'shape': [n]})
        profiles[policy] = {'encode': encoded, 'restore': decoded, 'frame': _ref(wire), 'metadata': _ref(metadata),
                            'artifact_bytes': len(wire) + len(metadata), 'restored': _ref(restored)}
        products[policy] = {'frame': wire, 'metadata.json': metadata}
    return {'profiles': profiles, 'same_field': _ref(raw),
            'identical_payloads': len({p['frame']['sha256'] for p in profiles.values()}) == 1}, products


def _quality(expected, restored):
    if not np.all(np.isfinite(restored)):
        return {'accepted': False, 'nonfinite_restored': int(np.count_nonzero(~np.isfinite(restored)))}
    with np.errstate(over='ignore'):
        errors = np.abs(restored - expected)
    policy = ARRAY_LAYOUT['quality']
    limits = np.maximum(policy['absolute_floor'], policy['relative_to_expected'] * np.abs(expected))
    n_bad = int(np.count_nonzero(errors > limits))
    return {'accepted': n_bad == 0, 'violations': n_bad,
            'max_abs_error': float(np.max(errors)) if np.all(np.isfinite(errors)) else None}


def array_evidence(raw, before, after, baseline, restored):
    """Validate trusted reopened arrays against original-domain values and immutable blocks."""
    n = len(raw) // 8
    wire_bytes = 16 * ((n + 3) // 4)
    require(8 <= n <= MAX_ARRAY_ROWS and len(raw) == len(baseline) == len(restored) == n * 8 and
            len(before) == len(after) == wire_bytes, 'ZFP array frame or restored extent differs')
    original = _f64(raw)
    require(np.all(np.isfinite(original)), 'ZFP fixed-rate array input must be finite')
    expected = original.copy()
    expected[1] = original[-1]
    expected[3:7] = original[0:4]
    # The frozen writes touch only the first two native 4-value blocks.
    require(before[32:] == after[32:] and baseline[64:] == restored[64:],
            'ZFP write changed an untouched array block')
    initial, updated = _quality(original, _f64(baseline)), _quality(expected, _f64(restored))
    return {'before': initial, 'after': updated, 'quality_passed': initial['accepted'] and updated['accepted'],
            'unchanged_native_blocks': (wire_bytes - 32) // 16,
            'exact_mutated_reference': _ref(expected.tobytes())}


def array_unit(control, work, raw, *, retained_sentinel=False):
    n = len(raw) // 8
    require(len(raw) == n * 8 and 8 <= n <= MAX_ARRAY_ROWS, 'ZFP array input outside frozen window limits')
    original = _f64(raw)
    require(np.all(np.isfinite(original)) and (not retained_sentinel or not np.any(original == -9999)),
            'ZFP array window includes a nonfinite value or retained sentinel')
    with TemporaryDirectory(prefix='zfp-array-', dir=work) as tmp:
        folder = Path(tmp)
        (folder / 'input').write_bytes(raw)
        observed = _call(control, folder, 'array-update', n, 'input')
        before, after = ((folder / name).read_bytes() for name in ('before', 'after'))
    baseline, reopened_before = _reopen(control, work, 'array-reopen', before, n)
    restored, reopened_after = _reopen(control, work, 'array-reopen', after, n)
    expected = {'rows': n, 'frame_bytes': 16 * ((n + 3) // 4), 'requested_rate': 18, 'effective_rate': 32}
    require(observed == reopened_before == reopened_after == expected, 'ZFP array rate or shape differs after reopen')
    metadata = canonical_bytes({'format': 'zfp-array-rank1-v1', 'type': 'f64', 'shape': [n], 'requested_rate': 18,
                                'effective_rate': 32})
    return {**array_evidence(raw, before, after, baseline, restored), 'config': observed,
            'before_frame': _ref(before), 'after_frame': _ref(after), 'metadata': _ref(metadata),
            'input': _ref(raw), 'restored': _ref(restored), 'artifact_bytes': len(after) + len(metadata)}, {
                'before': before, 'after': after, 'metadata.json': metadata}


def run_corpus(root, plan, item, entry, work, run):
    from ..assets import local_file
    from ..planner.m3_zfp import DRIVER
    from .m3_sprintz_query import _stage

    route = item['route']
    array = route == 'fixed-rate-array'
    openmp = route == 'openmp-encode'
    cols, rows, extent = entry['value_count'], entry['rows'], item['input']
    row_ranges = extent['row_ranges']
    require(extent['representation'] == 'f64_columns' and extent['value_column_range'] == [0, cols] and
            len(row_ranges) == 1 and (row_ranges[0]['start'], row_ranges[0]['end']) == (0, rows),
            'ZFP frozen corpus input differs from the complete stored source')
    if array:
        geometry = array_windows(extent['array_contract'], cols, rows)
    else:
        require(extent['full_extent_of_file_rows_and_value_columns'] and extent['slice_extent']['max_per_unit'] is None,
                'ZFP reversible field requires one full column per unit')
        geometry = ((col, 0, rows) for col in range(cols))
    control = local_file(root, plan['build']['zfp_corpus']['executable']['path'])
    paths = _stage(root, entry, work / 'values')
    records, sample, rejected = [], None, 0
    profile_bytes = {profile: 0 for profile in (PROFILES if openmp else ('serial',))} if not array else {}
    for col, start, stop in geometry:
        with paths[col].open('rb') as staged:
            staged.seek(start * 8)
            raw = staged.read((stop - start) * 8)
        require(len(raw) == (stop - start) * 8, 'ZFP staged input cut short')
        if array:
            evidence, products = array_unit(control, work, raw,
                    retained_sentinel=entry['parser']['missing'] == 'retain_source_minus_9999')
            passes = evidence['quality_passed']
            rejected += not passes
            sample_files = products
        else:
            evidence, products = field_unit(control, work, raw, openmp=openmp)
            for profile, observation in evidence['profiles'].items():
                profile_bytes[profile] += observation['artifact_bytes']
            sample_files = {f'{profile}.{name}': data for profile, files in products.items() for name, data in files.items()}
            passes = True
        records.append({'column': col, 'row_range': [start, stop], 'logical_input_bytes': len(raw), **evidence})
        # Keep the first object, but replace a passing array sample with a failing one if present.
        if sample is None or sample['quality_passed'] and not passes:
            rel = Path('retained') / item['work_item_id']
            (run / rel).mkdir(parents=True, exist_ok=True)
            for name, data in sample_files.items():
                (run / rel / name).write_bytes(data)
            sample = {'column': col, 'row_range': [start, stop], 'quality_passed': passes,
                      'parts': {name: {'path': (rel / name).as_posix(), **_ref(data)} for name, data in sample_files.items()}}
    sizes = extent['size_estimate']
    nbytes = sum(unit['logical_input_bytes'] for unit in records)
    require(sample and (len(records), nbytes, max(u['logical_input_bytes'] for u in records)) ==
            (sizes['input_units'], sizes['native_input_bytes_one_pass'], sizes['largest_input_unit_bytes']),
            'ZFP executed units differ from the frozen input accounting')
    return {'driver': DRIVER, 'units': records, 'columns': cols, 'input_bytes_one_pass': nbytes,
            'retained_sample': sample, 'quality_rejected_units': rejected,
            'artifact_bytes': sum(r['artifact_bytes'] for r in records) if array else profile_bytes,
            'input_domain': 'bounded_balanced_windows' if array else 'full_reversible_columns',
            'worker_evidence': 'configured_policy_only' if openmp else None,
            'timing_admitted': False}
