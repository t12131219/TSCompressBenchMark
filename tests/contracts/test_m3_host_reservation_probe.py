from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import probe_m3_host_reservation as probe


def _judge(*, exclusive=(4, 5, 6, 7), root_isolated=(4, 5, 6, 7), partition='isolated',
           member='member', member_stable=True, affinity=(4, 6), topology_changed=False):
    topo = {n: {'core_id': c, 'package_id': 0, 'sibling_cpu_ids': [n, n+1], 'cpu_numa_nodes': [0]}
            for c, n in enumerate((4, 6))}
    leaf = {'path': '/reserve/job', 'partition': member, 'same_directory_during_read': True,
            'effective_cpus': [4, 6], 'effective_mems': [0], 'exclusive_cpus': None}
    parent = {**leaf, 'path': '/reserve', 'partition': partition,
              'exclusive_cpus': exclusive, 'effective_cpus': [4, 5, 6, 7]}
    root = {**parent, 'path': '/', 'partition': None}
    actual = {n: dict(e) for n, e in topo.items()}
    if topology_changed:
        actual[6]['core_id'] = 3
    return probe._assess(topo, actual, affinity, range(8), root_isolated, [leaf, parent, root], member_stable)


def test_snapshot_requires_both_partition_and_root_to_cover_smt():
    assert _judge() == ([4, 5, 6, 7], '/reserve', [])
    assert _judge(exclusive=[4, 6])[-1] == ['partition_exclusive_set_omits_required_cpus_or_smt_siblings']
    assert _judge(root_isolated=[4, 6])[-1] == ['kernel_root_isolated_set_omits_required_cpus_or_smt_siblings']
    assert _judge(partition='isolated invalid (no cpu)')[-1] == ['no_valid_isolated_partition_for_controller']
    assert _judge(member=None)[-1] == ['no_valid_isolated_partition_for_controller']
    assert _judge(member_stable=False)[-1] == ['cgroup_hierarchy_unavailable_or_changed_during_probe']
    assert _judge(affinity=[4])[-1] == ['controller_affinity_omits_planned_cpus']
    assert _judge(topology_changed=True)[-1] == ['frozen_cpu_topology_or_online_set_not_confirmed']


def test_probe_rejects_subtree_mount_and_malformed_membership():
    entry = '32 23 0:29 {} /sys/fs/cgroup ro,nosuid,nodev,noexec,relatime - cgroup2 cgroup2 rw\n'
    mount = entry.format('/')
    assert probe._hierarchy(mount, '0::/reserve/job\n') == (
        '/reserve/job', ['ro', 'nosuid', 'nodev', 'noexec', 'relatime'])
    assert probe._hierarchy(entry.format('/hidden'), '0::/job\n') == (None, None)
    assert probe._hierarchy(mount, '0::/../unexpected\n') == (None, None)
    assert probe._ids('') == [] and probe._ids(None) is None
