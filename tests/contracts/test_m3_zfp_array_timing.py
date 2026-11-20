from struct import pack

import pytest

from tsbench.application import m3_zfp_array_timing as z
from tsbench.application.m3_measurement_inventory import _linked
from tsbench.assets import ContractError, canonical_bytes
from tsbench.supervisor import zfp_array_grouped as launch


def case_fixture():
    values = (2., 1., 4., 8., 16., 32., 64., 128., 256.)
    raw = pack('<9d', *values)
    updated = list(values)
    updated[1] = values[-1]
    updated[3:7] = values[:4]
    before, after = b'I'*32 + b'U'*16, b'F'*32 + b'U'*16
    recovered = pack('<9d', *updated)
    broken = pack('<9d', *(updated[:-1] + [32.]))
    u = {'column': 0, 'row_range': [2, 11], 'logical_input_bytes': len(raw), 'input': z._stamp(raw),
         'restored': z._stamp(recovered), 'exact_mutated_reference': z._stamp(recovered),
         'config': z._config(9), 'before_frame': z._stamp(before), 'after_frame': z._stamp(after),
         'before': {'accepted': True, 'violations': 0, 'max_abs_error': 0.},
         'after': {'accepted': True, 'violations': 0, 'max_abs_error': 0.}}
    c = {'units': [u], 'columns': 1, 'rows': 12, 'native_frame_bytes': 48, 'logical_bytes': len(raw)}
    assets = (raw, before, after, recovered, broken)
    return c, assets


def product(c, tag, payload):
    head = z.HEAD.pack(tag, *z._shape(c))
    r = z.RATES.pack(18,32) if tag == z.WIRE else b''
    return head + r + z.WINDOW.pack(0,2,9) + payload


def test_both_fixed_archives_are_verified_in_frozen_window_ownership(tmp_path):
    c, (_, before, after, _, _) = case_fixture()
    paths = {role: tmp_path/role for role in z.ARCHIVE_ROLES}
    paths['initial'].write_bytes(product(c, z.WIRE, before))
    paths['updated'].write_bytes(product(c, z.WIRE, after))
    assert all(a['bytes'] == 84 for a in z._archives(c, paths).values())
    paths['updated'].write_bytes(product(c,z.WIRE,after) + b'\x00')
    with pytest.raises(ContractError, match='trailing'):
        z._archives(c, paths)
    # Even an input digest matched to an edited payload cannot excuse changing an untouched block.
    bad = after[:-1] + b'!'
    paths['updated'].write_bytes(product(c,z.WIRE,bad))
    c['units'][0]['after_frame'] = z._stamp(bad)
    with pytest.raises(ContractError, match='untouched'):
        z._archives(c, paths)


def test_reopened_validation_is_original_domain_and_side_specific(tmp_path):
    c, (raw, _, _, expected, broken) = case_fixture()
    original = tmp_path/'original.zar'
    original.write_bytes(product(c, z.RAW, raw))
    got = tmp_path/'restored.zav'
    got.write_bytes(product(c, z.VALUES, expected))
    _, quality = z._reopened(c,'updated',original,got)
    assert quality['compared_windows'] == 1 and quality['rejected_windows'] == 0
    with pytest.raises(ContractError, match='quality differs'):
        z._reopened(c,'initial',original,got)
    got.write_bytes(product(c, z.VALUES, broken))
    with pytest.raises(ContractError, match='exact mutated reference differs'):
        z._reopened(c,'updated',original,got)
    assert launch._binding('reopen_updated', got) == ('updated', got, ['reopen', '/inputs/updated', '/out/values'])


def test_array_audit_does_not_grant_coverage_for_measured_rejections(tmp_path, monkeypatch):
    from tsbench.application import m3_measurement_inventory as inv
    run = tmp_path/'demo'
    run.mkdir()
    doc = {'run_id': run.name}
    (run/'report.json').write_bytes(canonical_bytes(doc))
    (run/'completion.json').write_bytes(b'{}')
    scope = {'size_estimate': {'input_units': 1, 'native_input_bytes_one_pass': 72}}
    def fields(i, status, reason):
        return {'dataset_id': i, 'work_item_id': i, 'case_id': i, 'route': z.ROUTE, 'operation_config_id': i,
                'canonical_object_id': i, 'reason': reason, 'status': status, 'configuration': scope,
                'units': [{}], 'logical_bytes': 72, 'rejected_windows': int(status != 'verified')}
    cases = [fields('ok', 'verified', ''), fields('bad', 'quality_rejected', 'frozen rejection')]
    plan = {'source_plan': 'r40', 'source_seal': 'r40-seal', 'cases': cases}
    (run/'plan.json').write_bytes(canonical_bytes(plan))
    def linked(modified=None):
        lookup = {c['work_item_id']: ({'status': c['status'], 'reason': c['reason']}, {**c, 'input': scope}) for c in cases}
        if modified:
            lookup['bad'][0]['status'] = modified
        return _linked(tmp_path, run, 'zfp-array', ('r40', 'r40-seal'), lookup, None)
    monkeypatch.setitem(inv.MODES,'zfp-array',(lambda _:doc, (z.ROUTE,), ('native_repeat',)))
    links, proof = linked()
    assert set(links) == {'ok'}
    assert proof['measured_but_excluded_by_quality'][0]['work_item_id'] == 'bad'
    with pytest.raises(ContractError, match='cannot change'):
        linked('verified')
