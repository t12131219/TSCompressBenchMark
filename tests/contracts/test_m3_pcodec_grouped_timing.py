from hashlib import sha256
import json
from struct import pack

import pytest

from tsbench.application import m3_pcodec_grouped_timing as g
from tsbench.assets import ContractError


def test_pgf1_archive_retains_inner_frame_geometry_and_checks_digest(tmp_path):
    wire = b'PM3PAGE1' + pack('<4I', 1, 2, 3, 0) + b'\0\0'
    frame = {'bytes': len(wire), 'sha256': sha256(wire).hexdigest()}
    enc = {'rows': 3, 'pages': 1, 'meta_bytes': 2, 'payload_bytes': 0, 'container_bytes': 24, 'zero_payload_pages': 1}
    c = {'columns': 1, 'rows': 3, 'variants': {'source': {'units': [{'frame': frame, 'semantics': {'encode': enc}}],
                                                         'frame_archive_bytes': g._archive_bytes(1, len(wire))}}}
    data = g.HEAD.pack(g.FRAME, 1, 3) + g.SIZE.pack(len(wire)) + wire
    f = tmp_path / 'frame.pgf'
    f.write_bytes(data)
    assert g._inspect_frames(c, 'source', f) == {'bytes': len(data), 'sha256': sha256(data).hexdigest()}
    f.write_bytes(data[:-1] + b'\xff')
    with pytest.raises(ContractError, match='differ from r40'):
        g._inspect_frames(c, 'source', f)


def test_group_spans_sum_wall_and_cpu_but_not_peak_rss(tmp_path):
    raw = [{'rows': 5}, {'rows': 1}]
    c = {'variants': {'native': {'units': [{'semantics': {'encode': data}} for data in raw]}}}
    stdout = tmp_path / 'native.stdout'
    def rec(row, wall, cpu, rss):
        return json.dumps({**row, 'operation_wall_ns': wall, 'operation_cpu_ns': cpu, 'process_peak_rss_bytes': rss}) + '\n'
    first = rec(raw[0], 9, 5, 1024)
    second = rec(raw[1], 11, 0, 512)
    stdout.write_text(first + second)
    assert g._metrics(c, 'native', 'encode', stdout) == {
        'group_api_wall_ns': 20, 'group_api_self_cpu_ns': 5, 'reported_child_hwm_bytes': 1024}
    stdout.write_text(first + second + second)
    with pytest.raises(ContractError, match='extra'):
        g._metrics(c, 'native', 'encode', stdout)
    stdout.write_text(second + first)
    with pytest.raises(ContractError, match='frozen unit'):
        g._metrics(c, 'native', 'encode', stdout)


def test_schedule_is_whole_file_trial_not_group(tmp_path):
    c = {'case_id': 'x', 'order': [['native', 'source'], ['source', 'native']]}
    slots = list(g._schedule(c))
    assert len(slots) == 8 and len({r['path'] for r in slots}) == 8
    assert [(x['direction'], x['lane']) for x in slots[:4]] == [
        ('encode', 'native'), ('encode', 'source'), ('decode', 'native'), ('decode', 'source')]
    assert all(r['phase'] == 'warmup' for r in slots[:4]) and all(r['phase'] == 'measure' for r in slots[4:])
