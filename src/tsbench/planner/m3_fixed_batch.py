"""Frozen call geometry and execution identity for six M3 batch routes."""

from ..assets import digest, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock

DRIVER = 'm3-fixed-batch-detached/1'
DIRECTORY = 'fixed-batch-runtime'
SAMPLE_DIRECTORY = 'fixed-batch-samples'
RETENTION = {'selection': 'first_unit_and_first_short_unit_if_distinct', 'directory': SAMPLE_DIRECTORY,
             'addressing': 'sha256_frame', 'decode_inputs': 'frame_and_frozen_runtime_only'}
LIMITS = {'address_space_bytes': 1 << 30, 'file_bytes': 1 << 20, 'wall_seconds': 30}
SCALAR = 'scalar-unfused'
AUTO = 'falp-auto'
ROUTES = {
    (9, 'auto-batch'): ('alp-auto', {'encode': 'auto'}, (SCALAR,)),
    (9, 'decode-backends'): ('alp-auto', {'decode': [SCALAR, AUTO],
                                         'conditional_dispatch': 'see_native_obligations'}, (SCALAR, AUTO)),
    (11, 'source-auto'): ('pcodec-source-auto', {}, ('default',)),
    (11, 'c-native-auto'): ('pcodec-c-native-auto', {}, ('default',)),
    (39, 'xz-baseline'): ('xz-baseline', {'preset': 6}, ('default',)),
    (40, 'zstd-baseline'): ('zstd', {'level': 3}, ('default',)),
}


def bind(root, build, definition):
    seen = set()
    for route in definition['routes']:
        rule = route['binding']
        key = rule['selection'], rule['route']
        if key not in ROUTES:
            continue
        _, options, backends = ROUTES[key]
        is_bytes = key[0] in (39, 40)
        require(rule['partition'] == 'full' and rule['options'] == options and
                rule['operation'] == ('decode_common_frame' if len(backends) > 1 else 'roundtrip') and
                rule['view'] == ('v_bytes_interleaved' if is_bytes else 'f64_columns') and
                rule.get('bytes_per_unit' if is_bytes else 'rows_per_unit') == 65536,
                f'unexpected M3 fixed batch route contract: {key}')
        seen.add(key)
    require(seen == ROUTES.keys(), 'incomplete M3 fixed batch route binding')
    code = ('planner/m3_fixed_batch.py', 'application/m3_fixed_batch.py', 'application/m3_real_corpus_execution.py',
            'recovery.py', 'supervisor/isolated_worker.py', 'supervisor/process.py', 'application/smoke.py')
    return {'driver': DRIVER, 'decoder': plan_recovery(root, build, {r[0] for r in ROUTES.values()}),
            'launchers': launcher_lock(), 'limits': LIMITS.copy(), 'retention': RETENTION.copy(),
            'code': {p: digest(root / 'src/tsbench' / p) for p in code}}


def units(item):
    """Yield exact logical coordinates, not a count/size approximation."""
    view = item['input']
    row, = view['row_ranges']
    columns = view['value_column_range']
    extent = view['slice_extent']
    require(view['full_extent_of_file_rows_and_value_columns'] and row['start'] == columns[0] == 0 and
            not view['skipped_row_ranges'] and row['end'] > 0 and columns[1] > 0 and extent['max_per_unit'] == 65536,
            'unexpected M3 fixed batch dataset extent')
    cap = extent['max_per_unit']
    if item['view'] == 'v_bytes_interleaved':
        require(extent['unit'] == 'byte_span' and view['column_grouping'] == 'all_values_interleaved',
                'unexpected M3 fixed byte grouping')
        size = row['end'] * columns[1] * 8
        for start in range(0, size, cap):
            end = min(start + cap, size)
            yield {'byte_range': [start, end], 'input_bytes': end - start}
    else:
        require(item['view'] == 'f64_columns' and extent['unit'] == 'row_span' and
                view['column_grouping'] == 'one_work_unit_series_per_value_column', 'unexpected M3 fixed column grouping')
        for column in range(columns[1]):
            for start in range(0, row['end'], cap):
                end = min(start + cap, row['end'])
                yield {'column': column, 'row_range': [start, end], 'input_bytes': (end - start) * 8}


def sample_indices(item):
    """Select representatives from pre-run geometry, not size or speed outcomes."""
    width = 1 if item['view'] == 'v_bytes_interleaved' else 8
    cap = item['input']['slice_extent']['max_per_unit'] * width
    first_short = next((i for i, u in enumerate(units(item)) if u['input_bytes'] < cap), 0)
    return (0, first_short) if first_short else (0,)
