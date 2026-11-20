import hashlib
from pathlib import Path
import struct

import pytest

from tsbench.application import m3_corad_raw_ingress as ingress
from tsbench.assets import ContractError


def _ref(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _fixture(tmp_path):
    raw = ('time,a,b,c\n' + ''.join(f'{i},-{i},{i}.25,{i}.5\n' for i in range(320))).encode()
    (tmp_path / 'source.csv').write_bytes(raw)
    entry = {'id':'synthetic', 'canonical':{'object_id':'binding'}, 'value_count':3, 'columns':['time','a','b','c'],
             'file':{'path':'source.csv', **_ref(raw)}, 'rows':320,
             'partitions':[{'start':0,'end':64},{'start':64,'end':96},{'start':96,'end':320}],
             'parser':{'decimal':'.','separator':',','timestamp':'integer_label'}}
    cases = []
    for lo,hi in [(97,139),(139,217),(299,320)]:
        vals = b''.join(struct.pack('<d', i+d) for d in (.25,.5) for i in range(lo,hi))
        axis = b''.join(struct.pack('<q', i) for i in range(lo,hi))
        span = {'absolute_rows':[lo,hi], 'values':_ref(vals), 'time':_ref(axis)}
        cases.append({'span':span,'producer':'C','raw':vals})
    b = {'input_binding_id':'cohort', 'source':'synthetic','canonical_object_id':'binding',
         'ordered_columns':['b','c'],'test_frames':[c['span'] for c in cases]}
    cases = [{**c,'b':b} for c in cases]
    return entry, cases + [{**c,'producer':'Source'} for c in cases]


def test_materialize_real_csv_once_deduplicates_producers_and_crosses_batches(tmp_path, monkeypatch):
    entry, cases = _fixture(tmp_path)
    scan = ingress.read_batches
    calls = []

    def count(root, entry):
        calls.append(entry['id'])
        yield from scan(root, entry)

    monkeypatch.setattr(ingress, 'read_batches', count)
    prepared, facts = ingress.materialize(tmp_path, entry, [{**c,'raw':None} for c in cases])
    assert calls == ['synthetic'] and prepared == cases and len(facts) == 3 and facts == ingress.expected_records(cases)


def test_materialize_rejects_changed_unselected_source_and_training_range(tmp_path):
    entry, cases = _fixture(tmp_path)
    path = tmp_path / 'source.csv'
    path.write_bytes(path.read_bytes().replace(b'1,-1,1.25,1.5\n', b'1,-1,1.25,1.8\n', 1))
    with pytest.raises(ContractError, match='SHA-256'):
        ingress.materialize(tmp_path, entry, cases)
    with pytest.raises(ContractError, match='held-out bounds'):
        ingress.materialize(tmp_path, entry, [{**cases[0], 'span':{**cases[0]['span'],'absolute_rows':[0,42]}}])


def test_pipeline_times_original_ingress_before_native_and_never_on_decode(tmp_path, monkeypatch):
    from tsbench.application import m3_in_run_corad_pipeline as pipeline

    entry, cases = _fixture(tmp_path)
    calls = []
    wall = iter([100, 210, 500])
    cpu = iter([0, 75])
    monkeypatch.setattr(pipeline, 'monotonic_ns', lambda: next(wall))
    monkeypatch.setattr(pipeline, 'process_time_ns', lambda: next(cpu))

    def native(plan, run, work, runtime, passed, slot, timed):
        calls.append(slot['direction'])
        assert passed == cases
        return {**slot, 'status':'measured_as_declared', 'whole_verified_durable_wall_ns':200}

    monkeypatch.setattr(pipeline.base, '_trial', native)
    slot = {'direction':'encode','phase':'measured'}
    trial = pipeline._trial(tmp_path,None,entry,None,None,None,cases,slot,None)
    assert trial['raw_source_to_verified_durable_and_published_wall_ns'] == 400
    assert pipeline._checked_trials(entry,cases,[slot],[trial]) == {'parse_verify_materialize_wall_ns':[110],
            'parse_verify_materialize_controller_cpu_ns':[75],'raw_source_to_verified_durable_and_published_wall_ns':[400]}
    with pytest.raises(ContractError, match='omits'):
        pipeline._checked_trials(entry,cases,[slot],[{**trial,'raw_source_to_verified_durable_and_published_wall_ns':309}])
    (tmp_path/'source.csv').unlink()
    decode = pipeline._trial(tmp_path,None,entry,None,None,None,cases,{'direction':'decode','phase':'measured'},None)
    assert 'raw_source' not in decode and calls == ['encode','decode']
    monkeypatch.setattr(pipeline,'monotonic_ns',lambda: 0)
    monkeypatch.setattr(pipeline,'process_time_ns',lambda: 0)
    result = pipeline._trial(tmp_path,None,entry,None,None,None,cases,slot,None)
    assert result['failure_stage']=='raw_source_ingress' and result['units']==[] and result['unissued_units']==len(cases)
    assert calls == ['encode','decode']
