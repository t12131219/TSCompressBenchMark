"""Linux timing resource binding. This is cooperative, not OS core isolation."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import stat

from ..assets import ContractError, require

TASKSET = '/usr/bin/taskset'
PRLIMIT = '/usr/bin/prlimit'
RESERVATION = 'nonblocking_host_local_flock_per_uid_for_tsbench_timing'
SYS = Path('/sys/devices/system/cpu')


def _read(p):
    return p.read_text(encoding='ascii').strip()


def _cplist(text):
    cpus = set()
    for token in text.split(','):
        require(re.fullmatch(r'[0-9]{1,6}(?:-[0-9]{1,6})?', token), 'invalid Linux CPU list')
        ends = token.split('-')
        lo, hi = int(ends[0]), int(ends[-1])
        require(0 <= lo <= hi < 131072, 'Linux CPU list outside supported range')
        cpus.update(range(lo, hi + 1))
    return sorted(cpus)


def environment(cpu):
    allowed = sorted(os.sched_getaffinity(0))
    require(type(cpu) is int and cpu in allowed, 'requested measurement CPU is outside current affinity')
    host = os.uname()
    require(host.sysname == 'Linux', 'measurement resource binding requires Linux')
    device = SYS / f'cpu{cpu}'
    topology = device / 'topology'
    siblings = _cplist(_read(topology / 'thread_siblings_list'))
    require(cpu in siblings, 'selected CPU is absent from its sibling set')
    nodes = [int(path.name[4:]) for path in device.glob('node[0-9]*') if path.name[4:].isdigit()]
    caches = []
    for path in sorted((device / 'cache').glob('index*')):
        size = re.fullmatch(r'([1-9][0-9]*)([KMG])', _read(path / 'size'))
        require(size is not None, 'unrecognized Linux cache size')
        caches.append({'level': int(_read(path / 'level')), 'kind': _read(path / 'type'),
                       'bytes': int(size[1]) << {'K': 10, 'M': 20, 'G': 30}[size[2]],
                       'shared_cpus': _cplist(_read(path / 'shared_cpu_list'))})
    require(caches, 'no Linux cache topology for selected measurement CPU')
    return {'cpu': cpu, 'allowed_cpu_ids': allowed, 'core_id': int(_read(topology / 'core_id')),
            'package_id': int(_read(topology / 'physical_package_id')), 'sibling_cpu_ids': siblings,
            'cpu_numa_nodes': sorted(nodes), 'cache_topology': caches, 'kernel_release': host.release,
            'machine': host.machine, 'numa_memory_policy': 'inherited_uncontrolled',
            'reservation': RESERVATION, 'exclusive_cpu': False}


def observe(cpu):
    """Advisory snapshots, not a measurement of competing load or memory locality."""
    prefix = f'cpu{cpu} '
    counters = None
    try:
        with Path('/proc/stat').open(encoding='ascii') as f:
            for line in f:
                if line.startswith(prefix):
                    # Linux user, nice, system, idle, iowait, irq, softirq, steal.
                    counters = [int(x) for x in line.split()[1:9]]
                    break
    except (OSError, ValueError):
        pass
    try:
        khz = int(_read(SYS / f'cpu{cpu}' / 'cpufreq/scaling_cur_freq'))
    except (OSError, ValueError):
        khz = None
    return {'cpu_ticks': counters, 'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'), 'sampling_freq_khz': khz}


@contextmanager
def reserve():
    """Serializes cooperative runs across CLI, API, directories and CPUs for one UID."""
    uid = os.getuid()
    path = Path('/tmp') / f'tsbench-timing-{uid}.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        ref = os.fstat(fd)
        require(stat.S_ISREG(ref.st_mode) and ref.st_uid == uid and
                stat.S_IMODE(ref.st_mode) == 0o600 and ref.st_nlink == 1,
                'invalid shared measurement reservation file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError('measurement resource is already reserved by another TSBench run') from exc
        current = path.stat(follow_symlinks=False)
        require((current.st_dev, current.st_ino) == (ref.st_dev, ref.st_ino), 'measurement reservation path changed')
        yield
    finally:
        os.close(fd)
