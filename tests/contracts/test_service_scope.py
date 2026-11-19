"""M0 configuration/identity gates; no service run or qualification is faked."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import struct
import unittest

from tsbench.api import PlanRequest, load_request, plan, verify_service_plan
from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.corpus import time_coordinate
from tsbench.planner.corpus_windows import bind_service_window, read_labeled_tv_window
from tsbench.planner.service_scope import _check_cases

ROOT = Path(__file__).resolve().parents[2]
SUITE = 'first_batch_service_v4'
CONFIG = f'configs/suites/{SUITE}/request.toml'
WORKLOADS = f'configs/suites/{SUITE}/workloads.json'


def reseal(doc):
    doc['plan_content_id'] = content_id({k:v for k,v in doc.items() if k!='plan_content_id'})
    return doc


class ServiceScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = plan(ROOT,load_request(ROOT,CONFIG)).document
        cls.work = load_json(ROOT/WORKLOADS)

    def test_relation_case_partition_complete_and_no_qualification(self):
        result = self.doc
        slots = {s['slot_id']:s for s in result['required_slots']}
        rels = {r['id']:r for r in result['atomic_relations']}
        self.assertEqual((204,264,564), (len(result['display_cells']),len(rels),len(slots)))
        self.assertCountEqual([i for r in rels.values() for i in r['slots']], slots.keys())
        self.assertCountEqual([i for c in result['display_cells'] for i in c['atomic_relations']], rels.keys())
        self.assertEqual(Counter(verified=432,expected_rejection=132),Counter(s['required_terminal'] for s in slots.values()))
        self.assertEqual(Counter({i:12 for i in result['cases']}),Counter(s['case_id'] for s in slots.values()))
        for rid, rel in rels.items():
            for sid in rel['slots']:
                s = slots[sid]
                self.assertEqual((s['atomic_relation_id'],s['selection'],result['cases'][s['case_id']]['requirement']),
                                 (rid,rel['selection'],rel['requirement']))
        self.assertFalse(result['runnable'] or result['stage_accepted'] or result['qualification_granted'])
        self.assertTrue(all(s['status']=='not_run' and s['reason'] for s in slots.values()))

    def test_resource_override_changes_plan_identity_not_workload_denominator(self):
        p = plan(ROOT,PlanRequest(SUITE,4)).document
        self.assertEqual(p['required_slots'],self.doc['required_slots'])
        self.assertEqual(p['scope_id'],self.doc['scope_id'])
        self.assertNotEqual(p['plan_content_id'],self.doc['plan_content_id'])
        with self.assertRaisesRegex(ContractError,'validation worker budget'):
            plan(ROOT,PlanRequest(SUITE,5))

    def test_resealed_edit_is_not_the_frozen_workload_closure(self):
        self.assertTrue(verify_service_plan(ROOT,self.doc)['verified_definition'])
        p = deepcopy(self.doc)
        p['required_slots'].pop(0)
        with self.assertRaisesRegex(ContractError,'differs from configured workload closure'):
            verify_service_plan(ROOT,reseal(p))
        p = deepcopy(self.doc)
        p['qualification_granted'] = True
        with self.assertRaisesRegex(ContractError,'differs from configured workload closure'):
            verify_service_plan(ROOT,reseal(p))

    def test_strict_parameters_and_semantic_failures(self):
        contract = load_contract(ROOT,'service-workloads')
        p = deepcopy(self.work)
        p['cases'][0]['parameters']['unknown'] = True
        with self.assertRaisesRegex(ContractError,'unknown'):
            contract.validate(p,'mutated workloads')
        for target, change, error in (
            ('cross-block-range', {'end':516}, 'range does not match'),
            ('chunked-stream-tail', {'max_buffer_rows':64}, 'does not exercise buffer'),
            ('three-quality-levels', {'level_abs_error_ppm_of_unit':[1,5,0]}, 'must tighten'),
            ('tail-point', {'chunk_rows':16}, 'unknown or missing parameters'),
        ):
            with self.subTest(target=target):
                p = deepcopy(self.work)
                c, = [c for c in p['cases'] if c['id']==target]
                c['parameters'].update(change)
                contract.validate(p,'mutated workloads')
                with self.assertRaisesRegex(ContractError,error):
                    _check_cases(p,self.doc['inputs'],4)
        p = deepcopy(self.work)
        c, = [c for c in p['cases'] if c['id']=='chronological-train-dev-test']
        c['inputs'][:2] = reversed(c['inputs'][:2])
        with self.assertRaisesRegex(ContractError,'chronological, disjoint'):
            _check_cases(p,self.doc['inputs'],4)

    def test_real_lineage_and_training_boundary(self):
        choices = self.doc['inputs']
        real = [choices[f'traffic-tail-{fmt}'] for fmt in ('csv','txt','npy')]
        self.assertEqual(len({o['canonical_dataset_hash'] for o in real}),1)
        self.assertEqual(len({o['source_file_hash'] for o in real}),3)
        self.assertTrue(all(o['origin']['window']['source_cluster']==choices['traffic-heldout']['window']['source_cluster'] for o in real))
        dev = choices['sensor-development']['window']
        m = 'datasets/manifests/first-batch-real-v3.json'
        d = load_json(ROOT/m)
        spec, = [s for s in d['datasets'] if s['id']==dev['dataset']]
        request = dict(dataset=dev['dataset'],column=dev['column'],partition='development',
                       offset=spec['audit']['partitions']['development']['rows']-1,count=1)
        window = bind_service_window(ROOT,m,dev['corpus_id'],request)
        _,ticks,_ = read_labeled_tv_window(ROOT,window)
        self.assertLess(struct.unpack('<q',ticks)[0],time_coordinate(window['profile'],window['partition_end']))
        with self.assertRaisesRegex(ContractError,'crosses its frozen partition'):
            bind_service_window(ROOT,m,dev['corpus_id'],{**request,'count':2})
