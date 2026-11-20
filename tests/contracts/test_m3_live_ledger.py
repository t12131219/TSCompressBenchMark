from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from check_m3_live_ledger import _read_prefix
from tsbench.assets import ContractError


def _row(key):
    return {'work_item_id':str(key),'dataset_id':str(key),'selection':9,'route':'auto-batch',
            'operation':'encode_decode','applicability':'input_domain_matches'}


def test_prefix_only_accepts_complete_ordered_rows_and_ignores_in_flight_tail(tmp_path):
    p=tmp_path/'ledger.jsonl'
    complete = (json.dumps(_row(1))+'\n').encode()
    tail = b'{"work_item_id":"2"'
    p.write_bytes(complete+tail)
    with p.open('rb') as s:
        count, seen, prefix, picked = _read_prefix(s, [_row(1),_row(2)], {('1','auto-batch')})
    assert count == 1 and seen == len(complete+tail) and prefix == sha256(complete).hexdigest()
    assert picked == [(_row(1),_row(1))]


def test_complete_corrupt_or_out_of_order_line_is_not_an_in_flight_tail(tmp_path):
    p=tmp_path/'ledger.jsonl'
    p.write_bytes((json.dumps(_row(2))+'\n').encode())
    with p.open('rb') as s, pytest.raises(ContractError, match='ordered prefix'):
        _read_prefix(s,[_row(1),_row(2)],set())
    p.write_bytes(b'bad JSON\n')
    with p.open('rb') as s, pytest.raises(ContractError, match='M3 live ledger line'):
        _read_prefix(s,[_row(1)],set())


def test_fixed_prefix_does_not_hash_or_require_later_rows(tmp_path):
    p=tmp_path/'ledger.jsonl'
    items = [_row(1),_row(2)]
    first,second = ((json.dumps(r)+'\n').encode() for r in items)
    p.write_bytes(first+second[:-1])
    with p.open('rb') as s:
        one = _read_prefix(s,items,{('1','auto-batch')},through=1)
    assert one[:3]==(1,len(first),sha256(first).hexdigest())
    with p.open('rb') as s, pytest.raises(ContractError,match='declared complete-line extent'):
        _read_prefix(s,items,set(),through=2)
    p.write_bytes(first+second)
    with p.open('rb') as s:
        assert _read_prefix(s,items,{('1','auto-batch')},through=1)==one
