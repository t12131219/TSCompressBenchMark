"""Record the resolved oracle packages and acquisition/installed file hashes.

Run with the chosen Python and PYTHONPATH. Does not alter the environment.
"""
import argparse
import hashlib
import json
from email.parser import Parser
from pathlib import Path
import sys
import pkg_resources


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--conda-cache', type=Path, required=True)
    p.add_argument('--downloads', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    conda = []
    conda_names = set()
    for meta in sorted((Path(sys.prefix) / 'conda-meta').glob('*.json')):
        record = json.loads(meta.read_text())
        archive = a.conda_cache / record['fn']
        if not archive.is_file():
            raise ValueError('missing conda archive: ' + str(archive))
        conda_names.add(record['name'].lower().replace('_', '-'))
        conda.append(dict(name=record['name'], version=record['version'],
                          build=record['build'], url=record['url'],
                          license=record.get('license'),
                          filename=record['fn'], sha256=sha(archive),
                          size_bytes=archive.stat().st_size))
    distributions = []
    requests = []
    for dist in sorted(pkg_resources.working_set, key=lambda d: d.key):
        files = []
        if dist.has_metadata('RECORD'):
            import csv
            for row in csv.reader(dist.get_metadata('RECORD').splitlines()):
                path = Path(dist.location) / row[0]
                if path.is_file() and not path.name.endswith('.pyc'):
                    files.append(dict(path=row[0], sha256=sha(path)))
        metadata_name = 'METADATA' if dist.has_metadata('METADATA') else 'PKG-INFO'
        metadata = Parser().parsestr(dist.get_metadata(metadata_name)) if dist.has_metadata(metadata_name) else {}
        distributions.append(dict(name=dist.project_name, version=dist.version,
                                  license=metadata.get('License'),
                                  homepage=metadata.get('Home-page'),
                                  location=dist.location, files=files))
        if dist.key not in conda_names:
            requests.append(dist.project_name + '==' + dist.version)
    (a.output / 'oracle-requirements.txt').write_text('\n'.join(requests) + '\n')
    archives = []
    if a.downloads.exists():
        for path in sorted(a.downloads.iterdir()):
            if path.is_file():
                archives.append(dict(filename=path.name, sha256=sha(path),
                                     size_bytes=path.stat().st_size))
    result = dict(schema_version=1, python=sys.version, executable=sys.executable,
                  prefix=sys.prefix, conda=conda, distributions=distributions,
                  pip_acquisition_archives=archives)
    (a.output / 'ORACLE_ENVIRONMENT_LOCK.json').write_text(
        json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(conda_packages=len(conda),
                         python_distributions=len(distributions),
                         pip_archives=len(archives))))


if __name__ == '__main__':
    main()
