"""Bind real-corpus ZFP routes to a control using the locked Unique CPU library."""
from pathlib import Path

from ..assets import digest, local_file, require, verify_asset

DRIVER = 'zfp-corpus-control/1'
PLUGIN = 'zfp-reversible'
ROUTES = {(31, name) for name in ('field-baseline', 'field-modes', 'openmp-encode', 'fixed-rate-array')}
SOURCES = ('cmake/m3-controls.cmake', 'plugins/codecs/zfp-reversible/corpus_control.cpp',
           'src/tsbench/application/m3_zfp.py', 'src/tsbench/application/m3_sprintz_query.py',
           'src/tsbench/planner/m3_zfp.py', 'src/tsbench/planner/zfp_execution.py')


def bind_corpus(root, build):
    plugin = build['plugins'][PLUGIN]
    parent = Path(plugin['library']['path']).parent
    exe = (parent / 'tsbench_zfp_corpus_control').as_posix()
    if not (root / exe).is_file():
        return None
    dependency = (parent / 'libzfp_native_c.so').as_posix()
    require(len(plugin['dependencies']) == 1 and plugin['dependencies'][0]['path'] == dependency,
            'ZFP corpus control must share the locked C11 dependency')
    native = verify_asset(root, plugin['dependencies'][0])
    control = local_file(root, exe)
    return {'executable': {'path': exe, 'bytes': control.stat().st_size, 'sha256': digest(control)},
            'dependency': {'path': dependency, 'bytes': native.stat().st_size, 'sha256': digest(native)},
            'code': {f: digest(local_file(root, f)) for f in SOURCES}}


def check_route(binding):
    route = binding['route']
    common = {'mode': 'reversible', 'rank': 1}
    wanted = {'field-baseline': ('roundtrip', common),
              'field-modes': ('roundtrip', {**common, 'other_modes': 'explicit_specialized_cases'}),
              'openmp-encode': ('encode_worker_comparison', {**common, 'threads': [1, 2]}),
              'fixed-rate-array': ('mutate_flush_reopen', {'schema': 'distinct_array_format'})}
    require(binding['view'] == 'f64_columns' and binding['partition'] == 'full' and
            binding.get('rows_per_unit') is None and (binding['operation'], binding['options']) == wanted[route],
            'ZFP real-corpus route differs from the frozen profile')
