"""Compile a bounded, replayable two-lane Linux frame measurement plan."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re

from ..assets import content_id, digest, local_file, relative_parts, require
from ..plugins import discover, resolve
from ..supervisor import timing_resource as resource
from .frame_batches import LANES, METHODS, compile_frame_batches, plan_frame_batches

SCHEMA = 'bmk.timing-plan/1'
POLICY = {'timeout_seconds': 20, 'address_space_bytes': 768 << 20, 'per_file_bytes': 64 << 20,
          'attempts': 1, 'parallel_batches': 1, 'cache': 'natural_repeated_input',
          'extent': 'steady_or_cold_context_same_repeated_frame_not_process_startup',
          'verification': 'artifact_each_encoded_bytes_and_original_bits_outside_codec_clock',
          'resource': resource.RESERVATION, 'clock': 'native_steady_clock_batch',
          'samples': 'one_observation_per_lane_per_matched_round_not_per_inner_loop'}
NATIVE_DEPENDENCIES = {'raw-store': [], 'zstd': ['liblzbench_native.so'], 'alp-auto': ['libalp_native.so']}


@dataclass(frozen=True, slots=True)
class TimingPlanRequest:
    build_dir: str
    cpu: int


def _paths(build):
    d = PurePosixPath(*relative_parts(build))
    def method_paths(m):
        base = d / 'plugins' / 'codecs' / m
        tag = m.replace('-', '_')
        return [base / f'tsbench_frame_batch_tsbench_{tag}', base / f'libbmk_{tag}.so',
                *(base / name for name in NATIVE_DEPENDENCIES[m])]
    return {key: path.as_posix() for key, path in [('dlopen', d/'tsbench_frame_batch_dlopen'),
              *((p.name, p) for m in METHODS for p in method_paths(m))]}


def build_roles(method):
    tag = method.replace('-', '_')
    return {'dlopen':'dlopen', 'linked_entry':f'tsbench_frame_batch_tsbench_{tag}',
            'plugin': f'libbmk_{tag}.so', 'dependencies': NATIVE_DEPENDENCIES[method]}


def protocol(root):
    files = ('planner/frame_batches.py', 'planner/timing.py', 'supervisor/process.py',
             'supervisor/timing_resource.py', 'application/timing.py', 'qualification/frame_batches.py')
    src = Path(__file__).resolve().parents[1]
    return {'implementation': {key: digest(src / key) for key in files},
            'native_driver': digest(local_file(root, 'native/measurement/frame_batches.cpp')),
            'launchers': {name: digest(Path(name)) for name in (resource.TASKSET, resource.PRLIMIT)}}


def effective_methods(root, batches):
    registry = discover(root, selected=set(METHODS))
    result = {}
    for group in batches['groups']:
        m = group['method']
        require(registry[m]['manifest'].get('runtime_dependencies', []) == NATIVE_DEPENDENCIES[m],
                'timing build dependency contract differs from registered plugin')
        resolved = resolve(root, m, group['options'], registry=registry)
        require(resolved['options'] == group['options'], 'effective timing options differ from plan')
        result[m] = {k: resolved[k] for k in ('configuration_id', 'manifest_id', 'options_schema_id', 'options')}
    return result


def schedule(group):
    yield from (('calibration', 0, lane) for lane in LANES)
    for round_number, order in enumerate(group['round_lane_order'], 1):
        yield from (('measured', round_number, lane) for lane in order)


def plan_timing(root: Path, request: TimingPlanRequest):
    batches = plan_frame_batches(root)
    l3_bytes = max((c['bytes'] for c in resource.environment(request.cpu)['cache_topology'] if c['level'] == 3), default=0)
    outside = next((c for c in batches['cases'] if c['id'] == 'large-copy-outside'), None)
    require(outside is not None and outside['bytes'] > l3_bytes,
            'M2 cache-outside case must exceed the selected CPU L3 cache')
    bindings = {key: {'path': path, 'sha256': digest(local_file(root, path))}
                for key, path in _paths(request.build_dir).items()}
    body = {'schema': SCHEMA, 'target_stage': 'M2', 'stage_accepted': False, 'formal_performance': False,
            'build_dir': request.build_dir, 'artifacts': bindings, 'batches': batches, 'policy': POLICY,
            'protocol': protocol(root), 'method_bindings': effective_methods(root, batches),
            'environment': resource.environment(request.cpu),
            'planned_batches': sum(len(list(schedule(group))) for group in batches['groups'])}
    return {**body, 'plan_content_id': content_id(body)}


def check_plan(plan):
    fixed = {'schema': SCHEMA, 'target_stage': 'M2', 'stage_accepted': False, 'formal_performance': False, 'policy': POLICY}
    require(isinstance(plan, dict) and plan.keys() == fixed.keys() | {'build_dir', 'artifacts', 'batches', 'protocol',
            'method_bindings', 'environment', 'plan_content_id', 'planned_batches'} and
            all(plan[k] == v for k, v in fixed.items()) and
            plan['plan_content_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}),
            'invalid frame timing plan')
    batches = plan['batches']
    require(batches == compile_frame_batches(batches['config']) and
            plan['planned_batches'] == sum(len(list(schedule(g))) for g in batches['groups']),
            'measurement schedule differs from frozen case configuration')
    l3_bytes = max((c['bytes'] for c in plan['environment']['cache_topology'] if c['level'] == 3), default=0)
    outside = next((c for c in batches['cases'] if c['id'] == 'large-copy-outside'), None)
    require(outside is not None and outside['bytes'] > l3_bytes,
            'frozen M2 cache-outside case does not exceed selected CPU L3 cache')
    paths = _paths(plan['build_dir'])
    require(plan['artifacts'].keys() == paths.keys() and all(row.keys() == {'path', 'sha256'} and row['path'] == paths[key]
            and isinstance(row['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
            for key, row in plan['artifacts'].items()), 'timing executable bindings differ from the build layout')
    require(plan['environment']['exclusive_cpu'] is False and plan['environment']['reservation'] == resource.RESERVATION and
            type(plan['environment']['cpu']) is int and plan['environment']['cpu'] in plan['environment']['allowed_cpu_ids'],
            'invalid measurement resource scope')
