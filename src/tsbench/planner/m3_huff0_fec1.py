"""Bind the detached FEC1 corpus driver without changing native frame geometry."""
from pathlib import PurePosixPath

from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock
from .huff0 import PLUGIN

KEY = (29, PLUGIN)
DRIVER = 'huff0-fec1-corpus/1'
TARGET = 'tsbench_huff0_fec1_control'
UNIT = 65536
BATCH = 4 << 20
DIRECTORY = 'huff0-fec1-runtime'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 5 << 20, 'wall_seconds': 60}
SOURCES = ('cmake/huff0-fec1.cmake', 'native/worker/huff0_fec1_control.cpp',
           'native/runtime/plugin_loader.cpp', 'native/runtime/plugin_loader.hpp',
           'src/tsbench/planner/m3_huff0_fec1.py', 'src/tsbench/application/m3_huff0_fec1.py',
           'src/tsbench/qualification/huff0.py', 'src/tsbench/recovery.py',
           'src/tsbench/supervisor/isolated_worker.py')


def bind(root, build):
    plugin = build['plugins'].get(PLUGIN)
    if plugin is None:
        return None
    lib = plugin['library']
    executable = (PurePosixPath(lib['path']).parent / TARGET).as_posix()
    if not (root / executable).is_file():
        return None
    dependency, = plugin['dependencies']
    require(PurePosixPath(dependency['path']).name == 'libreference.so', 'FEC1 library differs from frozen reference')
    tool = {'path': executable, 'sha256': digest(local_file(root, executable))}
    return {'decoder': plan_recovery(root, {}, [], tools={TARGET: tool}, libraries=[lib, dependency]),
            'launchers': launcher_lock(), 'limits': LIMITS, 'process_input_limit_bytes': BATCH,
            'code': {p: digest(local_file(root, p)) for p in SOURCES}}


def check_route(rule):
    require(rule['view'] == 'v_bytes_interleaved' and rule['operation'] == 'roundtrip' and
            rule['partition'] == 'full' and rule['missing'] == 'preserve' and rule['options'] == {} and
            rule['bytes_per_unit'] == UNIT, 'FEC1 input policy differs from frozen route')
