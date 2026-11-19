"""Integration control for a trusted sealed candidate under nested Bubblewrap.

Call with only the control layer, its runtime and the sealed runs mounted.
The production restore audit adds a files-only namespace for each decoder.
"""
from copy import deepcopy
from pathlib import Path
import sys

from tsbench.api import audit_smoke_restore
from tsbench.application.restore import _restore
from tsbench.application.smoke import _read_report
from tsbench.assets import ContractError, canonical_bytes, verify_asset
from tsbench.recovery import DIRECTORY


def expect_rejected(call, reason):
    try:
        call()
    except ContractError as exc:
        assert reason in str(exc), str(exc)
        return str(exc)
    raise AssertionError('incorrectly accepted negative restore control')


def main(root, run_id):
    report, run, plan, _ = _read_report(root, run_id)
    assert canonical_bytes(report) + b'\n' == (run / 'derived/report.json').read_bytes()
    audit = audit_smoke_restore(root, run_id)
    assert audit['restored_verified_slots']==audit['planned_slots']==18 and not audit['qualification_granted']
    spec = plan['contract_bindings']['recovery']
    bundle = run/DIRECTORY
    timeout = plan['suite']['timeout_seconds_per_operation']
    cases = {(c['method_id'],c['input_id']):c for c in report['cases']}
    short = cases['alp-auto','short-finite-f64']
    special = cases['alp-auto','special-f64-bits']
    method = plan['methods']['alp-auto']
    short_source = plan['inputs'][short['input_id']]
    wrong_artifact = verify_asset(run, special['artifact'])
    short_artifact = verify_asset(run, short['artifact'])
    assert short_source['count']==plan['inputs'][special['input_id']]['count']
    incomplete = deepcopy(spec)
    del incomplete['files']['lib/libalp_native.so']
    # Bypass only the planner's graph check to observe the actual loader rejecting this namespace.
    missing = expect_rejected(lambda: _restore(bundle,incomplete,method,short_artifact,short_source,timeout),
                              'libalp_native.so: cannot open shared object file')
    differing = expect_rejected(lambda: _restore(bundle,spec,method,wrong_artifact,short_source,timeout),
                                'values or schema differ')
    wrong_schema = {**short_source, 'schema_sha256':'0'*64}
    bad_schema = expect_rejected(lambda: _restore(bundle,spec,method,short_artifact,wrong_schema,timeout),
                                 'values or schema differ')
    return {'audit':audit, 'report_byte_identical':True, 'negative_controls':{'missing_dso_no_host_fallback':missing,
                                               'different_valid_same_shape_frame':differing,
                                               'different_expected_schema':bad_schema}}


if __name__=='__main__':
    _, root, run_id = sys.argv
    sys.stdout.buffer.write(canonical_bytes(main(Path(root), run_id))+b'\n')
