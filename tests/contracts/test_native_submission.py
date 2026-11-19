from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tsbench.application import native_submission as app
from tsbench.assets import ContractError, load_json
from tsbench.contracts import load_contract

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    policy = load_json(ROOT / app.POLICY)
    driver = {'operations': [{'label': 'decode'}, {'label': 'train'}],
              'process_limits': {'address_space_bytes': 128 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 5},
              'configuration': {'step_limits': {'train': {'address_space_bytes': 768 << 20,
                                                         'file_bytes': 16384, 'wall_seconds': 25}}}}
    plan = {'admission_coverage': {'selections': 12, 'required_checks': 180, 'conditional_checks': 6},
            'execution_binding': {'total_routes': 36, 'bound_routes': 36,
                                  'bound_obligations': dict.fromkeys(range(186)), 'unbound_obligations': {},
                                  'drivers': {'driver': driver}},
            'slots': [{'product_slot': 'driver'}], 'unbound_controls': {},
            'retention_bounds': dict.fromkeys(app.RETENTION_KEYS, 1024)}
    return policy, plan


class NativeSubmissionTests(unittest.TestCase):
    def test_work_includes_helper_steps_and_recovery_storage(self):
        policy, plan = fixture()
        estimate = app._estimate(plan, policy)
        self.assertEqual({'slots': 1, 'operations': 2, 'sum_child_deadlines_seconds': 30}, estimate['work'])
        self.assertEqual({'address_space_bytes': 768 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 25},
                         estimate['peak_declared_process_limits'])
        self.assertEqual(4096, estimate['planned_retained_bytes'])
        self.assertEqual(1 << 30, estimate['minimum_capacity']['host_memavailable_bytes'])
        for section, key, threshold, failure in (
            ('work', 'max_operations', 1, 'work budget'),
            ('work', 'max_sum_child_deadlines_seconds', 29, 'work budget'),
            ('process', 'wall_seconds', 24, 'per-operation limit'),
            ('retention', 'max_planned_retained_bytes', 4095, 'retention ceiling'),
        ):
            changed = deepcopy(policy)
            changed[section][key] = threshold
            with self.subTest(section=section, key=key), self.assertRaisesRegex(ContractError, failure):
                app._estimate(plan, changed)
        plan['execution_binding']['unbound_obligations']['missing'] = {}
        with self.assertRaisesRegex(ContractError, 'complete first-batch denominator'):
            app._estimate(plan, policy)

    def test_policy_rejects_threshold_of_wrong_type_and_unknown_fields(self):
        policy, _ = fixture()
        schema = load_contract(ROOT, 'native-submission-policy')
        schema.validate(policy, 'fixture')
        with self.assertRaisesRegex(ContractError, 'additional properties|Additional properties'):
            schema.validate({**policy, 'formal': True}, 'fixture')
        policy['work']['max_slots'] = 200.0
        with self.assertRaisesRegex(ContractError, 'not of type'):
            schema.validate(policy, 'fixture')

    def test_predecessor_must_be_same_candidate_and_unaccepted(self):
        _, plan = fixture()
        with self.assertRaisesRegex(ContractError, 'predecessor is not an unaccepted'):
            app._predecessor(ROOT, plan, 'configs/profiles/native_submission_v1.json')

    def test_execute_path_rejects_before_creating_run(self):
        policy, plan = fixture()
        estimate = app._estimate(plan, policy)
        locked = {'schema': app.SCHEMA, 'execution': plan, 'estimate': estimate}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'plan_native_submission', return_value=locked), \
                patch.object(app, 'run_batch_execution') as runner:
            results = Path(tmp)
            minimum = estimate['minimum_capacity']
            nominal = {'disk': {'device': results.stat().st_dev,
                                **{k: minimum[k] for k in ('available_bytes', 'available_inodes')}},
                       'host_memavailable_bytes': minimum['host_memavailable_bytes']}
            for key, reading, failure in (
                ('disk', {**nominal, 'disk': None}, 'cannot measure'),
                ('bytes', {**nominal, 'disk': {**nominal['disk'], 'available_bytes': minimum['available_bytes'] - 1}}, 'bytes below'),
                ('inodes', {**nominal, 'disk': {**nominal['disk'], 'available_inodes': 0}}, 'inodes below'),
                ('memory', {**nominal, 'host_memavailable_bytes': None}, 'MemAvailable'),
                ('mount', {**nominal, 'disk': {**nominal['disk'], 'device': -1}}, 'output mount changed'),
            ):
                with self.subTest(key=key), patch.object(app.resource, 'sample', return_value=reading):
                    with self.assertRaisesRegex(ContractError, failure):
                        app.run_native_submission(ROOT, locked, results)
                self.assertEqual([], list(results.iterdir()))
            with self.assertRaisesRegex(ContractError, 'resource policy drift'):
                app.run_native_submission(ROOT, {**locked, 'stage_accepted': True}, results)
            with self.assertRaisesRegex(ContractError, 'cancelled before'):
                app.run_native_submission(ROOT, locked, results, cancelled=lambda: True)
            runner.assert_not_called()

    def test_directory_lock_is_nonblocking_and_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            with app._reserve_results(path) as device:
                self.assertEqual(path.stat().st_dev, device)
                with self.assertRaisesRegex(ContractError, 'already reserved'):
                    with app._reserve_results(path):
                        self.fail('acquired the competing lock')
            with app._reserve_results(path):
                self.assertEqual([], list(path.iterdir()))
