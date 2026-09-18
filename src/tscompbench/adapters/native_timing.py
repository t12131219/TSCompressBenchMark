from __future__ import annotations

import ctypes
from typing import Any

from tscompbench.execution.protocol import ExecutionContractError


class _NativeTiming(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("native_encode_wall_ns", ctypes.c_uint64),
        ("native_decode_wall_ns", ctypes.c_uint64),
    ]


class NativeTimingProbe:
    """Optional ABI extension; old binaries and disabled probes remain unmeasured."""

    def __init__(self, library: Any, handle: ctypes.c_void_p, *, enabled: bool):
        self.handle = handle
        self.query = None
        if not enabled:
            return
        setter = getattr(library, "tscb_set_native_timing", None)
        query = getattr(library, "tscb_get_native_timing", None)
        if setter is None or query is None:
            return
        setter.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        setter.restype = ctypes.c_uint32
        query.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NativeTiming)]
        query.restype = ctypes.c_uint32
        status = int(setter(handle, 1))
        if status == 2:
            return
        if status != 0:
            raise ExecutionContractError(f"native timing enable failed ({status})")
        self.query = query

    def read(self) -> tuple[int, int] | None:
        if self.query is None:
            return None
        timing = _NativeTiming(ctypes.sizeof(_NativeTiming), 1, 0, 0)
        status = int(self.query(self.handle, ctypes.byref(timing)))
        if status == 2:
            return None
        if status != 0:
            raise ExecutionContractError(f"native timing query failed ({status})")
        return int(timing.native_encode_wall_ns), int(timing.native_decode_wall_ns)
