#!/usr/bin/env python3
"""A new, bounded Zstd/XZ matched control; never extends an existing M3 run."""
from argparse import ArgumentParser
from hashlib import sha256
import json
import os
from pathlib import Path
from random import Random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.smoke import _worker_json, write_new
from tsbench.assets import ContractError, content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.corpus_ingress import read_batches
from tsbench.recovery import plan_recovery, stage_recovery
from tsbench.supervisor import matched_round_ledger as ledger, matched_round_retry as retry
from tsbench.supervisor.isolated_worker import invoke_isolated_worker, launcher_lock
from tsbench.supervisor.timing_resource import reserve
from tsbench.supervisor.worker_environment import governor_snapshot

SCHEMA = 'bmk.m3-matched-abi-control/1'
OPS = ('encode', 'decode')
METHOD = {'zstd': (40, 'zstd-baseline', 'ln-zstd-baseline', 'level', 3),
          'xz-baseline': (39, 'xz-baseline', 'ln-xz-baseline', 'preset', 6)}
LIMITS = {'address_space_bytes': 1 << 30, 'file_bytes': 1 << 20, 'wall_seconds': 30}
CODE = ('tools/m3_matched_abi_control.py', 'native/measurement/matched_abi/CMakeLists.txt',
        'native/measurement/matched_abi/main.cpp', 'native/measurement/common/worker_environment.hpp',
        'native/worker/worker_main.cpp', 'native/runtime/plugin_loader.hpp', 'native/runtime/plugin_loader.cpp',
        'include/tsbench/plugin_abi.h', 'src/tsbench/supervisor/matched_round_ledger.py',
        'src/tsbench/supervisor/matched_round_retry.py', 'src/tsbench/supervisor/worker_environment.py',
        'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py',
        'src/tsbench/recovery.py', 'src/tsbench/corpus_ingress.py')


def _ref(root, path):
    return {'path': path.relative_to(root).as_posix(), **_identity(path)}


def _identity(path):
    require(path.is_file() and not path.is_symlink(), 'matched ABI asset is not a regular file')
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def _bytes(data):
    return {'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def _input(root, definition, dataset):
    entry = _entry_map(root, load_json(verify_asset(root, definition)))[dataset]
    # Keep only one frozen ABI-sized prefix; exhaust the parser so the source,
    # canonical shape and full original-byte digest are checked, not just prefix.
    first = bytearray()
    for batch in read_batches(root, entry):
        first.extend(batch.values[:65536 - len(first)])
    schema = json.dumps({'role': 'bytes', 'dtype': 'u8', 'rows': entry['rows']}, separators=(',', ':')).encode()
    require(len(first) == min(65536, 8 * entry['rows'] * entry['value_count']) > 0, 'matched ABI input extent differs')
    return entry, bytes(first), schema


def freeze(root, baseline, worker, dataset, cpu, governor, seed):
    parent = load_json(baseline)
    require(parent['plan_content_id'] == content_id({k: v for k, v in parent.items() if k != 'plan_content_id'}),
            'matched ABI baseline plan identity differs')
    lock = parent['build']['lock']
    build = load_json(verify_asset(root, lock))
    require(build['build_id'] == parent['build']['build_id'], 'matched ABI baseline build identity differs')
    for selection, route, *_ in METHOD.values():
        matches = [i for i in parent['work_items'] if (i['selection'], i['route'], i['dataset_id']) == (selection, route, dataset)]
        require(len(matches) == 1 and matches[0]['applicability'] == 'input_domain_matches' and
                matches[0]['input']['slice_extent']['max_per_unit'] == 65536, 'matched ABI route not applicable to frozen input')
    closure = plan_recovery(root, {**build, 'worker': _ref(root, worker)}, METHOD)
    definition = parent['definition']['plan']
    entry, raw, schema = _input(root, definition, dataset)
    rng = Random(seed)
    schedule = [{'slot_id': f'{op}:{p}', 'cpu_ids': [cpu]} for op in OPS for p in rng.sample(list(METHOD), len(METHOD))]
    block = {'canonical_object_id': entry['canonical']['object_id'], 'range': [0, len(raw)], 'raw': _bytes(raw), 'schema': _bytes(schema)}
    body = {'schema': SCHEMA, 'baseline': _ref(root, baseline), 'old_build': lock, 'entry': entry['file'], 'dataset': dataset,
            'definition': definition, 'worker': _ref(root, worker), 'runtime': closure, 'launchers': launcher_lock(),
            'seed': seed, 'input': block, 'limits': LIMITS,
            'policy': retry.freeze(content_id(block), schedule, {str(cpu): governor}, max_retries=1),
            'code': {p: digest(local_file(root, p)) for p in CODE},
            'scope': 'one_frozen_byte_prefix_fresh_abi_worker_each_operation_functional_diagnostic_not_main_timing',
            **ledger.FLAGS}
    return {**body, 'plan_id': content_id(body)}


def _check(root, plan):
    first = plan['policy']['slots'][0]
    cpu, = first['cpu_ids']
    baseline = verify_asset(root, plan['baseline'])
    worker = verify_asset(root, plan['worker'])
    require(plan == freeze(root, baseline, worker, plan['dataset'], cpu, plan['policy']['governors'][str(cpu)], plan['seed']),
            'matched ABI plan no longer reproduces frozen inputs, executable or schedule')
    return cpu


def _binding(directory, op, plugin, observations, expected):
    backend, knob, value = METHOD[plugin][2:]
    wanted = ['frame'] if op == 'encode' else ['raw', 'schema']
    files = {n: _identity(directory / n) for n in wanted}
    require(set(p.name for p in directory.iterdir()) == set(wanted), 'unexpected matched ABI operation files')
    meta = observations[-1]
    require(meta['backend'] == backend and meta['threads'] == meta['blocks'] == 1 and meta['mode'] == 'batch' and
            meta['fallback'] is False and meta['operation'] == op and (op != 'encode' or meta[knob] == value),
            'matched ABI worker reported a different native configuration')
    if op == 'decode':
        require(files == {k: expected[k] for k in wanted} and observations[0] == {
            'columns': [{'dtype': 2, 'count': expected['raw']['bytes']}]}, 'matched ABI detached recovery differs')
    else:
        require(0 < files['frame']['bytes'] <= LIMITS['file_bytes'], 'empty or oversized matched frame')
    return {'native': observations, 'outputs': files}


def _sync(p):
    fd = os.open(p, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _run_id(plan, parent):
    return content_id({'plan_id': plan['plan_id'], 'directory': parent.name})


def execute(root, plan, parent):
    with reserve():
        cpu = _check(root, plan)
        allowed = os.sched_getaffinity(0)
        require(cpu in allowed and governor_snapshot([cpu]) == plan['policy']['governors'], 'matched control host outside predeclared policy')
        _, raw, schema = _input(root, plan['definition'], plan['dataset'])
        parent.mkdir()
        write_new(parent / 'plan.json', plan)
        for n, data in (('raw', raw), ('schema', schema)):
            (parent / n).write_bytes(data)
            _sync(parent / n)
        stage_recovery(root, parent, plan['runtime'], directory='runtime')
        _sync(parent)
        _sync(parent.parent)
        frames = {}

        def perform(slot, attempt, work):
            op, plugin = slot['slot_id'].split(':', 1)
            key = (attempt, plugin)
            if op == 'decode' and key not in frames:
                return 'dependency_failed', {'session_id': None, 'pid': None, 'status': 'not_launched', 'returncode': None}
            inputs = {n: parent / n for n in ('raw', 'schema')} if op == 'encode' else {'frame': frames[key]}
            args = (['/inputs/schema', '/out/frame', '2', '/inputs/raw'] if op == 'encode' else ['/inputs/frame', '/out/schema', '/out/raw'])
            out, facts = invoke_isolated_worker(parent/'runtime', plan['runtime'], {'plugin': plugin, 'options': {}},
                                                LIMITS, work, work, op+'-columns', inputs, args, lambda: False,
                                                label='worker', observe=True)
            witness = out / ledger.WITNESS
            if witness.exists():
                witness.rename(work / ledger.WITNESS)
                _sync(out)
            if facts['status'] != 'completed':
                return facts['status'], facts
            require(facts['input_mounts'] == {n:_identity(p) for n,p in inputs.items()} and
                    (work/'worker.stderr').stat().st_size == 0, 'matched ABI operation mounts or stderr differ')
            try:
                raw_obs = _worker_json(work/'worker.stdout', 1 if op == 'encode' else 2)
                output = _binding(out, op, plugin, raw_obs, plan['input'])
            except (ContractError, OSError, KeyError) as exc:
                return 'validation_failed', {**facts, 'validation_reason': str(exc)}
            for name in output['outputs']:
                _sync(out/name)
            _sync(work/'worker.stdout')
            _sync(out)
            if op == 'encode':
                frames[key] = out / 'frame'
            return 'verified', {**facts, 'codec_evidence': output}

        try:
            os.sched_setaffinity(0, {cpu})
            return ledger.execute(parent/'observations', plan['policy'], _run_id(plan, parent), perform)
        finally:
            os.sched_setaffinity(0, allowed)


def verify(parent):
    plan = load_json(parent/'plan.json')
    report = ledger.verify(parent/'observations')
    require(plan['plan_id'] == content_id({k: v for k,v in plan.items() if k != 'plan_id'}) and
            plan['policy'] == load_json(parent/'observations/run.json')['policy'] and
            report['run_id'] == _run_id(plan, parent), 'matched ABI report not bound to plan')
    require({n: _identity(parent/n) for n in ('raw','schema')} == {n: plan['input'][n] for n in ('raw','schema')},
            'matched ABI input files changed')
    retained = {}
    positions = {s['slot_id']:i for i,s in enumerate(plan['policy']['slots'])}
    with (parent/'observations/ledger.jsonl').open('rb') as stream:
        for line in stream:
            row = parse_json(line)
            if row['kind'] != 'terminal' or row['attempt']['terminal'] != 'verified':
                continue
            attempt = row['attempt']
            op, plugin = attempt['slot_id'].split(':', 1)
            key = (attempt['attempt'], plugin)
            work = ledger._work(parent/'observations', attempt['attempt'], positions[attempt['slot_id']])
            facts = row['process']
            inp = {n:plan['input'][n] for n in ('raw', 'schema')} if op == 'encode' else {'frame': retained[key]}
            require(facts['input_mounts'] == inp and facts['codec_evidence'] == _binding(
                work/'out', op, plugin, _worker_json(work/'worker.stdout', 1 if op == 'encode' else 2), plan['input']),
                'matched ABI codec proof does not independently recompute')
            if op == 'encode':
                retained[key] = facts['codec_evidence']['outputs']['frame']
    return report


def main():
    p = ArgumentParser(description=__doc__)
    s = p.add_subparsers(dest='op', required=True)
    f = s.add_parser('plan')
    for n in ('baseline','worker','out'):
        f.add_argument('--'+n, type=Path, required=True)
    f.add_argument('--dataset', required=True)
    f.add_argument('--cpu', type=int, required=True)
    f.add_argument('--governor', required=True)
    f.add_argument('--seed', type=int, default=20261120)
    r = s.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--out', type=Path, required=True)
    v = s.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.op == 'plan':
            plan = freeze(ROOT,args.baseline.resolve(strict=True),args.worker.resolve(strict=True),
                          args.dataset,args.cpu,args.governor,args.seed)
            write_new(args.out,plan)
            print(plan['plan_id'])
        elif args.op == 'run':
            print(execute(ROOT, load_json(args.plan), args.out.resolve()))
        else:
            print(verify(args.run.resolve(strict=True)))
    except (KeyError, ValueError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
