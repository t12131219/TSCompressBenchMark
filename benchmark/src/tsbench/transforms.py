"""Explicit reversible transformations; all parameters travel in the object wire."""
from __future__ import annotations

from math import gcd

import numpy as np

from .errors import Unsupported


def encode_integer_affine(array):
    if array.dtype.kind not in {'i', 'u'}:
        raise Unsupported('integer_affine_gcd requires an integer component', stage='transform')
    flat = array.ravel(order='C')
    bias = min((int(x) for x in flat), default=0)
    scale = 0
    for value in flat:
        scale = gcd(scale, int(value) - bias)
    scale = scale or 1
    maximum = max(((int(x) - bias) // scale for x in flat), default=0)
    if maximum > np.iinfo(array.dtype).max:
        raise Unsupported('integer_affine_gcd normalized values exceed the original integer dtype', stage='transform')
    normalized = np.fromiter(((int(x) - bias) // scale for x in flat), dtype=array.dtype, count=array.size).reshape(array.shape)
    order = 'F' if array.flags.f_contiguous and not array.flags.c_contiguous else 'C'
    normalized = np.array(normalized, copy=True, order=order)
    return normalized, {'kind': 'integer_affine_gcd', 'version': 1, 'bias': bias, 'scale': scale}


def forward(array, kind=None):
    if kind in {None, 'identity'}:
        return array, None
    if kind == 'integer_affine_gcd':
        return encode_integer_affine(array)
    raise Unsupported(f'unknown transform: {kind}', stage='transform')


def inverse(array, descriptor):
    if descriptor is None:
        return array
    if not isinstance(descriptor, dict) or set(descriptor) != {'kind', 'version', 'bias', 'scale'}:
        raise ValueError('invalid integer transformation descriptor')
    if descriptor['kind'] != 'integer_affine_gcd' or descriptor['version'] != 1 or array.dtype.kind not in {'i', 'u'}:
        raise ValueError('unsupported integer transformation')
    bias, scale = descriptor['bias'], descriptor['scale']
    bounds = np.iinfo(array.dtype)
    if type(bias) is not int or type(scale) is not int or not bounds.min <= bias <= bounds.max or not 1 <= scale <= max(1, int(bounds.max) - int(bounds.min)):
        raise ValueError('integer transformation parameters out of range')
    def restored():
        for value in array.ravel(order='C'):
            if int(value) < 0:
                raise ValueError('negative normalized integer')
            result = int(value) * scale + bias
            if not bounds.min <= result <= bounds.max:
                raise ValueError('inverse integer transformation overflows original dtype')
            yield result
    output = np.fromiter(restored(), dtype=array.dtype, count=array.size).reshape(array.shape)
    order = 'F' if array.flags.f_contiguous and not array.flags.c_contiguous else 'C'
    return np.array(output, copy=True, order=order)
