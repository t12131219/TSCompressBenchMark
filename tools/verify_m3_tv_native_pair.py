#!/usr/bin/env python3
"""Replay the real single-value TV comparison and run fail-closed route controls."""
import argparse
from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.smoke import write_new
from tsbench.application.tv import _replay_bundle, report_tv, restore_tv, run_tv
from tsbench.assets import ContractError, content_id, digest, load_json, require, verify_asset
from tsbench.planner.tv import compile_tv
from tsbench.plugins import registrations

NATIVE = 'gorilla-tv'
COMPOSED = 'gorilla-t-gorilla-v'
ALT_T = 'raw-t-gorilla-v'
ALT_V = 'gorilla-t-alp-f64'
METHODS = {NATIVE: ('gorilla-c11',), COMPOSED: ('gorilla-t-c11-derived', 'gorilla-v-c11-derived'),
           ALT_T: ('raw-copy', 'gorilla-v-c11-derived'), ALT_V: ('gorilla-t-c11-derived', 'alpn-auto-encoder')}
CONTROLS = {'native-vs-composed': ('whole_object', None, NATIVE, COMPOSED, None),
            'fixed-t': ('shared_t_controlled', 'fixed_timestamp_route', COMPOSED, ALT_V, 0),
            'fixed-value': ('whole_object', 'fixed_value_route', COMPOSED, ALT_T, 1)}


def reject(action, expected):
    try:
        action()
    except ContractError as exc:
        require(expected in str(exc), f'wrong TV rejection: {exc}')
        return {'reason': str(exc), 'launched': False}
    raise ContractError(f'TV did not reject: {expected}')


def plan_gates(root, plan, wider_suite_path):
    registry = registrations(root)
    out = {}
    # Override only registration input, not planner/runner decisions or source files.
    for plugin in sorted(p['plugin'] for p in plan['profiles'].values()):
        disabled = {**registry, plugin: {**registry[plugin], 'enabled': False}}
        with patch('tsbench.plugins.registrations', return_value=disabled), \
             patch('tsbench.application.tv._one', side_effect=AssertionError('disabled route reached execution')):
            before = set((root / 'results').iterdir())
            out[f'disabled:{plugin}'] = reject(lambda: run_tv(root, plan), f'disabled plugin: {plugin}')
            require(set((root / 'results').iterdir()) == before, 'disabled route created run artifacts')
    with TemporaryDirectory(prefix='.native-tv-gate-', dir=root / 'results') as tmp:
        def compile_bad(label, suite, diagnostic):
            label_path = Path(tmp) / (label + '.json')
            write_new(label_path, suite)
            spec = label_path.relative_to(root).as_posix()
            out[label] = {**reject(lambda: compile_tv(root, spec, plan['build'], plan['recovery']), diagnostic),
                          'suite_id': content_id(suite)}
            # Omit the transient workspace name from the recorded output if applicable.
            out[label]['reason'] = out[label]['reason'].replace(spec, '<probe-suite>')

        suite = deepcopy(plan['suite'])
        suite['profiles']['gorilla-tv']['plugin'] = 'gorilla-t-derived'
        compile_bad('joint_role_replaced_by_t_only', suite, 'plugin role or build configuration incompatible')
        suite = deepcopy(plan['suite'])
        wide = load_json(wider_suite_path)
        suite['cases'] = wide['cases']
        suite['source_groups'] = wide['source_groups']
        require(suite['cases'].keys() == plan['suite']['cases'].keys(), 'five-V negative needs the matching provider cases')
        compile_bad('native_pair_given_five_real_values', suite, 'exactly one value column')
        suite = deepcopy(plan['suite'])
        suite['comparisons']['fixed-t']['methods'] = [COMPOSED, ALT_T]
        compile_bad('fixed_t_route_not_held', suite, 'does not hold one route fixed')
    return out


def _subprojection(root, plan, projection_path, wider_projection_path):
    projection = load_json(projection_path)
    wide = load_json(wider_projection_path)
    for x in (projection, wide):
        require(x['projection_id'] == content_id({k: v for k, v in x.items() if k != 'projection_id'}), 'projection hash differs')
    require(digest(root / plan['suite_path']) == projection['suite_sha256'] and
            projection['groups'].keys() == wide['groups'].keys(), 'projection suite or group identity differs')
    matched = {}
    for name, row in projection['groups'].items():
        full = wide['groups'][name]
        [col] = row['column_mapping']
        col_index = 1 + list(full['column_mapping']).index(col)
        require(row['row_range'] == full['row_range'] and row['original_file'] == full['original_file'] and
                row['column_mapping'][col] == full['column_mapping'][col] and
                row['projected_column_sha256'] == [full['projected_column_sha256'][i] for i in (0, col_index)],
                'native pair projection is not the matching T+single-V subprojection')
        for fmt, manifest in row['manifests'].items():
            verify_asset(root, manifest)
            case = plan['cases'][f'{name}-{fmt}']
            require(case['source']['ingress'] == {'group': name, 'manifest': manifest['path']} and
                    case['lineage']['source_column_sha256'] == row['projected_column_sha256'], 'sealed TV lineage differs from projection')
        matched[name] = {'row_range': row['row_range'], 'original_file': row['original_file'],
                         'selected_value': row['column_mapping'][col], 'original_columns_sha256': row['projected_column_sha256']}
    return matched


def verify(root, run, projection, wider_suite, wider_projection):
    plan, report = load_json(run / 'plan.json'), report_tv(run)
    require(report['verified'] and report['qualification_granted'] is False, 'TV run is not a verified development run')
    slots = {(row['case'], row['method']): row for row in report['slots']}
    require(plan['methods'].keys() == METHODS.keys() and len(slots) == len(report['slots']) and
            slots.keys() == {(case, method) for case in plan['cases'] for method in METHODS}, 'TV method/case census differs')
    require(plan['suite']['chunk_rows'] == 512 and all(case['rows'] == 515 and len(case['column_sha256']) == 2
            for case in plan['cases'].values()), 'single-V or tail geometry differs')
    require(plan['comparisons'].keys() == CONTROLS.keys(), 'control census differs')
    expected_deps = ('libgorilla_c.so',)
    native_profile = plan['profiles'][plan['methods'][NATIVE]['routes']['joint']]
    require(len(native_profile['dependencies']) == len(expected_deps) and
            tuple(Path(ref['path']).name for ref in native_profile['dependencies']) == expected_deps,
            'native TV does not bind Gorilla C11')
    matched = _subprojection(root, plan, projection, wider_projection)
    replay = restore_tv(run)
    restored = {row['slot_id']: row for row in replay['slots']}
    require(len(restored) == len(slots), 'not all TV slots replayed')
    for (_, method), row in slots.items():
        expected = METHODS[method]
        account = row['accounting']
        for direction, calls in row['execution'].items():
            backends = expected if (direction, method) != ('decode', ALT_V) else (expected[0], 'scalar-unfused')
            require(tuple(c['backend'] for c in calls) == backends * 2 and
                    all(c['operation'] == direction and c['mode'] == 'batch' and c['threads'] == 1 for c in calls),
                    'unexpected observed TV batch execution')
        require(account['bundle_bytes'] == row['artifact']['bytes'] == account['container_bytes'] + account['schema_bytes'] + account['stream_bytes'] and
                {s['rows'] for s in account['streams']} == {512, 3} and
                all(s['column_count'] == (2 if method == NATIVE else 1) for s in account['streams']), 'full TV byte bill or geometry differs')
        mount = restored[row['slot_id']]['mounted_decoder_files']
        require(('lib/libgorilla_c.so' in mount) == (method == NATIVE), 'native C11 runtime leaked across TV methods')
    controls = {}
    for label, (task, kind, a, b, column) in CONTROLS.items():
        spec = plan['suite']['comparisons'][label]
        require((spec['task'], spec['control'], set(spec['methods']), set(spec['cases'])) ==
                (task, kind, {a, b}, plan['cases'].keys()), 'wrong TV comparison scope')
        controls[label] = {}
        for case in sorted(plan['cases']):
            left, right = slots[case, a], slots[case, b]
            require(left['restored'] == right['restored'] and label in left['comparisons'] and label in right['comparisons'],
                    'comparison did not restore the same original object')
            def stream_ids(row):
                return [s['sha256'] for s in row['accounting']['streams'] if s['first_column'] == column]
            fixed = stream_ids(left)
            require(column is None or len(fixed) == 2 and fixed == stream_ids(right), 'fixed branch produced different frames')
            controls[label][case] = {'methods': {a: left['artifact'], b: right['artifact']}, 'fixed_stream_sha256': fixed}
    negatives = plan_gates(root, plan, wider_suite)
    for case in sorted(c for c in plan['cases'] if c.endswith('-csv')):
        for a, b in [(NATIVE, COMPOSED), (COMPOSED, NATIVE), (ALT_T, COMPOSED), (ALT_V, COMPOSED)]:
            artifact = slots[case, a]['artifact']
            target = slots[case, b]
            with TemporaryDirectory(prefix='m3-tv-cross-decode-') as tmp:
                work = Path(tmp)
                rc, mounts = _replay_bundle(run, plan, target, verify_asset(run, artifact), work)
                diagnostic = (work / 'stderr').read_text().strip()
                files = sorted(p.name for p in (work / 'out').iterdir())
            require(rc == 3 and 'TV method, layout or schema bound differs' in diagnostic and not files,
                    'cross-method decoder did not reject cleanly')
            negatives[f'{case}:{a}->{b}'] = {'input': artifact, 'decoder_method_id': plan['methods'][b]['method_id'],
                                              'returncode': rc, 'diagnostic': diagnostic, 'published_files': files,
                                              'mounted_decoder_files': mounts}
    return {'schema': 'bmk.m3-real-native-tv-controls/1', 'run_id': report['run_id'], 'seal_id': report['seal_id'],
            'plan_content_id': plan['plan_content_id'], 'same_window_subprojections': matched,
            'controls': controls, 'rejections': negatives, 'restore': replay, 'qualification_granted': False, 'stage_accepted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'projection', 'wider-suite', 'wider-projection', 'out'):
        parser.add_argument(f'--{name}', type=Path, required=True)
    args = parser.parse_args()
    write_new(args.out, verify(ROOT, args.run.resolve(strict=True), args.projection, args.wider_suite, args.wider_projection))


if __name__ == '__main__':
    main()
