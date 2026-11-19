"""Check semantic recipe rejections separately from real TV-worker integration."""
from copy import deepcopy
from pathlib import Path
import unittest

from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.planner.recipe import _graph, bind_recipe, check_sealed_recipe

ROOT = Path(__file__).resolve().parents[2]
RECIPE = 'configs/recipes/tv-cross-format-v2.json'


class RecipeContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_contract(ROOT, 'recipe')
        self.recipe = load_json(ROOT / RECIPE)
        suite = load_json(ROOT / self.recipe['suite']['path'])
        c = {'quality': {'kind':'bitwise_exact', 'exact_components':['T','V']},
             'access': {'mode':'batch_whole'}, 'validation': {'strength':'artifact_each'},
             'boundary': {'extent':'pipeline_service', 'state':'reset_per_message', 'size_scope':'bundle'},
             'resource': {'deadline_ns':10**10, 'max_serialized_bytes':2**21, 'participant_threads':1}}
        tv = {'suite_path': self.recipe['suite']['path'], 'suite': suite,
              'comparisons': {'fixed-t': {'case': {'encode': {'contract': c}}}},
              'measurement': {'resource_enforcement': self.recipe['conditions']['resources']['enforcement']},
              'profiles': {p: {'route_id': content_id(p)} for p in suite['profiles']},
              'methods': {m: {'layout': 'grouped-limbs' if 'value_transform' in r else 'separate',
                              'routes': {k:r[k] for k in ('timestamp','value')}, 'method_id': content_id(m)}
                          for m,r in suite['methods'].items()}}
        self.tv = {**tv, 'plan_content_id': content_id(tv)}

    def bind(self):
        return bind_recipe(self.contract, RECIPE, self.recipe, self.tv)

    def test_schema_is_strict(self):
        self.recipe['max_depth'] = 7.0
        with self.assertRaisesRegex(ContractError,'integer'):
            self.bind()
        self.recipe['max_depth'] = 7
        self.recipe['conditions']['threads_override'] = 1
        with self.assertRaisesRegex(ContractError,'threads_override'):
            self.bind()

    def test_type_cycle_inverse_and_depth_fail_at_node(self):
        self.assertEqual(self.bind()['graphs']['grouped-limbs']['depth'],7)
        src = self.recipe['graphs']['grouped-limbs']
        for index, field, value, msg in (
                (-1,'inputs',['v-codec','t-codec'],'incompatible input types'),
                (1,'inputs',['product'],'forward or cyclic'),
                (-3,'inverse','cast-numeric','inverse must be unpack-limbs-bitwise'),
                (-3,'op','unchecked-cast','operation not implemented'),
        ):
            with self.subTest(field=field,value=value):
                nodes = deepcopy(src)
                nodes[index][field] = value
                with self.assertRaisesRegex(ContractError,msg):
                    _graph('grouped-limbs',nodes,7)
        self.recipe['max_depth'] = 6
        with self.assertRaisesRegex(ContractError,'node product: maximum graph depth'):
            self.bind()

    def test_cannot_rename_an_existing_method_into_new_semantics(self):
        self.recipe['methods']['gorilla-t-alp-f64'] = 'grouped-limbs'
        self.recipe['graphs'].pop('separate')
        with self.assertRaisesRegex(ContractError,'not implemented by the separate lowering'):
            self.bind()

    def test_boundary_conditions_do_not_inherit_qualification(self):
        for block, key, value in (
                ('conditions','access','stream_chunked'), ('conditions','extent','end_to_end'),
                ('conditions','ingress','source_inside_clock'), ('conditions','state','ordered_session'),
                ('resources','deadline_ns',1), ('resources','enforcement','exclusive_cpu_and_memory'),
        ):
            section = self.recipe['conditions'] if block=='conditions' else self.recipe['conditions']['resources']
            with self.subTest(key=key), self.assertRaisesRegex(ContractError,key):
                old = section[key]
                try:
                    section[key] = value
                    self.bind()
                finally:
                    section[key] = old
        binding = self.bind()
        self.assertFalse(binding['qualification_granted'])
        self.assertEqual(binding['binding_status'],'resolved_for_development')
        direct = binding['methods']['gorilla-t-alp-f64']['codec_routes']
        grouped = binding['methods']['gorilla-t-fire-u16']['codec_routes']
        self.assertEqual(direct['t-codec'],grouped['t-codec'])
        self.assertNotEqual(direct['v-codec'],grouped['v-codec'])

    def test_resealed_forged_lowering_and_mismatched_suite_rejected(self):
        binding = self.bind()
        plan = {**self.tv, 'recipe_binding': binding}
        check_sealed_recipe(self.contract,plan)
        binding['methods']['gorilla-t-fire-u16']['codec_routes']['v-codec'] = '0'*64
        binding['recipe_binding_id'] = content_id({k:v for k,v in binding.items() if k!='recipe_binding_id'})
        with self.assertRaisesRegex(ContractError,'differs from TV lowering'):
            check_sealed_recipe(self.contract,plan)
        self.recipe['suite']['content_id'] = '0'*64
        with self.assertRaisesRegex(ContractError,'suite content differs'):
            self.bind()
