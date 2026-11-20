"""v5 Gorilla observer: identical operation boundaries with durable failure diagnostics."""
from pathlib import Path
from tempfile import TemporaryDirectory

from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_in_run_failure as failure, m3_in_run_gorilla as original
from .m3_in_run_measurement import guard

FAILED = 'measurement-gorilla-failures'


def measure(root, plan, item, entry, work, run, row):
    frozen = plan['measurement']
    prescribed = frozen['population'][item['work_item_id']]
    case_id = prescribed['case_id']
    directory = f'{FAILED}/{case_id}'
    base = run / original.DIRECTORY / case_id
    before = resource.observe(frozen['environment']['cpu'])
    binding = frozen['gorilla']
    lane = 'original' if item['route'] == 'tv-batch' else 'repair'
    clock = original.clock
    directions = tuple(clock.CLOCKS[item['route']])
    anchors = error = None
    trials, logs = [], []
    scratch = work / 'reference'
    try:
        case = original._case(plan, item, row, entry)
        stage_recovery(root, work, binding['bindings'][lane]['runtime'], directory=f'runtime-{lane}')
        source = work / 'canonical'
        canonical = original._stage(root, entry, case, source)
        restored = original._outputs(case, row, source)
        fixed, product, _ = clock._invoke(work, binding, case, source, base, scratch / 'encode', 'encode')
        control = {}
        for direction in directions[1:]:
            output, record, _ = clock._invoke(work, binding, case, source, fixed, scratch / direction, direction)
            control[direction] = (output, record)
        clock._verify_products(case, source, fixed, product, control['decode'], control.get('snapshot_decode'))
        archive = original._check_anchor(fixed, case, row)
        base.mkdir(parents=True)
        fixed.rename(base / 'fixed')
        anchors = {'canonical': canonical, 'fixed': archive, 'restored': restored}
    except (OSError, ValueError) as exc:
        logs = failure.retain(run, directory, 'anchor', scratch, directions)
        error = 'Gorilla same-run anchor failed: ' + failure.reason(exc, scratch, run / directory / 'anchor')
    for slot in original.schedule(case_id, item['route']):
        identity = {**slot, 'case_id': case_id}
        if error:
            trials.append({**identity, 'status': 'not_run_after_measurement_failure', 'reason': error})
            continue
        with TemporaryDirectory(prefix='trial-', dir=work) as tmp:
            scratch = Path(tmp)
            try:
                trials.append(original._trial(root, run, work, scratch, binding, case, entry, slot, anchors))
            except (OSError, ValueError) as exc:
                logs = failure.retain(run, directory, 'trial', scratch, (slot['direction'],))
                error = failure.reason(exc, scratch, run / directory / 'trial')
                trials.append({**identity, 'status': 'measurement_failed', 'reason': error})
    doc = {**prescribed, 'status': 'measurement_failed' if error else 'measured_and_verified', 'reason': error,
           'trials': trials, 'anchors': anchors, 'resource_before': before,
           'resource_after': resource.observe(frozen['environment']['cpu']), 'timing_admitted': False,
           'failure_logs': logs}
    return {**doc, 'summary': recompute(root, plan, item, row, entry, run, doc, set(), check_anchors=False)}


def recompute(root, plan, item, row, entry, run, doc, seen, *, check_anchors=True):
    case_id = plan['measurement']['population'][item['work_item_id']]['case_id']
    failure.check(run, f'{FAILED}/{case_id}', doc, tuple(original.clock.CLOCKS[item['route']]), full=check_anchors)
    return original.recompute(root, plan, item, row, entry, run, doc, seen, check_anchors=check_anchors)


def observe(root, plan, item, entry, run, row):
    with guard(plan), TemporaryDirectory(prefix='m3-gorilla-retained-', dir=run) as work:
        return measure(root, plan, item, entry, Path(work), run, row)
