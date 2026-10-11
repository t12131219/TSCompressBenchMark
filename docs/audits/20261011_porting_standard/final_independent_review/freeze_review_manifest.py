"""Freeze independent review files while verifying the immutable before bundle."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent

def entry(path):
    return {'path': str(path.relative_to(ROOT)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

before = json.loads((OUT / 'before-manifest.json').read_text())
drift = [item['path'] for item in before['files']
         if entry(ROOT / item['path'])['sha256'] != item['sha256']]
if drift:
    raise ValueError('Immutable before evidence drift: ' + str(drift))
files = [p for p in sorted(OUT.rglob('*')) if p.is_file()
         and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')
         and p.name not in ('fixed-manifest.json', 'final-manifest.json')]
fixed = [p for p in files if not p.is_relative_to(OUT / 'before')
         and p.name != 'before-manifest.json']
for name, selected, scope in [
    ('fixed-manifest.json', fixed, 'FIXED_SCOPED_COUNTEREXAMPLES_AND_READONLY_FINAL_RECEIPTS'),
    ('final-manifest.json', files, 'INDEPENDENT_REVIEW_BUNDLE_BYTES_ONLY_NO_FORMAL_OR_FULL_PARITY'),
]:
    manifest = {'schema_version': 'tscb.independent-review-files.v1', 'scope': scope,
                'immutable_before_file_count': len(before['files']),
                'immutable_before_hash_drift': [], 'file_count': len(selected),
                'files': [entry(p) for p in selected]}
    (OUT / name).write_text(json.dumps(manifest, indent=2) + '\n')
    print(name, len(selected), hashlib.sha256((OUT / name).read_bytes()).hexdigest())
