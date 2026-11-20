"""Adapter dispatch for current measured execution without changing legacy runs."""
from pathlib import Path
from tempfile import TemporaryDirectory

from ..assets import require
from ..planner.m3_pbepla import PROGRESSIVE, REPLAY
from ..planner.m3_in_run_measurement import ADAPTER as PBEPLA
from .m3_in_run_batch import DIRECTORIES, measure as measure_batch
from .m3_in_run_measurement import guard, measure as measure_pbepla, unavailable


def observe(root, plan, item, entry, pbepla_pairs, run, row):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    if prescribed['status'] != 'scheduled' or row['status'] != 'verified':
        return unavailable(prescribed, row['status'])
    adapter = prescribed['adapter']
    with guard(plan), TemporaryDirectory(prefix='m3-timing-', dir=run) as work:
        if adapter == PBEPLA:
            partner = pbepla_pairs[item['dataset_id'], PROGRESSIVE if item['route'] == REPLAY else REPLAY]
            return measure_pbepla(root, plan, item, partner, entry, Path(work), run, row)
        require(adapter in DIRECTORIES, 'unknown frozen measurement adapter')
        return measure_batch(root, plan, item, entry, Path(work), run, row)
