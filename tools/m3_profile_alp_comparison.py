#!/usr/bin/env python3
"""Build a same-ABI main-clock comparison for the exact fused ALP M4 unit."""
import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_batch_timing import _inputs, report_timing
from tsbench.application.m3_fixed_batch import ENCODE, _call, _identity, restore_frame
from tsbench.application.m3_real_corpus_execution import _entry_map, _stage_dataset
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.m4_real_profile import recompute
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, load_json, local_file, require
from tsbench.planner.m3_batch_timing import (CONFIG, POLICY, PROFILE_EXACT, SCHEMA, _frame_cost, _groups, check_plan,
                                           checked_file, protocol, reference, schedule)
from tsbench.planner.m3_fixed_batch import DIRECTORY, ROUTES
from tsbench.supervisor import timing_resource as resource
from tsbench.supervisor.isolated_worker import launcher_lock, program_files


def _exact_unit(plan, ledger, profile):
    matched = None
    for row, item in full_run_rows(plan, ledger):
        if row.get('entry_kind') is not None or item['work_item_id'] != profile['work_item_id']:
            continue
        facts = row['evidence']
        require(row['status'] == 'verified' and item['selection'] == 9 and item['plugin'] == 'alp-auto' and
                item['route'] == 'decode-backends' and facts['driver'] == plan['build']['fixed_batch']['driver'] and
                facts['recovery_id'] == plan['build']['fixed_batch']['decoder']['recovery_id'] and
                all(item[k] == profile[k] for k in ('view', 'dataset_id', 'operation_config_id', 'canonical_object_id')),
                'M4 ALP does not match a verified fixed-batch ALP decision')
        hits = [(i, u) for i, u in enumerate(facts['units']) if all(u.get(k) == v for k, v in profile['geometry'].items())]
        require(len(hits) == 1, 'M4 ALP geometry does not bind one M3 unit')
        index, unit = hits[0]
        require(index not in {r['unit_index'] for r in facts['retained_samples']},
                'M4 released-unit path must not replace existing retained evidence')
        native = unit['decodes']['falp-auto']['native']
        cfg = profile['native_config']
        require(unit['original'] == profile['original'] and unit['artifact'] == profile['expected_m3_frame'] and
                native['backend'] == cfg['effective_backend'] == 'falp-avx2' and cfg['decode'] == 'ALPN_FALP_AVX2' and
                native['threads'] == cfg['threads'] == 1 and native['falp_avx2_vectors'] == cfg['fused_vectors'] > 0,
                'M4 ALP inputs, byte identities, or actual fused dispatch differ')
        matched = item, index, unit
    require(matched is not None, 'sealed M3 ledger omits the M4 ALP unit')
    return matched


def prepare(root, m3_path, m3_run, profile_run, paired_run, out, *, cpu):
    require(all(p.is_relative_to(root) for p in (m3_path, m3_run, profile_run, paired_run, out)),
            'ALP timing inputs and output must stay in project')
    require(not out.exists(), 'ALP exact comparison output already exists')
    main = load_json(m3_path)
    ledger, seal = full_run_source(main, m3_run)
    profile = recompute(profile_run)
    require(profile == load_json(profile_run / 'report.json') and profile['stage_accepted'] is False and
            load_json(profile_run / 'plan.json')['m3_plan'] == reference(root, m3_path), 'M4 sealed profile lineage differs')
    prof_case = profile['inputs']['alp-fused']
    item, index, unit = _exact_unit(main, ledger, prof_case)
    paired = report_timing(paired_run)
    require(paired == load_json(paired_run / 'report.json') and paired['functional_seal_id'] == seal and
            paired['status_counts'] == {'verified': len(paired['groups']) * 8}, 'ALP paired reference is not a successful same-run diagnostic')
    roles = load_json(paired_run / 'plan.json')['physical_build']['alp-auto']
    binding = main['build']['fixed_batch']
    decoder = binding['decoder']
    module = decoder['plugins']['alp-auto']
    closure = {name: {'path': f['source'], 'bytes': f['bytes'], 'sha256': f['sha256']}
               for name in program_files(decoder, [module]) if (f := decoder['files'][name])['origin'] == 'build'}
    require(roles['project_runtime_assets'] == closure and binding['launchers'] == launcher_lock(),
            'ALP paired runtime differs from the locked diagnostic codec build')
    for ref in (*roles['lanes'].values(), *closure.values()):
        checked_file(root, ref)
    entry = _entry_map(root, load_json(checked_file(root, main['definition']['plan'])))[item['dataset_id']]
    _, _, backends = ROUTES[item['selection'], item['route']]
    with TemporaryDirectory(prefix='m3-alp-profile-exact-', dir=out.parent) as tmp:
        work = Path(tmp)
        staged = _stage_dataset(root, entry, work, item['view'])
        original, artifact = unit['original'], unit['artifact']
        geometry = prof_case['geometry']
        raw, schema = _inputs(staged, {**item, 'original': original, 'geometry': geometry}, work / 'source')
        encoded, enc, (info,) = _call(m3_run / DIRECTORY, binding, 'alp-auto', backends[0], work / 'encode', ENCODE,
                                     {'raw': raw, 'schema': schema}, ['/inputs/schema', '/out/frame', str(original['dtype']), '/inputs/raw'],
                                     ('frame',), 1)
        frame = encoded / 'frame'
        require(_identity(frame) == artifact and info == unit['encode']['native'] and enc['input_mounts'] ==
                {k: original[k] for k in ('raw', 'schema')}, 'ALP reconstruction does not reproduce r40 exact frame')
        restores = {b: restore_frame(m3_run / DIRECTORY, binding, item, b, work / f'decode-{b}', frame, artifact, original)
                    for b in backends}
        sessions = {enc['session_id'], *(r['process']['session_id'] for r in restores.values())}
        require(len(sessions) == len(backends) + 1 and all(restores[b]['native'] == unit['decodes'][b]['native'] for b in backends),
                'ALP reconstruction did not verify both frozen backends in fresh processes')
        wire = frame.read_bytes()
    out.mkdir()
    frame = out / 'reconstructed.bmk'
    with frame.open('xb') as stream:
        stream.write(wire)
    receipt = {'schema': 'bmk.alp-exact-profile-diagnostic-anchor/1', 'basis': PROFILE_EXACT,
               'functional_seal_id': seal, 'profile_seal_id': profile['seal_id'], 'profile_case_id': prof_case['case_content_id'],
               'work_item_id': item['work_item_id'], 'unit_index': index, 'geometry': geometry,
               'original': original, 'frame': reference(root, frame), 'encode': {'native': info, 'process': enc},
               'restores': restores, 'stage_accepted': False, 'timing_admitted': False}
    write_new(out / 'anchor.json', {**receipt, 'anchor_id': content_id(receipt)})
    cases = []
    for backend in backends:
        case = {k: item[k] for k in ('dataset_id', 'work_item_id', 'canonical_object_id', 'operation_config_id', 'selection', 'route', 'view', 'plugin')}
        case.update(unit_index=index, geometry=geometry, original=original, frame=receipt['frame'], module=module,
                    decode_backend=backend, options={'decode_backend': backend}, bytes=_frame_cost(wire, 'alp-auto', original),
                    expected_native={'encode': info, 'decode': restores[backend]['native']})
        cases.append({**case, 'case_id': content_id(case)})
    seed = 20261120
    groups = _groups(cases, seed)
    functional = {'source_projection': PROFILE_EXACT, 'plan': reference(root, m3_path), 'report': reference(root, m3_run / 'report.json'),
                  'ledger': reference(root, ledger), 'seal_id': seal, 'anchor': reference(root, out / 'anchor.json'),
                  'profile_plan': reference(root, profile_run / 'plan.json'), 'profile_reference_seal': reference(root, profile_run / 'completion.json'),
                  'logically_matched_profile_seal': profile['seal_id'], 'runtime_reference_seal': reference(root, paired_run / 'completion.json')}
    body = {'schema': SCHEMA, 'diagnostic_only': True, 'performance_admitted': False, 'seed': seed,
            'functional': functional, 'definition': main['definition']['plan'], 'physical_build': {'alp-auto': roles},
            'environment': resource.environment(cpu), 'protocol': protocol(root), 'config': CONFIG, 'policy': POLICY,
            'cases': cases, 'groups': groups, 'expected_batches': sum(len(list(schedule(g))) for g in groups)}
    plan = {**body, 'plan_content_id': content_id(body)}
    check_plan(plan)
    write_new(out / 'plan.json', plan)
    return plan['plan_content_id']


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('m3-plan', 'm3-run', 'profile-run', 'paired-run', 'out'):
        p.add_argument('--' + arg, required=True, type=Path)
    p.add_argument('--cpu', required=True, type=int)
    a = p.parse_args()
    try:
        print(prepare(ROOT, *(p.resolve(strict=True) for p in (a.m3_plan, a.m3_run, a.profile_run, a.paired_run)),
                      a.out.resolve(), cpu=a.cpu))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')
