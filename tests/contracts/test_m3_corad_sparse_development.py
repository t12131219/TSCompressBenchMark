"""A development worker can never obtain held-out rows from the prefix loader."""
from hashlib import sha256
from pathlib import Path
from struct import pack
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from build_m3_corad_sparse_restore import CAP, WIDE_CAP, widened
import m3_corad_sparse_development as sparse
from m3_corad_sparse_development import train_dev_matrix
from tsbench.assets import ContractError
from tsbench.corpus_ingress import _identity


def make(tmp):
    src = tmp/'data.csv'
    # The invalid first test row would raise during a full-file read.
    blob = b't,x,y\n0,1,2\n1,2,3\n2,3,4\n3,4,5\nINVALID,TEST,ROW\n'
    src.write_bytes(blob)
    e = {'file':{'path':src.name,'bytes':len(blob)},'value_count':2,'rows':5,'columns':['t','x','y'],
         'parser':{'timestamp':'integer_label','decimal':'.','separator':',','missing':'reject_missing'}}
    e['partitions'] = [{'name':n,'start':lo,'end':hi,
                        'canonical':_identity(e,hi-lo,sha256(b''.join(pack('<q',r) for r in range(lo,hi))),
                                               sha256(b''.join(pack('<dd',r+1,r+2) for r in range(lo,hi))))}
                       for n,lo,hi in [('train',0,2),('development',2,4),('test',4,5)]]
    (tmp/'staging').mkdir()
    return e,tmp/'staging'


def test_development_reads_frozen_prefix_only(tmp_path):
    manifest, scratch = make(tmp_path)
    assert train_dev_matrix(tmp_path,manifest,scratch).tolist()==[[1,2],[2,3],[3,4],[4,5]]
    assert b'INVALID' not in (scratch/'prefix.csv').read_bytes()


def test_source_prefix_must_match_registered_partitions(tmp_path):
    manifest, scratch = make(tmp_path)
    source = tmp_path/'data.csv'
    source.write_bytes(source.read_bytes().replace(b'3,4,5',b'3,4,6'))
    with pytest.raises(ContractError,match='canonical train/development identity'):
        train_dev_matrix(tmp_path,manifest,scratch)


def test_restore_buffer_matches_encoder_without_changing_decoder_call():
    original = f'{CAP}\ncorad_decode(frame, n, values, cap, cap, &used, &cfg);\n'
    assert widened(original, WIDE_CAP) == original.replace(CAP, WIDE_CAP)
    with pytest.raises(ContractError, match='buffer difference'):
        widened(original, CAP)


@pytest.mark.parametrize('frame,restored,status', [
    (b'CRD1 test frame', b'restored values', 'native_restored'),
    (b'CRD1 test frame', None, 'native_restore_failed'),
    (None, None, 'native_encode_failed'),
])
def test_development_produce_consumes_native_bytes(tmp_path, monkeypatch, frame, restored, status):
    monkeypatch.setattr(sparse, 'ROOT', tmp_path)
    run = tmp_path/'run'; (run/'frames').mkdir(parents=True)
    scratch = tmp_path/'scratch'; scratch.mkdir()
    model = tmp_path/'model'; model.write_bytes(b'model')
    key = {'development_rows':[2,4], 'columns':['x','y'], 'nonzero':3, 'model':sparse.ref(tmp_path,model)}
    raw = b'development values'
    calls = []

    def native(lane, closure, temp, logs, operation, inputs, argv, product, observations):
        calls.append(operation)
        if operation == 'encode':
            assert {k:p.read_bytes() for k,p in inputs.items()} == {'model':b'model','development':raw}
            assert argv[-3:] == ['2','2','3']
            assert lane == run/'encoder' and closure == {'decoder':'encode closure'} and product == 'frame'
            output = frame
        else:
            assert {k:p.read_bytes() for k,p in inputs.items()} == {'frame':frame}
            assert lane == run/'decoder' and closure == {'decoder':'restore closure'} and product == 'values'
            output = restored
        observations[operation] = {}
        return output, observations[operation]

    monkeypatch.setattr(sparse,'_native',native)
    row = sparse.produce(run,{'encode':'encode closure','restore':'restore closure'},key,raw,0,scratch)
    assert row['status'] == status
    assert calls == (['encode'] if frame is None else ['encode','restore'])
    if frame is not None:
        assert sparse.check(tmp_path,row['frame']).read_bytes() == frame
    else:
        assert 'frame' not in row and not list((run/'frames').iterdir())
    if restored is not None:
        assert row['restore'] == sparse._identity(restored)
    else:
        assert 'restore' not in row
