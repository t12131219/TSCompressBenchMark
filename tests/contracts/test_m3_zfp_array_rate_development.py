"""The new ZFP experiment keeps the frozen domains and tests only development."""
from pathlib import Path
from struct import pack
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from prepare_m3_zfp_array_rate_development import ARRAY_LAYOUT, CONTROL, derived, project_windows
import m3_zfp_array_rate_development as runner
from tsbench.assets import ContractError, canonical_bytes


def test_projection_rebalances_usable_boundary_without_including_excluded_rows():
    contract = {'layout':ARRAY_LAYOUT,'row_coordinates':'absolute_zero_based_half_open','column_overrides':[],
                'default_column':{'accepted_spans':[
                    {'rows':[0,8192],'windows':2,'base_rows':4096,'first_windows_with_one_extra_row':0},
                    {'rows':[8195,8205],'windows':1,'base_rows':10,'first_windows_with_one_extra_row':0}],
                    'excluded_spans':[{'rows':[8192,8195]}]}}
    # The old 4,096-row boundaries leave a small left fragment. Keeping the
    # frozen domain and balancing after projection covers every eligible row.
    keep,short = project_windows(contract,1,8205,4094,8201)
    assert keep==[[0,4094,6143],[0,6143,8192]] and short==[[0,8195,8201]]
    assert sum(b-a for _,a,b in keep)==8192-4094


def test_controller_adds_rates_but_not_different_update_or_import_operations():
    text = (ROOT/CONTROL).read_text()
    result = derived(text)
    assert all(pair in result for pair in ('{18, 32}','{33, 48}','{49, 64}'))
    for op in ('zn_array_count(raw)','zn_array_set(raw, 1, &values.back())','zn_array_flush(raw)',
               'zn_array_import(&cfg, frame.data(), frame.size(), &raw)'):
        assert result.count(op)==text.count(op)==1
    with pytest.raises(ContractError,match='expected rate-18 harness'):
        derived(text.replace('cfg.parameter = 18;', 'cfg.parameter = 17;'))


@pytest.mark.parametrize('requested,effective,block_bytes',[(18,32,16),(33,48,24),(49,64,32)])
def test_rate_controls_byte_charges_and_untouched_block_extent(requested,effective,block_bytes):
    config = runner.configuration(12,requested,effective)
    values = list(range(12)); mutated = values[:]
    mutated[1] = values[-1]; mutated[3:7] = values[:4]
    raw,correct = (pack('<12d',*v) for v in (values,mutated))
    before,after = bytes(3*block_bytes),b'x'*(2*block_bytes)+bytes(block_bytes)
    result = runner.evaluate(config,raw,before,after,raw,correct)
    assert result['status']=='verified' and result['published_frame_bytes']==3*block_bytes
    assert result['complete_billed_bytes']==len(after)+result['metadata']['bytes']
    assert result['separate_before_diagnostic_bytes']==len(before)
    assert runner.evaluate(config,raw,before,after,raw,raw)['status']=='quality_rejected'
    assert runner.evaluate(config,raw,before,after[:-1]+b'x',raw,correct)['status']=='untouched_block_changed'


def test_detached_native_products_and_command_metadata_are_bound(tmp_path,monkeypatch):
    config = runner.configuration(8,33,48)
    data = list(range(8)); updated = data[:]
    updated[1] = data[-1]; updated[3:7] = data[:4]
    raw,restored = (pack('<8d',*v) for v in (data,updated))
    bf,af = bytes(48),b'x'*48
    fake = {'update':{'before':bf,'after':af},'before':{'values':raw},'after':{'values':restored}}
    run,scratch = tmp_path/'run',tmp_path/'scratch'; scratch.mkdir(); run.mkdir()
    runtime = {'test':'closure'}
    def invoke(bundle,spec,tool,limits,work,logs,label,inputs,args,*_,**kwargs):
        op,mount,_ = runner.STEPS[label]
        assert bundle==run/runner.DIRECTORY and spec==runtime and kwargs['observe']
        expected = {'update':raw,'before':bf,'after':af}[label]
        assert set(inputs)=={mount} and inputs[mount].read_bytes()==expected
        assert args==[op,'8','/inputs/'+mount,'33']
        out = work/'out'; out.mkdir()
        for name,content in fake[label].items():
            (out/name).write_bytes(content)
        (logs/(label+'.stdout')).write_bytes(canonical_bytes(config))
        (logs/(label+'.stderr')).write_bytes(b'')
        return out,{'status':'completed','reason':'','returncode':0,'session_id':label,'pid':9,'input_mounts':{mount:runner.identity(expected)}}
    monkeypatch.setattr(runner,'invoke_isolated_tool',invoke)
    row = runner.produce(run,runtime,{'window':0},config,raw,0,scratch)
    assert runner.decide(run,row,{'window':0},config,raw,0,set())['status']=='verified'
    row['processes']['before']['input_mounts']['input'] = runner.identity(raw)
    with pytest.raises(ContractError,match='changed input mounts'):
        runner.decide(run,row,{'window':0},config,raw,0,set())


def test_no_selection_from_projection_or_incomplete_rate():
    files = {'a':2,'b':2}
    from collections import Counter
    rates = {'18':Counter(verified=3,complete_billed_bytes=1),
             '33':Counter(verified=4,complete_billed_bytes=20),'49':Counter(verified=4,complete_billed_bytes=20)}
    assert runner.selected_rate(files,rates,projected=False)==33
    assert runner.selected_rate(files,rates,projected=True) is None
