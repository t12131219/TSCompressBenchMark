"""Apply the recorded size rule, after verifying a recoverable source archive.

Run from any directory with --apply. Without --apply, only print the plan.
"""
from pathlib import Path
import argparse
import csv
from datetime import datetime
import hashlib
import json
import tarfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / 'forecasting_transpose'
INVENTORY = ROOT / 'benchmark/experiments/forecasting-20261018-1614/inventory.json'
RESULTS = ROOT / 'docs/forecasting_results_20261018_1614/primary.csv'
ARCHIVE = OUT / 'removed_csv.tar.gz'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    rows = json.loads(INVENTORY.read_text())['files']
    paths = {p.name: p for p in SOURCE.glob('*.csv')}
    expected = {Path(row['source']).name for row in rows}
    if set(paths) != expected or len(expected) != len(rows):
        raise RuntimeError('Source files differ from the complete frozen inventory; no files removed')
    for row in rows:
        path = paths[Path(row['source']).name]
        if row['status'] != 'ok' or path.is_symlink():
            raise RuntimeError(f'Unverified source: {path}')
        if path.stat().st_size != row['source_bytes'] or digest(path) != row['source_sha256']:
            raise RuntimeError(f'Source changed: {path}; no files removed')
    records = []
    for row in rows:
        reasons = []
        if row['shape'][0] < 128:
            reasons.append('rows_lt_128')
        if row['raw_bytes'] < 1024:
            reasons.append('f64_value_bytes_lt_1024')
        records.append({
            'filename': Path(row['source']).name,
            'family': row['id'].split('_dataset')[0],
            'rows': row['shape'][0],
            'value_columns': len(row['columns']),
            'f64_value_bytes': row['raw_bytes'],
            'csv_bytes': row['source_bytes'],
            'sha256': row['source_sha256'],
            'decision': 'remove' if reasons else 'keep',
            'reason': '|'.join(reasons),
        })
    removed = [r for r in records if r['decision'] == 'remove']
    kept = [r for r in records if r['decision'] == 'keep']
    print(json.dumps({'before': len(records), 'remove': len(removed), 'keep': len(kept),
                      'removed_csv_bytes': sum(r['csv_bytes'] for r in removed)}), flush=True)
    if not args.apply:
        return
    if ARCHIVE.exists() or (OUT / 'manifest.json').exists():
        raise FileExistsError('Archive or manifest already exists; refusing overwrite')
    # No source file is removed until every archived member has been hashed.
    with tarfile.open(ARCHIVE, 'w:gz') as archive:
        for r in removed:
            archive.add(paths[r['filename']], arcname='forecasting_transpose/' + r['filename'])
    with tarfile.open(ARCHIVE, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) != len(removed) or not all(m.isfile() for m in members):
            raise RuntimeError('Archive member count/type mismatch')
        by_name = {m.name: m for m in members}
        for r in removed:
            member = by_name['forecasting_transpose/' + r['filename']]
            with archive.extractfile(member) as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != r['sha256']:
                raise RuntimeError(f'Archive verification failed: {r["filename"]}')
    for name, items in [('removed.csv', removed), ('retained.csv', kept)]:
        with (OUT / name).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(items)
    manifest = {
        'created_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'rule': {'remove_if': 'rows < 128 OR f64_value_bytes < 1024',
                 'value_bytes_exclude': ['date column', 'CSV text formatting']},
        'source_root': str(SOURCE),
        'inventory': {'path': str(INVENTORY), 'sha256': digest(INVENTORY)},
        'reference_results': {'path': str(RESULTS), 'sha256': digest(RESULTS)},
        'archive': {'path': str(ARCHIVE), 'sha256': digest(ARCHIVE),
                    'member_count': len(removed), 'all_member_hashes_verified': True},
        'before_count': len(records), 'removed_count': len(removed), 'retained_count': len(kept),
        'removed_csv_bytes': sum(r['csv_bytes'] for r in removed),
        'retained_csv_bytes': sum(r['csv_bytes'] for r in kept),
        'status': 'archive_verified_before_removal',
    }
    manifest_path = OUT / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    for r in removed:
        path = paths[r['filename']]
        if digest(path) != r['sha256']:
            raise RuntimeError(f'Source changed before removal: {path}')
        path.unlink()
    remaining = {p.name: p for p in SOURCE.glob('*.csv')}
    if set(remaining) != {r['filename'] for r in kept}:
        raise RuntimeError('Remaining file set differs from retained manifest')
    for r in kept:
        if digest(remaining[r['filename']]) != r['sha256']:
            raise RuntimeError(f'Retained source changed: {r["filename"]}')
    manifest['status'] = 'complete'
    manifest['all_retained_hashes_verified'] = True
    manifest['removed_files_absent'] = all(not (SOURCE / r['filename']).exists() for r in removed)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('Archive and retained source hashes verified; removal complete.', flush=True)


if __name__ == '__main__':
    main()
