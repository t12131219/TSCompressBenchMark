"""Connect Sprintz source, ABI and native controls to the accepted M0 cases."""
from pathlib import Path

from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import sprintz_execution as sprintz

BATCH = (19, 'fire-batch')
QUERY = (19, 'query')
DRIVER = 'sprintz-corpus-batch-abi/1'
SPECIALIZED = 'sprintz-specialized/1'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 15}
CODE = (*sprintz.SOURCES, 'src/tsbench/planner/m3_sprintz.py', 'src/tsbench/application/m3_sprintz.py',
        'src/tsbench/application/m3_sprintz_query.py', 'src/tsbench/recovery.py',
        'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py')


def bind_sprintz(root, build, obligations, query_control):
    if query_control is None:
        return None
    plugin = build['plugins'][sprintz.PLUGIN]
    direct = Path(plugin['library']['path']).with_name(sprintz.TARGET).as_posix()
    if not (root / direct).is_file():
        return None
    dependency, = plugin['dependencies']
    require(all(query_control['dependency'][k] == dependency[k] for k in ('sha256', 'path')),
            'Sprintz batch, query and specialist dependencies differ')
    products, cases = sprintz.sprintz_inputs()
    targets = [o for o in obligations if (o['selection'], o['route']) in sprintz.ROUTES]
    require(len(targets) == len(cases) == 10 and all(o['kind'] == 'required' for o in targets),
            'Sprintz specialist obligation scope differs')
    mapping = {}
    seen_cases = set()
    for row in targets:
        case, = row['planned_case_inputs']
        cid = case['case_id']
        require(cid in cases and cid not in seen_cases and case['bundle_key'] == 'sprintz_cases' and
                cases[cid][0] == case['bundle_id'] and all(products[sid][0]['method'] == sprintz.ROUTES[19, row['route']]
                                                        for sid in cases[cid][1]), 'Sprintz fixture origin or route differs')
        seen_cases.add(cid)
        mapping[row['obligation_id']] = cases[cid][1]
    require(set().union(*mapping.values()) == products.keys(), 'Sprintz specialist slot coverage differs')
    validate_limits(LIMITS)
    require(all(sprintz.file_limit(s) <= 1 << 20 for s, _ in products.values()), 'Sprintz slot exceeds supervisor ceiling')
    tools = {sprintz.TOOL: {'path': direct, 'sha256': digest(local_file(root, direct))}}
    decoder = plan_recovery(root, build, {sprintz.PLUGIN: sprintz.ABI_METHOD}, tools=tools)
    return {'driver': SPECIALIZED, 'decoder': decoder, 'limits': dict(LIMITS), 'launchers': launcher_lock(),
            'code': {p: digest(local_file(root, p)) for p in CODE}, 'obligation_slots': mapping,
            'slots': {sid: s for sid, (s, _) in products.items()}}
