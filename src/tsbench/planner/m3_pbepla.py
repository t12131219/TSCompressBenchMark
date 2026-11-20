"""Expand the paired PBEPLA input denominator without reopening the source per window."""
from dataclasses import dataclass

from ..assets import require
from .pbepla_execution import CAP, PROGRESSIVE, REPLAY

LAYOUT = {'profile': 'pbepla_original_abs_eps_v1', 'min_rows': 1, 'max_rows': 4096,
          'requested_eps': [16, 4, 1], 'max_delay': 64, 'value_layer_budget': 2097152,
          'max_prefix_frame_bytes': CAP}


@dataclass(frozen=True, slots=True)
class Window:
    column: int
    ordinal: int
    start: int
    end: int

    @property
    def rows(self):
        return self.end - self.start


def windows(entry, progressive, replay):
    """Return every applicable, source-ordered window shared by both native paths."""
    n, cols = entry['rows'], entry['value_count']
    for work, route in ((progressive, PROGRESSIVE), (replay, REPLAY)):
        extent = work['input']
        require((work['selection'], work['route'], work['dataset_id'], work['canonical_object_id'], work['applicability']) ==
                (87, route, entry['id'], entry['canonical']['object_id'], 'input_domain_matches') and
                extent['representation'] == 'f64_columns' and extent['value_column_range'] == [0, cols] and
                len(extent['row_ranges']) == 1 and (extent['row_ranges'][0]['start'], extent['row_ranges'][0]['end']) == (0, n),
                'PBEPLA file or value-column identity differs from accepted corpus scope')
    batch_input, replay_input = (w['input'] for w in (progressive, replay))
    contract, other = (w['pbepla_contract'] for w in (batch_input, replay_input))
    require(contract == {**other, 'replay': None} and contract['layout'] == LAYOUT and
            contract['row_coordinates'] == 'absolute_zero_based_half_open' and
            other['replay'] == {'native_same_window_as_batch': True, 'verify_identical_full_frame': True,
                'online_input': False, 'observe_actual_passes_retries_first_sink_and_logical_temp_traffic': True},
            'PBEPLA batch and replay contracts must use the same frozen window geometry and replay policy')
    overrides = {g['value_column_index']: g for g in contract['column_overrides']}
    require(len(overrides) == len(contract['column_overrides']) and all(0 <= i < cols for i in overrides),
            'PBEPLA column override closure differs')
    result = []
    for col in range(cols):
        group = overrides.get(col, contract['default_column'])
        spans = sorted([(r['rows'], r) for r in group['accepted_spans']] + [(r['rows'], None) for r in group['excluded_spans']],
                       key=lambda p: p[0])
        cursor = ordinal = 0
        for (start, end), details in spans:
            require(start == cursor and start < end <= n, 'PBEPLA spans overlap or leave an undeclared gap')
            cursor = end
            if details is None:
                continue
            count, base, extra = (details[k] for k in ('windows', 'base_rows', 'first_windows_with_one_extra_row'))
            require(count > 0 and 0 <= extra < count and end-start == count*base+extra and
                    1 <= base <= base+bool(extra) <= 4096 and (base+bool(extra))*len(LAYOUT['requested_eps']) <= LAYOUT['value_layer_budget'],
                    'PBEPLA balanced window is outside the frozen extent or regression budget')
            for i in range(count):
                stop = start + base + (i < extra)
                result.append(Window(col, ordinal, start, stop))
                start = stop
                ordinal += 1
        require(cursor == n, 'PBEPLA column coverage does not close at source extent')
    executed = (len(result), 8*sum(w.rows for w in result), 8*max((w.rows for w in result), default=0))
    keys = ('input_units', 'native_input_bytes_one_pass', 'largest_input_unit_bytes')
    require(result and all(executed == tuple(w['size_estimate'][k] for k in keys) for w in (batch_input,replay_input)),
            'PBEPLA expanded windows differ from the planned denominator')
    return result

DRIVER = 'pbepla-corpus-control/1'
ROUTES = {(87, PROGRESSIVE), (87, REPLAY)}
SOURCES = ('plugins/codecs/pbepla-rr/corpus_control.cpp', 'cmake/pbepla-corpus.cmake',
           'src/tsbench/planner/m3_pbepla.py', 'src/tsbench/application/m3_pbepla.py',
           'src/tsbench/application/m3_sprintz_query.py', 'src/tsbench/qualification/pbepla_progressive.py')


def bind_corpus(root, build):
    from pathlib import Path
    from ..assets import digest, local_file, verify_asset
    plugin = build['plugins']['pbepla-rr']
    folder = Path(plugin['library']['path']).parent
    path = (folder / 'tsbench_pbepla_corpus_control').as_posix()
    if not (root / path).is_file():
        return None
    dependency = (folder / 'libtba_native.so').as_posix()
    require(len(plugin['dependencies']) == 1 and plugin['dependencies'][0]['path'] == dependency,
            'PBEPLA corpus and plugin must share the locked Unique native library')
    path_on_disk = verify_asset(root, plugin['dependencies'][0])
    executable = local_file(root, path)
    def ref(rel, asset):
        return {'path': rel, 'bytes': asset.stat().st_size, 'sha256': digest(asset)}
    return {'executable': ref(path, executable), 'dependency': ref(dependency, path_on_disk),
            'code': {p: digest(local_file(root, p)) for p in SOURCES}}


def check_route(binding):
    require(binding['view'] == 'f64_columns' and binding['partition'] == 'full' and binding['options'] == {} and
            binding.get('rows_per_unit') is None and binding['missing'] == 'require_no_retained_sentinel' and
            binding['prefix_layout'] == LAYOUT and binding['operation'] ==
            {PROGRESSIVE: 'each_prefix_restore', REPLAY: 'bounded_source_rewind_and_prefix_restore'}[binding['route']],
            'PBEPLA corpus route changed from the accepted profile')
