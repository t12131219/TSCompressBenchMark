"""Dispatch the final CORAD producer and inference measurements."""
from ..planner.m3_in_run_measurement_v13 import CORAD
from . import m3_in_run_corad as corad
from .m3_in_run_measurement import unavailable
from .m3_primary_measurement_v12 import observe as previous


def observe(root,plan,item,entry,pbepla_pairs,run,row):
    prescribed=plan['measurement']['population'][item['work_item_id']]
    if prescribed.get('adapter')!=CORAD:
        return previous(root,plan,item,entry,pbepla_pairs,run,row)
    if row['status'] not in corad.READY:
        return unavailable(prescribed,row['status'])
    return corad.observe(root,plan,item,entry,run,row)
