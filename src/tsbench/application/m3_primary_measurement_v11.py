"""Dispatch native Sprintz query clocks without perturbing v10 decisions."""
from ..planner.m3_in_run_measurement_v11 import SPRINTZ
from . import m3_in_run_sprintz_query as sprintz
from .m3_in_run_measurement import unavailable
from .m3_primary_measurement_v10 import observe as previous


def observe(root,plan,item,entry,pbepla_pairs,run,row):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    if prescribed.get('adapter') != SPRINTZ:
        return previous(root,plan,item,entry,pbepla_pairs,run,row)
    if row['status'] != 'verified':
        return unavailable(prescribed,row['status'])
    return sprintz.observe(root,plan,item,entry,run,row)
