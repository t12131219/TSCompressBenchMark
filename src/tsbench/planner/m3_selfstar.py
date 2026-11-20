"""Bind full-column SElf* routes and the existing frozen ordered fixtures."""
from pathlib import Path

from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import selfstar_execution as probes

DRIVERS = {(4, probes.PLUGIN): 'selfstar-public-abi-column/1',
           (4, probes.LIVE): 'selfstar-native-finalized-column/1'}
DRIVER = 'selfstar-specialized/1'
CORPUS_TOOL = 'selfstar-corpus-control'
CORPUS_TARGET = 'tsbench_selfstar_corpus_control'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 256 << 10, 'wall_seconds': 15}
CODE = (*probes.SOURCES, 'plugins/codecs/selfstar-batch/corpus_control.cpp', 'src/tsbench/planner/m3_selfstar.py',
        'src/tsbench/application/m3_selfstar.py', 'src/tsbench/application/m3_sprintz_query.py',
        'src/tsbench/recovery.py', 'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py')


def available(root, build):
    parent = Path(build['plugins'][probes.PLUGIN]['library']['path']).parent
    return all((root / parent / exe).is_file() for exe in (probes.TARGET, CORPUS_TARGET))


def bind_selfstar(root, build, obligations):
    require(available(root, build), 'missing SElf* corpus or specialist control')
    parent = Path(build['plugins'][probes.PLUGIN]['library']['path']).parent
    products, cases = probes.selfstar_inputs(root)
    rows = [r for r in obligations if (r['selection'], r['route']) in DRIVERS]
    mapping = {}
    seen = set()
    require(len(cases) == len(rows) == 9 and all(r['kind'] == 'required' for r in rows), 'SElf* frozen obligation scope differs')
    for row in rows:
        case, = row['planned_case_inputs']
        cid = case['case_id']
        require(cid in cases and cid not in seen and case['bundle_key'] == 'selfstar_cases' and
                case['bundle_id'] == cases[cid][0] and
                all(products[sid][0]['method'] == row['route'] for sid in cases[cid][1]), 'SElf* fixture or route differs')
        seen.add(cid)
        mapping[row['obligation_id']] = cases[cid][1]
    require(len(products) == 25 and set().union(*mapping.values()) == products.keys(), 'SElf* fixture coverage differs')
    validate_limits(LIMITS)
    require(all(max(s['original']['bytes'], max(s['parts'].values(), default=0)) <= LIMITS['file_bytes']
                for s, _ in products.values()), 'SElf* specialist exceeds size bound')
    tools = {key: {'path': (parent / target).as_posix(), 'sha256': digest(local_file(root, (parent / target).as_posix()))}
             for key, target in ((probes.TOOL, probes.TARGET), (CORPUS_TOOL, CORPUS_TARGET))}
    decoder = plan_recovery(root, build, {probes.PLUGIN: {'plugin': probes.PLUGIN, 'options': {}}}, tools=tools)
    return {'driver': DRIVER, 'limits': dict(LIMITS), 'launchers': launcher_lock(), 'decoder': decoder,
            'code': {p: digest(local_file(root, p)) for p in CODE}, 'obligation_slots': mapping,
            'slots': {sid: slot for sid, (slot, _) in products.items()}}
