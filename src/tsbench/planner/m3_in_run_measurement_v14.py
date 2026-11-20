"""Extend CORAD inference clock to timed raw source ingress on encode."""
from ..assets import digest, local_file
from .m3_in_run_measurement_v13 import freeze as freeze_v13

SCHEMA = 'bmk.m3-in-run-measurement/14'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v14.py', 'src/tsbench/application/m3_in_run_corad_pipeline.py',
        'src/tsbench/application/m3_corad_raw_ingress.py', 'src/tsbench/corpus_ingress.py')


def freeze(root, plan, *args):
    prior = freeze_v13(root, plan, *args)
    corad = prior['corad_clock']
    return {**prior, 'schema': SCHEMA, 'corad_clock': {**corad,
            'policy': {**corad['policy'], 'not_measured':'original_source_ingress_not_part_of_train_or_decode_trials',
                       'raw_encode':'one_full_verified_source_parse_per_trial_selecting_only_frozen_heldout_slices_shared_by_both_producers',
                       'raw_encode_wall':'from_source_parse_through_both_producers_encode_verify_sync_and_evidence_publication'},
            'code': {**corad['code'], **{p:digest(local_file(root,p)) for p in CODE}}}}
