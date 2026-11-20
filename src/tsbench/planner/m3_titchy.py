"""Bind Titchy's four native routes to the accepted M0 specialist cases."""
from pathlib import Path

from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import titchy_execution as access, titchy_stream as stream, typed_batch as batch
from .linear_batch import EXTENDED, MIXED_SCHEMA

BATCH = (85, 'batch')
BATCH_DRIVER = 'titchy-corpus-batch-abi/1'
DRIVER = 'titchy-specialized/1'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 15}
CODE = tuple(dict.fromkeys((*batch.SOURCES, *access.SOURCES, *stream.SOURCES,
        'src/tsbench/planner/m3_titchy.py', 'src/tsbench/application/m3_titchy.py',
        'src/tsbench/application/m3_titchy_access.py', 'src/tsbench/application/m3_titchy_stream.py',
        'src/tsbench/application/m3_sprintz_query.py', 'src/tsbench/application/batch_execution.py',
        'src/tsbench/planner/linear_batch.py', 'src/tsbench/recovery.py',
        'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py')))


def inputs(root):
    typed, causes = batch.typed_inputs(root, LIMITS['file_bytes'])
    products = {sid: pair for sid, pair in typed.items() if pair[0]['method'] == batch.TITCHY}
    binds = {cid: (bundle, ids) for cid, (bundle, ids) in causes.items() if set(ids) <= products.keys()}
    for fn in (stream.stream_inputs, access.access_inputs):
        rows, cases = fn(root)
        require(not rows.keys() & products.keys() and not cases.keys() & binds.keys(), 'duplicate Titchy specialist identity')
        products.update(rows)
        binds.update(cases)
    return products, binds


def bind_titchy(root, build, obligations, access_control, stream_control):
    if not (access_control and stream_control):
        return None
    plugin = build['plugins'][batch.TITCHY]
    parent = Path(plugin['library']['path']).parent
    targets = ((batch.TITCHY_TOOL, batch.TITCHY_TARGET), (stream.TOOL, stream.TARGET), (access.TOOL, access.TARGET))
    if not all((root / parent / exe).is_file() for _, exe in targets):
        return None
    dependency, = plugin['dependencies']
    require(all(all(c['dependency'][k] == dependency[k] for k in ('path', 'sha256')) for c in (access_control, stream_control)),
            'Titchy batch, stream and access dependencies differ')
    products, cases = inputs(root)
    by_route = {'batch': batch.TITCHY, 'packet-stream': stream.METHOD, **{k[1]: m for k, m in access.ROUTES.items()}}
    accepted = [r for r in obligations if r['selection'] == 85]
    require(len(cases) == len(accepted) == 22 and all(r['kind'] == 'required' for r in accepted), 'Titchy specialist obligations differ')
    seen, mapping = set(), {}
    for row in accepted:
        case, = row['planned_case_inputs']
        cid = case['case_id']
        require(cid in cases and cid not in seen and case['bundle_id'] == cases[cid][0] and
                case['bundle_key'] in {'titchy_native_cases', 'titchy_access_cases'} and
                all(products[sid][0]['method'] == by_route[row['route']] for sid in cases[cid][1]), 'Titchy specialist case differs')
        seen.add(cid)
        mapping[row['obligation_id']] = cases[cid][1]
    require(len(products) == 18 and set().union(*mapping.values()) == products.keys(), 'Titchy specialist product coverage differs')
    validate_limits(LIMITS)
    require(all(max(len(sample.schema), *(len(col) for col in sample.columns),
                    slot.get('max_frame_bytes', max(slot.get('parts', {}).values(), default=0))) <= LIMITS['file_bytes']
                for slot, sample in products.values()), 'Titchy specialist exceeds file ceiling')
    tools = {key: {'path': (parent / target).as_posix(), 'sha256': digest(local_file(root, (parent / target).as_posix()))}
             for key, target in targets}
    methods = {batch.TITCHY: batch.METHODS[batch.TITCHY]}
    decoder = plan_recovery(root, build, methods, tools=tools)
    return {'driver': DRIVER, 'schema': MIXED_SCHEMA, 'suite': EXTENDED, 'decoder': decoder, 'methods': methods,
            'direct_control': {'tool_refs': tools}, 'limits': dict(LIMITS), 'launchers': launcher_lock(),
            'obligation_slots': mapping, 'slots': {sid: slot for sid, (slot, _) in products.items()},
            'code': {p: digest(local_file(root, p)) for p in CODE}}
