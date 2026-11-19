"""Versioned provider groups preserve the legacy ingress contract and denominator."""
from copy import deepcopy
from pathlib import Path
import unittest

from tsbench.assets import ContractError, load_json
from tsbench.contracts import load_contract
from tsbench.planner.tv import ingress_groups, load_case, measurement, suite_schema_name

ROOT = Path(__file__).resolve().parents[2]
LEGACY = 'configs/suites/dev_tv_cross_format_v2/suite.json'
PROVIDERS = 'configs/suites/dev_tv_source_providers_v3/suite.json'


class SourceProviderGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = load_json(ROOT/LEGACY)
        cls.providers = load_json(ROOT/PROVIDERS)
        cls.cases = {name:load_case(ROOT,cls.providers,src)[0] for name,src in cls.providers['cases'].items()}

    def test_versioned_providers_preserve_legacy_comparison_inputs_and_scope(self):
        for suite in (self.legacy,self.providers):
            load_contract(ROOT,suite_schema_name(suite)).validate(suite,'TV suite')
        self.assertEqual(ingress_groups(self.legacy,self.cases),ingress_groups(self.providers,self.cases))
        self.assertEqual(measurement(self.legacy),measurement(self.providers))
        bad = {**self.legacy,'source_groups':self.providers['source_groups']}
        with self.assertRaisesRegex(ContractError,'source_groups'):
            load_contract(ROOT,suite_schema_name(bad)).validate(bad,'legacy must not use versioned declarations')

    def test_provider_declaration_cannot_hide_source_or_inflate_denominator(self):
        bad = deepcopy(self.providers)
        bad['source_groups']['traffic-tail'] = ['csv','npy']
        with self.assertRaisesRegex(ContractError,'must match declared providers'):
            ingress_groups(bad,self.cases)
        bad = deepcopy(self.providers)
        bad['source_groups']['unused'] = ['csv','npy']
        with self.assertRaisesRegex(ContractError,'do not match scheduled groups'):
            ingress_groups(bad,self.cases)
        bad = deepcopy(self.providers)
        bad['source_groups']['traffic-tail'] = ['csv','npy','npy']
        with self.assertRaisesRegex(ContractError,'non-unique'):
            load_contract(ROOT,suite_schema_name(bad)).validate(bad,'provider alias repetition')
