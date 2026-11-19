"""Replay-checkable contract for the M1 files-only diagnostic, not formal timing."""
from pathlib import Path
import re

from ..assets import digest, require
from ..supervisor import isolated_worker

SUITE = 'm1_lossless_candidate_v3'
SCOPE = 'launcher_start_to_reap_including_bubblewrap_setup_and_exit'
NAMESPACE = 'bubblewrap_network_pid_ipc_sealed_files_only'
USAGE = 'wait4_direct_launcher_child_not_codec_cpu_or_rss'


def active(suite):
    return suite['id'] == SUITE


def _policy(suite):
    return {'namespace': NAMESPACE, 'clock_boundary': SCOPE, 'usage_boundary': USAGE,
            'limits': {'address_space_bytes': 256 << 20, 'file_bytes': suite['max_serialized_bytes_per_slot'],
                       'wall_seconds': suite['timeout_seconds_per_operation']},
            'encode_inputs': ['original.bin', 'original.json'], 'decode_inputs': ['frame.bmk']}


def bind(suite):
    return {**_policy(suite), 'launchers': isolated_worker.launcher_lock(),
            'launcher_protocol_sha256': digest(Path(isolated_worker.__file__))}


def check(suite, binding):
    policy = _policy(suite)
    require(isinstance(binding, dict) and binding.keys() == policy.keys() | {'launchers', 'launcher_protocol_sha256'}
            and all(binding[k] == value for k, value in policy.items()), 'isolated smoke policy differs from suite')
    isolated_worker.validate_limits(binding['limits'])
    launchers = binding['launchers']
    require(isinstance(launchers, dict) and launchers.keys() == set(isolated_worker.LAUNCHERS) and
            all(isinstance(x, str) and re.fullmatch('[0-9a-f]{64}', x)
                for x in [*launchers.values(), binding['launcher_protocol_sha256']]),
            'invalid isolated smoke launcher identity')
