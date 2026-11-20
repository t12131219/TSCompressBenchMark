"""Execute T-only/V-only on real sources and replay a detached, billed role bundle."""
from collections import Counter
from pathlib import Path
import re
from struct import Struct
from tempfile import TemporaryDirectory
import uuid

from ..assets import ContractError, content_id, digest, load_json, local_file, require, verify_asset
from ..ingress import sha
from ..planner.m3_axis_roles import (MAGIC, MS_SCHEMA, POLICY, ROUTES, S_SCHEMA, binding, check_plan, file_ref,
                                    non_exact_probe, plan_roles, projection_doc, rejection_anchor, source_cases, units)
from ..planner.tv import exact_ticks
from ..recovery import stage_recovery
from ..supervisor.isolated_worker import invoke_isolated_worker, launcher_lock
from .smoke import _worker_json, write_new

RUNTIME = 'role-runtime'
HEADER = Struct('<8sIQIQ')
BACKENDS = {'gorilla-t-derived': 'gorilla-t-c11-derived', 'raw-timestamp': 'raw-copy',
            'gorilla-v-derived': 'gorilla-v-c11-derived', 'alp-auto': 'scalar-unfused'}
EN, DE = 'encode-columns', 'decode-columns'
T, V = 'gorilla-t-derived', 'gorilla-v-derived'


def _facts(path):
    require(path.is_file() and not path.is_symlink(), 'M3 role worker omitted a regular file')
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def _inspect(path, plugin, unit):
    data = path.read_bytes()
    require(HEADER.size < len(data) <= 1 << 20, 'M3 role frame outside transport bound')
    magic, dtype, count, schema_bytes, payload = HEADER.unpack_from(data)
    require((magic, dtype, count, schema_bytes) == (MAGIC[plugin], unit['dtype'], unit['count'], unit['schema']['bytes']) and
            len(data) == HEADER.size + schema_bytes + payload and payload > 0 and
            sha(data[HEADER.size:HEADER.size + schema_bytes]) == unit['schema']['sha256'], 'M3 role frame mismatch')
    return {'payload_bytes': payload, 'embedded_schema_bytes': schema_bytes, 'header_bytes': HEADER.size}


def _invoke(run, plan, plugin, work, op, inputs, args):
    work.mkdir()
    return invoke_isolated_worker(run / RUNTIME, plan['decoder'], plan['methods'][plugin], plan['limits'],
                                  work, work, op, inputs, args, lambda: False, observe=True)


def _terminal(proc, mounts, seen=None, *, success=True):
    require(proc['input_mounts'] == mounts and type(proc['pid']) is int and proc['pid'] > 0 and
            re.fullmatch(r'[a-f0-9]{32}', proc['session_id'] or '') and
            (proc['status'], proc['returncode']) == (('completed', 0) if success else ('failed', 3)),
            'M3 role process terminal or mounts differ')
    if seen is not None:
        require(proc['session_id'] not in seen, 'M3 role reused process session')
        seen.add(proc['session_id'])


def _native(plugin, operation, info):
    expected = 'alpn-auto-encoder' if plugin == 'alp-auto' and operation == 'encode' else BACKENDS[plugin]
    require(info.get('backend') == expected and info.get('operation') == operation and
            info.get('mode') == 'batch' and info.get('threads') == 1, 'M3 role native route/operation differs')


def _encode(run, plan, plugin, work, raw, schema, unit):
    out, proc = _invoke(run, plan, plugin, work, EN, {'raw': raw, 'schema': schema},
                        ['/inputs/schema', '/out/frame', str(unit['dtype']), '/inputs/raw'])
    _terminal(proc, {'raw': unit['codec_input'], 'schema': unit['schema']})
    [info] = _worker_json(work / f'{EN}.stdout', 1)
    _native(plugin, 'encode', info)
    require({p.name for p in out.iterdir()} == {'frame'}, 'invalid M3 role encode output set')
    return out / 'frame', {'process': proc, 'native': info}


def _decode(run, plan, plugin, work, frame, unit, case, seen=None):
    out, proc = _invoke(run, plan, plugin, work, DE, {'frame': frame}, ['/inputs/frame', '/out/schema', '/out/raw'])
    _terminal(proc, {'frame': _facts(frame)}, seen)
    require({p.name for p in out.iterdir()} == {'raw', 'schema'}, 'invalid M3 role decode output set')
    result = {'raw': _facts(out / 'raw'), 'schema': _facts(out / 'schema')}
    shape, info = _worker_json(work / f'{DE}.stdout', 2)
    require(result == {'raw': unit['codec_input'], 'schema': unit['schema']} and
            shape == {'columns': [{'dtype': unit['dtype'], 'count': unit['count']}]}, 'M3 role restored schema/bits differ')
    _native(plugin, 'decode', info)
    data = (out / 'raw').read_bytes()
    if case['task'] == 'timestamps_only':
        data = exact_ticks(data, 'ms', case['schema']['columns'][0]['unit'])
    require(sha(data) == unit['original_sha256'], 'M3 role original-domain restoration differs')
    return data, {'process': proc, 'native': info, 'restored': result, 'original_sha256': sha(data)}


def _bundle(case, plugin, frames):
    return {'schema': POLICY['format'], 'task': case['task'], 'object_id': case['object_id'],
            'original_schema': case['schema'], 'plugin': plugin, 'chunks': frames}


def _verify_whole(case, columns):
    require([sha(c) for c in columns] == case['original_columns_sha256'] and
            all(len(c) == 8 * case['schema']['rows'] for c in columns), 'M3 role bundle order or original-domain bits differ')


def _negative_specs():
    pre = ['/inputs/schema', '/out/frame']
    decode = ['/inputs/frame', '/out/schema', '/out/raw']
    tv = {'schema': 'ms', 'time': 'T', 'value': 'V'}
    both = [*pre, '7', '/inputs/time', '10', '/inputs/value']
    return [
        ('tv-to-t', T, EN, tv, both),
        ('tv-to-v', V, EN, tv, both),
        ('wrong-dtype-t', T, EN, {'schema': 'ms', 'raw': 'V'}, [*pre, '10', '/inputs/raw']),
        ('wrong-dtype-v', V, EN, {'schema': 'ms', 'raw': 'T'}, [*pre, '7', '/inputs/raw']),
        ('wrong-unit-t', T, EN, {'schema': 's', 'raw': 'T'}, [*pre, '7', '/inputs/raw']),
        ('v-frame-to-t', T, DE, {'frame': 'V-frame'}, decode),
        ('t-frame-to-v', V, DE, {'frame': 'T-frame'}, decode),
    ]


def _probe_result(probe):
    try:
        exact_ticks(bytes.fromhex(probe['input_hex']), probe['from'], probe['to'])
    except ContractError as exc:
        return {**probe, 'status': 'input_rejected_before_launch', 'diagnostic': str(exc), 'published_files': 0}
    raise ContractError('M3 role accepted lossy timestamp conversion')


def _probe_assets(run, plan):
    t, v = rejection_anchor(plan['cases'])
    index = plan['rejection_anchor']['unit_index']
    paths = {f'{role}-frame': local_file(run, f"bundles/{content_id([case['case_id'], plugin])}/{index:03}.bmk")
             for role, case, plugin in [('T', t, T), ('V', v, V)]}
    facts = {**{name: _facts(path) for name, path in paths.items()},
             'T': t['units'][index]['codec_input'], 'V': v['units'][index]['codec_input'],
             'ms': {'bytes': len(MS_SCHEMA), 'sha256': sha(MS_SCHEMA)},
             's': {'bytes': len(S_SCHEMA), 'sha256': sha(S_SCHEMA)}}
    return paths, facts


def _check_negative(plan, result, facts, seen):
    require(result.keys() == plan['negative_statuses'].keys() | {'non-exact-tick'}, 'M3 role rejection classes differ')
    for label, plugin, op, roles, _ in _negative_specs():
        row, status = result[label], plan['negative_statuses'][label]
        require((row['plugin'], row['operation'], row['status'], row['published_files']) == (plugin, op, status, 0) and
                row['diagnostic'].startswith(f'plugin status {status}:'), 'M3 role rejection result differs from plan')
        _terminal(row['process'], {name: facts[role] for name, role in roles.items()}, seen, success=False)
    probe = plan['non_exact_probe']
    require((probe['from'], probe['to']) == ('ms', 's') and len(bytes.fromhex(probe['input_hex'])) == 8 and
            result['non-exact-tick'] == _probe_result(probe), 'M3 role unit conversion rejection differs')


def _negative(run, plan, scratch, source, seen=None):
    paths, facts = _probe_assets(run, plan)
    for role, data in {**source, 'ms': MS_SCHEMA, 's': S_SCHEMA}.items():
        paths[role] = scratch / (role + '.bin')
        paths[role].write_bytes(data)
        require(_facts(paths[role]) == facts[role], 'M3 role rejection source differs from frozen unit')
    require(non_exact_probe(source['T']) == plan['non_exact_probe'], 'M3 role timestamp probe differs from anchor')
    result = {}
    for label, plugin, op, roles, args in _negative_specs():
        work = scratch / label
        out, proc = _invoke(run, plan, plugin, work, op, {name: paths[role] for name, role in roles.items()}, args)
        status = plan['negative_statuses'][label]
        diagnostic = (work / f'{op}.stderr').read_text().strip()
        result[label] = {'plugin': plugin, 'operation': op, 'status': status, 'process': proc,
                         'diagnostic': diagnostic, 'published_files': len(list(out.iterdir()))}
    result['non-exact-tick'] = _probe_result(plan['non_exact_probe'])
    _check_negative(plan, result, facts, seen)
    return result


def run_roles(root, plan, results):
    check_plan(plan)
    require(plan['protocol'] == binding(root) and plan == plan_roles(root, verify_asset(root, plan['projection']),
                                                                     verify_asset(root, plan['build'])), 'M3 role frozen plan changed')
    projection = projection_doc(root, plan['projection'])
    sources = {(group, fmt): (lineage['ingestion']['object'], raw)
               for group, fmt, _, lineage, raw in source_cases(root, projection)}
    run = results / uuid.uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    write_new(run / 'plan.json', plan)
    stage_recovery(root, run, plan['decoder'], directory=RUNTIME)
    rows, negative_source = [], {}
    anchor = {plan['rejection_anchor']['T']: ('T', T), plan['rejection_anchor']['V']: ('V', V)}
    with TemporaryDirectory(dir=run, prefix='.work-') as tmp:
        scratch = Path(tmp)
        for case in plan['cases']:
            spec, raw = sources[case['group'], case['format']]
            inputs = list(units(case['task'], spec, raw))
            require([u for u, _, _ in inputs] == case['units'], 'M3 role execution inputs differ from frozen case')
            for plugin in ROUTES[case['task']]:
                slot = content_id([case['case_id'], plugin])
                target = run / 'bundles' / slot
                target.mkdir(parents=True)
                entries, ops, columns = [], [], [bytearray() for _ in case['schema']['columns']]
                for index, (unit, encoded, schema) in enumerate(inputs):
                    with TemporaryDirectory(dir=scratch) as sub:
                        work = Path(sub)
                        data, metadata = work / 'raw', work / 'schema'
                        data.write_bytes(encoded); metadata.write_bytes(schema)
                        frame, enc = _encode(run, plan, plugin, work / 'encode', data, metadata, unit)
                        output = target / f'{index:03}.bmk'
                        frame.rename(output)
                        entry = {'column': unit['column'], 'range': unit['range'], 'frame': file_ref(target, output),
                                 **_inspect(output, plugin, unit)}
                        restored, dec = _decode(run, plan, plugin, work / 'decode', output, unit, case)
                        columns[unit['column']].extend(restored)
                        entries.append(entry)
                        ops.append({'encode': enc, 'decode': dec})
                        if index == plan['rejection_anchor']['unit_index'] and case['case_id'] in anchor:
                            role, provider = anchor[case['case_id']]
                            if plugin == provider:
                                negative_source[role] = encoded
                _verify_whole(case, columns)
                manifest = target / 'manifest.json'
                write_new(manifest, _bundle(case, plugin, entries))
                rows.append({'case_id': case['case_id'], 'plugin': plugin, 'slot': slot, 'bundle': file_ref(run, manifest),
                             'operations': ops, 'status': 'verified'})
        negatives = _negative(run, plan, scratch, negative_source)
    write_new(run / 'observations.json', {'rows': rows, 'rejections': negatives})
    files = {p.relative_to(run).as_posix(): file_ref(run, p) for p in run.rglob('*') if p.is_file()}
    body = {'schema': 'bmk.m3-real-axis-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'], 'files': files}
    write_new(run / 'completion.json', {**body, 'seal_id': content_id(body)})
    return run


def audit_roles(run, *, replay=False):
    """Verify custody and optionally recover all retained objects without source files."""
    seal = load_json(local_file(run, 'completion.json'))
    require(seal['schema'] == 'bmk.m3-real-axis-seal/1' and seal['run_id'] == run.name and
            seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}), 'M3 role run seal differs')
    files = seal['files']
    require(files.keys() == {p.relative_to(run).as_posix() for p in run.rglob('*') if p.is_file() and p not in {run / 'completion.json', run / 'report.json'}} and
            not any(p.is_symlink() for p in run.rglob('*')), 'M3 role evidence closure differs')
    for name, ref in files.items():
        require(ref['path'] == name and verify_asset(run, ref).stat().st_size == ref['bytes'], 'M3 role sealed file changed')
    plan = load_json(local_file(run, 'plan.json'))
    check_plan(plan)
    require(plan['plan_content_id'] == seal['plan_content_id'], 'M3 role run points at wrong plan')
    declared = {'plan.json', 'observations.json'}
    for rel, identity in plan['decoder']['files'].items():
        name = f'{RUNTIME}/{rel}'
        require(all(files[name][k] == identity[k] for k in ('bytes', 'sha256')), 'M3 role runtime differs from plan')
        declared.add(name)
    if replay:
        require(launcher_lock() == plan['protocol']['launchers'], 'M3 role replay launcher changed')
    observed = load_json(local_file(run, 'observations.json'))
    expected = [(case, plugin) for case in plan['cases'] for plugin in ROUTES[case['task']]]
    require(len(observed['rows']) == len(expected), 'M3 role execution census differs from plan')
    seen, replay_sessions, equivalent, rows = set(), set(), {}, []
    anchor = {(plan['rejection_anchor']['T'], T): 'T', (plan['rejection_anchor']['V'], V): 'V'}
    probe_source = {}
    for row, (case, plugin) in zip(observed['rows'], expected, strict=True):
        slot = content_id([case['case_id'], plugin])
        base = f'bundles/{slot}'
        manifest = f'{base}/manifest.json'
        require((row['case_id'], row['plugin'], row['slot'], row['status']) == (case['case_id'], plugin, slot, 'verified') and
                row['bundle'] == files[manifest], 'M3 role row or bundle identity differs')
        declared.add(manifest)
        bundle = load_json(local_file(run, manifest))
        frames = bundle['chunks']
        require(bundle == _bundle(case, plugin, frames) and len(frames) == len(case['units']) == len(row['operations']),
                'M3 role bundle dropped original schema or units')
        restored = [bytearray() for _ in case['schema']['columns']]
        fresh, payload_bytes, frame_bytes, header_bytes, schema_bytes = [], 0, 0, 0, 0
        for index, (unit, chunk, ops) in enumerate(zip(case['units'], frames, row['operations'], strict=True)):
            path = f'{base}/{index:03}.bmk'
            require(path in files, 'M3 role bundle is missing a frozen frame')
            ref = {**files[path], 'path': f'{index:03}.bmk'}
            frame = local_file(run, path)
            require(chunk == {'column': unit['column'], 'range': unit['range'], 'frame': ref, **_inspect(frame, plugin, unit)},
                    'M3 role bundle changed chunk mapping, frame or byte accounting')
            declared.add(path)
            enc, dec = ops['encode'], ops['decode']
            _terminal(enc['process'], {'raw': unit['codec_input'], 'schema': unit['schema']}, seen)
            _terminal(dec['process'], {'frame': _facts(frame)}, seen)
            _native(plugin, 'encode', enc['native']); _native(plugin, 'decode', dec['native'])
            require(dec['restored'] == {'raw': unit['codec_input'], 'schema': unit['schema']} and
                    dec['original_sha256'] == unit['original_sha256'], 'M3 role recovery observations differ')
            payload_bytes += chunk['payload_bytes']; frame_bytes += ref['bytes']
            header_bytes += chunk['header_bytes']; schema_bytes += chunk['embedded_schema_bytes']
            if replay:
                with TemporaryDirectory(prefix='m3-role-replay-') as tmp:
                    data, facts = _decode(run, plan, plugin, Path(tmp) / 'restore', frame, unit, case, replay_sessions)
                restored[unit['column']].extend(data)
                fresh.append(facts)
                role = anchor.get((case['case_id'], plugin))
                if role and index == plan['rejection_anchor']['unit_index']:
                    probe_source[role] = exact_ticks(data, case['schema']['columns'][0]['unit'], 'ms') if role == 'T' else data
        if replay:
            _verify_whole(case, restored)
        require(frame_bytes == payload_bytes + header_bytes + schema_bytes, 'M3 role frame charges do not balance')
        signature = [files[manifest]['sha256'], *[f['frame']['sha256'] for f in frames]]
        key = case['source_group_id'], case['task'], plugin
        prior = equivalent.setdefault(key, {'signature': signature, 'formats': []})
        require(prior['signature'] == signature and case['format'] not in prior['formats'], 'M3 axis bundle differs between providers')
        prior['formats'].append(case['format'])
        rows.append({'group': case['group'], 'format': case['format'], 'task': case['task'], 'role_provider': plugin,
                     'object_id': case['object_id'], 'source_group_id': case['source_group_id'],
                     'comparison_id': case['comparison']['comparison_id'],
                     'status': 'verified', 'chunks': len(frames), 'frame_bytes': frame_bytes, 'native_payload_bytes': payload_bytes,
                     'frame_header_bytes': header_bytes, 'embedded_schema_bytes': schema_bytes,
                     'manifest_bytes': files[manifest]['bytes'], 'bundle_bytes': frame_bytes + files[manifest]['bytes'],
                     'original_logical_bytes': case['comparison']['contract']['original']['logical_bytes'], 'replay': fresh})
    require(declared == files.keys() and
            all(set(e['formats']) == {'csv', 'npy', 'txt'} for e in equivalent.values()), 'M3 role evidence or provider coverage differs')
    rejects = observed['rejections']
    _check_negative(plan, rejects, _probe_assets(run, plan)[1], seen)
    fresh_rejections = None
    if replay:
        with TemporaryDirectory(prefix='m3-role-rejections-') as tmp:
            fresh_rejections = _negative(run, plan, Path(tmp), probe_source, replay_sessions)
    require(seen.isdisjoint(replay_sessions), 'M3 role replay reused process session')
    return {'schema': 'bmk.m3-real-axis-audit/2', 'run_id': run.name, 'seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], 'role_cases': dict(Counter(r['task'] for r in rows)),
            'provider_equivalence_groups': len(equivalent), 'replay_performed': replay,
            'replayed_frames': sum(len(r['replay']) for r in rows), 'rejections': rejects,
            'replayed_rejections': fresh_rejections, 'rows': rows,
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}
