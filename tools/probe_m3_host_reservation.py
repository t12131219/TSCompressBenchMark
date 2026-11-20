#!/usr/bin/env python3
"""Read a cgroup-v2 CPU reservation snapshot for the frozen M3 timing budgets.

This probe never edits the host, moves a process, or grants timing admission.
Run it from the intended run controller's cgroup, not an unrelated shell.
"""
from argparse import ArgumentParser
from datetime import datetime, timezone
import os
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, require
from tsbench.supervisor.timing_resource import _cplist

CG = Path('/sys/fs/cgroup')
PROC = Path('/proc')
CPU = Path('/sys/devices/system/cpu')
PART = 'cpuset.cpus.partition'
EXCL = 'cpuset.cpus.exclusive.effective'
EFFECTIVE = 'cpuset.cpus.effective'
MEMS = 'cpuset.mems.effective'


def _read(path):
    try:
        return path.read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return None


def _ids(text):
    if text is None:
        return None
    return _cplist(text) if text else []


def _covers(observed, requested):
    return observed is not None and set(requested) <= set(observed)


def _budgets(plan):
    require(plan.get('plan_content_id') == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}),
            'M3 reservation probe plan identity differs')
    m = plan['measurement']
    require(m['schema'] == 'bmk.m3-in-run-measurement/13', 'probe supports the complete v13 timing plan')
    lines = {'default': [m['environment']], 'zfp-field': m['zfp']['field_environment'],
             'zstd-xz-workers': m['lzbench_clock']['worker_environment']}
    budgets = {}
    topology = {}
    for cohort, envs in lines.items():
        require(len(envs) == {'default': 1, 'zfp-field': 2, 'zstd-xz-workers': 3}[cohort],
                'M3 probe plan CPU budget has unexpected width')
        budgets[cohort] = []
        used = set()
        for env in envs:
            cpu = env['cpu']
            topo = {k: env[k] for k in ('sibling_cpu_ids', 'cpu_numa_nodes', 'core_id', 'package_id')}
            core = (topo['package_id'], topo['core_id'])
            require(cpu in topo['sibling_cpu_ids'] and core not in used and topology.get(cpu, topo) == topo,
                    'M3 probe plan physical core budget differs')
            used.add(core)
            topology[cpu] = topo
            budgets[cohort].append(cpu)
    return budgets, topology


def _hierarchy(mountinfo, membership):
    lines = [left.split() for line in (mountinfo or '').splitlines()
             for left, sep, right in [line.partition(' - ')] if sep and right.startswith('cgroup2 ')]
    # Only interpret hierarchy paths when /sys/fs/cgroup exposes its whole root.
    mounts = [line for line in lines if len(line) >= 6 and line[3:5] == ['/', str(CG)]]
    members = [line[3:] for line in (membership or '').splitlines() if line.startswith('0::')]
    if len(mounts) != 1 or len(members) != 1:
        return None, None
    member = PurePosixPath(members[0])
    if not member.is_absolute() or member.anchor != '/' or '..' in member.parts or members[0] != str(member):
        return None, None
    return str(member), mounts[0][5].split(',')


def _cpu_state(cpu):
    base = CPU / f'cpu{cpu}'
    topo = base / 'topology'
    core, package = (_read(topo / k) for k in ('core_id', 'physical_package_id'))
    nodes = sorted(int(p.name[4:]) for p in base.glob('node[0-9]*') if p.name[4:].isdigit()) if base.is_dir() else None
    return {'core_id': int(core) if core is not None else None, 'package_id': int(package) if package is not None else None,
            'sibling_cpu_ids': _ids(_read(topo / 'thread_siblings_list')), 'cpu_numa_nodes': nodes}


def _state(cgroup):
    def directory_id():
        try:
            st = cgroup.stat()
            return [st.st_dev, st.st_ino]
        except OSError:
            return None

    before = directory_id()
    out = {'path': '/' + cgroup.relative_to(CG).as_posix() if cgroup != CG else '/',
           'directory_id': before, 'partition': _read(cgroup / PART),
           'exclusive_cpus': _ids(_read(cgroup / EXCL)), 'effective_cpus': _ids(_read(cgroup / EFFECTIVE)),
           'effective_mems': _ids(_read(cgroup / MEMS))}
    out['same_directory_during_read'] = before is not None and before == directory_id()
    return out


def _assess(topology, actual, affinity, online, isolated, states, member_stable):
    active = set(topology)
    # Reserve the entire physical core, even when a method uses only one SMT lane.
    reserved = set().union(*(set(t['sibling_cpu_ids']) for t in topology.values()))
    reasons = []
    if not member_stable or not states or not all(s['same_directory_during_read'] for s in states):
        reasons.append('cgroup_hierarchy_unavailable_or_changed_during_probe')
    if actual != topology or not _covers(online, reserved):
        reasons.append('frozen_cpu_topology_or_online_set_not_confirmed')
    if not _covers(affinity, active):
        reasons.append('controller_affinity_omits_planned_cpus')
    if not _covers(isolated, reserved):
        reasons.append('kernel_root_isolated_set_omits_required_cpus_or_smt_siblings')
    # The nearest non-member partition determines which reservation the controller uses.
    # An invalid or unobservable state must never be filled from a more distant ancestor.
    partition = next((s for s in states[:-1] if s['partition'] != 'member'), None)
    if not partition or partition['partition'] != 'isolated':
        reasons.append('no_valid_isolated_partition_for_controller')
    elif not _covers(partition['exclusive_cpus'], reserved):
        reasons.append('partition_exclusive_set_omits_required_cpus_or_smt_siblings')
    nodes = set().union(*(set(t['cpu_numa_nodes']) for t in topology.values()))
    if not states or not _covers(states[0]['effective_cpus'], active):
        reasons.append('controller_effective_cpuset_omits_planned_cpus')
    if not nodes or not states or not _covers(states[0]['effective_mems'], nodes):
        reasons.append('controller_effective_memory_nodes_not_confirmed')
    return sorted(reserved), partition['path'] if partition else None, reasons


def snapshot(plan):
    budgets, topology = _budgets(plan)
    observed_from = datetime.now(timezone.utc).isoformat()
    cgroup, mount_options = _hierarchy(_read(PROC / 'self/mountinfo'), _read(PROC / 'self/cgroup'))
    states = []
    if cgroup is not None:
        path = CG.joinpath(*PurePosixPath(cgroup).parts[1:])
        while True:
            states.append(_state(path))
            if path == CG:
                break
            path = path.parent
    actual = {cpu: _cpu_state(cpu) for cpu in topology}
    affinity = sorted(os.sched_getaffinity(0))
    online = _ids(_read(CPU / 'online'))
    isolated = _ids(_read(CG / 'cpuset.cpus.isolated'))
    member_stable = cgroup is not None and (cgroup, mount_options) == _hierarchy(
        _read(PROC / 'self/mountinfo'), _read(PROC / 'self/cgroup'))
    reserved, partition, reasons = _assess(topology, actual, affinity, online, isolated, states, member_stable)
    body = {'schema': 'bmk.m3-host-reservation-probe/1', 'plan_content_id': plan['plan_content_id'],
            'scope': 'controller_snapshot_only_not_a_lease_or_timing_admission',
            'observed_from_utc': observed_from, 'observed_until_utc': datetime.now(timezone.utc).isoformat(),
            'boot_id': _read(PROC / 'sys/kernel/random/boot_id'), 'kernel_release': os.uname().release,
            'cpu_budgets': budgets, 'must_reserve_including_smt': reserved,
            'frozen_topology': {str(k): v for k, v in topology.items()},
            'observed_topology': {str(k): v for k, v in actual.items()}, 'controller_affinity': affinity,
            'online_cpus': online, 'root_isolated_cpus': isolated, 'controller_cgroup': cgroup,
            'cgroup_mount_options': mount_options, 'cgroup_ancestry_leaf_first': states, 'partition_path': partition,
            'kernel_cpu_partition_snapshot_confirmed': not reasons, 'unconfirmed_reasons': reasons,
            'outside_probe_scope': ['reservation_owner_and_valid_interval', 'other_tasks_inside_partition',
                                    'irq_and_other_interference', 'numa_process_memory_policy',
                                    'per_trial_affinity_and_migration', 'predeclared_interference_and_retry_policy'],
            'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False}
    return {**body, 'probe_id': content_id(body)}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        doc = snapshot(load_json(args.plan))
        write_new(args.out, doc)
        print(doc['probe_id'], 'observed' if doc['kernel_cpu_partition_snapshot_confirmed'] else 'unconfirmed',
              ', '.join(doc['unconfirmed_reasons']))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
