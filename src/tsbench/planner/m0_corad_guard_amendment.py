"""Amend only the evidence recipes of the six frozen CORAD inference obligations."""
from struct import pack

from ..assets import content_id, digest, load_json, local_file, require
from .corad_corpus import INFERENCE
from .corad_deployment import DEPLOYMENT, NATIVE
from .corad_execution import COLS, identity, is_corad, split_deployment
from .m3_corad_specialized import fixture_inputs

SCHEMA = 'bmk.m0-corad-guard-amendment/1'
POLICY = 'configs/suites/m3_corad_guard_v2/qualification.json'
DRIVER = 'corad-specialized/2'
SOURCE = ('src/tsbench/planner/m0_corad_guard_amendment.py',
          'src/tsbench/application/m3_corad_specialized_v2.py',
          'src/tsbench/application/m3_real_corpus_amended.py')
CHECKS = {
    'ordered_finite_columns': ['original_ordered_frames', 'input_refusals'],
    'model_identity_and_short_tail': ['original_pinned_frames', 'bit_exact_tails'],
    'isolated_crd1_restore': ['original_frame_only_restores', 'both_reference_controls'],
    'original_domain_max_error_and_rmse': ['original_domain_exact_measurements'],
    'bound_predeclared_before_formal_run': ['original_domain_unchanged_train_bounds'],
    'wrong_model_order_and_budget_rejected': ['original_refusals', 'safe_reference_mutated_to_self_rejected'],
}


def ref(root, path):
    f = local_file(root, path)
    return {'path': path, 'bytes': f.stat().st_size, 'sha256': digest(f)}


def controls(root, slot):
    policy = load_json(local_file(root, POLICY))
    require(policy['schema'] == 'bmk.corad-guard-qualification/2' and
            policy['heldout_geometry'] == 'unchanged_m0_windows_models_and_training_bounds' and
            policy['heldout_branch_requirement'] == 'none_quality_independent_of_branch_mix' and
            policy['reference_mutation'] == 'self_reference' and policy['reference_refusal_fixture'] == 'safe-reference' and
            (policy['tricklet'], policy['atoms'], policy['nonzero'], policy['threshold']) == (4, 4, 2, 0.9),
            'invalid CORAD guard qualification policy')
    schema, _ = split_deployment(slot['deployments'][0])
    model = NATIVE.pack(b'CRD1', 0, 3, 4, 4, 2, 0.9, NATIVE.size + 22*8)
    model += pack('<22d', *(float(i == j) for i in range(4) for j in range(4)), 0., 1., 0., 1., 0., 1.)
    deployment = (DEPLOYMENT.pack(b'BMKCDP\x01\0', len(schema), len(model)) + schema + model).hex()
    out = []
    for case, name, refs in zip(policy['cases'], ('safe-reference', 'unsafe-correlated-reference'), (1, 0), strict=True):
        cols = case['columns']
        require(case['id'] == name and case['references'] == refs and len(cols) == 3 and
                all(len(col) == 7 and all(type(x) is int for x in col) for col in cols) and
                cols[2][:4] == [0,1,0,2] and cols[0][:4] == [1,0,2,0] and
                cols[1][:4] == ([1,0,2,0] if refs else [100,0,200,0]), 'CORAD reference counterexamples differ')
        inputs = {'schema': schema, **{k: pack('<7d', *v) for k, v in zip(COLS, cols, strict=True)}}
        out.append({'id': name, 'deployment': deployment, 'inputs': {k: v.hex() for k, v in inputs.items()},
                    'expected_references': refs, 'expected_sparse_records': 3-refs, 'tail_bytes': 72})
    return out


def freeze(root, m0_path):
    m0 = load_json(local_file(root, m0_path))
    require(m0['stage'] == 'M0' and m0['stage_accepted'] is True and m0['qualification_granted'] is False and
            m0['receipt_id'] == content_id({k: v for k, v in m0.items() if k != 'receipt_id'}), 'CORAD amendment needs accepted M0')
    definition_ref = m0['evidence']['native_definition']
    require(definition_ref == ref(root, definition_ref['path']), 'M0 definition differs from receipt')
    definition = load_json(local_file(root, definition_ref['path']))
    (slot, _), = (pair for pair in fixture_inputs(root)[0].values() if is_corad(pair[0]))
    bundle = slot['bundle']
    obligations = {o['check']: o for o in definition['obligations'] if (o['selection'], o['route']) == (80, INFERENCE)}
    require(obligations.keys() == CHECKS.keys() and all(o['kind'] == 'required' and
            all(r['bundle_id'] == bundle['bundle_id'] for r in o['planned_case_inputs']) for o in obligations.values()),
            'CORAD amendment changes original obligation scope')
    body = {'schema': SCHEMA, 'base_m0': ref(root, m0_path), 'base_definition': definition_ref,
            'case_policy': ref(root, POLICY), 'unchanged': ['all_corpus_decisions', 'two_training_routes',
                'heldout_inputs_models_bounds', 'quality_units_and_inequalities', 'm1_m2_contracts'],
            'base_slot_id': slot['product_slot'], 'quality_policy_id': bundle['quality_policy']['policy_id'],
            'controls': controls(root, slot),
            'obligations': {o['obligation_id']: {'check': k, 'planned_case_inputs': o['planned_case_inputs'],
                              'evidence': CHECKS[k]} for k, o in obligations.items()},
            'code': [ref(root, s) for s in SOURCE], 'stage': 'M0', 'qualification_granted': False}
    return {**body, 'amendment_id': content_id(body)}


def bind(root, path, m0, definition, specialized, guard):
    amendment = load_json(local_file(root, path))
    require(amendment == freeze(root, m0['path']) and amendment['base_definition'] == definition and
            amendment['base_m0'] == {k: m0[k] for k in ('path', 'bytes', 'sha256')} and
            specialized and guard and amendment['base_slot_id'] in specialized['slots'],
            'CORAD guard amendment does not match the accepted definition and guarded build')
    return {'receipt': ref(root, path), 'contract': amendment, 'driver': DRIVER}
