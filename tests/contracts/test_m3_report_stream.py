from pathlib import Path
import json

import pytest

from tsbench.application.m3_report_stream import stream_report
from tsbench.assets import ContractError


def make(tmp):
    p = tmp/'report.json'
    doc = {'head':'before','rows':[{'detail':[2,{'x':'\n    }\n'}]},{'z':'中文'}],
           'tail':{'execution_policy':{'scope':'test'}}}
    p.write_text(json.dumps(doc,indent=2,ensure_ascii=False)+'\n')
    return p,doc


def test_stream_respects_row_boundaries_and_preserves_tail(tmp_path):
    p,expected = make(tmp_path)
    with stream_report(p) as (metadata,rows):
        assert metadata=={'head':'before'}
        assert list(rows)==expected.pop('rows')
    assert metadata==expected


def test_incomplete_or_abandoned_report_is_not_usable(tmp_path):
    p,_ = make(tmp_path)
    with pytest.raises(ContractError,match='not fully read'):
        with stream_report(p) as (_,rows):
            next(rows)
    p.write_bytes(p.read_bytes()[:-2])
    with pytest.raises(ContractError,match='incomplete'):
        with stream_report(p) as (_,rows):
            list(rows)


def test_reject_conflicting_keys_across_metadata_sections(tmp_path):
    p,_ = make(tmp_path)
    p.write_text(p.read_text().replace('  "tail":', '  "head":'))
    with pytest.raises(ContractError,match='repeats a metadata field'):
        with stream_report(p) as (_,rows):
            list(rows)
