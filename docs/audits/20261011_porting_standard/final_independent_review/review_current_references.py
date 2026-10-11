"""File-only current worklist-reference review without registry or codec execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
folder = ROOT / 'docs/audits/20261011_porting_standard/current_reference_refresh_r1'
report_path = folder / 'report.json'
report = json.loads(report_path.read_text())
before_path = ROOT / report['before']['path']
current_path = ROOT / report['current']['path']
before = json.loads(before_path.read_text())
current = json.loads(current_path.read_text())
errors = []
references = []

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check(condition, label):
    if not condition:
        errors.append(label)

for item in [report['before'], report['current'], *report['evidence']]:
    check(sha(ROOT / item['path']) == item['sha256'], 'reference SHA ' + item['path'])
    references.append(item)
inventory_path = ROOT / 'docs/audits/20261011_porting_standard/source_build_inventory_r1/inventory-final-r2.json'
inventory = json.loads(inventory_path.read_text())
identities = {row['codec_key']: (row['algorithm_id'], row['source_artifact_id'])
              for row in inventory['rows']}
reverted = deepcopy(current)
changes = []
check(len(current['entries']) == len(before['entries']), 'worklist entry universe unchanged')
for old_entry, new_entry, restored_entry in zip(before['entries'], current['entries'], reverted['entries']):
    check(old_entry['audit_index'] == new_entry['audit_index'], 'audit slot unchanged')
    old_candidates = old_entry.get('registered_candidates', [])
    new_candidates = new_entry.get('registered_candidates', [])
    restored_candidates = restored_entry.get('registered_candidates', [])
    check(len(old_candidates) == len(new_candidates), 'candidate universe unchanged')
    for old, new, restored in zip(old_candidates, new_candidates, restored_candidates):
        check(old['key'] == new['key'], 'candidate key unchanged')
        if old != new:
            key = new['key']
            check((new['algorithm_id'], new['source_artifact_id']) == identities[key],
                  'candidate identities match current scoped inventory')
            changes.append({'audit_index': new_entry['audit_index'], 'key': key,
                            'previous_algorithm_id': old['algorithm_id'],
                            'current_algorithm_id': new['algorithm_id'],
                            'previous_source_artifact_id': old['source_artifact_id'],
                            'current_source_artifact_id': new['source_artifact_id']})
            restored['algorithm_id'] = old['algorithm_id']
            restored['source_artifact_id'] = old['source_artifact_id']
check(current['registration_identity_refreshes'][:-1] == before['registration_identity_refreshes'],
      'prior refresh receipts unchanged')
reverted['registration_identity_refreshes'] = before['registration_identity_refreshes']
check(reverted == before, 'only candidate identity fields and appended refresh receipt changed')
receipt = current['registration_identity_refreshes'][-1]
check(changes == receipt['changes'] == report['changes'], 'actual changes match receipt and report')
check(len(changes) == report['updated_reference_count'] == 47
      and len({c['key'] for c in changes}) == report['unique_codec_count'] == 30,
      '47 references across 30 codec keys')
check(receipt['qualification_claims_changed'] is False
      and receipt['formal_granted'] is False and receipt['full_parity_granted'] is False,
      'no qualification/formal/parity claim changed')
check(receipt['review_evidence'] == report['evidence'], 'evidence references match')
result = {'status': 'PASS_CURRENT_REFERENCE_FILE_REVIEW' if not errors else 'FAIL',
          'scope': 'PURE_FILE_DIFFERENCE_REVIEW_NO_CODEC_OR_FACTORY_EXECUTION',
          'review_script_sha256': sha(Path(__file__)), 'updated_reference_count': len(changes),
          'unique_codec_count': len({c['key'] for c in changes}),
          'old_historical_fields_preserved': reverted == before,
          'qualification_claims_changed': False, 'full_parity_granted': False, 'formal_granted': False,
          'references': references + [{'path': str(report_path.relative_to(ROOT)),
                                        'sha256': sha(report_path)}], 'errors': errors}
(OUT / 'current_reference_file_review.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
raise SystemExit(1 if errors else 0)
