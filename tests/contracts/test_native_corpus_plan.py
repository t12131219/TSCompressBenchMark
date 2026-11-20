from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import unittest
from unittest.mock import patch

from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import MANIFEST, fingerprint
from tsbench.planner.corad_corpus import C, INFERENCE, SOURCE, calibrate_quality
from tsbench.planner.native_admission import plan_native_admission
from tsbench.planner.native_corpus import POLICY, _compile, verify_native_corpus_plan
from tsbench.planner.pbepla_corpus import bind_native_pair

ROOT = Path(__file__).resolve().parents[2]


class NativeCorpusPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_json(ROOT / MANIFEST)
        cls.policy = load_json(ROOT / POLICY)
        cls.native = plan_native_admission(ROOT)
        weather = next(row for row in cls.manifest['datasets'] if row['id'] == 'weather')
        cls.sentinels = {}
        stats = fingerprint(ROOT, weather, sentinel_spans=cls.sentinels)
        assert stats['canonical'] == weather['canonical']
        cls.plan = _compile(cls.manifest, cls.policy, cls.native, {'manifest': MANIFEST, 'policy': POLICY},
                            {'weather': cls.sentinels})
        cls.index = {(row['dataset_id'], row['route']): row for row in cls.plan['decisions']}

    def test_exact_real_applicability_and_specialized_obligations_are_separate(self):
        p = self.plan
        self.assertEqual(p['coverage']['file_route_decisions'], len(self.index))
        self.assertEqual(len(self.index), 23*36)
        self.assertEqual(p['coverage']['selections'], 12)
        self.assertEqual(Counter(item['kind'] for item in p['obligations']), {'required': 180, 'conditional': 6})
        self.assertEqual({x['obligation_id'] for x in p['obligations']}, {x['obligation_id'] for x in self.native['obligations']})
        self.assertFalse(any(x['corpus_cases_replace_specialized_checks'] for x in p['obligations']))
        self.assertTrue(all(x['planned_case_inputs'] for x in p['obligations'] if x['kind'] == 'required'))
        self.assertTrue(any(x.get('condition_case', {}).get('predicate') == 'alp_f64_avx512bw_available'
                            for x in p['obligations']))
        self.assertTrue(all(x['execution_state'] == 'not_run' and not x['qualification_granted'] for x in p['decisions']))
        self.assertFalse(p['runnable'])
        self.assertFalse(p['stage_accepted'])

    def test_declared_domains_not_inferred_from_suffix_configuration_or_host(self):
        def status(dataset, route):
            d = self.index[dataset, route]
            return d['state'], d['reasons']
        self.assertEqual(status('economics-17', 'tv-batch'),
                         ('outside_declared_domain', ['source_index_has_no_defined_mapping_to_ms']))
        self.assertEqual(status('economics-17', 'intmult'),
                         ('outside_declared_domain', ['native_unsigned_integer_semantics_required_no_implicit_cast']))
        self.assertEqual(status('economics-17', 'zstd-workers'),
                         ('condition_not_triggered', ['smaller_than_frozen_worker_probe_extent_no_padding']))
        self.assertEqual(status('traffic', 'zstd-workers')[0], 'input_domain_matches')
        self.assertEqual(status('etth1', 'corad-inference')[0], 'input_domain_matches')
        self.assertEqual(status('weather', 'pbepla-progressive')[0], 'input_domain_matches')
        self.assertEqual(status('weather', 'auto-batch')[0], 'input_domain_matches')

    def test_size_and_scope_are_not_confused_with_success_or_full_rows(self):
        d = self.index['etth1', 'tv-batch']['input']
        self.assertEqual(d['size_estimate']['unique_logical_axis_bytes'], 8 * 17420)
        self.assertEqual(d['size_estimate']['unique_logical_value_bytes'], 8 * 17420 * 7)
        self.assertEqual(d['size_estimate']['native_input_bytes_one_pass'], 16 * 17420 * 7)
        self.assertEqual(d['size_estimate']['input_units'], 7 * 35)
        self.assertFalse(d['source_bytes_recovery'])
        d = self.index['traffic', 'zstd-dictionary']['input']
        self.assertEqual([p['partition'] for p in d['row_ranges']], ['train', 'test'])
        self.assertEqual([p['partition'] for p in d['skipped_row_ranges']], ['development'])
        self.assertFalse(d['full_extent_of_file_rows_and_value_columns'])
        d = self.index['etth1', 'query']['input']
        self.assertEqual(d['planned_transforms'], ['f64_bitcast_to_u16_le_limb0_to_limb3'])
        self.assertEqual(d['shape'], ['rows', 4])
        self.assertEqual(d['size_estimate']['largest_input_unit_bytes'], 65536)

    def test_frozen_training_consumes_only_an_exact_prefix_and_keeps_test_separate(self):
        huff = self.index['economics-17', 'huff0-shared-table']
        self.assertEqual(huff['state'], 'input_domain_matches')
        self.assertEqual(huff['input']['training']['consumed_byte_range'], [0, 920])
        self.assertEqual(huff['input']['training']['evaluation']['absolute_rows'], [154, 193])
        self.assertFalse(huff['input']['training']['training_success_assumed'])
        small = self.index['economics-17', 'zstd-dictionary']
        self.assertEqual(small['state'], 'input_domain_matches')
        self.assertEqual(small['input']['training']['extent_tier'], 'short')
        self.assertEqual(small['input']['training']['dictionary_capacity_bytes'], 256)
        self.assertEqual(small['input']['training']['consumed_byte_range'], [0, 896])
        self.assertEqual(small['input']['training']['unconsumed_train_byte_range'], [896, 920])
        long = self.index['traffic', 'zstd-dictionary']['input']
        self.assertEqual(long['training']['sample_geometry'],
                         {'first_byte': 0, 'count': 128, 'bytes_each': 2048, 'stride_bytes': 2048})
        self.assertEqual(long['training']['consumed_byte_range'], [0, 262144])
        self.assertNotEqual(long['training']['partition_object_id'], long['training']['evaluation']['partition_object_id'])
        self.assertEqual(long['training']['failure_policy'], 'record_native_failure_do_not_fallback')
        self.assertNotEqual(long['training']['unconsumed_train_byte_range'][0],
                            long['training']['unconsumed_train_byte_range'][1])

    def test_corad_orders_all_columns_binds_producers_and_excludes_only_required_ranges(self):
        for e in self.manifest['datasets']:
            rows = {r: self.index[e['id'], r] for r in (C, SOURCE, INFERENCE)}
            if e['value_count'] < 2:
                self.assertTrue(all(d['state'] == 'outside_declared_domain' for d in rows.values()))
                continue
            inputs = {k: v['input'] for k, v in rows.items()}
            cohorts = inputs[INFERENCE]['corad_contract']['cohorts']
            names = []
            train, dev, test = e['partitions']
            for cohort in cohorts:
                names.extend(cohort['ordered_column_names'])
                self.assertTrue(2 <= len(cohort['ordered_column_names']) <= 8)
                start, end = cohort['train']['rows']
                self.assertTrue(train['start'] <= start < end <= train['end'])
                self.assertEqual(end - start, 129)
                self.assertTrue(all(test['start'] <= lo < hi <= test['end'] for lo,hi in cohort['test']['eligible_row_spans']))
                self.assertEqual(cohort['development_not_consumed'], [dev['start'], dev['end']])
                self.assertNotEqual(cohort['producer_binding_ids'][C], cohort['producer_binding_ids'][SOURCE])
                cols = range(*cohort['columns'])
                for col in cols:
                    for lo, hi in self.sentinels.get(col, []) if e['id']=='weather' else []:
                        self.assertTrue(end <= lo or start >= hi)
                        self.assertTrue(all(b <= lo or a >= hi for a,b in cohort['test']['eligible_row_spans']))
            self.assertEqual(names, e['columns'][1:])
            for role in (C, SOURCE):
                self.assertEqual(inputs[role]['corad_contract']['cohorts'], cohorts)
                self.assertEqual(inputs[role]['corad_contract']['deployment']['eligible_producers'], [role])
                self.assertEqual(inputs[role]['size_estimate']['native_input_bytes_one_pass'], 8*129*e['value_count'])
                self.assertEqual([r['partition'] for r in inputs[role]['row_ranges']], ['train'])
            stats = inputs[INFERENCE]['size_estimate']
            self.assertEqual(stats['native_input_bytes_one_pass'], 2*stats['unique_logical_value_bytes'])

    def test_corad_exact_train_only_calibration(self):
        from struct import pack
        self.assertEqual(calibrate_quality(pack('<6d', 1,2,4, 2,2,2), count=3, width=2), [
            {'constant_predictor':'7/3','max_abs_error':'5/3','mse':'14/9'},
            {'constant_predictor':'2','max_abs_error':'0','mse':'0'},
        ])

    def test_zfp_array_materializes_an_exact_bounded_layout_without_granting_admission(self):
        real = self.index['weather', 'fixed-rate-array']
        self.assertEqual(real['state'], 'input_domain_matches')
        self.assertEqual(real['open_execution_bindings'], ['new_corpus_driver_resource_and_validator_binding'])
        d = real['input']
        self.assertFalse(d['full_extent_of_file_rows_and_value_columns'])
        layout = d['array_contract']
        default = layout['default_column']
        overrides = {v['value_column_index']: v for v in layout['column_overrides']}
        self.assertEqual(overrides.keys(), self.sentinels.keys())
        missing = 0
        total_rows = total_units = 0
        for col in range(21):
            piece = overrides.get(col, default)
            intervals = [x['rows'] for x in piece['accepted_spans'] + piece['excluded_spans']]
            ordered = sorted(intervals)
            self.assertEqual(ordered[0][0], 0)
            self.assertEqual(ordered[-1][1], 52696)
            self.assertEqual([x[1] for x in ordered[:-1]], [x[0] for x in ordered[1:]])
            for r in piece['accepted_spans']:
                lo, hi = r['rows']
                self.assertEqual(r['windows'] * r['base_rows'] + r['first_windows_with_one_extra_row'], hi - lo)
                self.assertTrue(8 <= r['base_rows'] <= r['base_rows'] + bool(r['first_windows_with_one_extra_row']) <= 4096)
                total_rows += hi - lo
                total_units += r['windows']
            excluded = [x['rows'] for x in piece['excluded_spans']
                        if x['reason'] == 'retained_missing_sentinel_no_lossy_mutation']
            self.assertEqual(excluded, self.sentinels.get(col, []))
            missing += sum(hi - lo for lo, hi in excluded)
        self.assertEqual(missing, 81)
        self.assertEqual(d['size_estimate']['native_input_bytes_one_pass'], total_rows * 8)
        self.assertEqual(d['size_estimate']['input_units'], total_units)
        self.assertTrue(self.index['traffic', 'fixed-rate-array']['input']['full_extent_of_file_rows_and_value_columns'])
        with self.assertRaisesRegex(ContractError, 'needs verified per-column sentinel spans'):
            _compile(self.manifest, self.policy, self.native, {})

    def test_policy_and_cover_checks_are_fail_closed(self):
        schema = load_contract(ROOT, 'native-corpus-policy')
        doc = deepcopy(self.policy)
        doc['routes'][0]['options']['typo'] = True
        with self.assertRaisesRegex(ContractError, 'typo'):
            schema.validate(doc, 'route policy')
        doc = deepcopy(self.policy)
        doc['routes'][0] = doc['routes'][1]
        with self.assertRaisesRegex(ContractError, '36 native route identities'):
            _compile(self.manifest, doc, self.native, {})
        native = deepcopy(self.native)
        native['obligations'].pop()
        with self.assertRaisesRegex(ContractError, 'obligation or specialized input denominator'):
            _compile(self.manifest, self.policy, native, {}, {'weather': self.sentinels})
        doc = deepcopy(self.policy)
        route = next(r for r in doc['routes'] if r['route'] == 'fixed-rate-array')
        route['array_layout']['quality']['relative_to_expected'] = 1.0
        with self.assertRaises(ContractError):
            schema.validate(doc, 'route policy')
        route.pop('array_layout')
        with self.assertRaisesRegex(ContractError, 'missing or misplaced'):
            _compile(self.manifest, doc, self.native, {})

    def test_pbepla_replay_and_progressive_bind_exactly_the_same_finite_windows(self):
        for entry in self.manifest['datasets']:
            routes = (self.index[entry['id'], route]['input'] for route in ('pbepla-progressive', 'pbepla-replay'))
            batch, replay = routes
            p = batch['pbepla_contract']
            self.assertEqual({**p, 'replay': replay['pbepla_contract']['replay']}, replay['pbepla_contract'])
            self.assertFalse(replay['pbepla_contract']['replay']['online_input'])
            self.assertEqual(p['layout']['requested_eps'], [16, 4, 1])
            self.assertEqual(batch['size_estimate'], replay['size_estimate'])
            self.assertEqual(batch['size_estimate']['unique_logical_value_bytes'],
                             8*(entry['rows']*entry['value_count'] - entry['retained_sentinel_values']))
            for row in p['column_overrides']:
                self.assertEqual([r['rows'] for r in row['excluded_spans']],
                                 self.sentinels[row['value_column_index']])
        doc = deepcopy(self.policy)
        route = next(r for r in doc['routes'] if r['route']=='pbepla-replay')
        route['prefix_layout']['requested_eps'] = [16, 4, 2]
        with self.assertRaisesRegex(ContractError, 'extent or quality differs'):
            _compile(self.manifest, doc, self.native, {})

    def test_pbepla_pair_reads_the_declared_column_not_a_fixture_or_another_value_column(self):
        e = next(r for r in self.manifest['datasets'] if r['id']=='national-illness')
        native = [self.index[e['id'], route] for route in ('pbepla-progressive', 'pbepla-replay')]
        (batch, replay), raw = bind_native_pair(ROOT, e, *native, column=2, window=0)
        (_, other), raw_other = bind_native_pair(ROOT, e, *native, column=3, window=0)
        self.assertEqual(batch['spec'], replay['spec'])
        self.assertEqual(replay['spec']['source']['absolute_row_range'], [0, e['rows']])
        self.assertEqual(replay['spec']['source']['column_name'], e['columns'][3])
        self.assertEqual(replay['spec']['input_sha256'], sha256(raw).hexdigest())
        self.assertNotEqual(replay['product_slot'], other['product_slot'])
        self.assertNotEqual(raw, raw_other)
        with self.assertRaisesRegex(ContractError, 'missing PBEPLA planned window ordinal'):
            bind_native_pair(ROOT, e, *native, column=2, window=1)

    def test_reseal_cannot_drop_decisions_or_elevate_admission(self):
        forged = deepcopy(self.plan)
        forged['decisions'].pop()
        forged['qualification_granted'] = True
        forged['plan_content_id'] = content_id({k: v for k, v in forged.items() if k != 'plan_content_id'})
        with patch('tsbench.planner.native_corpus.plan_native_corpus', return_value=self.plan):
            self.assertTrue(verify_native_corpus_plan(ROOT, self.plan)['definition_verified'])
            with self.assertRaisesRegex(ContractError, 'differs from the full rederived definition'):
                verify_native_corpus_plan(ROOT, forged)
