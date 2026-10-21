"""Package the qualified closure, verify every member, then rebuild the archive.

No build caches, original clone directories or installed Python environments are
distributed. Root-level build exclusions deliberately preserve xz/build-aux.
The external audit binds the archive digest without creating a self-reference.
"""
from pathlib import Path, PurePosixPath
import argparse
import gzip
import hashlib
import io
import json
import os
import posixpath
import subprocess
import tarfile

P = Path(__file__).resolve().parents[1]
R = P.parents[1]
ROOT = "Compression_Rewrite"
NAME = "abba-family-20261020-v1"
EPOCH = 1789776000


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def files():
    for area, names in [('Source', ['abba', 'fabba', 'qabba', 'abba-family-dependencies']),
                        ('ReWrite', ['abba', 'fabba', 'qabba', 'abba-family'])]:
        for name in names:
            base = R / area / name
            for path in sorted(base.rglob('*')):
                rel = path.relative_to(base)
                if any(n in ('__pycache__', '.git', 'core') or n.startswith('core.') for n in rel.parts):
                    continue
                if path.suffix == '.pyc':
                    continue
                if area == 'ReWrite' and name == 'abba-family' and (
                    rel.parts[0] in ('build', 'oracle-runtime', 'install') or rel.parts[0].startswith('build-')
                ):
                    continue
                if path.is_symlink() or path.is_file():
                    yield path


def record(path):
    rel = path.relative_to(R).as_posix()
    if path.is_symlink():
        target = os.readlink(path)
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(rel), target))
        assert not target.startswith('/') and not resolved.startswith('../'), (rel, target)
        return {'path': rel, 'type': 'symlink', 'target': target}
    return {'path': rel, 'type': 'file', 'bytes': path.stat().st_size, 'sha256': digest(path)}


def add_bytes(archive, name, data):
    info = tarfile.TarInfo(ROOT + '/' + name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = EPOCH
    archive.addfile(info, io.BytesIO(data))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--restore-root', default='/tmp/abba-family-final-archive-recovery-20261020')
    args = ap.parse_args()
    summary = json.loads((P / 'validation/qualification-summary.json').read_text())
    assert summary['status'] == 'PASS' and all(v == 'PASS' for v in summary['gates'].values())
    for item in summary['evidence']:
        assert digest(P / 'validation' / item['file']) == item['sha256'], item['file']
    for name in ('abba', 'fabba', 'qabba'):
        assert json.loads((R / 'ReWrite' / name / 'PORT_MANIFEST.json').read_text())['status'] == 'REWRITE_DONE'

    # Bind current implementation and actual executable identities to all saved
    # evidence, including historical debug artifacts (not PASS qualifications).
    evidence = P / 'validation/EVIDENCE_INDEX.json'
    entries = [record(f) for f in files() if f != evidence]
    products = ['libabba_family.so', 'libabba_family_static.a', 'libaf_ckmeans.a',
                'libaf_byte_zlib.a', 'libaf_byte_zstd.a', 'libaf_byte_bz2.a',
                'xz-build/src/liblzma/.libs/liblzma.a', 'abba_family_cli',
                'af_native_tests', 'af_benchmark']
    builds = {}
    for build in ('build', 'build-asan', 'build-tsan', 'build-arm64', 'build-fuzz'):
        builds[build] = [{'path': name, 'sha256': digest(P / build / name)}
                         for name in products + (['af_fuzz'] if build == 'build-fuzz' else [])
                         if (P / build / name).is_file()]
    save(evidence, {'format': 'abba-family-evidence-index-v1', 'qualification': summary,
                    'files': entries, 'build_artifacts_not_distributed': builds,
                    'note': 'File integrity does not promote historical failures to qualification; '
                            'qualification-summary.json selects the current PASS evidence.'})
    paths = list(files())
    entries = [record(f) for f in paths]
    index = {'format': 'abba-family-release-index-v1', 'archive_root': ROOT,
             'files': entries, 'excluded': ['build caches', 'installed runtimes', 'original Git clones'],
             'self_hash_policy': 'RELEASE_FILE_INDEX.json and SHA256SUMS are metadata; external archive digest binds both.'}
    index_data = (json.dumps(index, indent=2, ensure_ascii=False) + '\n').encode()
    checksums = ''.join(f"{e['sha256']}  {e['path']}\n" for e in entries if e['type'] == 'file')
    checksums += hashlib.sha256(index_data).hexdigest() + '  RELEASE_FILE_INDEX.json\n'
    release = R / 'Release'
    release.mkdir(exist_ok=True)
    archive_path = release / (NAME + '.tar.gz')
    assert not archive_path.exists(), 'Refusing to overwrite an existing frozen release'
    with archive_path.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=EPOCH) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as archive:
            for path, entry in zip(paths, entries):
                info = archive.gettarinfo(str(path), ROOT + '/' + entry['path'])
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.mtime = EPOCH
                if info.isfile():
                    with path.open('rb') as stream:
                        archive.addfile(info, stream)
                else:
                    archive.addfile(info)
            add_bytes(archive, 'RELEASE_FILE_INDEX.json', index_data)
            add_bytes(archive, 'SHA256SUMS', checksums.encode())
    archive_hash = digest(archive_path)
    archive_path.with_suffix(archive_path.suffix + '.sha256').write_text(archive_hash + '  ' + archive_path.name + '\n')

    restore = Path(args.restore_root)
    restore.mkdir(parents=True, exist_ok=True)
    assert not (restore / ROOT).exists(), 'Choose an empty recovery location'
    expected = {ROOT + '/' + e['path']: e for e in entries}
    seen = set()
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive:
            assert member.name not in seen
            seen.add(member.name)
            relative = PurePosixPath(member.name)
            assert not relative.is_absolute() and '..' not in relative.parts and relative.parts[0] == ROOT
            target = restore / member.name
            if member.name in (ROOT + '/RELEASE_FILE_INDEX.json', ROOT + '/SHA256SUMS'):
                data = archive.extractfile(member).read()
                assert data == (index_data if member.name.endswith('.json') else checksums.encode())
            else:
                entry = expected[member.name]
                if entry['type'] == 'symlink':
                    assert member.issym() and member.linkname == entry['target']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(member.linkname)
                    continue
                assert member.isfile() and member.size == entry['bytes']
                data = archive.extractfile(member).read()
                assert hashlib.sha256(data).hexdigest() == entry['sha256'], member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(member.mode & 0o777)
    assert seen == set(expected) | {ROOT + '/RELEASE_FILE_INDEX.json', ROOT + '/SHA256SUMS'}
    print('Archive hashes and restored members PASS', len(entries), flush=True)
    family = restore / ROOT / 'ReWrite/abba-family'
    env = dict(os.environ, LC_ALL='C', TZ='UTC', SOURCE_DATE_EPOCH=str(EPOCH))
    env.pop('PYTHONPATH', None)
    env.pop('LD_LIBRARY_PATH', None)
    steps = []
    for i, command in enumerate([
        ['cmake', '-S', '.', '-B', 'build', '-DCMAKE_BUILD_TYPE=Release'],
        ['cmake', '--build', 'build', '-j3'],
        ['ctest', '--test-dir', 'build', '--output-on-failure'],
        ['python3', 'tools/install_consumer.py'],
    ]):
        log = release / (NAME + f'.recovery-{i}.log')
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=family, env=env, stdout=stream, stderr=subprocess.STDOUT)
        steps.append({'command': command, 'exit': result.returncode, 'log': log.name, 'sha256': digest(log)})
        result.check_returncode()
        print('Cold archive recovery step PASS', i, flush=True)
    restored_build = {name: digest(family / 'build' / name) for name in products}
    baseline = json.loads((P / 'validation/build-reproducibility.json').read_text())['artifacts'][0]
    differences = [name for name in products if restored_build[name] != baseline[name]]
    assert not differences, differences
    save(release / (NAME + '.audit.json'), {
        'status': 'PASS', 'archive': archive_path.name, 'sha256': archive_hash,
        'bytes': archive_path.stat().st_size, 'files_verified': len(entries),
        'file_index_sha256': hashlib.sha256(index_data).hexdigest(),
        'qualification_sha256': digest(P / 'validation/qualification-summary.json'),
        'restored_root': str(restore / ROOT), 'steps': steps,
        'cold_build_artifacts': restored_build, 'reproducible_artifact_differences': differences,
        'scope': 'Every archive member verified and restored; offline build/CTest and '
                 'C11/shared/static consumers; 10 artifacts identical to the two qualified builds. '
                 'Source-oracle cold rebuild/replay is separately recorded in the bundled package-recovery-audit.json.'})
    print('Frozen archive, cold recovery and byte reproducibility PASS', archive_path, flush=True)


if __name__ == '__main__':
    main()
