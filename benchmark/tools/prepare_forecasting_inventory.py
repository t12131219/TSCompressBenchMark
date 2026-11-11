"""Inventory current forecasting CSVs and materialize one full file per family."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def family(name: str) -> str:
    return name.split('_dataset')[0] if '_dataset' in name else re.sub(r'_\d+$', '', name)


def main(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    data = destination / 'data'
    data.mkdir()
    rows = []
    started = time.monotonic()
    sources = sorted((ROOT / 'forecasting_transpose').glob('*.csv'))
    for index, source in enumerate(sources, 1):
        row = {'id': source.stem, 'family': family(source.stem), 'source': str(source),
               'source_bytes': source.stat().st_size,
               'source_sha256': hashlib.file_digest(source.open('rb'), 'sha256').hexdigest()}
        try:
            frame = pd.read_csv(source)
            columns = [column for column in frame if column != 'date']
            array = np.ascontiguousarray(frame[columns].to_numpy(dtype='<f8'))
            if array.shape[1] == 1:
                array = array[:, 0].copy()
            row.update(shape=list(array.shape), columns=columns, values=int(array.size),
                       raw_bytes=int(array.nbytes),
                       nonfinite=int(np.count_nonzero(~np.isfinite(array))),
                       min=float(np.nanmin(array)), max=float(np.nanmax(array)),
                       integral=bool(np.isfinite(array).all() and np.equal(array, np.trunc(array)).all()),
                       timestamp_parser='int' if str(frame['date'].iloc[0]).isdigit() else 'datetime64',
                       status='ok')
        except Exception as error:
            row.update(status='error', reason=str(error))
        rows.append(row)
        if index % 500 == 0:
            print(f'inventoried {index}/{len(sources)} in {time.monotonic()-started:.1f}s', flush=True)

    grouped = defaultdict(list)
    for row in rows:
        if row['status'] == 'ok':
            grouped[row['family']].append(row)
    selected = []
    for members in grouped.values():
        row = sorted(members, key=lambda item: (item['values'], item['id']))[(len(members)-1)//2]
        frame = pd.read_csv(row['source'])
        columns = [column for column in frame if column != 'date']
        array = np.ascontiguousarray(frame[columns].to_numpy(dtype='<f8'))
        if array.shape[1] == 1:
            array = array[:, 0].copy()
        path = data / f"{row['id']}.npy"
        np.save(path, array, allow_pickle=False)
        row['npy'] = str(path)
        selected.append(row['id'])

    document = {'files': rows, 'count': len(rows), 'source_root': str(ROOT / 'forecasting_transpose'),
                'parse': 'all non-date columns as float64, C-order; single channel rank1; all rows; no fill, scale or quantization',
                'parse_errors': sum(row['status'] != 'ok' for row in rows),
                'representatives_materialized': sorted(selected)}
    (destination / 'inventory.json').write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=True))
    print(json.dumps({'files': len(rows), 'families': len(grouped), 'representatives': len(selected),
                      'errors': document['parse_errors'], 'seconds': round(time.monotonic()-started, 1)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    import sys
    main(Path(sys.argv[1]).resolve())
