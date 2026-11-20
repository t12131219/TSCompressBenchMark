#!/usr/bin/env python3
"""Reconcile direct retained-corpus replay evidence against one full M3 seal."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_full_custody import _collect
from tsbench.application.m3_sealed_ledger import full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, parse_json, require
from tsbench.recovery import check_recovery

CUSTODY = 'bmk.m3-corpus-retention-audit/1'
FIXED = 'bmk.m3-fixed-batch-retention-audit/1'
TITCHY = 'bmk.m3-titchy-full-corpus-replay/1'
ZFP = 'bmk.m3-zfp-full-ledger-audit/1'
ZFP_ISOLATED = 'bmk.m3-zfp-full-ledger-audit/2'
ZFP_SCOPE = 'one_new_bubblewrap_network_namespace_per_retained_frame_no_native_timing'
PBEPLA = 'bmk.m3-pbepla-full-ledger-audit/1'
GORILLA = 'bmk.m3-gorilla-full-ledger-audit/1'
SELFSTAR = 'bmk.m3-selfstar-full-ledger-audit/1'
SPRINTZ = 'bmk.m3-sprintz-full-ledger-audit/1'
HUFF0 = 'bmk.m3-huff0-full-ledger-audit/1'
LZBENCH = 'bmk.m3-lzbench-full-ledger-audit/1'
FLAGS = ('timing_admitted', 'qualification_granted', 'stage_accepted')


def _bound(doc, run_id, plan_id, seal_id):
    schema = doc['schema']
    plan_key, seal_key = {
        CUSTODY: ('plan_content_id', 'source_seal_id'),
        FIXED: ('plan_content_id', 'seal_id'),
        TITCHY: ('plan_content_id', 'run_seal_id'),
        ZFP: ('plan_id', 'run_seal_id'), ZFP_ISOLATED: ('plan_id', 'run_seal_id'), PBEPLA: ('plan_id', 'run_seal_id'),
        GORILLA: ('plan_id', 'run_seal_id'), SELFSTAR: ('plan_id', 'run_seal_id'), SPRINTZ: ('plan_id', 'run_seal_id'),
        LZBENCH: ('plan_id', 'run_seal_id'), HUFF0: ('plan_id', 'run_seal_id'),
    }.get(schema, (None, None))
    require(plan_key is not None, 'unsupported direct M3 replay evidence schema')
    require(doc['run_id'] == run_id and doc[plan_key] == plan_id and doc[seal_key] == seal_id and
            all(doc.get(flag) is False for flag in FLAGS), 'M3 replay source is foreign or claims admission')
    if schema not in (CUSTODY, FIXED):
        require(doc['audit_id'] == content_id({k: v for k, v in doc.items() if k != 'audit_id'}),
                'M3 replay audit content identity differs')
    return schema


def _zfp_isolated(doc, binding):
    require(binding is not None and doc['corpus_replay_scope'] == ZFP_SCOPE,
            'ZFP archive-only network replay scope or frozen build is missing')
    runtime = doc['corpus_replay_runtime']
    exe = {k: binding['executable'][k] for k in ('path', 'sha256')}
    check_recovery(runtime, {}, (), tools={'zfp-corpus-reopen': exe}, libraries=[binding['dependency']])
    require(runtime['recovery_id'] == doc['corpus_replay_runtime_id'] and
            doc['corpus_replay_launchers'] == binding['launchers'], 'ZFP replay runtime or launchers differ')
    frames, metadata, sessions = set(), set(), set()
    for sample in doc['replayed_samples']:
        parts = sample['sample']['parts']
        array = sample['route'] == 'fixed-rate-array'
        expected = {'before', 'after'} if array else {n for n in parts if n.endswith('.frame')}
        sidecars = {'metadata.json'} if array else {n.removesuffix('.frame') + '.metadata.json' for n in expected}
        require(expected and parts.keys() == expected | sidecars, 'ZFP isolated replay part closure differs')
        metadata.update(parts[n]['path'] for n in sidecars)
        opened = set()
        start, end = sample['sample']['row_range']
        for process in sample['processes']:
            name, sid = process['part'], process['session_id']
            require(name in expected and name not in opened and isinstance(sid, str) and sid and sid not in sessions,
                    'ZFP isolated replay session or frame coverage differs')
            ref = {k: parts[name][k] for k in ('bytes', 'sha256')}
            observed = process['observed']
            require(process['operation'] == ('array-reopen' if array else 'field-restore') and
                    process['input_mounts'] == {'frame': ref} and process['logs']['stderr']['bytes'] == 0 and
                    observed['rows'] == end - start > 0 and observed['frame_bytes'] == ref['bytes'] and
                    process['restored']['bytes'] == 8 * (end - start) and
                    (not array or (observed['requested_rate'], observed['effective_rate']) == (18, 32)),
                    'ZFP isolated replay mount, shape or aligned rate differs')
            frames.add(parts[name]['path'])
            opened.add(name)
            sessions.add(sid)
        require(opened == expected, 'ZFP isolated replay omitted a retained frame')
    require(len(sessions) == len(frames) == doc['isolated_corpus_processes'] and not frames & metadata,
            'ZFP archive-only replay frame population differs')
    return {'scope': ZFP_SCOPE, 'frame_only_processes': len(sessions), 'isolated_frames': len(frames),
            'validated_metadata_files_not_mounted': len(metadata)}


def _references(doc, schema):
    # Extract only decoder-consumed corpus objects; never walk arbitrary paths in
    # the report (e.g. specialists, fixtures, or newly encoded comparisons).
    if schema == CUSTODY:
        require(doc['all_corpus_decisions_present'] and doc['page_replay_requested'] and
                len(doc['isolated_page_replays']) == doc['page_samples_eligible_for_replay'],
                'M3 pcodec inventory is not a complete replay report')
        return [x['frame'] for x in doc['isolated_page_replays']]
    if schema == FIXED:
        full_projection = (doc['partial_preflight'] is None and
                           doc.get('source_projection') == 'complete_frozen_population_from_sealed_ledger')
        require(doc['replay_performed'] is True and (doc['partial_preflight'] is False or full_projection),
                'M3 fixed batch evidence is inventory-only or partial')
        return [x['artifact'] for x in doc['replayed']]
    if schema == TITCHY:
        return [r for x in doc['replayed_samples'] for r in x['parts'].values()]
    if schema in (ZFP, ZFP_ISOLATED):
        return [r for x in doc['replayed_samples'] for r in x['sample']['parts'].values()]
    if schema == PBEPLA:
        require(all(type(x['decoded']) is bool for x in doc['replayed_samples']), 'M3 PBEPLA replay terminal differs')
        return [r for x in doc['replayed_samples'] if x['decoded'] for r in x['sample']['parts']]
    if schema == GORILLA:
        return doc['independently_decoded_samples']
    if schema in (SELFSTAR, SPRINTZ):
        return [x['artifact'] for x in doc['replayed_samples']]
    if schema == HUFF0:
        return [r for x in doc['replayed_samples'] for r in x['references']]
    return doc['replayed_files']  # LZBENCH


def reconcile(root, run_id, plan_id, seal_id, inventory, proof_paths, *, zfp_binding=None):
    paths, seen_schemas, seen_paths = {}, set(), set()
    proofs = []
    for path in sorted(p.resolve(strict=True) for p in proof_paths):
        require(path.is_relative_to(root) and path not in seen_paths, 'duplicate or external M3 replay audit path')
        seen_paths.add(path)
        payload = path.read_bytes()
        doc = parse_json(payload, str(path))
        schema = _bound(doc, run_id, plan_id, seal_id)
        family = ZFP if schema == ZFP_ISOLATED else schema
        require(family not in seen_schemas, 'duplicate M3 replay evidence family')
        seen_schemas.add(family)
        raw = _references(doc, schema)
        extra = {'zfp_frame_isolation': _zfp_isolated(doc, zfp_binding)} if schema == ZFP_ISOLATED else {}
        consumed = set()
        for row in raw:
            part = row['path']
            require(part in inventory and all(inventory[part][k] == row[k] for k in ('bytes', 'sha256')),
                    'M3 replay refers to an unbound or changed retained corpus object')
            consumed.add(part)
        if schema == ZFP_ISOLATED:
            require(len(raw) == len(consumed) == extra['zfp_frame_isolation']['isolated_frames'] +
                    extra['zfp_frame_isolation']['validated_metadata_files_not_mounted'],
                    'ZFP isolated replay duplicated or omitted a retained identity')
        count_key = ('unique_retained_frames' if schema == FIXED else
                     'replayed_physical_files' if family in (ZFP, PBEPLA, GORILLA) else None)
        if count_key:
            require(len(consumed) == doc[count_key], 'M3 replay physical file count differs')
        require(not (consumed & paths.keys()), 'M3 replay coverage double counts a physical file across audits')
        paths.update({p: inventory[p] for p in consumed})
        proofs.append({'schema': schema, 'path': path.relative_to(root).as_posix(), 'sha256': sha256(payload).hexdigest(),
                       'replay_reference_count': len(raw), 'physical_file_count': len(consumed),
                       'physical_files': sorted(consumed), **extra})
    missing = sorted(inventory.keys() - paths.keys())
    return {'physical_files': len(inventory), 'physical_bytes': sum(r['bytes'] for r in inventory.values()),
            'replayed_physical_files': len(paths), 'replayed_physical_bytes': sum(r['bytes'] for r in paths.values()),
            'unreplayed_physical_files': len(missing), 'unreplayed_physical_paths': missing, 'proofs': proofs}


def audit(root, plan, run, proof_paths):
    ledger, seal_id = full_run_source(plan, run)
    # _collect requires every corpus decision in plan order and independently
    # checks file identities. Do not materialize the detailed sealed report.
    _, inventory, _, _ = _collect(plan, run, ledger, full=True)
    zfp = plan.get('build', {}).get('zfp_corpus')
    zfp_binding = {**zfp, 'launchers': plan['specialized']['zfp']['launchers']} if zfp is not None else None
    body = {'schema': 'bmk.m3-primary-retained-replay-coverage/1',
            'scope': 'reconciles_existing_direct_corpus_replay_reports_does_not_replay_or_award_qualification',
            'run_id': run.name, 'run_seal_id': seal_id, 'plan_content_id': plan['plan_content_id'],
            'excludes': ['specialist_products', 'measurement_anchors', 'released_frames', 'new_reference_artifacts'],
            **reconcile(root, run.name, plan['plan_content_id'], seal_id, inventory, proof_paths, zfp_binding=zfp_binding),
            **dict.fromkeys(FLAGS, False)}
    return {**body, 'coverage_id': content_id(body)}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--proof', type=Path, action='append', default=[])
    out = parser.add_mutually_exclusive_group(required=True)
    out.add_argument('--out', type=Path)
    out.add_argument('--verify', type=Path)
    args = parser.parse_args()
    try:
        result = audit(ROOT, load_json(args.plan), args.run.resolve(strict=True), args.proof)
        if args.verify:
            require(load_json(args.verify) == result, 'M3 retained replay coverage differs from recomputation')
        else:
            write_new(args.out, result)
        print(result['coverage_id'], result['replayed_physical_files'], '/', result['physical_files'])
    except (KeyError, OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
