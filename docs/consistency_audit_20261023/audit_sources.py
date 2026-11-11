"""Read-only source identity audit; run from any working directory."""
from pathlib import Path
from collections import Counter
import hashlib
import json

BENCH = Path(__file__).resolve().parents[2]
REWRITE = BENCH.parent / 'Compression_Rewrite'
OUTPUT = Path(__file__).resolve().parent

def sha(path):
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def rows_from_lock(path):
    d = json.loads(path.read_text())
    for field in ('packages', 'algorithms'):
        if field in d:
            for key, package in d[field].items():
                for row in package['files']:
                    yield key, row, d
            return
    for row in d['files']:
        yield path.parent.name, row, d

def current_path(group, row, lock):
    for field in ('original', 'member', 'release_member', 'archive_member'):
        member = row.get(field, '')
        for prefix in ('ReWrite/', 'Source/'):
            at = member.find(prefix)
            if at >= 0:
                return REWRITE / member[at:]
    if row.get('standalone_path') and lock.get('standalone_root'):
        return Path(lock['standalone_root']) / row['standalone_path']
    vendor_prefix = f'adapters/{group}/vendor/'
    if row['path'].startswith(vendor_prefix):
        rest = row['path'][len(vendor_prefix):].split('/', 1)
        if group == 'sprintz_family' and len(rest) == 2:
            if rest[1].startswith('reference-source/'):
                return REWRITE / 'Source/sprintz-family' / rest[1][len('reference-source/'):]
            return REWRITE / 'ReWrite/sprintz-family' / rest[1]
    if group in ('elf', 'elf-plus', 'elf-star', 'self-star'):
        prefix = f'adapters/rewrite_lossless/vendor/{group}/'
        if row['path'].startswith(prefix):
            return REWRITE / 'ReWrite' / group / row['path'][len(prefix):]
    return None

def main():
    records = []
    releases = []
    for lock in sorted((BENCH / 'adapters').glob('*/FROZEN*.json')):
        for group, row, data in rows_from_lock(lock):
            local = BENCH / row['path']
            current = current_path(group, row, data)
            actual = sha(local)
            other = sha(current) if current is not None else None
            records.append(dict(group=group, path=row['path'], expected=row['sha256'],
                                bench_sha256=actual, frozen_ok=actual == row['sha256'],
                                current_path=str(current) if current else None,
                                current_sha256=other,
                                comparison=('unmapped' if current is None else 'missing' if other is None
                                            else 'equal' if other == actual else 'different')))
        data = json.loads(lock.read_text())
        archive = data.get('release_archive', data.get('release'))
        if lock.parent.name == 'cameo_family':
            archive = REWRITE / 'Release/cameo-family/cameo-family-full-parity-20261021.tar.gz'
        if archive:
            archive = Path(archive)
            if not archive.is_absolute():
                archive = REWRITE / 'Release' / archive
            actual = sha(archive)
            releases.append(dict(lock=str(lock.relative_to(BENCH)), path=str(archive),
                                 actual=actual, expected=data.get('release_sha256'),
                                 ok=actual is not None and actual == data.get('release_sha256')))

    inventory = []
    for p in sorted((BENCH / 'registry/codecs').glob('*.json')):
        d = json.loads(p.read_text())
        inventory.append(dict(key=d['key'], identity=d['identity'],
                              adapter=d.get('adapter'), input=d.get('input'),
                              quality=d.get('quality'), execution=d.get('execution'),
                              admission=d.get('admission'), status=d.get('status')))
    native = []
    mappings = {'brotli_stream': 'lz/brotli', 'bzip2_stream': 'bwt/bzip2',
                'deflate_zlib': 'lz/zlib', 'lz4_frame': 'lz/lz4',
                'lzsse2_raw': 'lz/lzsse', 'lzsse8_raw': 'lz/lzsse',
                'snappy_raw': 'lz/snappy', 'xz_stream': 'lz/xz', 'zstd_frame': 'lz/zstd'}
    lz = REWRITE / 'ReWrite/lzbench'
    for adapter, subdir in mappings.items():
        vendor = BENCH / 'adapters' / adapter / 'vendor'
        for package in sorted(vendor.iterdir()):
            if not package.is_dir():
                continue
            for file in sorted(package.rglob('*')):
                if file.is_file():
                    rel = file.relative_to(package)
                    target = lz / subdir / rel
                    a, b = sha(file), sha(target)
                    native.append(dict(group=adapter, path=str(file.relative_to(BENCH)),
                                       current_path=str(target), bench_sha256=a, current_sha256=b,
                                       comparison='missing' if b is None else 'equal' if a == b else 'different'))
    summary = {}
    for group in sorted({r['group'] for r in records}):
        rows = [r for r in records if r['group'] == group]
        summary[group] = dict(total=len(rows), frozen_ok=sum(r['frozen_ok'] for r in rows),
                              comparisons=dict(Counter(r['comparison'] for r in rows)))
    source_checks = []
    for name in ('alp-cwida', 'abba', 'fabba', 'qabba', 'chimp-family',
                 'elf-family', 'elf-original', 'gorilla-prometheus-xor', 'sprintz-family'):
        source = REWRITE / 'Source' / name
        manifests = [source / n for n in ('SOURCE_MANIFEST.json', 'SOURCE_MANIFEST.yaml', 'SOURCE_LOCK.json')]
        manifest = next(p for p in manifests if p.is_file())
        data = json.loads(manifest.read_text())
        entries = data['files']
        if isinstance(entries, dict):
            entries = [dict(path=k, sha256=v) for k, v in entries.items()]
        for row in entries:
            target = source / ('' if name == 'sprintz-family' else 'upstream') / row['path']
            actual = sha(target)
            source_checks.append(dict(group=name, path=str(target), expected=row['sha256'],
                                      actual=actual, ok=actual == row['sha256']))
    source = REWRITE / 'Source/cameo-family'
    data = json.loads((source / 'SOURCE_MANIFEST.json').read_text())
    for repo in data['repositories']:
        for row in repo['files']:
            target = source / 'upstream' / repo['id'] / row['path']
            actual = sha(target)
            source_checks.append(dict(group='cameo-family:' + repo['id'], path=str(target),
                                      expected=row['sha256'], actual=actual, ok=actual == row['sha256']))
    originals = BENCH.parent / 'Compression_Source_Code/Source_Code/_repos'
    source_roots = {
        'alp-cwida': originals / 'cwida_ALP',
        'abba': originals / 'nla-group_ABBA_web_20261020',
        'fabba': originals / 'nla-group_fABBA_web_20261020',
        'qabba': originals / 'inEXASCALE_qabba',
        'chimp-family': originals / 'panagiotisl_chimp',
        'elf-family': originals / 'Spatio-Temporal-Lab_SElfStar',
        'elf-original': originals / 'Spatio-Temporal-Lab_elf',
        'gorilla-prometheus-xor': originals / 'prometheus_prometheus',
        'cameo-family:cameo': BENCH.parent / '材料/New_Source_Code/cameo-reproducibility/edbt2026-CAMEO',
        'cameo-family:tersets': originals / 'cmcuza_TerseTS',
    }
    for row in source_checks:
        group = row['group']
        local = Path(row['path'])
        if group == 'sprintz-family':
            rel = local.relative_to(REWRITE / 'Source/sprintz-family/upstream')
            target = originals / 'dblalock_sprintz' / rel
            if str(rel).startswith('core/'):
                target = originals / 'dblalock_sprintz/cpp/Compress' / str(rel)[len('core/'):]
            if str(rel).startswith('lzbench/'):
                target = originals / 'sprintz-lzbench' / str(rel)[len('lzbench/'):]
        else:
            prefix = REWRITE / 'Source' / group / 'upstream'
            if group.startswith('cameo-family:'):
                prefix = REWRITE / 'Source/cameo-family/upstream' / group.split(':')[1]
            target = source_roots[group] / local.relative_to(prefix)
            if group == 'cameo-family:cameo' and local.name == 'LICENSE':
                target = source_roots[group].parent / 'LICENSE'
        row['upstream_path'] = str(target)
        row['upstream_sha256'] = sha(target)
        row['upstream_ok'] = row['upstream_sha256'] == row['expected']
    native_direct = []
    direct_mappings = {
        'fse+huff0': ('adapters/entropy_fse/vendor/lib', 'Cyan4973_FiniteStateEntropy/lib'),
        'neats+leats': ('adapters/neats/vendor/neats', 'and-gue_NeaTS'),
        'serf-qt+xor': ('adapters/serf/vendor/serf', 'Spatio-Temporal-Lab_Serf'),
        'simdcomp': ('adapters/simdcomp/vendor/simdcomp', 'lemire_simdcomp'),
        'zfp': ('adapters/zfp/vendor/zfp', 'LLNL_zfp'),
        'cuszp': ('adapters/cuszp/vendor/cuszp', 'szcompressor_cuSZp'),
    }
    for group, (vendor, upstream) in direct_mappings.items():
        for file in sorted((BENCH / vendor).rglob('*')):
            if not file.is_file():
                continue
            target = originals / upstream / file.relative_to(BENCH / vendor)
            a, b = sha(file), sha(target)
            native_direct.append(dict(group=group, path=str(file.relative_to(BENCH)),
                                      upstream=str(target), bench_sha256=a, upstream_sha256=b,
                                      comparison='missing' if b is None else 'equal' if a == b else 'different'))
    lz_original = []
    for row in native:
        target = originals / 'inikep_lzbench' / Path(row['current_path']).relative_to(lz)
        actual = sha(target)
        lz_original.append(dict(path=str(target), expected=row['current_sha256'], actual=actual,
                                ok=actual is not None and actual == row['current_sha256']))
    evidence_checks = []
    def check_evidence(group, base, path, expected):
        target = base / path
        actual = sha(target)
        evidence_checks.append(dict(group=group, path=str(target), expected=expected,
                                    actual=actual, ok=actual == expected))
    base = REWRITE / 'ReWrite/abba-family/validation'
    for row in json.loads((base / 'qualification-summary.json').read_text())['evidence']:
        check_evidence('abba', base, row['file'], row['sha256'])
    base = REWRITE / 'ReWrite/cameo-family'
    for row in json.loads((base / 'validation/final_qualification.json').read_text())['evidence']:
        check_evidence('cameo', base, row['path'], row['sha256'])
    base = REWRITE / 'ReWrite/sprintz-family'
    for row in json.loads((base / 'docs/EVIDENCE_INDEX.json').read_text()):
        check_evidence('sprintz', base, row['path'], row['sha256'])
    base = REWRITE / 'ReWrite/alp-cwida'
    for gate in json.loads((base / 'reports/QUALIFICATION.json').read_text())['gates']:
        for path, expected in gate['evidence'].items():
            check_evidence('alp', base, path, expected)
    result = dict(scope='Current filesystem hashes; no equivalence inferred from roundtrip alone',
                  locks=summary, releases=releases, registry=inventory, files=records,
                  original_source_checks=source_checks,
                  original_source_summary={g:dict(total=sum(r['group']==g for r in source_checks),
                                                 ok=sum(r['group']==g and r['ok'] for r in source_checks),
                                                 upstream_ok=sum(r['group']==g and r['upstream_ok'] for r in source_checks))
                                           for g in sorted({r['group'] for r in source_checks})},
                  native_direct_files=native_direct,
                  native_direct_summary={g:dict(Counter(r['comparison'] for r in native_direct if r['group']==g))
                                         for g in direct_mappings},
                  lzbench_vs_original=lz_original,
                  qualification_evidence=evidence_checks,
                  qualification_evidence_summary={g:dict(total=sum(r['group']==g for r in evidence_checks),
                                                        ok=sum(r['group']==g and r['ok'] for r in evidence_checks))
                                                  for g in ('abba', 'cameo', 'sprintz', 'alp')},
                  lzbench_summary={g: dict(Counter(r['comparison'] for r in native if r['group'] == g))
                                   for g in mappings}, lzbench_files=native)
    (OUTPUT / 'source_identity.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('locks', 'releases', 'lzbench_summary', 'original_source_summary', 'native_direct_summary', 'qualification_evidence_summary')}, indent=2))

if __name__ == '__main__':
    main()
