"""Canonical typed objects. Source parsing never changes dtype implicitly."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
import csv
import hashlib
import json
import numpy as np

DTYPES = frozenset(np.dtype(x).str for x in ('i1','u1','<i2','<u2','<i4','<u4','<i8','<u8','<f4','<f8','bool'))
MAX_OBJECT_BYTES = 2 * 1024**3


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def array_order(a):
    return 'F' if a.ndim > 1 and a.flags.f_contiguous and not a.flags.c_contiguous else 'C'


def array_descriptor(a):
    return {'dtype': a.dtype.str, 'shape': list(a.shape), 'order': array_order(a)}


@dataclass(frozen=True)
class TimeSeriesObject:
    components: Mapping[str, np.ndarray]
    schema: Mapping[str, object]
    lineage: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        if not self.components or len(self.components) > 64:
            raise ValueError('an object needs 1..64 named components')
        for name, a in self.components.items():
            if not isinstance(name, str) or not name or len(name) > 128:
                raise ValueError('invalid component name')
            if not isinstance(a, np.ndarray) or a.dtype.str not in DTYPES:
                raise ValueError(f'unsupported canonical dtype in {name}')
            if not 1 <= a.ndim <= 8 or not (a.flags.c_contiguous or a.flags.f_contiguous):
                raise ValueError(f'{name}: need contiguous rank 1..8 array')
        if raw_bytes(self) > MAX_OBJECT_BYTES:
            raise ValueError('object exceeds configured 2 GiB safety ceiling')
        canonical_json(self.schema)
        roles=self.schema.get('roles',{})
        values=[a for k,a in self.components.items() if roles.get(k,k)=='V']
        times=[a for k,a in self.components.items() if roles.get(k,k)=='T']
        masks=[a for k,a in self.components.items() if roles.get(k,k)=='mask']
        if self.schema.get('topology') in {'UTS','SYNCHRONOUS_MTS'} and values:
            if any(t.ndim!=1 or len(t)!=values[0].shape[0] for t in times):raise ValueError('timestamp axis does not align with values')
            if any(m.shape!=values[0].shape or m.dtype.kind not in 'bu' or np.any((m!=0)&(m!=1)) for m in masks):raise ValueError('validity mask must align and contain 0/1')


def raw_bytes(obj):
    return sum(a.nbytes for a in obj.components.values())


def fingerprint(obj):
    digest = hashlib.sha256()
    digest.update(canonical_json(obj.schema))
    for name, a in sorted(obj.components.items()):
        digest.update(canonical_json({'name': name, **array_descriptor(a)}))
        digest.update(a.tobytes(order=array_order(a)))
    return 'sha256:' + digest.hexdigest()


def object_id(obj):
    return fingerprint(obj)


def project(obj, task):
    kind = task.get('kind', 'values') if isinstance(task, dict) else task
    roles = obj.schema.get('roles', {k:k for k in obj.components})
    selected = {}
    for k, a in obj.components.items():
        role = roles.get(k, k)
        if kind in {'records','component'} or kind == 'values' and role in {'V','mask'} or kind == 'timestamps' and role == 'T':
            selected[k] = a
    if not selected or kind=='values' and not any(roles.get(k,k)=='V' for k in selected):
        raise ValueError(f'no component for task {kind}')
    schema = dict(obj.schema)
    schema['roles'] = {k: roles.get(k,k) for k in selected}
    if not any(roles.get(k,k)=='V' for k in selected):schema.pop('columns',None);schema['topology']='UTS'
    if not any(roles.get(k,k)=='T' for k in selected):schema.pop('time_unit',None)
    schema['task'] = kind
    return TimeSeriesObject(selected, schema, obj.lineage)


def _file_hash(path):
    with path.open('rb') as f:
        return 'sha256:' + hashlib.file_digest(f, 'sha256').hexdigest()


def validate_selection_spec(spec):
    """Validate declared slicing without Python's silent coercion/clipping.

    Config has no negative-index opt-in: rows and channels use explicit
    nonnegative, zero-based indices. An empty row window is a valid object.
    Actual file dimensions are checked separately after loading.
    """
    start, stop, step = spec.get('start', 0), spec.get('stop'), spec.get('step', 1)
    if type(start) is not int or start < 0:
        raise ValueError('window start must be a nonnegative integer')
    if stop is not None and (type(stop) is not int or stop < 0):
        raise ValueError('window stop must be a nonnegative integer or omitted')
    if type(step) is not int or step < 1:
        raise ValueError('window step must be a positive integer')
    if stop is not None and stop < start:
        raise ValueError('window stop must be >= start')
    columns = spec.get('columns_indices')
    if columns is not None:
        if not isinstance(columns, list) or any(type(index) is not int or index < 0 for index in columns):
            raise ValueError('columns_indices must be a list of nonnegative integers')
        if len(set(columns)) != len(columns):
            raise ValueError('columns_indices must not contain duplicates')
    if 'order' in spec and spec['order'] not in ('C', 'F'):
        raise ValueError('order must be C/F')
    return start, stop, step, columns


def load_dataset(spec, base_dir=None):
    start, stop, step, selected_columns = validate_selection_spec(spec)
    path = Path(spec['path']).expanduser()
    if not path.is_absolute(): path = Path(base_dir or '.') / path
    path = path.resolve(strict=True)
    fmt = spec.get('format', path.suffix.lstrip('.')).lower()
    components, roles = {}, {}
    rule = {k:v for k,v in spec.items() if k not in {'id','path','source','license'}}
    if fmt == 'npy':
        a = np.load(path, allow_pickle=False)
        name = spec.get('component','V')
        components[name] = a
        roles[name] = name
    elif fmt == 'npz':
        with np.load(path, allow_pickle=False) as data:
            keys = spec.get('components')
            if keys:
                for name, key in keys.items(): components[name] = data[key].copy(order='K'); roles[name] = name
            else:
                name = spec.get('component','V')
                key = spec.get('key') or (data.files[0] if len(data.files) == 1 else None)
                if key is None: raise ValueError('npz with multiple arrays needs key or components')
                components[name] = data[key].copy(order='K'); roles[name] = name
    elif fmt == 'csv':
        if 'dtype' not in spec: raise ValueError('CSV requires explicit target dtype')
        dtype = np.dtype(spec['dtype'])
        if dtype.str not in DTYPES: raise ValueError('unsupported CSV target dtype')
        with path.open(newline='', encoding=spec.get('encoding','utf-8')) as f:
            reader = csv.DictReader(f, delimiter=spec.get('delimiter',','))
            if not reader.fieldnames: raise ValueError('CSV needs a named header')
            tcol = spec.get('timestamp_column')
            cols = spec.get('columns') or [c for c in reader.fieldnames if c != tcol]
            if not cols or not set(cols).issubset(reader.fieldnames): raise ValueError('invalid CSV value columns')
            if tcol and tcol not in reader.fieldnames: raise ValueError('timestamp column missing')
            missing = set(spec.get('missing_tokens',['','NA','NaN','nan']))
            values, mask, times = [], [], []
            for row in reader:
                vals, valid = [], []
                for c in cols:
                    text = row[c]
                    ok = text not in missing
                    if not ok and spec.get('missing', 'reject') == 'reject': raise ValueError(f'missing value in {c}')
                    if ok:
                        # Python int avoids precision loss before integer casting.
                        v = int(text) if dtype.kind in 'iu' else float(text)
                        if dtype.kind in 'iu' and not np.iinfo(dtype).min <= v <= np.iinfo(dtype).max:
                            raise ValueError(f'CSV integer overflow in {c}')
                        vals.append(v)
                    else: vals.append(spec.get('fill_value',0))
                    valid.append(ok)
                values.append(vals); mask.append(valid)
                if tcol:
                    parser = spec.get('timestamp_parser','int')
                    if parser == 'int': times.append(int(row[tcol]))
                    elif parser == 'datetime64':
                        unit = spec.get('time_unit')
                        if unit not in {'s','ms','us','ns'}: raise ValueError('datetime64 timestamps require time_unit s/ms/us/ns')
                        value = np.datetime64(row[tcol],unit)
                        if np.isnat(value): raise ValueError('NaT timestamp')
                        times.append(int(value.astype('int64')))
                    else: raise ValueError('unknown timestamp_parser')
        a = np.array(values,dtype=dtype).reshape(-1,len(cols))
        if len(cols) == 1: a = a[:,0].copy()
        components['V'] = a; roles['V']='V'
        if spec.get('missing','reject') == 'mask':
            m = np.array(mask,dtype='u1').reshape(-1,len(cols))
            components['mask'] = m[:,0].copy() if len(cols)==1 else m; roles['mask']='mask'
        if tcol: components['T']=np.array(times,dtype='<i8'); roles['T']='T'
    else: raise ValueError(f'unsupported loader {fmt}')
    schema = dict(spec.get('schema',{}))
    if fmt == 'csv': schema['columns'] = list(cols)
    value_arrays = [array for name, array in components.items() if roles.get(name, name) == 'V']
    if selected_columns is not None:
        if not value_arrays or any(array.ndim != 2 for array in value_arrays):
            raise ValueError('columns_indices requires rank-2 V matrices')
        if len({array.shape[1] for array in value_arrays}) != 1:
            raise ValueError('columns_indices requires a common V channel count')
        width = value_arrays[0].shape[1]
        if any(index >= width for index in selected_columns):
            raise ValueError('columns_indices exceeds V channel bounds')
        for name, array in components.items():
            if roles.get(name, name) == 'mask' and array.shape != value_arrays[0].shape:
                raise ValueError('validity mask must align with V before column selection')
        names = schema.get('columns')
        if names is not None:
            if not isinstance(names, list) or len(names) != width or any(not isinstance(name, str) for name in names):
                raise ValueError('schema columns must match the original V channel count')
            schema['columns'] = [names[index] for index in selected_columns]
    resolved_windows = {}
    for k,a in list(components.items()):
        if a.dtype.str not in DTYPES: raise ValueError(f'{k}: dtype {a.dtype.str} not supported')
        if not 1 <= a.ndim <= 8: raise ValueError(f'{k}: canonical arrays require rank 1..8')
        source_order = array_order(a)
        # Window/slicing is explicit and retained in lineage.
        end = len(a) if stop is None else stop
        if start > len(a) or end > len(a):
            raise ValueError(f'{k}: window bounds exceed {len(a)} source rows')
        resolved_windows[k] = {'start': start, 'stop': end, 'step': step, 'source_rows': len(a),
                               'selected_rows': len(range(start, end, step))}
        a = a[start:end:step]
        if selected_columns is not None and roles.get(k,k) in {'V', 'mask'}:
            a = a[:, selected_columns]
        # Preserve native NPY/NPZ precision; explicit dtype cast is only CSV.
        components[k] = np.array(a,copy=True,order=spec.get('order',source_order))
        components[k].flags.writeable = False
    rank=components.get('V', next(iter(components.values()))).ndim
    schema.update({'roles': roles, 'topology':schema.get('topology','UTS' if rank==1 else 'SYNCHRONOUS_MTS' if rank==2 else 'NATIVE_ND_ARRAY')})
    if spec.get('time_unit'): schema['time_unit']=spec['time_unit']
    schema.setdefault('masked_value_policy','preserve_all_bits')
    lineage={'source_path':str(path),'source_hash':_file_hash(path),'parse_rule':rule,'source':spec.get('source'),'license':spec.get('license'),
             'selection': {'windows': resolved_windows, 'columns_indices': selected_columns,
                           'index_policy': 'nonnegative zero-based rows/channels; exclusive stop; no implicit clipping'}}
    return TimeSeriesObject(components,schema,lineage)
