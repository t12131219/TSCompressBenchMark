"""The full-ledger Titchy auditor must never mount originals or accept extra output."""
from pathlib import Path
import sys

import pytest

from tsbench.assets import ContractError, digest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import verify_m3_titchy as audit


@pytest.mark.parametrize('mode,inputs,outputs', [
    ('batch', ['frame'], ['schema', 'raw']),
    ('packet-stream', ['archive', 'config'], ['raw']),
    ('loaded-file-access', ['frame'], ['raw']),
    ('batch-range', ['frame'], ['raw']),
])
def test_exact_mount_closure_and_fresh_worker_record(tmp_path, monkeypatch, mode, inputs, outputs):
    work = tmp_path / 'isolated'
    work.mkdir()
    files = {name: tmp_path / name for name in inputs}
    for f in files.values():
        f.write_bytes(f.name.encode())
    bundle = tmp_path / 'runtime'
    spec = {'spec': 'frozen'}
    args = [f'/inputs/{n}' for n in inputs] + [f'/out/{n}' for n in outputs]
    mounts = {key: {'bytes': path.stat().st_size, 'sha256': digest(path)} for key, path in files.items()}
    proc = {'status': 'completed', 'returncode': 0, 'input_mounts': mounts, 'session_id': 'new'}

    def invoke(b, s, control, limits, w, logs, action, sources, argv, cancelled, **kwargs):
        assert (b, s, limits, w, logs, sources, argv) == (bundle, spec, audit.LIMITS, work, work, files, args)
        assert not cancelled()
        if mode == 'batch':
            assert control == {'plugin': audit.TITCHY, 'options': {}} and action == 'decode-columns'
            assert kwargs == {'label': 'replay', 'observe': True}
        else:
            assert control == (mode if mode == 'packet-stream' else 'access') and action == 'replay'
            assert kwargs == {'bind_inputs': True}
        out = w / 'out'
        out.mkdir(exist_ok=True)
        for name in outputs:
            (out / name).write_bytes(b'')
        (w / 'replay.stderr').write_bytes(b'')
        (w / 'replay.stdout').write_text('{}\n' * (2 if mode == 'batch' else 1))
        return out, proc

    monkeypatch.setattr(audit, 'invoke_isolated_worker' if mode == 'batch' else 'invoke_isolated_tool', invoke)
    out, _, actual = audit._isolated_sample((bundle, spec), work, mode, files, args)
    assert out == work / 'out' and actual == proc
    with pytest.raises(ContractError, match='may mount only'):
        audit._isolated_sample((bundle, spec), work, mode, {**files, 'original': tmp_path / 'original'}, args)
    proc['input_mounts'] = {**mounts, 'original': {'bytes': 42}}
    with pytest.raises(ContractError, match='isolated replay failed'):
        audit._isolated_sample((bundle, spec), work, mode, files, args)
    proc['input_mounts'] = mounts
    (out / 'extra').touch()
    with pytest.raises(ContractError, match='isolated replay failed'):
        audit._isolated_sample((bundle, spec), work, mode, files, args)
