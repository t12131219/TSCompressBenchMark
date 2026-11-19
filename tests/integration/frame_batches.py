"""Serial, matched same-ABI batches; no admission or ranking."""
import argparse
from hashlib import sha256
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest, parse_json, require
from tsbench.planner.frame_batches import LANES, METHODS, choose_loops, materialize, plan_frame_batches, reference_path
from tsbench.plugins import discover, resolve
from tsbench.qualification.frame_batches import verify_frame_batches


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('dlopen', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--method', action='append', nargs='+', required=True)
    args = parser.parse_args()
    require([m[0] for m in args.method] == list(METHODS), 'wrong method closure')
    plan = plan_frame_batches(ROOT)
    cfg = plan['config']
    methods = {method: [Path(p) for p in paths] for method, *paths in args.method}
    paths = [args.dlopen, *(p for parts in methods.values() for p in parts)]
    build = {p.name: digest(p) for p in paths}
    require(len(build) == len(paths), 'ambiguous batch artifacts')
    registry = discover(ROOT, selected=set(METHODS))
    affinity = sorted(os.sched_getaffinity(0))
    env = {'allowed_cpu_ids': affinity, 'kernel_release': os.uname().release, 'clock': 'std::chrono::steady_clock',
           'exclusive_cpu': 'not_reserved', 'numa_placement': 'not_measured', 'cache': cfg['cache'],
           'frequency_and_interference': 'not_measured'}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    # CTest can rerun into an existing build directory. Each file is replaced, report last.
    with tempfile.TemporaryDirectory(prefix='.frame-batches-', dir=args.evidence.parent) as tmp:
        stage = Path(tmp)
        work = stage / 'work'
        work.mkdir()
        evidence = stage / 'frame-batches'
        evidence.mkdir()
        data_paths = {}
        for case in plan['cases']:
            data, schema = materialize(case)
            values_path = work / (case['id'] + '.f64')
            schema_path = work / (case['id'] + '.json')
            values_path.write_bytes(data)
            schema_path.write_bytes(schema)
            data_paths[case['id']] = (values_path, schema_path, len(data) + len(schema))
        bound = {}
        for method, parts in methods.items():
            directory = work / method
            directory.mkdir()
            linked, module, *deps = parts
            require([p.name for p in deps] == registry[method]['manifest'].get('runtime_dependencies', []),
                    'unexpected staged runtime dependencies')
            for p in (args.dlopen, linked, module, *deps):
                dest = directory / p.name
                shutil.copy2(p, dest)
                require(digest(dest) == build[p.name], 'unstable batch build input')
            bound[method] = (directory, directory / args.dlopen.name, directory / linked.name, directory / module.name)
        groups = []
        for group in plan['groups']:
            method, case = group['method'], group['case']
            directory, dlopen, linked, module = bound[method]
            lanes = dict(zip(LANES, (dlopen, linked), strict=True))
            values, schema, logical = data_paths[case]
            sample = directory / 'warmup.bmk'
            retained = evidence / reference_path(case, method)
            options = resolve(ROOT, method, group['options'], registry=registry)['options']
            require(options == group['options'], 'effective batch options differ from plan')

            def run(lane, loops):
                result = run_worker(directory, [lanes[lane], module, method, canonical_bytes(options).decode('ascii'),
                                    group['lifecycle'], '10', str(loops), str(cfg['warmups']),
                                    str(cfg['retention_budget_bytes']), values, schema, sample, lane])
                observed = parse_json(result.stdout.decode('utf-8'), 'native frame batch')
                frame = sample.read_bytes()
                sample.unlink()
                if retained.exists():
                    require(retained.read_bytes() == frame, 'byte reference differs across lane, launch or lifecycle')
                else:
                    retained.write_bytes(frame)
                return {**observed, 'reference_sha256': sha256(frame).hexdigest()}

            calibration = [run(lane, 1) for lane in LANES]
            loops = choose_loops(cfg, logical, calibration)
            rounds = [[run(lane, loops) for lane in order] for order in group['round_lane_order']]
            groups.append({'group_id': group['group_id'], 'loops': loops, 'calibration': calibration, 'rounds': rounds})
        report = {'schema': 'bmk.frame-batches-evidence/1', 'plan_id': plan['plan_id'], 'build_sha256': build,
                  'environment': env, 'groups': groups, 'formal_performance': False, 'qualification_granted': False}
        (evidence / 'frame-batches.json').write_bytes(canonical_bytes(report))
        verify_frame_batches(plan, build, stage)
        args.evidence.mkdir(exist_ok=True)
        for frame in sorted(evidence.glob('*.bmk')):
            frame.replace(args.evidence / frame.name)
        (evidence / 'frame-batches.json').replace(args.evidence / 'frame-batches.json')


if __name__ == '__main__':
    main()
