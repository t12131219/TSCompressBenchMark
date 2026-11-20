"""Titchy native packet sessions and query validation use separate statistics."""
import pytest

from tsbench.application import m3_titchy_grouped as g, m3_titchy_grouped_timing as timing
from tsbench.application.m3_measurement_inventory import _exact_extent
from tsbench.assets import ContractError


def test_packet_stream_does_not_replace_whole_column_with_windows():
    extent = {'value_column_range':[0,2], 'row_ranges':[{'start':0,'end':3}], 'slice_extent':{'max_per_unit':None},
              'size_estimate':{'input_units':2,'native_input_bytes_one_pass':48}}
    full = [{'column':c,'row_range':[0,3],'original':{'bytes':24}} for c in range(2)]
    case = {'route':'packet-stream','configuration':extent,'units':full}
    assert _exact_extent('titchy-grouped',case,{'input':extent})
    wrong = [full[0],{'column':1,'row_range':[0,2],'original':{'bytes':24}}]
    assert not _exact_extent('titchy-grouped',{**case,'units':wrong},{'input':extent})
    assert 'rows' not in g.expected({**case,'units':[{'parts':{'wire':{},'config':{}}}]},'wire')


def test_query_and_restoration_high_level_clocks_are_separate():
    case = {'route':'batch-range'}
    calls = [{'wall_ns':3,'restore':{'wall_ns':11},'process_peak_rss_bytes':100},
             {'wall_ns':5,'restore':{'wall_ns':11},'process_peak_rss_bytes':110}]
    ns = timing.metrics(case,'decode',calls)['native_category_ns']
    assert ns == {'full_validation_restore_wall_ns':22,'stateless_range_with_container_validation_wall_ns':8}


def test_first_packet_is_not_sample_repetition_and_must_precede_finish():
    packet = {'route':'packet-stream'}
    rows = [{'first_packet_ns':n,'wall_ns':13} for n in (2,9,7)]
    v = timing.metrics(packet,'encode',rows)
    assert v == {'native_category_ns':{'native_operation_wall_ns':39},
                 'per_unit_not_independent_repeats':{'first_packet_wall_ns':{'count':3,'min':2,'max':9}}}
    with pytest.raises(ContractError,match='first packet outside'):
        timing.metrics(packet,'encode',[{'first_packet_ns':14,'wall_ns':13}])


def test_normalization_disregards_only_clocks_and_rss():
    probe = {'file':{'request':None,'wall_ns':20},'process_peak_rss_bytes':100,'first_packet_ns':7,
             'other':[{'requested_bytes':4,'wall_ns':3}]}
    assert g.facts(probe)=={'file':{'request':None},'other':[{'requested_bytes':4}]}
