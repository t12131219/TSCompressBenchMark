"""Contract regression tests for the sealed T-only/V-only artifacts and rejection inputs."""
from pathlib import Path
from struct import pack
import uuid

import pytest

from tsbench.application import m3_axis_roles as app
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json
from tsbench.ingress import sha
from tsbench.planner import m3_axis_roles as planner


def _write(path, data):
    path.write_bytes(canonical_bytes(data))


def _reseal(run):
    path = run / 'completion.json'
    seal = load_json(path)
    del seal['seal_id']
    seal['files'] = {p.relative_to(run).as_posix(): planner.file_ref(run, p)
                     for p in run.rglob('*') if p.is_file() and p != path}
    _write(path, {**seal, 'seal_id': content_id(seal)})


@pytest.fixture
def axis_run(tmp_path, monkeypatch):
    # A fake transport exercises the production assembly/auditor without installed plugins
    # or namespaces. The real-input r2 run separately exercises the actual isolated worker.
    rows = planner.CHUNK + 3
    spec = {'rows': rows, 'timestamp': {'unit': 's', 'dtype': 'i64', 'name': 't'},
            'values': [{'dtype': 'f64', 'name': name} for name in ('x', 'y')]}
    raw = (b''.join(pack('<q', x) for x in range(rows)),
           pack('<Q', 0x8000000000000000) * rows, pack('<Q', 0x7ff8000000000042) * rows)
    cases = []
    for fmt in ('csv', 'npy', 'txt'):
        for task in planner.ROUTES:
            is_t = task == 'timestamps_only'
            schema = {'rows': rows, 'columns': [spec['timestamp']] if is_t else spec['values']}
            hashes = list(map(sha, raw[:1] if is_t else raw[1:]))
            logical = rows * 8 * len(hashes)
            c = {'group': 'fixture', 'format': fmt, 'task': task, 'source_group_id': content_id('fixture'),
                 'object_id': content_id([schema, hashes]), 'schema': schema, 'original_columns_sha256': hashes,
                 'units': [u for u, _, _ in planner.units(task, spec, raw)],
                 'comparison': {'comparison_id': task, 'contract': {'original': {'logical_bytes': logical}}}}
            cases.append({**c, 'case_id': content_id(c)})
    t, v = planner.rejection_anchor(cases)
    body = {'schema': planner.SCHEMA, 'policy': planner.POLICY, 'limits': planner.LIMITS, 'cases': cases,
            'decoder': {'files': {}}, 'protocol': {'launchers': {}}, 'projection': {}, 'build': {},
            'negative_statuses': planner.NEGATIVES, 'stage_accepted': False, 'qualification_granted': False,
            'non_exact_probe': planner.non_exact_probe(pack('<q', 0)),
            'rejection_anchor': {'T': t['case_id'], 'V': v['case_id'], 'unit_index': 0}}
    plan = {**body, 'plan_content_id': content_id(body)}
    monkeypatch.setattr(app, 'verify_asset', lambda root, ref: root / ref['path'] if ref else root)
    monkeypatch.setattr(app, 'binding', lambda root: plan['protocol'])
    monkeypatch.setattr(app, 'launcher_lock', lambda: {})
    monkeypatch.setattr(app, 'plan_roles', lambda *args: plan)
    monkeypatch.setattr(app, 'projection_doc', lambda *args: {})
    monkeypatch.setattr(app, 'stage_recovery', lambda *args, **kwargs: None)
    monkeypatch.setattr(app, 'source_cases', lambda *args:
                        [('fixture', fmt, {}, {'ingestion': {'object': spec}}, raw) for fmt in ('csv', 'npy', 'txt')])

    def invoke(run, plan, plugin, work, op, inputs, args):
        out = work / 'out'
        out.mkdir(parents=True)
        encoding = op == app.EN
        direction = 'encode' if encoding else 'decode'
        info = {'operation': direction, 'threads': 1, 'mode': 'batch', 'backend':
                'alpn-auto-encoder' if plugin == 'alp-auto' and encoding else app.BACKENDS[plugin]}
        status = 0
        paths = {k: p.read_bytes() for k, p in inputs.items()}
        magic = planner.MAGIC[plugin]
        if encoding:
            dtype, caps = int(args[2]), paths['schema']
            if len(args) != 4 or (plugin, dtype) in [(app.T, 10), (app.V, 7)] or caps == planner.S_SCHEMA:
                status = 1
            else:
                data = paths['raw']
                (out / 'frame').write_bytes(app.HEADER.pack(magic, dtype, len(data)//8, len(caps), len(data)) + caps + data)
        else:
            frame = paths['frame']
            m, dtype, count, schema_bytes, _ = app.HEADER.unpack_from(frame)
            if m != magic:
                status = 5
            else:
                start = app.HEADER.size
                (out / 'schema').write_bytes(frame[start:start+schema_bytes])
                (out / 'raw').write_bytes(frame[start+schema_bytes:])
                info = [{'columns': [{'dtype': dtype, 'count': count}]}, info]
        (work / f'{op}.stdout').write_bytes(b'\n'.join(map(canonical_bytes, info if isinstance(info, list) else [info])))
        (work / f'{op}.stderr').write_text(f'plugin status {status}: fixture' if status else '')
        return out, {'input_mounts': {k: app._facts(p) for k, p in inputs.items()}, 'pid': 1,
                     'session_id': uuid.uuid4().hex, 'status': 'failed' if status else 'completed', 'returncode': 3 if status else 0}

    monkeypatch.setattr(app, '_invoke', invoke)
    run = app.run_roles(tmp_path, plan, tmp_path / 'runs')
    monkeypatch.setattr(app, 'verify_asset', planner.verify_asset)
    return run


def test_detached_replay_and_full_cost(axis_run):
    audit = app.audit_roles(axis_run, replay=True)
    assert audit['role_cases'] == {'timestamps_only': 6, 'values_only': 6}
    assert audit['replayed_frames'] == 36
    assert audit['replayed_rejections'].keys() == audit['rejections'].keys()
    for row in audit['rows']:
        assert row['bundle_bytes'] == row['manifest_bytes'] + row['frame_bytes']
        assert row['frame_bytes'] == row['frame_header_bytes'] + row['embedded_schema_bytes'] + row['native_payload_bytes']
        assert row['frame_header_bytes'] == row['chunks'] * app.HEADER.size
    assert not audit['stage_accepted'] and not audit['qualification_granted']


@pytest.mark.parametrize(('edit', 'message'), [
    ('delete', 'missing a frozen frame'), ('swap', 'frame mismatch'), ('schema', 'frame mismatch'),
    ('column', 'changed chunk mapping'), ('tail', 'changed chunk mapping'), ('cost', 'byte accounting'),
    ('original-schema', 'dropped original schema'),
])
def test_resealed_damage_is_not_accepted(axis_run, edit, message):
    path = axis_run / 'observations.json'
    data = load_json(path)
    row = data['rows'][2]  # two-column V slot
    manifest = axis_run / row['bundle']['path']
    doc = load_json(manifest)
    first, tail = (manifest.parent / chunk['frame']['path'] for chunk in doc['chunks'][:2])
    if edit == 'delete':
        tail.unlink()
    if edit == 'swap':
        contents = first.read_bytes(), tail.read_bytes()
        first.write_bytes(contents[1]); tail.write_bytes(contents[0])
    if edit == 'schema':
        body = bytearray(tail.read_bytes())
        body[app.HEADER.size] ^= 1
        tail.write_bytes(body)
    if edit in ('column', 'tail', 'cost', 'original-schema'):
        chunk = doc['chunks'][1]
        if edit == 'column':
            chunk['column'] = 1
        elif edit == 'tail':
            chunk['range'][1] += 1
        elif edit == 'cost':
            chunk['embedded_schema_bytes'] = 0
        else:
            doc['original_schema']['columns'].reverse()
        _write(manifest, doc)
        row['bundle'] = planner.file_ref(axis_run, manifest)
        _write(path, data)
    _reseal(axis_run)
    with pytest.raises(ContractError, match=message):
        app.audit_roles(axis_run)


def test_replay_detects_resealed_payload_with_unchanged_frame_shape(axis_run):
    path = axis_run / 'observations.json'
    observations = load_json(path)
    # Replace the same statically valid payload in all formats so that comparing
    # provider hashes alone cannot detect the substitution.
    for row in observations['rows']:
        if row['plugin'] != 'raw-timestamp':
            continue
        manifest = axis_run / row['bundle']['path']
        doc = load_json(manifest)
        chunk = doc['chunks'][1]
        frame = manifest.parent / chunk['frame']['path']
        body = bytearray(frame.read_bytes())
        body[-1] ^= 1
        frame.write_bytes(body)
        chunk['frame'] = planner.file_ref(manifest.parent, frame)
        row['operations'][1]['decode']['process']['input_mounts']['frame'] = app._facts(frame)
        _write(manifest, doc)
        row['bundle'] = planner.file_ref(axis_run, manifest)
    _write(path, observations)
    _reseal(axis_run)
    assert app.audit_roles(axis_run)['replay_performed'] is False
    with pytest.raises(ContractError, match='restored schema/bits differ'):
        app.audit_roles(axis_run, replay=True)


@pytest.mark.parametrize(('label', 'key', 'edit'), [
    ('tv-to-t', 'process', lambda r: r['input_mounts'].pop('value')),
    ('wrong-dtype-t', 'plugin', lambda _: app.V),
    ('t-frame-to-v', 'operation', lambda _: app.EN),
    ('v-frame-to-t', 'process', lambda r: r['input_mounts']['frame'].update(sha256='0' * 64)),
    ('non-exact-tick', 'input_hex', lambda _: pack('<q', 2).hex()),
])
def test_resealed_rejection_must_match_frozen_role_and_inputs(axis_run, label, key, edit):
    path = axis_run / 'observations.json'
    doc = load_json(path)
    row = doc['rejections'][label]
    replacement = edit(row[key])
    if key != 'process':
        row[key] = replacement
    _write(path, doc)
    _reseal(axis_run)
    with pytest.raises(ContractError, match='role (?:process terminal|rejection result|unit conversion)'):
        app.audit_roles(axis_run)
