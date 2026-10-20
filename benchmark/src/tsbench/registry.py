"""Capability declarations and parameters for the preserved native assets."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import numpy as np

from .errors import BenchError, Unsupported


class CodecError(BenchError):
    """A native codec operation failed; never substitute another algorithm."""


class UnsupportedError(Unsupported, CodecError):
    """Input, platform or parameters lie outside a declared capability."""


class ExcludedError(UnsupportedError):
    """A registered implementation is excluded from current execution."""
    status = 'excluded'


class SourceDomainError(UnsupportedError):
    """The actual content was rejected by the frozen source algorithm."""


class CapacityError(CodecError):
    """The native output bound was insufficient."""


@dataclass(frozen=True)
class CodecSpec:
    root: Path
    key: str
    document: dict[str, Any]

    @property
    def excluded(self) -> bool:
        return self.document.get('admission', {}).get('status') == 'EXCLUDED'

    @property
    def exclusion_reason(self) -> str | None:
        return self.document.get('admission', {}).get('reason') if self.excluded else None

    def require_enabled(self) -> None:
        if self.excluded:
            raise ExcludedError(f'{self.key}: {self.exclusion_reason}', stage='registry.admission')

    @property
    def dtypes(self) -> tuple[str, ...]:
        return tuple(self.document['input']['dtypes'])

    @property
    def ranks(self) -> tuple[int, ...]:
        return tuple(self.document['input']['ranks'])

    @property
    def lossy(self) -> bool:
        return self.loss_mode != 'LOSSLESS'

    @property
    def loss_mode(self) -> str:
        return self.document['semantics']['loss_modes'][0]

    @property
    def threading(self) -> str:
        return self.document['execution']['threading']

    @property
    def features(self) -> dict[str, bool]:
        return dict(self.document['features'])

    @property
    def backend(self) -> str:
        return self.document['adapter']['backend']

    @property
    def isa(self) -> tuple[str, ...]:
        return tuple(self.document['execution']['isa'])

    def validate_array(self, array: np.ndarray) -> None:
        self.require_enabled()
        if not isinstance(array, np.ndarray) or array.dtype.str not in self.dtypes:
            raise UnsupportedError(f'{self.key}: dtype must be one of {self.dtypes}')
        if array.ndim not in self.ranks:
            raise UnsupportedError(f'{self.key}: rank must be one of {self.ranks}')
        contract = self.document['input']
        n = array.shape[0]
        m = array.shape[1] if array.ndim == 2 else 1
        for name, value in [('n', n), ('m', m)]:
            if not contract.get('min_' + name, 0) <= value <= contract.get('max_' + name, 2**63-1):
                raise UnsupportedError(f'{self.key}: {name}={value} exceeds native limits')
        if array.size > contract.get('max_total_elements', 2**63-1):
            raise UnsupportedError(f'{self.key}: element limit exceeded')
        if array.nbytes > contract.get('max_total_raw_bytes', 2**63-1):
            raise UnsupportedError(f'{self.key}: native byte limit exceeded')
        if self.key == 'serf-xor' and array.dtype.itemsize == 4:
            pass  # adjust_digit is checked with the resolved parameters by its bridge.
        if self.key in {'abba', 'fabba'} and not np.isfinite(array).all():
            raise SourceDomainError(f'{self.key}: FINITE_INPUT_REQUIRED')


class Registry:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._specs: dict[str, CodecSpec] = {}
        for path in sorted((self.root / 'registry/codecs').glob('*.json')):
            document = json.loads(path.read_text())
            if 'key' not in document or document.get('identity', {}).get('family') == 'HARNESS_ORACLE':
                continue
            self._specs[document['key']] = CodecSpec(self.root, document['key'], document)
        raw = {
            'key': 'raw-store',
            'identity': {'family': 'REFERENCE', 'source_artifact_id': 'builtin:raw-store-v1'},
            'input': {'dtypes': ['|b1','|i1','|u1','<i2','<u2','<i4','<u4','<i8','<u8','<f4','<f8'], 'ranks': list(range(1,9)), 'min_n': 0, 'min_m': 0},
            'semantics': {'loss_modes': ['LOSSLESS']},
            'execution': {'threading': 'SINGLE_THREAD', 'isa': ['SCALAR']},
            'features': {'streaming': False, 'query': False, 'random_access': False},
            'adapter': {'backend': 'BUILTIN'},
            'parameters': {'properties': {}, 'constraints': []},
        }
        self._specs['raw-store'] = CodecSpec(self.root, 'raw-store', raw)

    def list(self, *, include_reference: bool = True, include_excluded: bool = False) -> list[CodecSpec]:
        return [v for k,v in sorted(self._specs.items())
                if (include_reference or k != 'raw-store') and (include_excluded or not v.excluded)]

    def get(self, key: str) -> CodecSpec:
        key = {'lz77': 'deflate-zlib'}.get(key, key)
        if key not in self._specs:
            raise UnsupportedError(f'unknown codec: {key}')
        return self._specs[key]

    def resolve_params(self, key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = self.get(key)
        params = {} if params is None else params
        contract = spec.document['parameters']
        properties = contract['properties']
        if not isinstance(params, dict) or set(params) - set(properties):
            raise UnsupportedError(f'{key}: unknown parameters {set(params) - set(properties) if isinstance(params,dict) else params}')
        resolved = {}
        for name, rule in properties.items():
            value = params.get(name, False if name == 'native_timing' else rule.get('default'))
            kind = rule['type']
            if kind == 'integer' and type(value) is not int:
                raise UnsupportedError(f'{key}: {name} must be an integer')
            if kind == 'boolean' and type(value) is not bool:
                raise UnsupportedError(f'{key}: {name} must be a boolean')
            if kind == 'string' and not isinstance(value, str):
                raise UnsupportedError(f'{key}: {name} must be a string')
            if kind == 'decimal-string':
                try:
                    number = Decimal(str(value))
                    if not number.is_finite() or not math.isfinite(float(number)):
                        raise ValueError('not finite')
                    value = str(number)
                except (InvalidOperation, ValueError, OverflowError) as error:
                    raise UnsupportedError(f'{key}: {name} must be a finite decimal') from error
            if 'enum' in rule and value not in rule['enum']:
                raise UnsupportedError(f'{key}: {name} must be one of {rule["enum"]}')
            if 'minimum' in rule and value < rule['minimum'] or 'maximum' in rule and value > rule['maximum']:
                raise UnsupportedError(f'{key}: {name} outside its parameter range')
            resolved[name] = value
        for constraint in contract.get('constraints', []):
            kind = constraint['kind']
            if kind == 'ordered' and resolved[constraint['lower']] > resolved[constraint['upper']]:
                raise UnsupportedError(f'{key}: parameter ordering violated')
            if kind == 'forbid_combination' and all(resolved.get(k) == v for k,v in constraint['when'].items()):
                raise UnsupportedError(f'{key}: {constraint["reason"]}')
            if kind == 'numeric_range':
                value = Decimal(str(resolved[constraint['parameter']]))
                if 'minimum' in constraint:
                    minimum = Decimal(str(constraint['minimum']))
                    if value < minimum or constraint.get('exclusive_minimum') and value == minimum:
                        raise UnsupportedError(f'{key}: {constraint["parameter"]} below allowed range')
                if 'maximum' in constraint and value > Decimal(str(constraint['maximum'])):
                    raise UnsupportedError(f'{key}: {constraint["parameter"]} above allowed range')
        if key.startswith('serf-') or key == 'zfp-accuracy-1d':
            if Decimal(resolved['error_bound']) <= 0:
                raise UnsupportedError(f'{key}: error_bound must be positive')
        if key in {'pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized'}:
            epsilon = Decimal(resolved['epsilon'])
            if epsilon > 0 and np.float32(float(epsilon)) == 0:
                raise UnsupportedError(f'{key}: positive epsilon underflows float32')
        if key in {'chimpn', 'chimpn32'} and resolved['history'] & (resolved['history'] - 1):
            raise UnsupportedError(f'{key}: history must be a power of two')
        return resolved
