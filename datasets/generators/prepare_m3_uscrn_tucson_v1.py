#!/usr/bin/env python3
"""Materialize a fixed, contiguous USCRN temperature projection for the M3 switch."""
from argparse import ArgumentParser
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.smoke import write_new
from tsbench.assets import digest, load_json, require
from tsbench.corpus_ingress import PARTITIONS, axis_contract, fingerprint

LOCATION = Path('datasets/raw/m3-uscrn-tucson-v1')
ORIGINAL = LOCATION / 'CRNH0203-2020-AZ_Tucson_11_W.txt'
README = LOCATION / 'hourly02-README.txt'
CSV = LOCATION / 'temperature-civil.csv'
MANIFEST = Path('datasets/manifests/m3-input-switch-noaa-uscrn-tucson-v1.json')
LINEAGE = LOCATION / 'lineage.json'
PRODUCT = 'https://www.ncei.noaa.gov/pub/data/uscrn/products/hourly02/'
SNAPSHOT = {
    ORIGINAL: ('2020/' + ORIGINAL.name, '154a18adc602477043a8a323615b24b2b7ec80751a2d3745ae6acfb6c957ae15'),
    README: ('README.txt', '4ace9cbbb3d63c98d8bbcf909e626d98ee4cc2ab8c1e4e59eece88eeec665872'),
}
ID = 'noaa-uscrn-53131-hourly-2020-temperature-v1'
CLUSTER = 'noaa-uscrn-station-53131-az-tucson-11-w'
COLUMNS = ['timestamp', 'T_HR_AVG', 'T_MAX', 'T_MIN']
SOURCE_ROWS = 8784
SOURCE_WINDOW = (0, 6916)
ROWS = SOURCE_WINDOW[1] - SOURCE_WINDOW[0]
BOUNDS = (0, 3072, 4608, ROWS)


def project(raw):
    result = []
    missing = []
    for i, line in enumerate(raw.splitlines()):
        parts = line.split()
        require(len(parts) == 38 and parts[0] == '53131', 'unexpected CRNH0203 station or column count')
        utc = datetime.strptime(parts[1] + parts[2], '%Y%m%d%H%M')
        lst = datetime.strptime(parts[3] + parts[4], '%Y%m%d%H%M')
        require(utc == datetime(2020, 1, 1) + timedelta(hours=i + 1) and lst == utc - timedelta(hours=7),
                'USCRN hourly order, extent or LST coordinate differs')
        values = [line[65:72].strip(), line[73:80].strip(), line[81:88].strip()]
        require(values == parts[9:12] and all(re.fullmatch(r'-?[0-9]+\.[0-9]', v) for v in values),
                'malformed USCRN temperature')
        if '-9999.0' in values:
            missing.append(i)
            result.append(None)
            continue
        mean, high, low = map(float, values)
        require(low <= mean <= high, 'USCRN temperatures outside observed hourly range')
        result.append(','.join([lst.isoformat(sep=' '), *values]))
    require(len(result) == SOURCE_ROWS and missing == [6916], 'USCRN annual snapshot extent or missing row differs')
    intervals = list(zip([0, *(x + 1 for x in missing)], [*missing, SOURCE_ROWS]))
    begin, end = max(intervals, key=lambda span: (span[1] - span[0], -span[0]))
    require((begin, end) == SOURCE_WINDOW, 'USCRN longest complete contiguous window differs')
    return ('\n'.join([','.join(COLUMNS), *result[begin:end]]) + '\n').encode('ascii')


def prepare(root, verify):
    sources = []
    for path, (url, sha) in SNAPSHOT.items():
        ref = root / path
        require(digest(ref) == sha, f'USCRN frozen input differs: {path}')
        sources.append({'path': path.as_posix(), 'url': PRODUCT + url, 'bytes': ref.stat().st_size, 'sha256': sha})
    data = project((root / ORIGINAL).read_text(encoding='ascii'))
    if verify:
        require((root / CSV).read_bytes() == data, 'USCRN projection differs')
    else:
        with (root / CSV).open('xb') as out:
            out.write(data)
    ref = {'path': CSV.as_posix(), 'bytes': len(data), 'sha256': sha256(data).hexdigest()}
    entry = {'id': ID, 'source_cluster': CLUSTER, 'file': ref, 'columns': COLUMNS,
             'parser': {'format': 'utf8_delimited_physical_rows_v1', 'separator': ',', 'decimal': '.',
                        'timestamp': 'civil_iso_seconds', 'missing': 'reject_empty_preserve_finite'},
             'axis': axis_contract('civil_iso_seconds'), 'values_dtype': '<f8', 'rows': ROWS, 'value_count': 3,
             'partitions': [{'name': n, 'start': BOUNDS[i], 'end': BOUNDS[i + 1]} for i, n in enumerate(PARTITIONS)]}
    entry.update(fingerprint(root, entry))
    manifest = {'schema': 'bmk.full-corpus/1', 'scope': 'same_entry_independent_real_projection_v1', 'datasets': [entry]}
    lineage = {
        'schema': 'bmk.m3-uscrn-snapshot-lineage/1', 'provider': 'NOAA NCEI US Climate Reference Network',
        'sources': sources, 'local_snapshot_date': '2026-11-20', 'product_format': 'CRNH0203',
        'station': {'wban': '53131', 'name': 'AZ Tucson 11 W', 'source_cluster': CLUSTER},
        'time_axis': 'LST observation hour-end civil labels; verified station UTC−07:00, not reinterpreted as UTC in benchmark',
        'projection': {'annual_source_rows': SOURCE_ROWS, 'retained_rows': ROWS, 'source_rows_half_open': list(SOURCE_WINDOW),
                       'missing_selected_field_rows_zero_based': [6916], 'value_unit': 'Celsius', 'columns': COLUMNS[1:],
                       'selection_rule': 'longest contiguous complete temperature window, earliest start on ties, before codec execution',
                       'missing_policy': 'no imputation, time-grid change or stitching across the missing hour', 'file': ref},
        'manifest': MANIFEST.as_posix(), 'canonical': entry['canonical'],
        'partitions': entry['partitions'], 'replaces_r40_corpus': False,
    }
    for path, doc in ((MANIFEST, manifest), (LINEAGE, lineage)):
        if verify:
            require(load_json(root / path) == doc, f'USCRN generated binding differs: {path}')
        else:
            write_new(root / path, doc)


if __name__ == '__main__':
    cli = ArgumentParser(description=__doc__)
    cli.add_argument('--verify', action='store_true')
    prepare(ROOT, cli.parse_args().verify)
