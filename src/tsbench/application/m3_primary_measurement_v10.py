"""Dispatch same-run lzbench clocks, retaining version-nine routes unchanged."""
from ..planner.m3_in_run_measurement_v10 import LZBENCH
from . import m3_in_run_lzbench as lzbench
from .m3_in_run_measurement import unavailable
from .m3_primary_measurement_v9 import observe as previous


def observe(root, plan, item, entry, pbepla_pairs, run, row):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    if prescribed.get('adapter') != LZBENCH:
        return previous(root,plan,item,entry,pbepla_pairs,run,row)
    if row['status'] != 'verified':
        return unavailable(prescribed,row['status'])
    return lzbench.observe(root,plan,item,entry,run,row)
