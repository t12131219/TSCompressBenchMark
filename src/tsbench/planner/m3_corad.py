"""Bind the CORAD corpus routes to one native library and a train-only Source runtime."""
from pathlib import PurePosixPath

from ..application.corad_corpus_execution import LIMITS, SOURCE_LIMITS, TOOL
from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from .corad_corpus import INFERENCE, TRAINERS
from .corad_training import plan_corad_training
from .corad_training_execution import source_runtime

METHOD = 'corad-frozen'
TARGET = 'tsbench_corad_corpus_control'
DRIVER = 'corad-same-run-corpus/1'
ROUTES = {(80, route) for route in (INFERENCE, *TRAINERS)}
FOLDER = 'corad-corpus'
PARALLEL_CEILING = 4
SOURCES = ('plugins/codecs/corad-frozen/corpus_control.c', 'plugins/codecs/corad-frozen/CMakeLists.txt',
           'src/tsbench/application/corad_corpus_execution.py', 'src/tsbench/application/m3_corad.py',
           'src/tsbench/planner/m3_corad.py', 'src/tsbench/planner/m3_corad_ingress.py',
           'src/tsbench/planner/corad_corpus.py', 'src/tsbench/planner/corad_training.py',
           'src/tsbench/planner/corad_training_execution.py', 'src/tsbench/qualification/corad_wire.py',
           'src/tsbench/qualification/corad_training.py', 'src/tsbench/supervisor/corad_source.py',
           'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py', 'src/tsbench/recovery.py')


def bind(root, build):
    plugin = build['plugins'][METHOD]
    executable = PurePosixPath(plugin['library']['path']).with_name(TARGET).as_posix()
    if not (root / executable).is_file():
        return None
    tool = {'path': executable, 'sha256': digest(local_file(root, executable))}
    decoder = plan_recovery(root, build, [METHOD], tools={TOOL: tool})
    lib, = plugin['dependencies']
    require(PurePosixPath(lib['path']).name == 'libcorad_c.so' and
            'libcorad_c.so' in decoder['files'][decoder['tools'][TOOL]]['needed'] and
            decoder['files']['lib/libcorad_c.so']['sha256'] == lib['sha256'], 'CORAD control does not bind the frozen native dependency')
    source, _ = plan_corad_training(root)
    for limits in (LIMITS, SOURCE_LIMITS):
        validate_limits(limits)
    return {'driver': DRIVER, 'decoder': decoder, 'source_runtime': source_runtime(root, source),
            'source_bridge_sha256': source['bridge_sha256'], 'source_archive_sha256': source['archive_sha256'],
            'limits': {'native': LIMITS, 'source': SOURCE_LIMITS}, 'launchers': launcher_lock(),
            'parallel_cohorts_max': PARALLEL_CEILING, 'code': {p: digest(local_file(root, p)) for p in SOURCES}}


def check_route(rule):
    inference = rule['route'] == INFERENCE
    layout = rule['corad_layout']
    require(rule['view'] == 'f64_multicolumn' and rule['missing'] == 'require_no_retained_sentinel' and
            rule['operation'] == ('model_roundtrip' if inference else 'train_validate_and_separate_heldout_inference') and
            rule['partition'] == ('test' if inference else 'train_test') and rule['options'] == {} and
            layout == {'profile': 'corad_ordered_cohort_train_and_test_v1', 'max_columns': 8, 'train_rows': 129,
                       'max_test_rows_per_frame': 4096, 'max_values_per_frame': 131072, 'tricklet': 4, 'atoms': 4,
                       'nonzero': 2, 'threshold': 0.9, 'model_bytes_limit': 16384, 'alpha': 0.25,
                       'c_lars': {'seed': 20261103, 'max_iter': 6, 'solver_max_iter': 4000,
                                  'objective_tolerance': 1e-8, 'solver_tolerance': 1e-8},
                       'source_bridge': {'iterations': 10, 'timeout_seconds': 25, 'rng': 'shipped_default',
                                         'runtime': 'locked_tsbench'}}, 'CORAD execution profile differs from the frozen scope')
