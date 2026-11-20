"""Exercise ZFP retained-sample replay without competing with a timed native run."""
from pathlib import Path
from struct import pack
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import verify_m3_zfp_corpus as audit
from tsbench.application.m3_zfp import array_evidence
from tsbench.assets import ContractError, canonical_bytes


def setup_replay(monkeypatch, tmp_path):
    def bind(name, data):
        (tmp_path / name).write_bytes(data)
        return {'path': name, **audit.ref(data)}

    executable, library = bind('control', b'program'), bind('libzfp_native_c.so', b'library')
    launchers = {'/usr/bin/bwrap': 'locked'}
    runtime = {'recovery_id': 'test-closure'}
    plan = {'build': {'zfp_corpus': {'executable': executable, 'dependency': library}},
            'specialized': {'zfp': {'launchers': launchers}}}

    def freeze(root, build, methods, *, tools, libraries):
        assert root == tmp_path and not build and not methods
        assert tools == {audit.TOOL: {k: executable[k] for k in ('path', 'sha256')}}
        assert libraries == [library]
        return runtime

    def stage(root, run, spec):
        assert root == run == tmp_path and spec == runtime
        (run / audit.DIRECTORY).mkdir()

    monkeypatch.setattr(audit, 'launcher_lock', lambda: launchers)
    monkeypatch.setattr(audit, 'plan_recovery', freeze)
    monkeypatch.setattr(audit, 'stage_recovery', stage)
    return audit.IsolatedReplay(tmp_path, plan, tmp_path)


def stub_invoker(isolated, results, *, failure=None):
    def invoke(bundle, runtime, tool, limits, work, logs, label, inputs, argv, cancelled, **kwargs):
        wire, values, config, sid = next(results)
        assert bundle == isolated.bundle and runtime == isolated.runtime and tool == audit.TOOL
        assert limits == audit.LIMITS and work == logs and not cancelled()
        assert kwargs == {'bind_inputs': True, 'process_env': audit.THREAD_ENV}
        assert inputs == {'frame': work / 'wire'} and inputs['frame'].read_bytes() == wire
        assert argv == [label, str(config['rows']), '/inputs/frame']
        out = work / 'out'
        out.mkdir()
        (out / 'values').write_bytes(values)
        (logs / f'{label}.stdout').write_bytes(canonical_bytes(config))
        (logs / f'{label}.stderr').write_bytes(b'bwrap: blocked\n' if failure == 'sandbox' else b'')
        mounts = {'frame': audit.ref(wire)}
        if failure == 'extra-mount':
            mounts['original'] = audit.ref(values)
        return out, {'status': 'sandbox_failed' if failure == 'sandbox' else 'completed',
                     'returncode': 1 if failure == 'sandbox' else 0, 'reason': '',
                     'session_id': sid, 'input_mounts': mounts}

    return invoke


def test_array_replay_checks_two_separate_frame_only_sessions(tmp_path, monkeypatch):
    isolated = setup_replay(monkeypatch, tmp_path)
    original = list(map(float, range(13)))
    updated = original.copy()
    updated[1], updated[3:7] = original[-1], original[:4]
    raw, restored = (pack('<13d', *values) for values in (original, updated))
    before, after = bytes(64), b'a' * 32 + bytes(32)
    config = {'rows': 13, 'frame_bytes': 64, 'requested_rate': 18, 'effective_rate': 32}
    metadata = canonical_bytes({'format': 'zfp-array-rank1-v1', 'type': 'f64', 'shape': [13],
                                'requested_rate': 18, 'effective_rate': 32})
    payloads = {'before': before, 'after': after, 'metadata.json': metadata}
    for name, payload in payloads.items():
        (tmp_path / name).write_bytes(payload)
    sample = {'parts': {name: {'path': name, **audit.ref(payload)} for name, payload in payloads.items()}}
    row = {**array_evidence(raw, before, after, raw, restored), 'before_frame': audit.ref(before),
           'after_frame': audit.ref(after), 'metadata': audit.ref(metadata), 'config': config, 'restored': audit.ref(restored)}
    results = iter([(before, raw, config, 'first'), (after, restored, config, 'second')])
    monkeypatch.setattr(audit, 'invoke_isolated_tool', stub_invoker(isolated, results))
    observed = audit.replay(None, tmp_path, tmp_path, row, sample, raw, True, isolated=isolated)
    assert [(p['part'], p['session_id']) for p in observed] == [('before', 'first'), ('after', 'second')]
    assert observed[1]['restored'] == row['restored'] and observed[1]['observed'] == config
    assert observed[1]['logs'] == {'stdout': audit.ref(canonical_bytes(config)), 'stderr': audit.ref(b'')}


@pytest.mark.parametrize('failure,reason', [('sandbox', 'bwrap: blocked'), ('extra-mount', 'fresh frame-only'),
                                             ('duplicate', 'fresh frame-only'), ('wrong-shape', 'restored extent')])
def test_isolated_reopen_fails_closed(tmp_path, monkeypatch, failure, reason):
    isolated = setup_replay(monkeypatch, tmp_path)
    if failure == 'duplicate':
        isolated.sessions.add('seen')
    wire, values = b'frame', b'' if failure == 'wrong-shape' else bytes(8)
    results = iter([(wire, values, {'rows': 1}, 'seen')])
    monkeypatch.setattr(audit, 'invoke_isolated_tool', stub_invoker(isolated, results, failure=failure))
    with pytest.raises(ContractError, match=reason):
        isolated.reopen(tmp_path, 'serial.frame', 'field-restore', wire, 1)
    assert isolated.sessions == ({'seen'} if failure == 'duplicate' else set())
