"""Dispatch native Huff0 shared-table clocks beside v11 routes."""
from ..planner.m3_in_run_measurement_v12 import HUFF0
from . import m3_in_run_huff0_table as table
from .m3_in_run_measurement import unavailable
from .m3_primary_measurement_v11 import observe as previous


def observe(root,plan,item,entry,pbepla_pairs,run,row):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    if prescribed.get('adapter') != HUFF0:
        return previous(root,plan,item,entry,pbepla_pairs,run,row)
    if row['status'] != 'verified':
        return unavailable(prescribed,row['status'])
    return table.observe(root,plan,item,entry,run,row)
