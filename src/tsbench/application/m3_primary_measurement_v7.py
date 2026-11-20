"""ZFP observer with explicit non-admitted array quality diagnostics."""
from ..planner.m3_in_run_measurement_v7 import ZFP
from . import m3_in_run_zfp as zfp
from .m3_in_run_measurement import unavailable
from .m3_primary_measurement_v6 import observe as previous


def observe(root, plan, item, entry, pbepla_pairs, run, row):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    if prescribed.get('adapter') != ZFP:
        return previous(root, plan, item, entry, pbepla_pairs, run, row)
    if row['status'] != 'verified' and not (item['route'] == zfp.array.ROUTE and row['status'] == 'quality_rejected'):
        return unavailable(prescribed, row['status'])
    return zfp.observe(root, plan, item, entry, run, row)
