"""Bounded, explicitly registered typed-file loaders for the development TV plan.

The project-local loader registry is trusted code, like the native codec catalog.
A data manifest can select an enabled loader, but cannot supply executable code.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import math
import struct
from types import ModuleType

from .assets import canonical_bytes, content_id, ContractError, digest, load_json, local_file, require
from .contracts import compile_contract, load_contract

LIMIT = 8 * 1024 * 1024
BATCH_ROWS = 256
OBJECT = 'bmk.canonical-dense-tv/1'
ENGINE = 'src/tsbench/ingress.py'


def sha(data):
    return sha256(data).hexdigest()


def canonical_id(spec, hashes):
    # Length-framed, domain-separated Merkle identity: the leaf digests cover
    # exactly rows*8 little-endian bytes in declared order, no validity bytes.
    fields = [OBJECT.encode(), canonical_bytes(spec), *(bytes.fromhex(h) for h in hashes)]
    return sha(b''.join(struct.pack('<Q', len(f)) + f for f in fields))


def source_file_hash(files):
    # Locations are tracked in provenance but not part of the ordered byte identity.
    if len(files)==1:
        return files[0]['sha256']
    return content_id([{k:r[k] for k in ('role','bytes','sha256')} for r in files])


@dataclass(frozen=True, slots=True)
class Batch:
    rows: int
    columns: tuple[bytes, ...]  # immutable, owned, dense little endian; no validity


def names(spec):
    return [spec['timestamp']['name'], *(c['name'] for c in spec['values'])]


def validate_object(spec):
    cols = names(spec)
    require(len(set(cols)) == len(cols), 'duplicate typed source columns')
    axis = spec['timestamp']
    expected = {'unix_epoch_integer':('1970-01-01 00:00:00','UTC'),
                'source_civil_label_coordinate_not_utc':('1970-01-01 00:00:00',None),
                'synthetic_integer_coordinate':(None,None)}[axis['interpretation']]
    require((axis['epoch'],axis['timezone']) == expected, 'inconsistent timestamp epoch/timezone')


def load_typed_source(root: Path, manifest_path: str):
    registry_schema = load_contract(root,'source-loader-registry')
    manifest_schema = load_contract(root,'typed-source')
    registry = load_json(local_file(root,'catalog/source-loaders.json'))
    manifest = load_json(local_file(root,manifest_path))
    registry_schema.validate(registry,'source loader registry')
    manifest_schema.validate(manifest,manifest_path)
    spec, options, refs = (manifest[k] for k in ('object','options','files'))
    validate_object(spec)
    require(len({r['role'] for r in refs}) == len({r['path'] for r in refs}) == len(refs) and
            sum(r['bytes'] for r in refs) <= LIMIT, 'duplicate or oversized source assets')
    plugin = manifest['plugin']
    require(plugin in registry['plugins'], 'source loader is not registered')
    entry = registry['plugins'][plugin]
    opts_schema = compile_contract('typed-source', load_json(local_file(root,entry['options_schema'])))
    opts_schema.validate(options,f'{plugin} options')
    code_path = local_file(root,entry['implementation'])
    code = code_path.read_bytes()
    module = ModuleType(f'_tsbench_source_{plugin}')
    exec(compile(code,code_path.as_posix(),'exec'),module.__dict__)
    data = {}
    for ref in refs:
        with local_file(root,ref['path']).open('rb') as f:
            buf = f.read(ref['bytes']+1)
        require(len(buf)==ref['bytes'] and sha(buf)==ref['sha256'], f"source asset bytes changed: {ref['path']}")
        data[ref['role']] = buf
    handle = module.probe_source(data, spec, options)
    try:
        require(module.resolve_schema(handle, spec, options)==spec, 'loader resolved a different source schema')
        columns = [bytearray() for _ in names(spec)]
        rows = 0
        for batch in module.read_batches(handle,spec,options,BATCH_ROWS):
            require(isinstance(batch,Batch) and type(batch.rows) is int and
                    0 < batch.rows <= BATCH_ROWS and rows + batch.rows <= spec['rows'] and
                    len(batch.columns) == len(columns) and
                    all(type(c) is bytes and len(c) == batch.rows*8 for c in batch.columns),'invalid typed source batch')
            for out, col in zip(columns,batch.columns,strict=True):
                out.extend(col)
            rows += batch.rows
        require(rows==spec['rows'], 'source row count differs from declaration')
    finally:
        module.close(handle)
    data = [bytes(c) for c in columns]
    hashes = [sha(c) for c in data]
    ingestion = {'plugin':plugin,'version':entry['version'],'implementation_sha256':sha(code),
                 'engine_sha256':digest(local_file(root,ENGINE)), 'manifest_schema_id':manifest_schema.document_id,
                 'options_schema_id':opts_schema.document_id,'object':spec,'options':options,'batch_rows':BATCH_ROWS}
    identity = canonical_id(spec,hashes)
    return {'manifest_id':content_id(manifest),'files':refs, 'source_file_hash':source_file_hash(refs),
            'source_bytes':sum(r['bytes'] for r in refs), 'ingestion':ingestion,'ingestion_id':content_id(ingestion),
            'canonical_dataset_hash':identity,'source_group_id':content_id(['bmk.canonical-source-group/1',identity]),
            'source_column_sha256':hashes}, data


def text_probe(data):
    require(list(data)==['table'], 'text loader requires exactly the table asset')
    try:
        text = data['table'].decode('utf-8','strict').replace('\r\n','\n')
    except UnicodeError as exc:
        raise ContractError('invalid declared UTF-8 source') from exc
    require('\x00' not in text and '\r' not in text and not text.startswith('\ufeff'), 'binary data or unsupported line ending/BOM')
    return text


_I64 = re.compile(r'-?(?:0|[1-9][0-9]{0,18})')
_IEEE = re.compile(r'bits:([0-9a-fA-F]{16})')
_FLOAT = {sep:re.compile(rf'[+-]?(?:[0-9]+(?:{re.escape(sep)}[0-9]+)?|{re.escape(sep)}[0-9]+)(?:[eE][+-]?[0-9]+)?')
          for sep in ('.',',')}


def text_rows(text, spec, options, fields, batch_rows):
    """Parse one physical row per record; no unannounced trims, skips, or NaN spelling."""
    lines = text.split('\n')
    if lines[-1] == '':
        lines.pop()  # optional final terminator, not an empty row
    cols = names(spec)
    if options['header']:
        require(bool(lines) and fields(lines[0]) == cols, 'source header differs from ordered columns')
        lines = lines[1:]
    require(len(lines)==spec['rows'], 'source row count differs from declaration')
    sep = options['decimal']
    for start in range(0,len(lines),batch_rows):
        values = [bytearray() for _ in cols]
        block = lines[start:start+batch_rows]
        for i,line in enumerate(block,start+1):
            require(0 < len(line) <= 4096, f'blank or oversized source row {i}')
            row = fields(line)
            require(len(row)==len(cols) and not any(x in options['missing_tokens'] for x in row), f'row {i}: width or missing field')
            require(_I64.fullmatch(row[0]) is not None, f'row {i}: invalid exact i64 timestamp')
            t = int(row[0])
            require(-2**63<=t<2**63,f'row {i}: timestamp outside i64')
            values[0].extend(struct.pack('<q',t))
            for out,token in zip(values[1:],row[1:],strict=True):
                explicit = _IEEE.fullmatch(token)
                if explicit:
                    out.extend(struct.pack('<Q',int(explicit[1],16)))
                else:
                    require(len(token)<=128 and _FLOAT[sep].fullmatch(token) is not None, f'row {i}: invalid f64 token')
                    f = float(token.replace(sep,'.'))
                    require(math.isfinite(f), f'row {i}: nonfinite decimal f64; use an explicit IEEE bit token')
                    # Reject nonzero decimals rounded all the way to zero. Normal binary64
                    # rounding otherwise applies; bitwise identity is checked separately.
                    significand = re.split('[eE]',token,maxsplit=1)[0]
                    require(f!=0.0 or not re.search('[1-9]',significand), f'row {i}: decimal f64 underflow to zero')
                    out.extend(struct.pack('<d',f))
        yield Batch(len(block),tuple(map(bytes,values)))
