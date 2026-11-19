from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tsbench.planner.measurement import PROFILE, comparison_identity, measurement_policy
from tsbench.supervisor.process import invoke

ROOT = Path(__file__).resolve().parents[2]


class ProcessMeasurementTests(unittest.TestCase):
    def test_profile_does_not_grant_or_mix_qualification(self):
        binding = measurement_policy(ROOT)
        profile = binding['policy']['profiles'][PROFILE]
        self.assertFalse(profile['rankable'])
        self.assertEqual(('frame', 'process', 'artifact_each', 'outside_extent'),
                         tuple(profile[k] for k in ('measurement_scope', 'lifecycle', 'verification_strength',
                                                    'verification_placement')))
        self.assertNotIn('sample_only', binding['policy']['admission']['formal_timing_only_m2_m4'])
        plan = {'scope_id': 'scope-a', 'suite': {'task': 'values_only', 'quality': 'bitwise',
                                                'access': 'batch', 'comparison_track': 'O'}}
        key = comparison_identity(plan, {'raw_sha256': 'same', 'schema_sha256': 'f64'})
        self.assertNotEqual(key, comparison_identity(plan, {'raw_sha256': 'same', 'schema_sha256': 'u64'}))
        self.assertNotEqual(key, comparison_identity({**plan, 'scope_id': 'scope-b'},
                                                     {'raw_sha256': 'same', 'schema_sha256': 'f64'}))

    def test_parent_observation_uses_blocking_notification_not_sleeping_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            t0 = time.monotonic_ns()
            with patch('tsbench.supervisor.process.time.sleep', side_effect=AssertionError('sleeping poll called')):
                row = invoke([sys.executable, '-B', '-c', 'print("ready")'], root, root, 'one', 5, lambda: False,
                             observe_process=True)
            self.assertEqual(('completed', 0), (row['status'], row['returncode']))
            self.assertTrue(0 < row['process_wall_ns'] <= time.monotonic_ns() - t0)
            self.assertEqual('ready\n', (root / 'one.stdout').read_text())

    def test_terminal_and_unlaunched_operations_keep_distinct_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [('failure', [sys.executable, '-B', '-c', 'raise SystemExit(7)'], 'failed', 7),
                     ('crash', [sys.executable, '-B', '-c', 'import os, signal; os.kill(os.getpid(), signal.SIGKILL)'],
                      'crash', -signal.SIGKILL),
                     ('timeout', [sys.executable, '-B', '-c', 'import time; time.sleep(10)'], 'timeout', -signal.SIGKILL),
                     ('missing', [str(root / 'missing')], 'dependency_failed', None)]
            for name, argv, status, code in cases:
                with self.subTest(name=name):
                    result = invoke(argv, root, root, name, 1 if name == 'timeout' else 5, lambda: False,
                                    observe_process=True)
                    self.assertEqual((status, code), (result['status'], result['returncode']))
                    if code is None:
                        self.assertNotIn('process_wall_ns', result)
                    else:
                        self.assertGreater(result['process_wall_ns'], 0)
            clock = time.monotonic()
            cancelled = invoke([sys.executable, '-B', '-c', 'import time; time.sleep(10)'], root, root, 'cancel', 5,
                               lambda: time.monotonic() - clock > 0.15, observe_process=True)
            self.assertEqual(('cancelled', -signal.SIGKILL), (cancelled['status'], cancelled['returncode']))
            self.assertGreater(cancelled['process_wall_ns'], 0)
            prelaunch = invoke([sys.executable], root, root, 'prelaunch', 5, lambda: True, observe_process=True)
            self.assertEqual('cancelled', prelaunch['status'])
            self.assertNotIn('process_wall_ns', prelaunch)
