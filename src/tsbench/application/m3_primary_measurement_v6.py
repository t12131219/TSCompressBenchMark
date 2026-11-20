"""Dispatch the added v6 whole-file timing population without changing prior observers."""
from ..planner.m3_in_run_measurement_v6 import WHOLE
from . import m3_in_run_whole as whole
from .m3_in_run_measurement import unavailable
from .m3_primary_measurement_v5 import observe as previous


def observe(root, plan, item, entry, pbepla_pairs, run, row):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    if prescribed.get('adapter') != WHOLE:
        return previous(root, plan, item, entry, pbepla_pairs, run, row)
    if row['status'] != 'verified':
        return unavailable(prescribed, row['status'])
    return whole.observe(root, plan, item, row, entry, run)
