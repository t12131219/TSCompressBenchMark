"""Resolve a CORAD deployment without giving the worker a filesystem path."""
import math
from pathlib import Path
import re
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require, verify_asset

NATIVE = struct.Struct('<4sIHHHHdQ')
DEPLOYMENT = struct.Struct('<8sII')
MAX_SCHEMA, MAX_MODEL = 4096, 16384
NAME = re.compile(r'[a-z0-9][a-z0-9._-]{0,127}\Z')
DIGEST = re.compile(r'[a-f0-9]{64}\Z')


def load_deployment(root: Path, manifest: str) -> tuple[dict, bytes, bytes, dict]:
    cfg = load_json(local_file(root, manifest))
    require(isinstance(cfg, dict) and cfg.keys() == {'schema','id','model','ordered_columns','training','quality_policy'} and
            cfg['schema'] == 'bmk.corad-deployment/1' and isinstance(cfg['id'], str) and NAME.fullmatch(cfg['id']) and
            cfg['quality_policy'] == 'development-observation-only', 'invalid CORAD deployment manifest')
    columns = cfg['ordered_columns']
    require(isinstance(columns, list) and 0 < len(columns) <= 64 and
            all(isinstance(c, str) and NAME.fullmatch(c) for c in columns) and len(set(columns)) == len(columns),
            'invalid CORAD ordered columns')
    ref = cfg['model']
    require(isinstance(ref, dict) and ref.keys() == {'path','sha256','bytes'} and
            isinstance(ref['path'], str) and ref['path'].startswith('assets/models/corad/') and
            type(ref['bytes']) is int and NATIVE.size <= ref['bytes'] <= MAX_MODEL, 'invalid CORAD model reference')
    source = cfg['training']
    require(isinstance(source, dict) and source.keys() == {'route','audit_id','audit_sha256','archive_sha256','dataset',
                                                          'corpus_id','partition','offset','rows','values_content_id'} and
            source['route'] in ('c-lars','source-sklearn') and source['partition'] == 'train' and
            all(isinstance(source[k], str) and DIGEST.fullmatch(source[k])
                for k in ('audit_sha256','archive_sha256','corpus_id','values_content_id')) and
            isinstance(source['audit_id'], str) and re.fullmatch(r'[a-f0-9]{32}', source['audit_id']) and
            isinstance(source['dataset'], str) and NAME.fullmatch(source['dataset']) and
            type(source['offset']) is int and source['offset'] >= 0 and type(source['rows']) is int and source['rows'] > 0,
            'invalid CORAD training provenance')
    path = local_file(root, ref['path'])
    require(path.stat().st_size == ref['bytes'], 'CORAD model byte count differs from manifest')
    model = verify_asset(root, ref).read_bytes()
    magic, rows, cols, width, atoms, nonzero, threshold, size = NATIVE.unpack_from(model)
    require(magic == b'CRD1' and rows == 0 and cols == len(columns) and 1 <= width <= 128 and 1 <= atoms <= 512 and
            1 <= nonzero <= min(32, width, atoms) and math.isfinite(threshold) and -1 <= threshold <= 1 and
            size == len(model) == NATIVE.size + 8 * width * atoms + 16 * cols, 'invalid CORAD zero-row CRD1 asset shape')
    schema = canonical_bytes({'schema':'bmk.corad-columns/1','columns':columns,'dtype':'f64le'})
    require(len(schema) <= MAX_SCHEMA, 'CORAD ordered schema exceeds its byte cap')
    packed = DEPLOYMENT.pack(b'BMKCDP\x01\x00', len(schema), len(model)) + schema + model
    return {**cfg, 'deployment_id':content_id(cfg)}, schema, model, {'deployment':packed.hex()}
