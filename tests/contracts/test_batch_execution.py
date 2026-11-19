from pathlib import Path
import tempfile
import unittest

from tsbench.application.batch_execution import _inspect
from tsbench.assets import ContractError
from tsbench.planner.batch_execution import _inputs
from tsbench.planner.gorilla import HEADER
from tsbench.supervisor.isolated_worker import validate_limits

ROOT = Path(__file__).resolve().parents[2]


class BatchExecutionContract(unittest.TestCase):
    def test_real_boundary_and_case_deduplication(self):
        sources, case_map = _inputs(ROOT)
        self.assertEqual(len(sources), 9)
        self.assertEqual(len(case_map), 6)
        self.assertEqual(len({v[0]['product_slot'] for v in sources.values()}), 9)
        for label, n, status in [('minus', 511, 0), ('at', 512, 0), ('plus', 513, 7)]:
            row, material = sources[f'gorilla-tv-{label}']
            self.assertEqual(row['original']['column_bytes'], [n * 8] * 2)
            self.assertEqual(row['expected_status'], status)
            self.assertEqual(tuple(map(len, material.columns)), (n * 8, n * 8))

    def test_empty_envelope_binds_exact_schema_and_rejects_trailer(self):
        sources, _ = _inputs(ROOT)
        slot, material = sources['empty']
        valid = HEADER.pack(b'BMKGTV\x01\0', len(material.schema), 0, 2) + material.schema + b'\0\0'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'frame'
            path.write_bytes(valid)
            self.assertEqual(_inspect(path, slot)['native_bits'], 16)
            for bad in (valid + b'\0', valid[:-1] + b'\1', valid.replace(b'ms', b'ns')):
                path.write_bytes(bad)
                with self.assertRaises(ContractError):
                    _inspect(path, slot)

    def test_limits_reject_boolean_unknown_and_unbounded(self):
        base = dict(address_space_bytes=128 << 20, file_bytes=16384, wall_seconds=5)
        validate_limits(base)
        for override in ({'wall_seconds': True}, {'address_space_bytes': 0}, {'rss_bytes': 128 << 20},
                         {'file_bytes': 1 << 30}, {'wall_seconds': 61}):
            with self.assertRaises(ContractError):
                validate_limits({**base, **override})

    def test_direct_control_and_plugin_have_separate_mount_roots(self):
        from tsbench.supervisor.isolated_worker import program_files

        spec = {'loader': 'lib/ld', 'files': {name: {'needed': deps} for name, deps in {
            'lib/ld': [], 'bin/worker': ['libxx'], 'lib/plugin': ['libgorilla'], 'lib/libxx': ['libc'],
            'bin/control': ['libgorilla', 'libc'], 'lib/libgorilla': ['libc'], 'lib/libc': ['ld'],
        }.items()}}
        self.assertEqual(program_files(spec, ['bin/control']),
                         ['bin/control', 'lib/ld', 'lib/libc', 'lib/libgorilla'])
        self.assertEqual(program_files(spec, ['bin/worker', 'lib/plugin']),
                         ['bin/worker', 'lib/ld', 'lib/libc', 'lib/libgorilla', 'lib/libxx', 'lib/plugin'])
