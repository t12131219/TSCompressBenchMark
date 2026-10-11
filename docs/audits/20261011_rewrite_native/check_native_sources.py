"""Read-only comparison of current native vendored closures and local authority."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path('/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos')
SPECS = {
    'alp': ('cwida_ALP', '.', 'alp'),
    'brotli_stream': ('inikep_lzbench', 'lz/brotli', 'brotli'),
    'bzip2_stream': ('inikep_lzbench', 'bwt/bzip2', 'bzip2'),
    'deflate_zlib': ('inikep_lzbench', 'lz/zlib', 'zlib'),
    'entropy_fse': ('Cyan4973_FiniteStateEntropy', '.', '.'),
    'lz4_frame': ('inikep_lzbench', 'lz/lz4', 'lz4'),
    'lzss_raw': ('alexkazik_lzss', 'lzss', 'lzss'),
    'lzsse2_raw': ('inikep_lzbench', 'lz/lzsse', 'lzsse'),
    'lzsse8_raw': ('inikep_lzbench', 'lz/lzsse', 'lzsse'),
    'neats': ('and-gue_NeaTS', '.', 'neats'),
    'serf': ('Spatio-Temporal-Lab_Serf', '.', 'serf'),
    'simdcomp': ('lemire_simdcomp', '.', 'simdcomp'),
    'snappy_raw': ('inikep_lzbench', 'lz/snappy', 'snappy'),
    'sprintz': ('sprintz-lzbench', 'sprintz', 'sprintz'),
    'xz_stream': ('inikep_lzbench', 'lz/xz', 'xz'),
    'zfp': ('LLNL_zfp', '.', 'zfp'),
    'zstd_frame': ('inikep_lzbench', 'lz/zstd', 'zstd'),
}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(repo, *args):
    proc = subprocess.run(['git', '-C', str(repo), *args], text=True, capture_output=True)
    return {'returncode': proc.returncode, 'output': proc.stdout.strip(), 'error': proc.stderr.strip()}

def main():
    report = {'scope': 'current native original vendor only; generated patches are separate', 'groups': {}}
    for adapter, (repo_name, subpath, vendor_dir) in SPECS.items():
        repo = SOURCE / repo_name
        authority = repo / subpath
        vendor = ROOT / 'adapters' / adapter / 'vendor'
        entries = []
        for file in sorted(p for p in vendor.rglob('*') if p.is_file()):
            relative = file.relative_to(vendor)
            local = file.relative_to(vendor / vendor_dir) if vendor_dir != '.' and file.is_relative_to(vendor / vendor_dir) else relative
            mapped = authority / local
            if file.name == 'README.upstream.md':
                mapped = repo / 'README.md'
            if file == vendor / 'LICENSE':
                mapped = (SOURCE / 'dblalock_sprintz' / 'LICENSE') if adapter == 'sprintz' else repo / 'LICENSE'
            # ALP copies its generated scalar FastLanes files from the original
            # FastLanes subtree; determine an exact path by byte equality.
            if not mapped.is_file() or sha(mapped) != sha(file):
                alternatives = [p for p in repo.rglob(file.name) if p.is_file() and '.git' not in p.parts]
                exact = [p for p in alternatives if sha(p) == sha(file)]
                if exact:
                    mapped = sorted(exact)[0]
            status = 'BYTE_IDENTICAL' if mapped.is_file() and sha(mapped) == sha(file) else 'MISSING_AUTHORITY' if not mapped.is_file() else 'DIFFERENT'
            entries.append({'path':str(file.relative_to(ROOT)), 'upstream':str(mapped), 'sha256':sha(file), 'upstream_sha256':sha(mapped) if mapped.is_file() else None, 'status':status})
        report['groups'][adapter] = {
            'repository':str(repo), 'commit':git(repo, 'rev-parse', 'HEAD'),
            'git_status':git(repo, 'status', '--short'), 'file_count':len(entries),
            'byte_identical':sum(x['status']=='BYTE_IDENTICAL' for x in entries),
            'unmatched':[x for x in entries if x['status']!='BYTE_IDENTICAL'], 'files':entries,
        }
    vendor = ROOT / 'adapters/lzss_dipperstein/vendor/lzss'
    report['groups']['lzss_dipperstein'] = {
        'status':'LOCAL_SOURCE_CODE_AUTHORITY_NOT_FOUND',
        'file_count':sum(p.is_file() for p in vendor.rglob('*')),
        'files':[{'path':str(p.relative_to(ROOT)), 'sha256':sha(p)} for p in sorted(vendor.rglob('*')) if p.is_file()],
        'limitation':'Neither MichaelDipperstein/lzss nor bitfile is present in the requested Source_Code corpus; compare against retained acquisition provenance separately.',
    }
    output = Path(__file__).with_name('native_source_comparison.json')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for name, item in report['groups'].items():
        print(name, item.get('byte_identical'), '/', item['file_count'], item.get('unmatched',item.get('status')))

if __name__=='__main__':
    main()
