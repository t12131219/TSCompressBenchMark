from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from tsbench.analysis.comparison import admission_reasons
from tsbench.api import plan_comparison
from tsbench.assets import ContractError, content_id
from tsbench.contracts import load_contract
from tsbench.planner.comparison import freeze_comparison

ROOT = Path(__file__).resolve().parents[2]


def spec():
    return dict(schema='bmk.comparison-contract/1',purpose='primary_timing',track='original_task',task='values_only',
        original=dict(object_id=content_id('data'),schema_id=content_id('f64 schema'),logical_bytes=4096),
        representation=None,control=None,
        quality=dict(kind='bitwise_exact',exact_components=['V'],max_abs_by_column={},exception_policy='preserve_bits'),
        access=dict(mode='batch_whole',mechanism='any_qualified',stream=None,ingress_id=content_id('ingress'),
                    partition_id=content_id('whole'),workload_id=content_id('read entire message')),
        resource=dict(hardware_group_id=content_id('hardware'),physical_cores=4,participant_threads=4,
                      peak_resident_bytes=1048576,max_serialized_bytes=8192,deadline_ns=1_000_000_000),
        boundary=dict(direction='roundtrip',extent='pipeline_service',lifecycle='steady',state='reset_per_message',
                      state_protocol_id=content_id('reset'),cache_policy_id=content_id('natural'),ownership='copied_return',
                      completion='result_ready',output_boundary_id=content_id('owned result'),size_scope='bundle',
                      size_accounting_id=content_id('all assets'),measurement_protocol_id=content_id('primary')),
        validation=dict(strength='artifact_each',placement='outside_extent',protocol_id=content_id('validator')),
        retention=dict(samples_per_case_method=1,independent_restore=True,retain_failures=True,
                       dependency_policy_id=content_id('closed bundle')))


def with_stream(s, mode='stream_chunked'):
    s['access'].update(mode=mode,stream=dict(max_buffer_bytes=64,max_first_output_ns=100,max_output_gap_ns=200,
                                            backpressure=True,finish_restores_all=True,replay_allowed=False))
    s['boundary'].update(state='carry_stream',state_protocol_id=content_id('full stream reset'),completion='stream_finished')
    return s


def observed(b, name='a', threads=1, backend='scalar', origin='native'):
    return dict(comparison_id=b['comparison_id'],status='ok',validation='passed',quality='passed',domain='passed',
                pass_kind='timing_only',method_id=content_id(name),build_id=content_id([name,'build']),
                configuration_id=content_id([name,'config']),qualification_id=content_id([name,'qualified']),
                observation_id=content_id([name,'operation']),verification_strength='artifact_each',
                recovery='passed',independently_restored_samples=1,accounting='complete',raw_bytes=4096,
                resource_validation='passed',resource_evidence_id=content_id([name,'resource']),
                resource=dict(hardware_group_id=b['contract']['resource']['hardware_group_id'],physical_cores=threads,
                              peak_active_threads_total=threads,peak_resident_bytes=2048,serialized_bytes=2048,operation_wall_ns=900),
                effective_backend=backend,access_validation='passed',service_origin=origin)


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_contract(ROOT,'comparison-contract')

    def freeze(self, s):
        return freeze_comparison(self.schema,s)

    def pair(self,b,a,c,other=None):
        return admission_reasons(self.schema,[b,other or b],[a,c])

    def test_same_budget_allows_different_actual_threads_isa_methods_and_builds(self):
        b = self.freeze(spec())
        a,c = observed(b),observed(b,'b',4,'avx2')
        self.assertEqual([],self.pair(b,a,c))
        c['resource']['peak_active_threads_total'] = 5  # Includes external worker plus native team.
        self.assertIn('1:resource_budget_not_verified',self.pair(b,a,c))
        c['resource']['peak_active_threads_total'] = None
        self.assertIn('1:resource_budget_not_verified',self.pair(b,a,c))
        altered = spec(); altered['resource']['physical_cores'] = 5
        other = self.freeze(altered)
        self.assertIn('different_comparison_contract',self.pair(b,a,observed(other,'b'),other))

    def test_r_requires_identical_encoded_representation_o_does_not(self):
        s = spec(); s['track'] = 'representation_controlled'
        with self.assertRaisesRegex(ContractError,'R requires'):
            self.freeze(s)
        s['representation'] = dict(input_id=content_id('input'),schema_id=content_id('u16'),layout_id=content_id('interleave'))
        b = self.freeze(s)
        s2 = deepcopy(s); s2['representation']['layout_id'] = content_id('planar')
        other = self.freeze(s2)
        self.assertIn('different_comparison_contract',self.pair(b,observed(b),observed(other,'b'),other))
        s['track'] = 'original_task'
        with self.assertRaisesRegex(ContractError,'O must not constrain'):
            self.freeze(s)

    def test_native_stream_and_bounded_batch_wrapper_only_share_effective_service(self):
        def lane(b,name,mechanism):
            return dict(observed(b,name,origin=mechanism),measure_includes_ingress_buffer_backpressure_finish=True,
                        stream=dict(max_buffer_bytes=32,max_first_output_ns=75,max_output_gap_ns=180,backpressure='passed',
                                    finish_restores_all=True,emitted_before_finish=True,replayed=False))
        s = with_stream(spec())
        b = self.freeze(s)
        a,c = lane(b,'a','native'),lane(b,'b','external_chunked_batch')
        self.assertEqual([],self.pair(b,a,c))
        for key,value in [('emitted_before_finish',False),('max_buffer_bytes',65),('max_first_output_ns',101),
                          ('max_output_gap_ns',201),('replayed',True),('backpressure','missing')]:
            changed = deepcopy(c); changed['stream'][key] = value
            self.assertIn('1:stream_bounds_completion_or_cost_not_verified',self.pair(b,a,changed))
        self.assertIn('1:stream_bounds_completion_or_cost_not_verified',
                      self.pair(b,a,{**c,'measure_includes_ingress_buffer_backpressure_finish':False}))
        s['access']['mechanism']='native_only'
        b = self.freeze(s)
        self.assertIn('1:native_mechanism_required',self.pair(b,lane(b,'a','native'),lane(b,'b','external_chunked_batch')))
        strict = self.freeze(with_stream(spec(),'stream_strict_online'))
        self.assertIn('1:batch_wrapper_not_strict_online',self.pair(strict,lane(strict,'a','native'),lane(strict,'b','external_chunked_batch')))
        s['boundary']['size_scope']='payload'
        with self.assertRaisesRegex(ContractError,'full time/byte accounting'):
            self.freeze(s)

    def test_tv_controls_quality_validation_retention_and_id_fail_closed(self):
        s = spec(); s['task'] = 'shared_t_controlled'; s['quality']['exact_components'].append('T')
        with self.assertRaisesRegex(ContractError,'requires a fixed timestamp'):
            self.freeze(s)
        s['control'] = dict(kind='fixed_timestamp_route',route_id=content_id('T route incl build options and policy'))
        b = self.freeze(s)
        a,c = observed(b),observed(b,'b')
        a['fixed_timestamp_route']=c['fixed_timestamp_route']=s['control']['route_id']
        self.assertEqual([],self.pair(b,a,c))
        changes = [('fixed_timestamp_route','', 'fixed_branch_differs'), ('quality','rejected','terminal_domain_or_quality_not_verified'),
                   ('independently_restored_samples',0,'independent_recovery_missing'),('raw_bytes',9,'work_or_byte_accounting_incomplete'),
                   ('pass_kind','profiled','not_primary_timing'),('qualification_id',None,'missing_method_build_or_evidence_identity')]
        for k,value,reason in changes:
            self.assertIn(f'1:{reason}',self.pair(b,a,{**c,k:value}))
        self.assertIn('duplicate_observations',self.pair(b,a,{**c,'observation_id':a['observation_id']}))
        self.assertIn('0:invalid_comparison_identity',self.pair({**b,'comparison_id':'0'*64},a,c))
        s['validation']['strength'] = 'artifact_replay'
        other = self.freeze(s); a,c = observed(other),observed(other,'b')
        for row in (a,c):
            row['verification_strength']='artifact_replay'
            row['fixed_timestamp_route']=s['control']['route_id']
        self.assertIn('1:verification_strength_or_replay_missing',self.pair(other,a,c))
        a['verified_replay_id']=content_id('actual replay a'); c['verified_replay_id']=content_id('actual replay b')
        self.assertEqual([],self.pair(other,a,c))

    def test_cli_freeze_matches_api_and_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'schemas').mkdir()
            (root/'schemas/comparison-contract.schema.json').write_text(json.dumps(self.schema.document))
            path = root/'comparison.json'; path.write_text(json.dumps(spec()))
            argv = [sys.executable,'-B',ROOT/'bmk','--root',root,'comparison-plan','--config',path.name]
            cp = subprocess.run(argv,check=True,capture_output=True,text=True)
            self.assertEqual(plan_comparison(root,path.name),json.loads(cp.stdout))
            path.write_text(json.dumps({**spec(),'comparison_group':'not a substitute for contract'}))
            cp = subprocess.run(argv,capture_output=True,text=True)
            self.assertEqual(2,cp.returncode)
            self.assertIn('violates comparison-contract schema',cp.stderr)
