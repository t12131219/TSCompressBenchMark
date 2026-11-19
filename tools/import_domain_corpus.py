#!/usr/bin/env python3
"""Stage v3 manifest and two derivatives using only the locked local publisher bytes."""
from pathlib import Path
import argparse
import csv
import gzip
import io
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import ContractError, canonical_bytes, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus import (CMIP6_MODELS, INTAKE_V3, MANIFEST, MANIFEST_V3, WESTERMO_COLUMNS,
                            audit_asset, check_corpus, f64, intake_assets)


def westermo(source, spec, out):
    labels = [name for name, _ in WESTERMO_COLUMNS]
    with source.open('r', encoding='ascii', newline='') as f:
        rows = csv.reader(f, strict=True)
        header = next(rows, None)
        require(header is not None and header[0] == 'timestamp' and len(header) == len(set(header)) == 24 and
                set(labels) <= set(header), 'unexpected Westermo source schema')
        index = [header.index(name) for name in labels]
        out.write(','.join(['timestamp', *labels]) + '\n')
        n = 0
        for i, row in enumerate(rows):
            require(len(row) == len(header) and row[0] == str(30 * i), f'invalid source row or elapsed tick: {i + 1}')
            selected = [row[pos] for pos in index]
            for token in selected:
                f64(token, '.')  # reject whitespace, scientific notation or blanks; no coerced zeros
            out.write(','.join([row[0], *selected]) + '\n')
            n += 1
        require(n == spec['rows'], 'Westermo sample differs from frozen prefix')


def cmip6(source, spec, out):
    # SciPy is needed to regenerate this one derivative, not to read canonical CSV.
    import numpy as np
    from scipy.io import netcdf_file

    with netcdf_file(source, 'r', mmap=False) as nc:
        t, v, m = (nc.variables[x] for x in ('time', 'tas', 'model'))
        require(t.dimensions == ('time',) and t.data.dtype.kind == 'i' and t.data.tolist() == list(range(1850, 2021)),
                'CEDA annual label mismatch')
        require(m.dimensions == ('model', 'model_char') and m.data.dtype.str == '|S1' and m.data.shape == (61, 18) and
                v.dimensions == ('model', 'time') and v.data.shape == (61, spec['rows']) and
                v.data.dtype.str == '>f8' and v.units == b'degree_Celsius' and
                float(v.missing_value) >= 1e19 and not {'scale_factor', 'add_offset'} & set(v._attributes),
                'unexpected CEDA field schema')
        models = [r.tobytes().rstrip(b'\x00').decode('ascii') for r in m.data]
        require(len(models) == len(set(models)) and models[-2:] == ['MultiModelMean', 'HadCRUT5'],
                'unexpected CEDA model list or derived columns')
        candidates = [(i, name) for i, name in enumerate(models[:-2]) if
                      np.all(np.isfinite(v.data[i]) & (v.data[i] != v.missing_value))]
        require(tuple(name for _, name in candidates[:8]) == CMIP6_MODELS, 'frozen complete-model selection differs')
        selected = [i for i, _ in candidates[:8]]
        out.write(','.join(['timestamp', *CMIP6_MODELS]) + '\n')
        for j, stamp in enumerate(t.data):
            values = [float(v.data[i, j]) for i in selected]
            tokens = [np.format_float_positional(x, unique=True, trim='-') for x in values]
            require(all(f64(token, '.') == struct.pack('<d', original) for token, original in zip(tokens, values)),
                    f'CEDA value cannot be preserved at year {stamp}')
            out.write(','.join([str(stamp), *tokens]) + '\n')


def stage(root: Path, out: Path) -> dict:
    require(out.is_dir() and not any(out.iterdir()), 'expected an empty staging directory')
    ref = {'path': INTAKE_V3, 'sha256': digest(local_file(root, INTAKE_V3))}
    specs, _ = intake_assets(root, ref)
    base = load_json(local_file(root, MANIFEST))
    check_corpus(root, MANIFEST)
    methods = {'westermo-system1': westermo, 'ceda-cmip6-gsat': cmip6}
    result = {'schema': base['schema'], 'id': 'first_batch_real_v3', 'state': 'domain_coverage_only',
              'intake': ref, 'datasets': list(base['datasets'])}
    for s in specs:
        if s['id'] not in methods:
            continue
        final_path = out / s['asset_path']
        final_path.parent.mkdir(parents=True, exist_ok=True)
        source = verify_asset(root, s['source_asset'])
        with final_path.open('xb') as dest, gzip.GzipFile(filename='', fileobj=dest, mode='wb', mtime=0, compresslevel=6) as binary:
            with io.TextIOWrapper(binary, encoding='ascii', newline='\n') as text:
                methods[s['id']](source, s, text)
        dataset = {k: s[k] for k in ('id', 'source_cluster', 'domain', 'header_profile', 'nominal_step_ticks', 'split_at')}
        dataset['asset'] = {'path': s['asset_path'], 'bytes': final_path.stat().st_size, 'sha256': digest(final_path)}
        dataset['audit'] = audit_asset(final_path, dataset)
        require(dataset['audit']['rows'] == s['rows'], 'v3 derivative row denominator mismatch')
        result['datasets'].append(dataset)
    load_contract(root, 'corpus').validate(result, MANIFEST_V3)
    path = out / MANIFEST_V3
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(result) + b'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(f"Staged {len(stage(ROOT, args.out)['datasets'])} corpus bindings with two new derivative files at {args.out}")
    except (ContractError, OSError, KeyError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
