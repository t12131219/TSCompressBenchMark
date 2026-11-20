"""Dispatch independent native Titchy file-local work without changing old observers."""
from ..planner.m3_in_run_measurement_v8 import TITCHY
from . import m3_in_run_titchy as titchy
from .m3_in_run_measurement import unavailable
from .m3_primary_measurement_v7 import observe as previous


def observe(root, plan, item, entry, pbepla_pairs, run, row):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    if prescribed.get('adapter') != TITCHY:
        return previous(root, plan, item, entry, pbepla_pairs, run, row)
    if row['status'] != 'verified':
        return unavailable(prescribed, row['status'])
    return titchy.observe(root, plan, item, entry, run, row)
