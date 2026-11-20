"""Representative real-profile bindings and sealed report negative controls."""
from pathlib import Path
import shutil

import pytest

from tsbench.application.m4_real_profile import _artifact, _check_link, _schedule, _schema, _sha, recompute
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'results/m4-real-profile-20261120-r3/runs/956a56a6325e46d38f0140dc1046f6f3'


def test_direct_native_payload_is_rewrapped_before_m3_identity_comparison():
    case = {'plugin': 'alp-auto', 'original': {'count': 17, 'dtype': 10}}
    schema = _schema(case)
    case['original']['schema'] = _sha(schema)
    payload = b'fixed native frame'
    wire = _artifact(payload, case)
    assert wire == (b'BMKALP\x01\x00\x0a\x00\x00\x00\x11\x00\x00\x00\x00\x00\x00\x00' +
                    len(schema).to_bytes(4, 'little') + len(payload).to_bytes(8, 'little') + schema + payload)
    case['original']['schema']['sha256'] = '0' * 64
    with pytest.raises(ContractError, match='schema differs'):
        _artifact(payload, case)


def test_native_worker_and_effective_backend_must_match_m3_not_merely_requested():
    a = {'plugin': 'alp-auto', 'route': 'decode-backends', 'native_config': {'fused_vectors': 51}}
    z = {'plugin': None, 'route': 'zstd-workers', 'native_config': {'jobs': {'jobs': 17, 'worker_threads': 2, 'caller_jobs': 0}}}
    _check_link(a, 'decode', {'native_counters': {'alp_fused_vectors': 51}})
    with pytest.raises(ContractError, match='vector count differs'):
        _check_link(a, 'decode', {'native_counters': {'alp_fused_vectors': 52}})
    with pytest.raises(ContractError, match='jobs differ'):
        _check_link(z, 'encode', {'native_counters': {'native_jobs': 17, 'native_worker_threads': 1, 'native_caller_jobs': 0}})
    assert len(_schedule()) == 28 and _schedule()[-1]['capacity'] == 2


@pytest.mark.skipif(not RUN.is_dir(), reason='requires locally sealed real-profile evidence')
@pytest.mark.parametrize('change,message', [('loss', 'coverage differs'), ('overlap', 'outside L0')])
def test_real_evidence_recomputation_and_resealed_trace_tamper(tmp_path, change, message):
    assert recompute(RUN) == load_json(RUN / 'report.json')
    run = tmp_path / RUN.name
    shutil.copytree(RUN, run)
    plan = load_json(run / 'plan.json')
    hit = next(t for t in plan['schedule'] if t['mode'] == 'profiled' and
               (t['round'] == 0 if change == 'loss' else t['case'] == 'zstd-mt'))
    op = 'decode' if change == 'loss' else 'encode'
    rel = f"logs/{hit['slot']}-{op}.stdout"
    obs = load_json(run / rel)
    if change == 'loss':
        obs['trace']['dropped'] = 0
    else:
        root = next(s for s in obs['trace']['spans'] if s['stage'] == 1)
        worker = next(s for s in obs['trace']['spans'] if s['stage'] == 6)
        worker['end_ns'] = root['end_ns'] + 1
    raw = canonical_bytes(obs) + b'\n'
    (run / rel).write_bytes(raw)
    seal = load_json(run / 'completion.json')
    next(r for r in seal['files'] if r['path'] == rel).update(_sha(raw))
    seal['seal_id'] = content_id({k: v for k, v in seal.items() if k != 'seal_id'})
    (run / 'completion.json').write_bytes(canonical_bytes(seal) + b'\n')
    with pytest.raises(ContractError, match=message):
        recompute(run)
