"""Replay the evidence contract without running a codec or changing any timings."""
from hashlib import sha256
from pathlib import Path
import struct

from ..assets import content_id, load_json, local_file, require
from ..planner.frame_batches import LANES, choose_loops, materialize, reference_path, retained_paths

_REPORT_SCHEMA = 'bmk.frame-batches-evidence/1'
_COUNTERS = ('encode_batch_ns', 'decode_batch_ns', 'release_ns')
_SAMPLE_KEYS = {
    'lane', 'lifecycle', 'pid', 'loops', 'warmups', 'encoded_verified', 'decoded_verified',
    *_COUNTERS, 'frame_bytes_each', 'frame_capacity_total', 'decoded_logical_and_schema_total',
    'budget_bytes', 'encode_cpu_endpoints', 'decode_cpu_endpoints', 'warmup_encode_info',
    'warmup_decode_info', 'reference_sha256',
}


def _integer(value, lo, hi):
    return type(value) is int and lo <= value <= hi


def verify_frame(wire, method, case):
    original, schema = materialize(case)
    require(len(original) == case['bytes'] and len(schema) == case['schema_bytes'] and
            sha256(original).hexdigest() == case['input_sha256'] and sha256(schema).hexdigest() == case['schema_sha256'],
            'retained batch fixture differs from frozen inputs')
    if method == 'raw-store':
        expected = struct.pack('<8sIQI', b'BMKRAW\x01\x00', 10, case['rows'], len(schema)) + schema + original
        require(wire == expected, 'raw batch frame does not reproduce the fixture')
        return
    magic = {'zstd': b'BMKZST\x01\x00', 'alp-auto': b'BMKALP\x01\x00'}[method]
    require(len(wire) > 32 + len(schema) and wire[:8] == magic and
            struct.unpack_from('<IQIQ', wire, 8) == (10, case['rows'], len(schema), len(wire) - 32 - len(schema)) and
            wire[32:32 + len(schema)] == schema, 'retained batch frame envelope differs from frozen fixture')
    prefix = {'zstd': b'\x28\xb5\x2f\xfd', 'alp-auto': b'ALN1'}[method]
    require(wire[32 + len(schema):].startswith(prefix), 'batch frame native payload magic differs')


def verify_sample(sample, lane, group, loops, cfg, reference, logical, allowed_cpu):
    label = f"{group['case']}/{group['method']}/{group['lifecycle']}/{lane}"
    require(isinstance(sample, dict) and sample.keys() == _SAMPLE_KEYS, f'invalid batch sample: {label}')
    require(sample['lane'] == lane and sample['lifecycle'] == group['lifecycle'] and
            _integer(sample['pid'], 1, 2**31 - 1) and
            all(_integer(sample[k], loops, loops) for k in ('loops', 'encoded_verified', 'decoded_verified')) and
            _integer(sample['warmups'], cfg['warmups'], cfg['warmups']) and
            all(_integer(sample[k], 1, 2**63 - 1) for k in _COUNTERS), f'invalid batch order, counts or time: {label}')
    size, checksum = reference
    budget = cfg['retention_budget_bytes']
    require(sample['reference_sha256'] == checksum and _integer(sample['frame_bytes_each'], size, size) and
            _integer(sample['decoded_logical_and_schema_total'], loops * logical, loops * logical) and
            _integer(sample['budget_bytes'], budget, budget) and
            _integer(sample['frame_capacity_total'], size * loops, budget - logical * loops - size),
            f'batch byte accounting differs from retained work: {label}')
    for key in ('encode_cpu_endpoints', 'decode_cpu_endpoints'):
        endpoints = sample[key]
        require(isinstance(endpoints, list) and len(endpoints) == 2 and
                all(type(cpu) is int and (cpu == -1 or cpu in allowed_cpu) for cpu in endpoints),
                f'invalid batch CPU endpoints: {label}')
    infos = []
    for op in ('encode', 'decode'):
        info = sample['warmup_' + op + '_info']
        backend = {'raw-store': 'copy', 'zstd': 'ln-zstd-baseline',
                   'alp-auto': 'alpn-auto-encoder' if op == 'encode' else 'falp-scalar'}[group['method']]
        require(isinstance(info, dict) and info.get('operation') == op and info.get('mode') == 'batch' and
                _integer(info.get('threads'), 1, 1) and info.get('backend') == backend and type(info.get('fallback')) is bool,
                f'unexpected warmup operation or backend: {label}/{op}')
        if group['method'] == 'alp-auto' and op == 'decode':
            require(info.get('requested_backend') == group['options']['decode_backend'], f'ALP request differs: {label}')
        if group['method'] == 'zstd' and op == 'encode':
            require(_integer(info.get('level'), 3, 3), f'Zstd level differs: {label}')
        infos.append(info)
    return infos


def verify_frame_batches(plan: dict, build: dict, out: Path, *, sealed_paths=None):
    require(plan['plan_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_id'}), 'frame batch plan identity differs')
    report = load_json(local_file(out, plan['evidence_path']))
    require(isinstance(report, dict) and report.keys() == {
                'schema', 'plan_id', 'build_sha256', 'environment', 'groups', 'formal_performance', 'qualification_granted'} and
            report['schema'] == _REPORT_SCHEMA and report['plan_id'] == plan['plan_id'] and report['build_sha256'] == build and
            report['formal_performance'] is False and report['qualification_granted'] is False,
            'frame batch evidence differs from plan or build')
    cfg = plan['config']
    env = report['environment']
    fixed_env = {'clock': 'std::chrono::steady_clock', 'cache': cfg['cache'], 'exclusive_cpu': 'not_reserved',
                 'numa_placement': 'not_measured', 'frequency_and_interference': 'not_measured'}
    require(isinstance(env, dict) and env.keys() == fixed_env.keys() | {'allowed_cpu_ids', 'kernel_release'} and
            all(env[k] == val for k, val in fixed_env.items()) and isinstance(env['kernel_release'], str) and env['kernel_release'],
            'invalid or unsupported frame batch environment claim')
    affinity = env['allowed_cpu_ids']
    require(isinstance(affinity, list) and affinity and all(_integer(v, 0, 2**31 - 1) for v in affinity) and
            affinity == sorted(set(affinity)), 'invalid batch CPU affinity record')
    allowed_cpu = set(affinity)
    cases = {c['id']: c for c in plan['cases']}
    dirname = Path(plan['evidence_path']).parent
    expected = {(dirname / p).as_posix() for p in retained_paths(plan)}
    if sealed_paths is not None:
        require(expected == {p for p in sealed_paths if p.startswith(dirname.as_posix() + '/') and p.endswith('.bmk')},
                'sealed batch sample set differs from plan')
    references = {}
    rows = report['groups']
    require(isinstance(rows, list) and len(rows) == len(plan['groups']), 'frame batch groups differ from plan')
    for group, row in zip(plan['groups'], rows, strict=True):
        case, method = cases[group['case']], group['method']
        rel = (dirname / reference_path(case['id'], method)).as_posix()
        if rel not in references:
            file = local_file(out, rel)
            require(_integer(file.stat().st_size, 1, cfg['retention_budget_bytes']), 'invalid retained batch frame size')
            wire = file.read_bytes()
            verify_frame(wire, method, case)
            references[rel] = (len(wire), sha256(wire).hexdigest())
        logical = case['bytes'] + case['schema_bytes']
        require(isinstance(row, dict) and row.keys() == {'group_id', 'loops', 'calibration', 'rounds'} and
                row['group_id'] == group['group_id'], 'frame batch group identity differs')
        metadata = []

        def compare(samples, order, loops):
            require(isinstance(samples, list) and len(samples) == len(order), 'frame batch lane closure differs')
            for lane, sample in zip(order, samples, strict=True):
                metadata.append(verify_sample(sample, lane, group, loops, cfg, references[rel], logical, allowed_cpu))

        compare(row['calibration'], LANES, 1)
        loops = choose_loops(cfg, logical, row['calibration'])
        require(_integer(row['loops'], loops, loops), 'frame batch loops do not replay from calibration')
        rounds, orders = row['rounds'], group['round_lane_order']
        require(isinstance(rounds, list) and len(rounds) == len(orders), 'frame batch matched-round closure differs')
        for samples, order in zip(rounds, orders, strict=True):
            compare(samples, order, loops)
        require(all(info == metadata[0] for info in metadata[1:]), 'batch lanes report different warmup work')
