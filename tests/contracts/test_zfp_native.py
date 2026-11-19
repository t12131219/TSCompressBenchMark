"""Offline original-domain and OpenMP evidence checks (no ZFP DSO required)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import ContractError, canonical_bytes
from tsbench.planner.zfp import field_input, field_layout, field_metadata, pack, ref, values
from tsbench.qualification.zfp import _verify_fields, compare_numeric, work_counts


class ZfpNativeTests(unittest.TestCase):
    def test_native_worker_records_require_actual_distinct_work(self):
        work = [{'tid': 203, 'blocks': 1024}, {'tid': 205, 'blocks': 1024}]
        work_counts(work, 2, 2048, 203)
        for rows, caller in (([work[0]], 203), ([work[0], work[0]], 203), (work, 206),
                             ([work[0], {'tid':205,'blocks':0}], 203), (work, True)):
            with self.subTest(rows=rows,caller=caller), self.assertRaises(ContractError):
                work_counts(rows, 2, 2048, caller)
        with self.assertRaisesRegex(ContractError,'total block work'):
            work_counts(work, 2, 2047, 203)

    def test_field_quality_comes_from_strided_original_domain(self):
        spec = {'id':'accuracy-reversed-padded','type':'f64','mode':'accuracy','shape':[2,2],
                'strides':[-2,7],'requested':.125,'effective':.125,'max_observed_error':.125,
                'artifacts':{'payload':'a.zfp','metadata':'a.json','restored_span':'a.out'}}
        layout = field_layout(spec)
        self.assertEqual(layout['offsets'], [4,2,11,9])
        source = field_input(spec,b'')
        spec['input'] = ref('frozen:'+spec['id'],source)
        span = [8191]*layout['span_count']
        for i,v in zip(layout['offsets'],values('f64',source),strict=True):
            span[i] = v+.0625
        payload, metadata = b'testword', canonical_bytes(field_metadata(spec))
        files = {'a.zfp':payload, 'a.json':metadata, 'a.out':pack('f64',span)}
        row = {'case':spec['id'],'dtype':'f64','mode':'accuracy','shape':[2,2],'strides_elements':[-2,7],
               'offset_bounds':[-2,7],'origin_elements':4,'input':spec['input'],'logical_bytes':len(source),
               'requested_parameter':.125,'effective_parameter':.125,'observed_max_abs_error':.0625,'observed_rmse':.0625,
               'predeclared_case_error_limit':.125,'bad_origin_status':1,
               'payload':ref('a.zfp',payload),'metadata':ref('a.json',metadata),'restored_span':ref('a.out',files['a.out'])}
        _verify_fields({'fields':[spec]},[row],files.__getitem__,b'')
        for idx,new,reason in ((0,8192,'padding'), (2,1e4,'original-domain'), (2,float('nan'),'nonfinite')):
            edited = span.copy(); edited[idx] = new
            files['a.out'] = pack('f64',edited)
            updated = {**row,'restored_span':ref('a.out',files['a.out'])}
            with self.subTest(reason=reason), self.assertRaisesRegex(ContractError,reason):
                _verify_fields({'fields':[spec]},[updated],files.__getitem__,b'')
        with self.assertRaisesRegex(ContractError,'incomplete'):
            compare_numeric([1,2],[1],0,'bad length')
