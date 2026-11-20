"""Functional smoke for same-work M4 direct ABI vs production Context lanes."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_lzbench_timing import _ref
from tsbench.application.smoke import write_new
from tsbench.assets import canonical_bytes, content_id, digest, load_json, local_file, require
from tsbench.corpus_ingress import load_full_manifest, read_batches
from tsbench.recovery import plan_recovery, stage_recovery
from tsbench.supervisor.isolated_worker import MOUNT, _invoke, launcher_lock

TOOLS = {key: 'tsbench_m4_abi_cost' + suffix for key, suffix in [('timing_only', ''), ('counted', '_counted')]}
PLUGINS = ('raw-store', 'zstd', 'alp-auto', 'xz-baseline')
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 15}


def validate(row, num, arm, lifecycle, direction, kind, src, dest):
    steady = int(lifecycle == 'steady_reset')
    require(row['arm'] == arm and row['lifecycle'] == lifecycle and row['direction'] == direction and
            row['logical_bytes'] == num * 8 and row['input_bytes'] == src.stat().st_size and row['output_bytes'] == dest.stat().st_size and
            row['protocol'] == {'create': 1, 'reset': steady, 'warmup': steady, 'operation': 1, 'measured_output_release': 1, 'info': 1, 'destroy': 1} and
            row['execution_info']['operation'] == direction, 'M4 smoke observed different public ABI work')
    for name in ('prepare', 'result_ready', 'release', 'destroy'):
        stage = row[name]
        is_count = kind == 'counted'
        require((stage['wall_ns'] is None and isinstance(stage['counts'], dict)) if is_count else
                (type(stage['wall_ns']) is int and stage['wall_ns'] > 0 and stage['counts'] is None), 'M4 smoke mixed counter and timing arms')
    if kind == 'counted':
        require(row['result_ready']['counts']['new_calls'] == int(arm == 'framework'),
                'M4 smoke did not observe the Context-owned result holder allocation')


def run(build, lock_path):
    lock = load_json(lock_path)
    modules = {p: lock['plugins'][p] for p in PLUGINS}
    tools = {k: {'path': (build / exe).relative_to(ROOT).as_posix(), 'sha256': digest(build / exe)} for k, exe in TOOLS.items()}
    methods = {p: {'plugin': p, 'options': {}} for p in modules}
    spec = plan_recovery(ROOT, lock, methods, tools=tools)
    entry, = [x for x in load_full_manifest(ROOT)['datasets'] if x['id'] == 'etth1']
    source = bytearray()
    num = 8192
    # Exhaust the original: independently validate its raw identity before using this projection.
    for batch in read_batches(ROOT, entry):
        width = entry['value_count'] * 8
        for i in range(min(batch.rows, max(0, num - batch.start))):
            source.extend(batch.values[i * width:i * width + 8])
    require(len(source) == num * 8, 'invalid ETT projection extent')
    results = []
    with TemporaryDirectory(prefix='tsbench-m4-abi-cost-smoke-') as work:
        sandbox = Path(work)
        stage_recovery(ROOT, sandbox, spec, directory='runtime')
        vals, schema = sandbox / 'original', sandbox / 'schema'
        vals.write_bytes(source)
        schema.write_bytes(canonical_bytes({'role': 'value', 'dtype': 'f64', 'rows': num}))
        seen = set()
        for plugin in PLUGINS:
            observed = []
            ref = None
            for tier in TOOLS:
                for lifecycle in ('cold', 'steady_reset'):
                    for arm in ('direct', 'framework'):
                        for direction in ('encode', 'decode'):
                            p = sandbox / f'test-{len(seen):02d}'
                            p.mkdir()
                            actual = vals if direction == 'encode' else ref
                            library = spec['plugins'][plugin]
                            executable = spec['tools'][tier]
                            options = '{"decode_backend":"falp-auto"}' if plugin == 'alp-auto' else '{}'
                            args = [arm, lifecycle, direction, plugin, f'{MOUNT}/{library}', options,
                                    '/inputs/object', '/inputs/schema', str(num), '10', '/out/result']
                            out, proc = _invoke(sandbox / 'runtime', spec, LIMITS, p, p, 'cost',
                                                {'object': actual, 'schema': schema}, executable, [library], args, lambda: False, observe=True)
                            error = local_file(p, 'cost.stderr').read_text()
                            require(proc['status'] == 'completed' and not error, f'{plugin} {tier} {arm} {direction}: {error}')
                            oid = proc['session_id']
                            require(oid not in seen, 'duplicate M4 cost session')
                            seen.add(oid)
                            dest = local_file(out, 'result')
                            row = load_json(local_file(p, 'cost.stdout'))
                            validate(row, num, arm, lifecycle, direction, tier, actual, dest)
                            if direction == 'encode' and ref is None:
                                ref = dest
                            expected = ref if direction == 'encode' else vals
                            require(dest.read_bytes() == expected.read_bytes(), 'M4 cost bytewise paired result differs')
                            observed.append({'trial': {'arm': arm, 'mode': tier, 'lifecycle': lifecycle, 'direction': direction},
                                             'input_sha256': digest(actual), 'product_sha256': digest(dest),
                                             'protocol': row['protocol'], 'execution_info': row['execution_info'],
                                             'call_site_counts': {s: row[s]['counts'] for s in ('prepare', 'result_ready', 'release', 'destroy')}})
            results.append({'plugin': plugin, 'trials': observed})
    body = {'schema': 'bmk.m4-same-work-abi-smoke/1', 'observation': 'functional isolation only; no performance figures retained',
            'range': {'dataset': entry['id'], 'column': 0, 'rows': [0, num]}, 'source_original': entry['file'],
            'input_values_sha256': results[0]['trials'][0]['input_sha256'], 'build_lock': _ref(ROOT, lock_path),
            'code': [_ref(ROOT, local_file(ROOT, n)) for n in ('tests/isolation/m4_abi_cost_smoke.py', 'native/measurement/m4_abi_cost/main.cpp',
                     'native/measurement/m4_abi_cost/CMakeLists.txt', 'native/runtime/plugin_loader.cpp')],
            'tools': tools, 'wall_timing_admitted': False, 'launchers': launcher_lock(),
            'cases': results, 'checked_directions': len(seen), 'scope': 'caller-side operator new and out-of-line memcpy only',
            'unobserved': ['plugin and stdlib allocations/copies', 'inlined copies', 'memory/cache residency'], 'stage_accepted': False}
    return {**body, 'report_id': content_id(body)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    report = run(args.build.resolve(strict=True), args.lock.resolve(strict=True))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_new(args.out, report)
    print(json.dumps({k: report[k] for k in ('report_id', 'checked_directions', 'stage_accepted')}))
