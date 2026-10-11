"""Shared byte-buffer view for the tscb_adapter_v1 C ABI."""

import ctypes

_MAX_RANK = 8
_DTYPE_BYTES = 11
_OWNERSHIP_BORROWED = 0


class _Buffer(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("capacity_bytes", ctypes.c_uint64),
        ("used_bytes", ctypes.c_uint64),
        ("dtype", ctypes.c_uint32),
        ("rank", ctypes.c_uint32),
        ("shape", ctypes.c_uint64 * _MAX_RANK),
        ("strides_bytes", ctypes.c_int64 * _MAX_RANK),
        ("alignment_bytes", ctypes.c_uint64),
        ("ownership", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


def _alignment(address: int) -> int:
    value = 1
    while value < 64 and address % (value * 2) == 0:
        value *= 2
    return value


def _buffer(address: int, *, capacity: int, used: int) -> _Buffer:
    shape = (ctypes.c_uint64 * _MAX_RANK)()
    strides = (ctypes.c_int64 * _MAX_RANK)()
    shape[0] = used
    strides[0] = 1
    return _Buffer(
        ctypes.c_void_p(address),
        capacity,
        used,
        _DTYPE_BYTES,
        1,
        shape,
        strides,
        _alignment(address) if address > 1 else 1,
        _OWNERSHIP_BORROWED,
        0,
    )

