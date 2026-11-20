"""Development-only CRD1 candidate preserves nonzero-gate reconstruction."""
from pathlib import Path
from struct import pack
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from m3_corad_exact_basis_development import HEADER, _identity, candidate, evaluate, interpret
import m3_corad_native_exact_basis as runner
from tsbench.assets import ContractError, canonical_bytes


ZERO = {'max_abs_error':'0','mse':'0'}
POSITIVE = {'max_abs_error':'1','mse':'1'}


def fixture():
    # Four complete samples and one raw-tail sample per column. The second
    # column's reference uses the first column's normalized sparse vector,
    # not its denormalized values. A third unrelated term remains unchanged.
    atoms = pack('<16d', *(float(i == j) for i in range(4) for j in range(4)))
    stats = pack('<6d',10.,2.,1.,4.,0.,1.)
    records = pack('<HHdHHHHd',1,0,2.,65535,0,1,1,3.)
    tail = pack('<3d',-0.,9.,8.)
    payload = atoms+stats+records+tail
    frame = HEADER.pack(b'CRD1',5,3,4,4,4,0.,HEADER.size+len(payload))+payload
    original = pack('<5d',-0.,7.,-2.,5.,-0.) + interpret(frame)[0][40:]
    return frame, original, tail, records


def test_changed_zero_gate_retains_referenced_vector_and_raw_tail():
    frame, raw, tail, _ = fixture()
    gates = [ZERO,POSITIVE,POSITIVE]
    base, _, _ = interpret(frame)
    changed, stats = candidate(frame,raw,gates)
    actual, _, _ = interpret(changed)
    assert changed.endswith(tail)
    assert actual == pack('<5d',0.,7.,-2.,5.,-0.) + base[40:]
    assert stats == {'exact_columns':1,'basis_bytes':128,'exact_sparse_records':1,'retargeted_references':1}
    result = evaluate(frame,raw,['a','b','c'],gates,_identity(base))
    assert result['verified']
    assert result['zero_gate_values'] == 5
    assert result['zero_gate_different_bits'] == result['zero_gate_signed_zero_changes'] == 1
    assert result['base_bytes'] == sum(result['base_accounting'].values()) == len(frame)
    assert result['candidate_bytes'] == sum(result['candidate_accounting'].values()) == len(changed)
    assert result['candidate_bytes']-result['base_bytes'] == 128+(2+3*10)-(2+10)+(2+10)-4


def test_no_zero_gate_returns_an_identical_frame():
    frame, _, _, _ = fixture()
    restored, _, _ = interpret(frame)
    gates = [POSITIVE]*3
    changed, stats = candidate(frame,restored,gates)
    result = evaluate(frame,restored,['a','b','c'],gates,_identity(restored))
    assert changed == frame and not any(stats.values())
    assert result['candidate_frame'] == _identity(frame)
    assert result['verified'] and result['zero_gate_values'] == 0


def test_rejects_bad_frame_and_restore_identity():
    frame, raw, _, records = fixture()
    restored, _, _ = interpret(frame)
    gates = [ZERO,POSITIVE,POSITIVE]
    with pytest.raises(ContractError,match='base shape'):
        candidate(frame[:-1],raw,gates)
    with pytest.raises(ContractError,match='wrong raw-tail extent'):
        candidate(HEADER.pack(*HEADER.unpack_from(frame)[:-1],len(frame)-1)+frame[HEADER.size:-1],raw,gates)
    bad = frame.replace(records,records[:14]+pack('<H',1)+records[16:])
    with pytest.raises(ContractError,match='invalid base reference'):
        candidate(bad,raw,gates)
    with pytest.raises(ContractError,match='base CRD1 recovery identity differs'):
        evaluate(frame,raw,['a','b','c'],gates,_identity(restored[::-1]))


def test_candidate_audit_checks_frame_only_recovery_and_log_custody(tmp_path, monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    frame, raw, _, _ = fixture()
    gates = [ZERO,POSITIVE,POSITIVE]
    expected = evaluate(frame,raw,['a','b','c'],gates,_identity(interpret(frame)[0]))
    wire,_ = candidate(frame,raw,gates)
    run = tmp_path/'run'; (run/'frames').mkdir(parents=True)
    work = tmp_path/'work'; work.mkdir()
    model = tmp_path/'model'; model.write_bytes(b'frozen model')
    key = {'model':runner.base.ref(tmp_path,model),'development_rows':[12,17],'columns':['a','b','c']}
    old = {'frame':_identity(frame),'decision':{'terminal':'quality_rejected'}}
    closures = {'encode':{'candidate':True},'restore':{'original':True}}

    def native(lane, closure, scratch, logs, name, inputs, args, product, observation):
        assert lane==run/('encoder' if name=='encode' else 'decoder')
        assert closure=={'decoder':closures[name]}
        if name=='encode':
            assert {k:p.read_bytes() for k,p in inputs.items()}=={'model':b'frozen model','development':raw}
            assert args==['encode','/inputs/model','/inputs/development','5','3','1'] and product=='frame'
            data = wire
        else:
            assert {k:p.read_bytes() for k,p in inputs.items()}=={'frame':wire}
            assert args==['decode','/inputs/frame','5','3'] and product=='values'
            data = interpret(wire)[0]
        message = {'native_status':0,'rows':5,'columns':3,'output_bytes':len(data)}
        (logs/(name+'.stdout')).write_bytes(canonical_bytes(message))
        (logs/(name+'.stderr')).write_bytes(b'')
        observation[name] = {'operation':name,'pid':100,'session_id':name,'returncode':0,'status':'completed',
                             'native':message,'input_mounts':{k:_identity(p.read_bytes()) for k,p in inputs.items()}}
        return data,message

    monkeypatch.setattr(runner.base,'_native',native)
    row = runner.produce(run,closures,key,raw,1,0,work)
    got = runner.decide(run,0,row,old,key,raw,gates,1,expected,set())
    assert got['terminal']=='verified' and got['frame_matches_reference'] and got['zero_gate_different_bits']==1
    with pytest.raises(ContractError,match='key or mask'):
        runner.decide(run,0,row,old,key,raw,gates,0,expected,set())
    with pytest.raises(ContractError,match='reused'):
        runner.decide(run,0,row,old,key,raw,gates,1,expected,{'restore'})
    (run/'steps/0/restore.stdout').write_bytes(b'altered output')
    with pytest.raises(ContractError,match='logs changed'):
        runner.decide(run,0,row,old,key,raw,gates,1,expected,set())
