import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tsbench.assets import ContractError, load_json
from tsbench.planner.smoke import FULL_CORPUS_SUITE, _suite, stage_suite_schema
from tsbench.planner.measurement import timed

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = f'configs/suites/{FULL_CORPUS_SUITE}/suite.json'
INPUTS = 'configs/experiments/m1_real_inputs/two_holdouts_v1.json'
SCHEMA = 'schemas/m1-full-corpus-suite.schema.json'


class M1FullCorpusSmokeContract(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        for relative in (TEMPLATE, INPUTS, SCHEMA):
            dst = self.root / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, dst)

    def test_only_input_config_changes_in_real_holdout_suite(self):
        doc = _suite(self.root, FULL_CORPUS_SUITE)
        self.assertEqual(stage_suite_schema(doc), 'm1-full-corpus-suite')
        self.assertTrue(timed(doc))
        self.assertEqual(doc['purpose'], 'm1_candidate_preflight')
        altered = load_json(self.root / INPUTS)
        altered['cases'][0]['input']['dataset'] = 'economics-18'
        (self.root / 'new.json').write_text(json.dumps(altered), encoding='utf-8')
        revised = _suite(self.root, FULL_CORPUS_SUITE, 'new.json')
        self.assertEqual(set(k for k in revised if revised[k] != doc[k]), {'input_config', 'cases'})
        self.assertEqual(revised['expected'], {'cases': 2, 'methods': 3, 'slots': 6})

    def test_rejects_unknown_options_noninteger_count_and_duplicate_cases(self):
        for change, reason in (
            (lambda d: d.update({'unexpected': True}), 'invalid M1 full-corpus input request'),
            (lambda d: d['cases'][0]['input'].update({'count': 31.0}), 'violates m1-full-corpus-suite'),
            (lambda d: d['cases'][1].update({'id': d['cases'][0]['id']}), 'duplicate lossless stage case'),
        ):
            doc = load_json(self.root / INPUTS)
            change(doc)
            (self.root / 'bad.json').write_text(json.dumps(doc), encoding='utf-8')
            with self.assertRaisesRegex(ContractError, reason):
                _suite(self.root, FULL_CORPUS_SUITE, 'bad.json')
