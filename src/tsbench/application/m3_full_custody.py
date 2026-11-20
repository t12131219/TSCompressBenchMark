"""Audit one M3 main ledger's retained corpus objects and pcodec page replays."""
from collections import Counter, defaultdict
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import numpy as np

from ..assets import content_id, digest, load_json, local_file, parse_json, relative_parts, require, verify_asset
from ..corpus_ingress import read_batches
from ..recovery import plan_recovery, stage_recovery
from ..supervisor.isolated_worker import invoke_isolated_tool
from .m3_pcodec_pages import CHUNK_ROWS, _verify_chunk
from .m3_real_corpus_execution import _entry_map

SCHEMA = 'bmk.m3-corpus-retention-audit/1'
ROOTS = frozenset({'retained', 'fixed-batch-samples'})
ROUTES = {'source-pages': 'source', 'native-pages': 'native'}
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 15}


def _references(node):
    if isinstance(node, dict):
        p = node.get('path')
        if isinstance(p, str) and p.partition('/')[0] in ROOTS:
            relative_parts(p)
            require('/' in p and type(node.get('bytes')) is int and node['bytes'] >= 0 and
                    isinstance(node.get('sha256'), str) and re.fullmatch('[a-f0-9]{64}', node['sha256']),
                    'M3 retained reference lacks size or SHA-256')
            yield p, {k: node[k] for k in ('path', 'bytes', 'sha256')}
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _references(value)
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                yield from _references(value)


def _inventory(run):
    files = set()
    for name in ROOTS:
        folder = run / name
        require(not folder.is_symlink() and (not folder.exists() or folder.is_dir()), 'invalid M3 retained corpus root')
        for p in folder.rglob('*'):
            require(not p.is_symlink() and (p.is_file() or p.is_dir()), 'M3 retained object is linked or non-regular')
            if p.is_file():
                files.add(p.relative_to(run).as_posix())
    return files


def _known_file(run, ref):
    path = verify_asset(run, ref)
    require(path.stat().st_size == ref['bytes'], 'M3 retained corpus object size differs')
    return path


def _collect(plan, run, ledger, *, full):
    expected = {w['work_item_id']: w for w in plan['work_items']}
    seen, refs, page_cases, route_counts = set(), {}, [], defaultdict(Counter)
    typed_tail = False
    previous, positions = -1, {k: i for i, k in enumerate(expected)}
    with ledger.open(encoding='utf-8') as stream:
        for index, text in enumerate(stream, 1):
            row = parse_json(text, f'M3 custody ledger line {index}')
            if row.get('entry_kind') is not None:
                typed_tail = True  # specialist products have their own audit scope and namespaces
                continue
            sid = row['work_item_id']
            require(not typed_tail and sid in expected and positions[sid] > previous,
                    'M3 custody row has duplicate, unknown or out-of-order decision')
            previous = positions[sid]
            seen.add(sid)
            item = expected[sid]
            require(all(row[k] == item[k] for k in ('dataset_id', 'selection', 'route', 'operation', 'applicability')),
                    'M3 custody decision coordinates differ')
            route = (item['selection'], item['route'])
            found = dict()
            for path, ref in _references(row['evidence']):
                section = path.split('/')[0]
                require((section == 'retained' and path.split('/')[1] == sid) or
                        (section == 'fixed-batch-samples' and path == f"{section}/{ref['sha256']}.bmk"),
                        'M3 retained object not in its frozen decision namespace')
                require(ref == refs.setdefault(path, ref), 'M3 retained corpus object has conflicting identities')
                found[path] = ref
            c = route_counts[route]
            c['decisions_with_references'] += bool(found)
            c['reference_count_deduplicated_per_decision'] += len(found)
            c['referenced_bytes_deduplicated_per_decision'] += sum(r['bytes'] for r in found.values())
            if row['status'] == 'verified' and row['route'] in ROUTES:
                ev = row['evidence']
                sample, first = ev['retained_sample'], ev['units'][0]
                region, = item['input']['row_ranges']
                require(region['partition'] == 'full' and region['start'] == 0 and ev['lane'] == ROUTES[row['route']] and ev['driver'] == 'pcodec-pages-control/1' and
                        sample['column'] == first['column'] == 0 and
                        sample['row_range'] == first['row_range'] == [0, min(CHUNK_ROWS, region['end'])] and
                        (sample['bytes'], sample['sha256']) == (first['artifact_bytes'], first['artifact_sha256']) and
                        sample['path'] in found, 'M3 pcodec page sample differs from frozen first unit')
                page_cases.append((item, ev['lane'], sample, first))
    require(seen and (not full or seen == expected.keys()), 'M3 retained corpus decision coverage differs')
    actual = _inventory(run)
    require(actual == refs.keys(), 'M3 retained corpus inventory differs: ' +
            f'{len(refs.keys() - actual)} missing, {len(actual - refs.keys())} unreferenced')
    for ref in refs.values():
        _known_file(run, ref)
    return seen, refs, page_cases, route_counts


def _first_column(root, entry, n):
    # Validate the whole original before deliberately taking only its first column slice.
    _known_file(root, entry['file'])
    remaining, chunks = n, []
    for batch in read_batches(root, entry):
        size = min(remaining, batch.rows)
        matrix = np.frombuffer(batch.values, dtype='V8').reshape(batch.rows, entry['value_count'])
        chunks.append(matrix[:size, 0].tobytes())
        remaining -= size
        if remaining == 0:
            break
    require(remaining == 0, 'M3 pcodec canonical source does not cover retained unit')
    return b''.join(chunks)


def _replay_pages(root, plan, run, samples):
    if not samples:
        return []
    b = plan['build']['pcodec_pages']
    for key in ('executable', 'dependency', 'adapter'):
        _known_file(root, b[key])
    runtime = plan_recovery(root, {}, (), tools={'pcodec-pages': {k: b['executable'][k] for k in ('path', 'sha256')}},
                            libraries=[b['dependency']])
    definition = load_json(_known_file(root, plan['definition']['plan']))
    entries = _entry_map(root, definition)
    canonical, sessions, replayed = {}, set(), []
    with TemporaryDirectory(prefix='tsbench-m3-pcodec-audit-') as temp:
        directory = Path(temp)
        stage_recovery(root, directory, runtime, directory='runtime')
        for i, (item, lane, sample, first) in enumerate(samples):
            ds, end = item['dataset_id'], sample['row_range'][1]
            if (ds, end) not in canonical:
                canonical[ds, end] = _first_column(root, entries[ds], end)
            expected_raw = canonical[ds, end]
            work = directory / f'page-{i:04d}'
            work.mkdir()
            path = _known_file(run, sample)
            out, result = invoke_isolated_tool(directory / 'runtime', runtime, 'pcodec-pages', LIMITS, work, work, 'decode',
                                                {'frame': path}, ['corpus-decode', lane, '/inputs/frame', '/out/f64'],
                                                lambda: False, bind_inputs=True)
            require(result['status'] == 'completed' and result['returncode'] == 0 and
                    result['session_id'] not in sessions and result['input_mounts'] == {'frame': {k: sample[k] for k in ('bytes', 'sha256')}} and
                    {p.name for p in out.iterdir()} == {'f64'} and (work / 'decode.stderr').stat().st_size == 0,
                    'M3 pcodec retained frame did not replay in a fresh files-only process')
            sessions.add(result['session_id'])
            observed = load_json(work / 'decode.stdout')
            restored = (out / 'f64').read_bytes()
            _verify_chunk(expected_raw, restored, sample['bytes'], first['encode'], observed)
            replayed.append({'work_item_id': item['work_item_id'], 'dataset_id': ds, 'route': item['route'],
                             'row_range': sample['row_range'], 'mounts': result['input_mounts'], 'frame': sample,
                             'decode_session': result['session_id'], 'restored_bytes': len(restored), 'restored_sha256': digest(out / 'f64')})
    return replayed


def audit(root, plan, run, *, replay_pages=False, allow_partial=False):
    run = run.resolve(strict=True)
    require(plan['plan_content_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}),
            'M3 custody plan identity differs')
    ledger, report, seal = (local_file(run, n) for n in ('ledger.jsonl', 'report.json', 'completion.json'))
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(report), 'ledger_sha256': digest(ledger)}
    require(load_json(seal) == {**body, 'seal_id': content_id(body)}, 'M3 custody source seal differs')
    seen, refs, pages, counts = _collect(plan, run, ledger, full=not allow_partial)
    replayed = _replay_pages(root, plan, run, pages) if replay_pages else []
    return {'schema': SCHEMA, 'run_id': run.name, 'plan_content_id': body['plan_content_id'], 'source_seal_id': content_id(body),
            'all_corpus_decisions_present': len(seen) == len(plan['work_items']), 'corpus_decision_count': len(seen),
            'scope': 'retained_corpus_artifact_hash_and_size_excludes_specialist_products_and_unretained_artifacts',
            'physical_retained_files': len(refs), 'physical_retained_bytes': sum(r['bytes'] for r in refs.values()),
            'physical_inventory': [r for _, r in sorted(refs.items())],
            'routes': [{'selection': s, 'route': r, **c} for (s, r), c in sorted(counts.items())],
            'page_samples_eligible_for_replay': len(pages), 'page_replay_requested': replay_pages,
            'isolated_page_replays': replayed, 'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}
