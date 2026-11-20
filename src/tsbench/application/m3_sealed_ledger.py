"""Read full M3 evidence in ledger order without materializing its detailed report."""
from ..assets import content_id, digest, load_json, local_file, parse_json, require


def full_run_source(plan, run):
    """Bind the immutable report and ledger bytes to one frozen plan and run."""
    require(plan['plan_content_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}),
            'M3 full ledger plan identity differs')
    ledger, report, seal = (local_file(run, n) for n in ('ledger.jsonl', 'report.json', 'completion.json'))
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(report), 'ledger_sha256': digest(ledger)}
    seal_id = content_id(body)
    require(load_json(seal) == {**body, 'seal_id': seal_id}, 'M3 full ledger source seal differs')
    return ledger, seal_id


def full_run_rows(plan, ledger):
    """Require the complete ordered corpus and obligation populations on exhaustion.

    Product payload validation and report-to-ledger equality remain separate
    audits. The caller must exhaust the iterator before publishing results.
    """
    work, obligations = iter(plan['work_items']), iter(plan['obligations'])
    phase = 'corpus'
    with ledger.open(encoding='utf-8') as stream:
        for index, text in enumerate(stream, 1):
            row = parse_json(text, f'M3 full ledger line {index}')
            kind = row.get('entry_kind')
            if kind is None:
                wanted = next(work, None)
                require(phase == 'corpus' and wanted is not None and
                        all(row.get(k) == wanted[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route',
                                                              'operation', 'applicability')),
                        'M3 full ledger corpus decision is extra, out of order or foreign')
                yield row, wanted
                continue
            if phase == 'corpus':
                require(next(work, None) is None, 'M3 full ledger omits frozen corpus decisions before its typed tail')
                phase = 'products'
            if kind == 'specialized_obligation':
                phase = 'obligations'
                wanted = next(obligations, None)
                require(wanted is not None and
                        all(row.get(k) == wanted[k] for k in ('obligation_id', 'selection', 'route', 'kind', 'check')),
                        'M3 full ledger obligation is extra, out of order or foreign')
                yield row, wanted
            else:
                require(phase == 'products' and kind in {'specialized_product', 'implementation_regression'},
                        'M3 full ledger contains an unexpected typed row')
                yield row, None
    require(next(work, None) is None and next(obligations, None) is None,
            'M3 full ledger omits frozen corpus decisions or obligations')
