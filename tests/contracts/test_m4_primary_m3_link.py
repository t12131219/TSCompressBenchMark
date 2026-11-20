from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from bind_m4_to_primary_m3 import _live_prefix, _match_row
from tsbench.assets import ContractError, canonical_bytes


def test_fused_link_checks_actual_backend_original_restore_and_frame():
    original = {'raw': {'bytes': 8, 'sha256': 'c' * 64}}
    frame = {'bytes': 100, 'sha256': 'b' * 64}
    enc = {'backend': 'alpn-auto-encoder', 'threads': 1}
    dec = {'requested_backend': 'falp-auto', 'backend': 'falp-avx2', 'falp_avx2_vectors': 4, 'threads': 1}
    cfg = {'m3_decode_dispatch': 'falp-auto', 'effective_backend': 'falp-avx2', 'fused_vectors': 4, 'threads': 1}
    case = {'geometry': {'row_range': [0, 8], 'column': 0}, 'original': original, 'expected_m3_frame': frame,
            'native_config': cfg}
    unit = {**case['geometry'], 'original': original, 'artifact': frame, 'encode': {'native': enc},
            'decodes': {'falp-auto': {'restored': original, 'native': dec}}}
    row = {'status': 'verified', 'evidence': {'units': [unit]}}
    assert _match_row('alp-fused', case, row, None)['decode'] == dec
    tampered = deepcopy(row)
    tampered['evidence']['units'][0]['decodes']['falp-auto']['native']['backend'] = 'falp-scalar'
    with pytest.raises(ContractError, match='fused decode'):
        _match_row('alp-fused', case, tampered, None)
    with pytest.raises(ContractError, match='identity'):
        _match_row('alp-fused', {**case, 'expected_m3_frame': {'bytes': 100, 'sha256': 'a' * 64}}, row, None)
    with pytest.raises(ContractError, match='ambiguous'):
        _match_row('alp-fused', case, {'status': 'verified', 'evidence': {'units': [unit, unit]}}, None)
    with pytest.raises(ContractError, match='verified'):
        _match_row('alp-fused', case, {**row, 'status': 'quality_rejected'}, None)


def test_live_prefix_is_stable_as_rows_append_and_rejects_incomplete_or_reordered_rows(tmp_path):
    shared = {'dataset_id':'d','selection':9,'route':'decode-backends','operation':'decode',
              'applicability':'input_domain_matches'}
    items = [{**shared,'work_item_id':str(i)} for i in range(2)]
    plan = {'work_items':items}
    def encode(item):
        return canonical_bytes({**item,'status':'verified'})+b'\n'
    first, second = map(encode,items)
    ledger = tmp_path/'ledger.jsonl'
    ledger.write_bytes(first+second[:-1])
    before = _live_prefix(plan,ledger,1,{'0','1'})
    assert before[0] == {'corpus_rows':1,'bytes':len(first),'sha256':sha256(first).hexdigest()}
    assert list(before[1]) == ['0'] and before[1]['0'][0] == 1
    with pytest.raises(ContractError,match='newline-terminated'):
        _live_prefix(plan,ledger,2,{'0','1'})
    ledger.write_bytes(first+second+b'ignored append')
    assert before == _live_prefix(plan,ledger,1,{'0','1'})
    ledger.write_bytes(second+first)
    with pytest.raises(ContractError,match='out-of-order'):
        _live_prefix(plan,ledger,1,{'0','1'})
