"""Dispatch the dictionary route without changing previous versions of the observer."""
from ..planner.m3_in_run_measurement_v9 import DICTIONARY
from . import m3_in_run_zstd_dictionary as dictionary
from .m3_in_run_measurement import unavailable
from .m3_primary_measurement_v8 import observe as previous


def observe(root, plan, item, entry, pbepla_pairs, run, row):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    if prescribed.get('adapter') != DICTIONARY:
        return previous(root,plan,item,entry,pbepla_pairs,run,row)
    if row['status'] != 'verified':
        return unavailable(prescribed,row['status'])
    return dictionary.observe(root,plan,item,entry,run,row)
