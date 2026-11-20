"""Bind named M3 Huff0 obligations to same-run native products and recovery assets."""
from pathlib import PurePosixPath

from ..assets import digest, load_json, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import huff0_bmi2 as bmi2
from . import huff0_execution as native
from .huff0 import plan_huff0

DRIVER = 'huff0-specialized/1'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 30}
SOURCES = (*native.SOURCES, *bmi2.SOURCES, 'src/tsbench/planner/m3_huff0_specialized.py',
           'src/tsbench/application/m3_huff0_specialized.py', 'src/tsbench/planner/native_conditions.py',
           'src/tsbench/planner/linear_batch.py', 'src/tsbench/supervisor/process.py')


def bind_obligations(root, obligations, slots, cases):
    bundle, _ = plan_huff0(root)
    declared = {c['case_id']: c for c in bundle['cases']}
    required, seen, conditional = {}, set(), None
    table_slots = [key for key, s in slots.items() if s['method'] == native.SHARED]
    for ob in obligations:
        if (ob['selection'], ob['route']) not in native.ROUTES:
            continue
        if bmi2.supports_condition(ob):
            require(conditional is None and not ob.get('planned_case_inputs') and
                    ob['condition_case']['bundle_id'] == bundle['bundle_id'], 'Huff0 BMI2 condition identity differs')
            # Validate the same frozen predicate and criteria even without a portable build.
            compared = [{**s, bmi2.KEY: True} for s in slots.values() if not s['expected_status']]
            conditional = {'obligation_id': ob['obligation_id'], 'slots': bmi2.condition_slots(ob, compared)}
            continue
        require(ob['kind'] == 'required' and len(ob['planned_case_inputs']) == 1, 'Huff0 named obligation scope differs')
        ref, = ob['planned_case_inputs']
        cid = ref['case_id']
        require(cid in declared and cid not in seen and ref['bundle_key'] == 'huff0_cases' and
                ref['bundle_id'] == bundle['bundle_id'] == cases[cid][0] and
                (ref['case_name'], ob['check'], ob['selection'], ob['route']) ==
                tuple(declared[cid][k] for k in ('name', 'check', 'selection', 'route')),
                'Huff0 named case differs from M0 definition')
        seen.add(cid)
        members = cases[cid][1]
        require(all(slots[p]['method'] == ob['route'] for p in members), 'Huff0 named case bound to wrong lane')
        if ob['check'] == 'fec1_fixed_4x_etb1_stream_boundary':
            members = [*members, *table_slots]
        required[ob['obligation_id']] = sorted(members)
    require(seen == declared.keys() and len(required) == 11 and conditional is not None and
            {p for members in required.values() for p in members} == slots.keys(),
            'Huff0 named evidence coverage differs')
    return required, conditional


def bind(root, build, obligations, fec1, table, portable_build=None):
    plugin = build['plugins'][native.PLUGIN]['library']
    executable = PurePosixPath(plugin['path']).with_name(native.TARGET).as_posix()
    if fec1 is None or table is None or not (root / executable).is_file():
        require(portable_build is None, 'Huff0 portable control requires both frozen corpus drivers and direct native tool')
        return None
    validate_limits(LIMITS)
    tools = {native.TOOL: {'path': executable, 'sha256': digest(local_file(root, executable))}}
    decoder = plan_recovery(root, build, [native.PLUGIN], tools=tools)
    lib = 'lib/libreference.so'
    require('libreference.so' in decoder['files'][decoder['tools'][native.TOOL]]['needed'] and
            decoder['files'][lib] == fec1['decoder']['files'][lib] and
            {k: decoder['files'][lib][k] for k in ('bytes', 'sha256')} ==
            {k: table['dependency'][k] for k in ('bytes', 'sha256')} and
            decoder['files'][lib]['source'] == table['dependency']['path'], 'Huff0 specialist and corpus library differ')
    portable = None
    if portable_build is not None:
        archive = load_json(local_file(root, 'third_party/sources.lock.json'))['sources']['FiniteStateEntropy']['archive']['sha256']
        portable = bmi2.plan_control(root, decoder, native.TOOL, portable_build, archive)
    fixtures, cases = native.huff0_inputs(root, compare_bmi2=portable is not None)
    slots = {key: slot for key, (slot, _) in fixtures.items()}
    native.check_slots({'slots': list(slots.values()), 'limits': LIMITS, 'suite': bmi2.SUITE if portable else None})
    require(all(max([native.input_bytes(s), *s['parts'].values()]) <= LIMITS['file_bytes'] for s in slots.values()),
            'Huff0 specialist fixture or product exceeds its file budget')
    mapping, condition = bind_obligations(root, obligations, slots, cases)
    return {'driver': DRIVER, 'decoder': decoder, 'limits': LIMITS, 'launchers': launcher_lock(),
            'slots': slots, 'required_slots': mapping, 'condition': condition,
            **({bmi2.KEY: portable} if portable else {}),
            'code': {p: digest(local_file(root, p)) for p in SOURCES}}
