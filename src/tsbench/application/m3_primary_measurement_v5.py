"""Primary measurement dispatch preserving prior observers and frozen policies."""
from ..planner.m3_in_run_measurement_v4 import GORILLA
from ..planner.m3_in_run_measurement_v5 import PCODEC_PAGES
from . import m3_in_run_gorilla_retained as gorilla, m3_in_run_pcodec_pages as pages
from .m3_in_run_measurement import unavailable
from .m3_primary_measurement import observe as previous


def observe(root, plan, item, entry, pbepla_pairs, run, row):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    adapter = prescribed.get('adapter')
    if adapter not in (GORILLA, PCODEC_PAGES):
        return previous(root, plan, item, entry, pbepla_pairs, run, row)
    if row['status'] != 'verified':
        return unavailable(prescribed, row['status'])
    return (gorilla if adapter == GORILLA else pages).observe(root, plan, item, entry, run, row)
