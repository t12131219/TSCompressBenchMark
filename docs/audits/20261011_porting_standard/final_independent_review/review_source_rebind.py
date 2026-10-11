"""Review current comparison source revisions from files, without planning or codec execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
proof_dir = ROOT / 'docs/audits/20261011_porting_standard/comparison_source_rebind_r2'
errors = []
cache = {}
references = 0

def check(condition, label):
    if not condition:
        errors.append(label)

def local(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path

def sha(path):
    path = path.resolve()
    if path not in cache:
        cache[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return cache[path]

def normalize(value):
    if isinstance(value, str):
        return unicodedata.normalize('NFC', value)
    if isinstance(value, dict):
        return {normalize(k): normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if value is None or type(value) in (int, bool):
        return value
    raise TypeError(type(value))

def canonical(value):
    return json.dumps(normalize(value), ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode()

def identity(domain, value):
    return 'v3:' + domain + ':sha256:' + hashlib.sha256(canonical(value)).hexdigest()

def method_identity(value):
    document = {'schema_version': 'tscb.method-definition.v1', **value}
    document.pop('name')
    return identity('method', document)

def verify(entry):
    global references
    references += 1
    check(sha(local(entry['path'])) == entry['sha256'], 'SHA ' + entry['path'])

def decisions(document):
    result = deepcopy(document)
    excluded = {'contract': ('revision',), 'config_map': ('contract_id',),
                'expected_matrix': ('contract_id', 'config_map_id'),
                'group': ('revision', 'contract_id', 'config_map_id', 'expected_matrix_id')}
    for section, keys in excluded.items():
        for key in keys:
            result[section].pop(key)
    for member in result['group']['members']:
        for key in ('source_artifact_id', 'source_closure_sha256', 'method_id'):
            member['implementation'].pop(key)
        member['method'].pop('name')
        member['shared_code_tags'] = ['SOURCE_ARTIFACT:BOUND' if tag.startswith('SOURCE_ARTIFACT:')
                                      else tag for tag in member['shared_code_tags']]
    for row in result['group']['method_equivalence']:
        row['evidence'] = ['SOURCE_ARTIFACT:BOUND' if tag.startswith('SOURCE_ARTIFACT:')
                           else tag for tag in row['evidence']]
    return result

inventory_path = ROOT / 'docs/audits/20261011_porting_standard/source_build_inventory_r1/inventory-final-r2.json'
inventory = json.loads(inventory_path.read_text())
rows_by_key = {row['codec_key']: row for row in inventory['rows']}
rows = []
for proof_path in sorted(proof_dir.glob('*-proof.json')):
    proof = json.loads(proof_path.read_text())
    for entry in [proof['base_bundle'], proof['output_bundle'], proof['driver'],
                  *proof['registration_snapshot']]:
        verify(entry)
    before = json.loads(local(proof['base_bundle']['path']).read_text())
    current = json.loads(local(proof['output_bundle']['path']).read_text())
    check(proof['status'] == 'PLANNED_SOURCE_REVISION_ONLY', 'plan-only status')
    check(all(proof[key] is False for key in ('qualification_transferred', 'formal_results_transferred',
                                            'full_parity_granted', 'historical_evidence_rewritten')),
          'no old qualification/formal transfer')
    check(current['contract']['revision'] != before['contract']['revision']
          and current['group']['revision'] != before['group']['revision'], 'new explicit revision')
    check(decisions(current) == decisions(before), 'non-source comparison decisions exactly preserved')
    check(hashlib.sha256(canonical(decisions(current))).hexdigest()
          == proof['non_source_decisions_sha256'], 'decision projection hash')
    check(identity('comparison-contract', before['contract']) == proof['old_contract_id']
          and identity('comparison-contract', current['contract']) == proof['current_contract_id'],
          'old and new contract identities')
    check(identity('group-spec', before['group']) == proof['old_group_id']
          and identity('group-spec', current['group']) == proof['current_group_id'], 'old and new group identities')
    check(identity('corpus-spec', before['corpus']) == identity('corpus-spec', current['corpus'])
          == proof['corpus_id_preserved'], 'corpus identity preserved')
    contract_id = identity('comparison-contract', current['contract'])
    configs_id = identity('method-config-map', current['config_map'])
    matrix_id = identity('expected-outcome-matrix', current['expected_matrix'])
    check(current['config_map']['contract_id'] == current['expected_matrix']['contract_id']
          == current['group']['contract_id'] == contract_id
          and current['expected_matrix']['config_map_id'] == current['group']['config_map_id'] == configs_id
          and current['group']['expected_matrix_id'] == matrix_id, 'new derived ID chain')
    check(len(before['group']['members']) == len(current['group']['members']) == len(proof['members']),
          'same member universe')
    name_changes = []
    source_tags = {}
    for old, new, observed in zip(before['group']['members'], current['group']['members'], proof['members']):
        key = new['codec_key']
        codec_path = ROOT / 'registry/codecs' / (key + '.json')
        codec = json.loads(codec_path.read_text())
        sha(codec_path)
        inventory_row = rows_by_key[key]
        check(key == old['codec_key'] == observed['codec_key'], 'member key preserved')
        check(new['implementation']['source_artifact_id'] == codec['identity']['source_artifact_id']
              == inventory_row['source_artifact_id'] == observed['current_source_artifact_id'],
              'source identity bound to current registration')
        check(observed['old_source_artifact_id'] == old['implementation']['source_artifact_id']
              and observed['old_source_closure_sha256'] == old['implementation']['source_closure_sha256']
              and observed['old_method_name'] == old['method']['name']
              and observed['current_method_name'] == new['method']['name']
              and observed['member_id'] == old['member_id'] == new['member_id']
              and observed['method_semantic_definition_preserved'] is True,
              'proof accurately records old and new member fields')
        source_tags['SOURCE_ARTIFACT:' + old['implementation']['source_artifact_id']] = (
            'SOURCE_ARTIFACT:' + new['implementation']['source_artifact_id'])
        closure = inventory_row['source_inventory']['identity'].get(
            'source_closure_sha256', inventory_row['source_artifact_id'].rsplit(':', 1)[-1])
        check(new['implementation']['source_closure_sha256'] == closure
              == observed['current_source_closure_sha256'], 'source closure matches registration protocol')
        expected_method = {'name': codec['identity']['display_name'], 'mechanism': codec['identity']['family'],
                           'variant': key, 'semantic_version': '1', 'definition_sha256': hashlib.sha256(
                               canonical({field: codec[field] for field in
                                          ('classification', 'semantics', 'input', 'lifecycle')})).hexdigest()}
        check(new['method'] == expected_method, 'new method metadata binds actual registered semantics')
        check({k: v for k, v in old['method'].items() if k != 'name'}
              == {k: v for k, v in new['method'].items() if k != 'name'}, 'method semantic definition unchanged')
        check(method_identity(old['method']) == old['implementation']['method_id'] == observed['old_method_id']
              == method_identity(new['method']) == new['implementation']['method_id']
              == observed['current_method_id'], 'MethodID preserved across source/display revision')
        check(observed['algorithm_id'] == inventory_row['algorithm_id'], 'proof current algorithm identity')
        check([tag for tag in new['shared_code_tags'] if tag.startswith('SOURCE_ARTIFACT:')]
              == ['SOURCE_ARTIFACT:' + inventory_row['source_artifact_id']], 'exact current shared source tag')
        if old['method']['name'] != new['method']['name']:
            name_changes.append({'codec': key, 'old': old['method']['name'], 'new': new['method']['name'],
                                 'method_id_preserved': True})
    for old, new in zip(before['group']['method_equivalence'], current['group']['method_equivalence']):
        check(new['evidence'] == [source_tags.get(tag, tag) for tag in old['evidence']],
              'equivalence evidence source tags exactly rebound')
    rows.append({'proof': str(proof_path.relative_to(ROOT)), 'sha256': sha(proof_path),
                 'bundle': proof['output_bundle'], 'members': len(proof['members']),
                 'name_changes': name_changes, 'planned_denominators': proof['planned_denominators']})
check(len(rows) == 4, 'four current source-rebound plans')
sha(inventory_path)
script_sha256 = sha(Path(__file__))
result = {'status': 'PASS_SOURCE_REBIND_FILE_REVIEW' if not errors else 'FAIL',
          'scope': 'PURE_FILE_REVIEW_NO_GROUP_PLAN_CODEC_PILOT_OR_FORMAL_EXECUTION',
          'review_script_sha256': script_sha256, 'hash_reference_count': references,
          'unique_files_hashed': len(cache), 'rows': rows, 'errors': errors,
          'new_plan_only': True, 'qualification_transferred': False,
          'formal_results_transferred': False, 'full_parity_granted': False}
(OUT / 'source_rebind_file_review.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
raise SystemExit(1 if errors else 0)
