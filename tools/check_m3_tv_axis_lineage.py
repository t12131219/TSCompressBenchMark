#!/usr/bin/env python3
"""Cross-check the two sealed runs' inputs without joining their observations or receipts."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_axis_roles import audit_roles
from tsbench.application.smoke import write_new
from tsbench.application.tv import report_tv
from tsbench.assets import load_json, require
from tsbench.planner.m3_axis_roles import file_ref, projection_doc, source_cases

CONTROL = {
    'fixed-t-direct-vs-limbs': ('shared_t_controlled', 'fixed_timestamp_route', 'timestamp',
                               'gorilla-t', {'gorilla-t-alp-f64', 'gorilla-t-fire-u16'}),
    'fixed-value': ('whole_object', 'fixed_value_route', 'value',
                    'alp-f64', {'gorilla-t-alp-f64', 'raw-t-alp-f64'}),
}


def check(root, axis_run, tv_run, tv_replay_path):
    axis_audit, tv_report = audit_roles(axis_run), report_tv(tv_run)
    axis, tv = (load_json(run / 'plan.json') for run in (axis_run, tv_run))
    replay = load_json(tv_replay_path)
    require(replay['schema'] == 'bmk.dev-tv-restore/1' and replay['isolation'] == 'files_only_bubblewrap' and
            (replay['run_id'], replay['seal_id']) == (tv_report['run_id'], tv_report['seal_id']) and
            replay['qualification_granted'] is False and tv_report['verified'], 'TV replay does not identify the verified sealed run')
    restored = {slot['slot_id']: slot for slot in replay['slots']}
    slots = {(slot['case'], slot['method']): slot for slot in tv_report['slots']}
    require(len(restored) == len(replay['slots']) == replay['restored_slots'] == len(slots) == len(tv_report['slots']) and
            restored.keys() == {slot['slot_id'] for slot in slots.values()}, 'TV replay slot census differs')
    for slot in slots.values():
        independently_restored = restored[slot['slot_id']]
        require(independently_restored['artifact'] == slot['artifact'] and
                all(independently_restored[k] == v for k, v in slot['restored'].items()), 'TV replay original object differs')

    projection = projection_doc(root, axis['projection'])
    roles = {(case['group'], case['format'], case['task']): case for case in axis['cases']}
    require(len(roles) == len(axis['cases']) and tv['suite']['chunk_rows'] == axis['policy']['chunk_rows'],
            'TV and axis provider census or chunk rows differ')
    records = []
    for group, fmt, manifest, lineage, _ in source_cases(root, projection):
        case = f'{group}-{fmt}'
        fixture = tv['cases'][case]
        require(fixture['source']['ingress'] == {'group': group, 'manifest': manifest['path']} and
                fixture['lineage'] == lineage, 'TV source ingress does not match the locked projection')
        t, v = (roles.pop((group, fmt, task)) for task in ('timestamps_only', 'values_only'))
        original = lineage['ingestion']['object']
        for row, columns in ((t, [original['timestamp']]), (v, original['values'])):
            require(row['manifest'] == manifest and row['schema']['rows'] == original['rows'] == fixture['rows'] and
                    row['schema']['columns'] == columns and
                    all(row[k] == lineage[k] for k in ('ingestion_id', 'source_group_id')),
                    'axis schema, source provider or identity differs from the TV projection')
        require(t['original_columns_sha256'] + v['original_columns_sha256'] == lineage['source_column_sha256'],
                'axis original-domain hashes do not reconstruct the TV projection')
        records.append({'case': case, 'source_group_id': lineage['source_group_id'], 'provider_manifest': manifest,
                        'canonical_tv_id': lineage['canonical_dataset_hash'], 'original_file': projection['groups'][group]['original_file'],
                        'row_range': projection['groups'][group]['row_range'], 'original_columns_sha256': lineage['source_column_sha256']})
    cases = {row['case'] for row in records}
    require(not roles and cases == tv['cases'].keys(), 'TV and axis source-provider coverage differs')
    methods_expected = set().union(*(control[-1] for control in CONTROL.values()))
    require(tv['suite']['comparisons'].keys() == CONTROL.keys() and tv['methods'].keys() == methods_expected and
            slots.keys() == {(case, method) for case in cases for method in methods_expected} and
            all(set(m['routes']) == {'timestamp', 'value'} for m in tv['methods'].values()), 'TV comparison or composed-method census differs')
    controls = {}
    for name, (task, kind, role, profile, methods) in CONTROL.items():
        spec = tv['suite']['comparisons'][name]
        require((spec['task'], spec['control']) == (task, kind) and set(spec['cases']) == cases and set(spec['methods']) == methods and
                all(tv['methods'][m]['routes'][role] == profile for m in methods), 'TV fixed route or compared methods differ')
        route_id = tv['profiles'][profile]['route_id']
        for case in cases:
            require(all(name in slots[case, m]['comparisons'] for m in methods) and
                    all(frozen['contract']['control'] == {'kind': kind, 'route_id': route_id} and frozen['contract']['task'] == task
                        for frozen in tv_report['comparisons'][name][case].values()), 'TV recorded comparison differs from frozen control')
        controls[name] = {'task': task, 'fixed_plugin': tv['profiles'][profile]['plugin'], 'methods': sorted(methods), 'provider_cases': len(cases)}
    return {'schema': 'bmk.m3-axis-tv-lineage-diagnostic/1', 'projection_id': projection['projection_id'], 'scope': projection['scope'],
            'axis': {'run_id': axis_audit['run_id'], 'seal_id': axis_audit['seal_id'], 'verified_by_role': axis_audit['role_cases']},
            'tv': {'run_id': tv_report['run_id'], 'seal_id': tv_report['seal_id'], 'restore_audit': file_ref(root, tv_replay_path),
                   'distinct_restored_slots': len(restored), 'controls': controls}, 'matched_provider_cases': records,
            'native_gorilla_tv_on_matched_projection': False, 'qualification_granted': False, 'stage_accepted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('axis-run', 'tv-run', 'tv-replay', 'out'):
        parser.add_argument(f'--{name}', type=Path, required=True)
    args = parser.parse_args()
    write_new(args.out, check(ROOT, args.axis_run.resolve(strict=True), args.tv_run.resolve(strict=True), args.tv_replay.resolve(strict=True)))


if __name__ == '__main__':
    main()
