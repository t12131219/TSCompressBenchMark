"""Frozen Zstd and ALP batch routes for the bounded product executor."""
from pathlib import PurePosixPath

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, require
from ..recovery import check_recovery, plan_recovery
from ..runtime import resolve_worker
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from .alp import plan_alp
from .gorilla import max_payload, sha
from .lzbench import plan_lzbench, sample
from .method_boundaries import plan_boundary_cases
from .native_admission import plan_native_admission
from . import typed_batch as typed
from . import xz_batch as xz
from . import pcodec_batch as pco
from . import pcodec_pages as pages
from . import selfstar_execution as selfstar
from . import huff0_execution as huff
from . import huff0_bmi2 as bmi2
from . import sprintz_execution as sprintz
from . import titchy_execution as access
from . import titchy_stream as stream
from . import pcodec_intmult as intmult
from . import gorilla_state as state
from . import lzbench_session as sessions
from . import lzbench_profiles as profiles
from . import alp_decode as decode
from . import zfp_execution as zfp
from . import pbepla_execution as pbepla
from . import corad_execution as corad
from . import corad_training_execution as training

EXTENDED = 'extended-v1'
EXTENDED_XZ = 'extended-v2'
EXTENDED_PCO = 'extended-v3'
EXTENDED_WRAPPED = 'extended-v4'
UNIFIED = 'extended-v5'
UNIFIED_POLICY = 'configs/suites/m3_first_batch_native_v2/unified-batch-execution.json'
ORDERED = 'extended-v6'
ORDERED_POLICY = 'configs/suites/m3_first_batch_native_v2/ordered-batch-execution.json'
ENTROPY = 'extended-v7'
ENTROPY_POLICY = 'configs/suites/m3_first_batch_native_v2/entropy-batch-execution.json'
SPRINTZ = 'extended-v8'
SPRINTZ_POLICY = 'configs/suites/m3_first_batch_native_v2/sprintz-batch-execution.json'
ACCESS = 'extended-v9'
ACCESS_POLICY = 'configs/suites/m3_first_batch_native_v2/titchy-access-execution.json'
STREAM = 'extended-v10'
STREAM_POLICY = 'configs/suites/m3_first_batch_native_v2/titchy-stream-execution.json'
INTMULT = 'extended-v11'
INTMULT_POLICY = 'configs/suites/m3_first_batch_native_v2/pcodec-intmult-execution.json'
GORILLA_STATE = 'extended-v12'
GORILLA_STATE_POLICY = 'configs/suites/m3_first_batch_native_v2/gorilla-state-execution.json'
LZBENCH_SESSION = 'extended-v13'
LZBENCH_SESSION_POLICY = 'configs/suites/m3_first_batch_native_v2/lzbench-session-execution.json'
LZBENCH_PROFILES = 'extended-v14'
LZBENCH_PROFILES_POLICY = 'configs/suites/m3_first_batch_native_v2/lzbench-profiles-execution.json'
ALP_DECODE = 'extended-v15'
ALP_DECODE_POLICY = 'configs/suites/m3_first_batch_native_v2/alp-decode-execution.json'
ZFP_NATIVE = 'extended-v16'
ZFP_NATIVE_POLICY = 'configs/suites/m3_first_batch_native_v2/zfp-native-execution.json'
PBEPLA_NATIVE = 'extended-v17'
PBEPLA_NATIVE_POLICY = 'configs/suites/m3_first_batch_native_v2/pbepla-native-execution.json'
CORAD_INFERENCE = 'extended-v18'
CORAD_INFERENCE_POLICY = 'configs/suites/m3_first_batch_native_v2/corad-inference-execution.json'
CORAD_TRAINING = 'extended-v19'
CORAD_TRAINING_POLICY = 'configs/suites/m3_first_batch_native_v2/corad-training-execution.json'
CORAD_TRAINING_SUITES = {CORAD_TRAINING,bmi2.SUITE}
CORAD_INFERENCE_SUITES = {CORAD_INFERENCE,*CORAD_TRAINING_SUITES}
PBEPLA_NATIVE_SUITES = {PBEPLA_NATIVE,*CORAD_INFERENCE_SUITES}
ZFP_NATIVE_SUITES = {ZFP_NATIVE,*PBEPLA_NATIVE_SUITES}
ALP_DECODE_SUITES = {ALP_DECODE,*ZFP_NATIVE_SUITES}
LZBENCH_PROFILE_SUITES = {LZBENCH_PROFILES,*ALP_DECODE_SUITES}
LZBENCH_SESSION_SUITES = {LZBENCH_SESSION,*LZBENCH_PROFILE_SUITES}
GORILLA_STATE_SUITES = {GORILLA_STATE,*LZBENCH_SESSION_SUITES}
INTMULT_SUITES = {INTMULT, *GORILLA_STATE_SUITES}
STREAM_SUITES = {STREAM, *INTMULT_SUITES}
ACCESS_SUITES = {ACCESS, *STREAM_SUITES}
SPRINTZ_SUITES = {SPRINTZ, *ACCESS_SUITES}
ENTROPY_SUITES = {ENTROPY, *SPRINTZ_SUITES}
ORDERED_SUITES = {ORDERED, *ENTROPY_SUITES}
UNIFIED_SUITES = {UNIFIED, *ORDERED_SUITES}
WRAPPED_SUITES = {EXTENDED_WRAPPED, *UNIFIED_SUITES}


def protocol_methods(suite):
    return {**pages.METHODS, **({selfstar.LIVE:selfstar.LIVE_METHOD} if suite in ORDERED_SUITES else {}),
            **({huff.SHARED:huff.METHOD} if suite in ENTROPY_SUITES else {}),
            **({sprintz.QUERY:sprintz.QUERY_METHOD} if suite in SPRINTZ_SUITES else {}),
            **(access.METHODS if suite in ACCESS_SUITES else {}),
            **(stream.METHODS if suite in STREAM_SUITES else {}),
            **(intmult.METHODS if suite in INTMULT_SUITES else {}),
            **(state.METHODS if suite in GORILLA_STATE_SUITES else {}),
            **(sessions.METHODS if suite in LZBENCH_SESSION_SUITES else {}),
            **(profiles.METHODS if suite in LZBENCH_PROFILE_SUITES else {}),
            **(decode.METHODS if suite in ALP_DECODE_SUITES else {}),
            **(zfp.METHODS if suite in ZFP_NATIVE_SUITES else {}),
            **(pbepla.METHODS if suite in PBEPLA_NATIVE_SUITES else {}),
            **(training.METHODS if suite in CORAD_TRAINING_SUITES else {})}

TYPED_SUITES = {EXTENDED, EXTENDED_XZ, EXTENDED_PCO, *WRAPPED_SUITES}
XZ_SUITES = {EXTENDED_XZ, EXTENDED_PCO, *WRAPPED_SUITES}
PCODEC_SUITES = {EXTENDED_PCO, *WRAPPED_SUITES}


SCHEMA = 'bmk.lossless-batch-execution/3'
MIXED_SCHEMA = 'bmk.native-batch-execution/1'
LINEAR_SCHEMAS = {SCHEMA,MIXED_SCHEMA}
POLICY = 'configs/suites/m3_first_batch_native_v2/linear-batch-execution.json'
METHODS = {'alp-auto': {'plugin': 'alp-auto', 'options': {'decode_backend': 'scalar-unfused'}},
           'zstd': {'plugin': 'zstd', 'options': {}}}
ROUTES = {9: ('auto-batch', 'alp-auto'), 40: ('zstd-baseline', 'zstd')}
ZSTD_TOOL = 'zstd-upstream-direct'
ZSTD_TARGET = 'tsbench_zstd_batch_control'
ZSTD_SOURCE = 'plugins/codecs/zstd/direct_control.c'
FENV_TOOL = 'alp-fenv-direct'
FENV_TARGET = 'tsbench_alp_fenv_control'
FENV_SOURCE = 'plugins/codecs/alp-auto/fenv_control.c'
FENV_CHECK = 'rounding_mode_controls'
PENDING = {FENV_CHECK: 'non_default_rounding_native_driver_not_bound'}
REJECTIONS = {
    'alp-auto': ('exception_out_of_range', 'duplicate_exception_position'),
    'zstd': ('wrong_output_count', 'truncated_payload'),
}


def linear_inputs(root, max_frame_bytes):
    from .batch_execution import BatchInput

    boundary, boundary_cases = plan_boundary_cases(root)
    alp, originals = plan_alp(root)
    lz = plan_lzbench(root)
    products, binds = {}, {}

    def add(method, name, dtype, rows, data, schema, lineage, *, status=0, checks=None, negatives=(), upstream=False):
        c = {'columns': [{'dtype': dtype, 'count': rows}], 'column_bytes': [len(data)], 'column_sha256': [sha(data)],
             'schema_bytes': len(schema), 'schema_sha256': sha(schema)}
        require(len(data) == rows*{2:1, 9:4, 10:8}[dtype], 'invalid one-column input extent')
        frame = max_frame_bytes if method == 'alp-auto' else 66000+32+len(schema)
        body = {'name': name, 'method': method, 'lineage': lineage, 'original': c, 'expected_status': status,
                'max_frame_bytes': frame if not status else 0, 'wire_checks': checks or {},
                'reject_decodes': list(negatives), 'upstream_zstd': upstream}
        sid = content_id(body)
        require(sid not in products, 'duplicate linear batch product')
        products[sid] = {**body, 'product_slot': sid}, BatchInput(schema, (data,))
        return sid

    for case in boundary_cases:
        d = case.definition
        if d['selection'] not in ROUTES:
            continue
        row = d['row']
        method = row['method']
        require(d['options'] == METHODS[method]['options'], 'boundary options differ from candidate binding')
        n = add(method, row['case'], d['abi_types'][0], row['rows'], case.columns[0], case.schema, row,
                status={'verified':0, 'resource_limit_7':7}[row['expected']],
                checks={'vector_count': d['expected_aln1_vectors']} if method == 'alp-auto' else {})
        binds[d['case_id']] = boundary['bundle_id'], [n]

    by_label = {}
    for f in alp['fixtures']:
        name, width = f['name'], f['width']
        raw = originals[name]
        require(len(raw) == f['input_bytes'] and sha(raw) == f['input_sha256'], 'ALP fixture source differs')
        mixed = f['label'] == 'mixed-decimal-raw'
        checks = {'rowgroup_kinds': f['expected_kinds'], 'decimal_rd_raw_vectors': f['decimal_rd_raw_vectors'],
                  'special_exception_bits': mixed}
        by_label[name] = add('alp-auto', name, {32:9, 64:10}[width], f['count'], raw, f['schema'].encode('ascii'), f,
                             checks=checks, negatives=REJECTIONS['alp-auto'] if mixed else ())
    for c in alp['cases']:
        if c['route'] == 'auto-batch':
            binds[c['case_id']] = alp['bundle_id'], [by_label[f['name']] for f in c['criteria']['fixtures']]

    zstd_ids = {}
    for fixture in lz['baseline']:
        n, salt = (fixture['input'][key] for key in ('bytes', 'salt'))
        name = fixture['frame']
        if name == 'zstd-upstream.zst':
            continue  # Source shared with the max-cap legacy block; do not double count it.
        raw = sample(n, salt)
        require(sha(raw) == fixture['input']['sha256'], 'Zstd baseline fixture source differs')
        zstd_ids[n] = add('zstd', name, 2, n, raw, canonical_bytes({'dtype': 'u8', 'role': 'bytes'}), fixture,
                          negatives=REJECTIONS['zstd'], upstream=n == 65536)
    require(set(zstd_ids) == {0, 1, 65535, 65536}, 'Zstd synthetic source sizes differ')
    require(lz['baseline'][-1]['frame'] == 'zstd-upstream.zst' and
            lz['baseline'][-1]['input'] == products[zstd_ids[65536]][0]['lineage']['input'], 'Zstd upstream source differs')
    for c in lz['cases']:
        if c['route'] == 'zstd-baseline':
            binds[c['case_id']] = lz['bundle_id'], ([zstd_ids[65536]] if c['check'] == 'independent_upstream_frame'
                                                 else list(zstd_ids.values()))
    return products, binds


def _control_path(build):
    return PurePosixPath(build['plugins']['zstd']['library']['path']).with_name(ZSTD_TARGET)


def _fenv_path(build):
    return PurePosixPath(build['plugins']['alp-auto']['library']['path']).with_name(FENV_TARGET)


def _titchy_path(build):
    return PurePosixPath(build['plugins'][typed.TITCHY]['library']['path']).with_name(typed.TITCHY_TARGET)


def _xz_path(build):
    return PurePosixPath(build['plugins'][xz.METHOD]['library']['path']).with_name(xz.TARGET)


def _pcodec_path(build, target=pco.TARGET):
    paths = {PurePosixPath(build['plugins'][method]['library']['path']).with_name(target) for method in pco.METHODS}
    require(len(paths) == 1, 'pcodec direct control and both plugins must share a build directory')
    return paths.pop()


def _check_tools(spec):
    tool = spec['files'][spec['tools'][ZSTD_TOOL]]
    plugin = spec['files'][spec['plugins']['zstd']]
    require('liblzbench_native.so' in tool['needed'] and 'liblzbench_native.so' in plugin['needed'] and
            set(tool['needed']) <= {'liblzbench_native.so', 'libc.so.6'}, 'Zstd upstream control ELF binding differs')
    if FENV_TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][FENV_TOOL]]
        plugin = spec['files'][spec['plugins']['alp-auto']]
        require('libalp_native.so' in tool['needed'] and 'libalp_native.so' in plugin['needed'] and
                set(tool['needed']) <= {'libalp_native.so', 'libm.so.6', 'libc.so.6'}, 'ALP fenv control ELF binding differs')

    if typed.TITCHY_TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][typed.TITCHY_TOOL]]
        plugin = spec['files'][spec['plugins'][typed.TITCHY]]
        require('libtitchy_c.so' in tool['needed'] and 'libtitchy_c.so' in plugin['needed'] and
                set(tool['needed']) <= {'libtitchy_c.so', 'libc.so.6'}, 'Titchy direct control ELF binding differs')
    if xz.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][xz.TOOL]]
        plugin = spec['files'][spec['plugins'][xz.METHOD]]
        require('liblzbench_native.so' in tool['needed'] and 'liblzbench_native.so' in plugin['needed'] and
                set(tool['needed']) <= {'liblzbench_native.so', 'libstdc++.so.6', 'libgcc_s.so.1', 'libc.so.6'},
                'XZ direct control ELF binding differs')
    if pco.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][pco.TOOL]]
        libs = [spec['files'][spec['plugins'][method]] for method in pco.METHODS]
        require('libpcodec_c.so' in tool['needed'] and all('libpcodec_c.so' in p['needed'] for p in libs) and
                set(tool['needed']) <= {'libpcodec_c.so', 'libc.so.6'}, 'pcodec direct control ELF binding differs')
    if pages.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][pages.TOOL]]
        require('libpcodec_c.so' in tool['needed'] and
                set(tool['needed']) <= {'libpcodec_c.so','libstdc++.so.6','libgcc_s.so.1','libc.so.6'},
                'wrapped pcodec driver ELF dependency differs')


    if selfstar.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][selfstar.TOOL]]
        plugin = spec['files'][spec['plugins'][selfstar.PLUGIN]]
        require('libselfstar_c.so' in tool['needed'] and 'libselfstar_c.so' in plugin['needed'] and
                set(tool['needed']) <= {'libselfstar_c.so','libstdc++.so.6','libgcc_s.so.1','libc.so.6','libm.so.6'},
                'SElf* direct control ELF binding differs')


    if huff.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][huff.TOOL]]
        plugin = spec['files'][spec['plugins'][huff.PLUGIN]]
        require('libreference.so' in tool['needed'] and 'libreference.so' in plugin['needed'],
                'Huff0 direct driver and ABI must share the frozen reference library')


    if sprintz.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][sprintz.TOOL]]
        plugin = spec['files'][spec['plugins'][sprintz.PLUGIN]]
        require('librepaired_codec.so' in tool['needed'] and 'librepaired_codec.so' in plugin['needed'],
                'Sprintz native driver and ABI must share the frozen repaired codec')


    if state.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][state.TOOL]]
        plugin = spec['files'][spec['plugins']['gorilla-tv']]
        require('libgorilla_c.so' in tool['needed'] and 'libgorilla_c.so' in plugin['needed'] and
                set(tool['needed']) <= {'libgorilla_c.so','libc.so.6','libdl.so.2'},
                'Gorilla observer must use the same frozen C library without loading a plugin')
    if decode.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][decode.TOOL]]
        plugin = spec['files'][spec['plugins'][decode.PLUGIN]]
        require('libalp_native.so' in tool['needed'] and 'libalp_native.so' in plugin['needed'] and
                set(tool['needed']) <= {'libalp_native.so','libc.so.6'},'ALP direct decode ELF binding differs')
    for name in zfp.TARGETS.keys() & spec['tools'].keys():
        tool = spec['files'][spec['tools'][name]]
        plugin = spec['files'][spec['plugins'][zfp.PLUGIN]]
        require('libzfp_native_c.so' in tool['needed'] and 'libzfp_native_c.so' in plugin['needed'] and
                set(tool['needed']) <= {'libzfp_native_c.so','libstdc++.so.6','libgcc_s.so.1','libm.so.6','libc.so.6','libdl.so.2'},
                'ZFP direct tool must use the sealed native CPU library')
    for name in {corad.TOOL,training.TOOL} & spec['tools'].keys():
        tool = spec['files'][spec['tools'][name]]
        plugin = spec['files'][spec['plugins'][corad.METHOD]]
        require('libcorad_c.so' in tool['needed'] and 'libcorad_c.so' in plugin['needed'] and
                set(tool['needed']) <= {'libcorad_c.so','libc.so.6','libm.so.6'},
                'CORAD direct tool must use the sealed C library without loading the ABI adapter')
    for name in pbepla.TARGETS.keys() & spec['tools'].keys():
        tool = spec['files'][spec['tools'][name]]
        plugin = spec['files'][spec['plugins'][pbepla.PLUG]]
        require('libtba_native.so' in tool['needed'] and 'libtba_native.so' in plugin['needed'] and
                set(tool['needed']) <= {'libtba_native.so','libstdc++.so.6','libgcc_s.so.1','libm.so.6','libc.so.6','libdl.so.2'},
                'PBEPLA direct tool must use the sealed native library without the ABI adapter')
    for name in {sessions.TOOL,*profiles.TARGETS} & spec['tools'].keys():
        tool = spec['files'][spec['tools'][name]]
        require('liblzbench_native.so' in tool['needed'] and
                all('liblzbench_native.so' in spec['files'][spec['plugins'][p]]['needed'] for p in ('zstd',xz.METHOD)) and
                set(tool['needed']) <= {'liblzbench_native.so','libstdc++.so.6','libgcc_s.so.1','libc.so.6'},
                'lzbench session tool must link the frozen library without batch plugins')
    if stream.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][stream.TOOL]]
        plugin = spec['files'][spec['plugins'][typed.TITCHY]]
        require('libtitchy_c.so' in tool['needed'] and 'libtitchy_c.so' in plugin['needed'] and
                set(tool['needed']) <= {'libtitchy_c.so','libstdc++.so.6','libgcc_s.so.1','libc.so.6'},
                'Titchy stream must use the frozen C library without the batch adapter')
    if access.TOOL in spec['tools']:
        tool = spec['files'][spec['tools'][access.TOOL]]
        plugin = spec['files'][spec['plugins'][typed.TITCHY]]
        require('libtitchy_c.so' in tool['needed'] and 'libtitchy_c.so' in plugin['needed'],
                'Titchy access and batch must use the same frozen C library')


def _stream_path(build):
    return PurePosixPath(build['plugins'][typed.TITCHY]['library']['path']).with_name(stream.TARGET)


def _access_path(build):
    return PurePosixPath(build['plugins'][typed.TITCHY]['library']['path']).with_name(access.TARGET)


def _sprintz_path(build):
    return PurePosixPath(build['plugins'][sprintz.PLUGIN]['library']['path']).with_name(sprintz.TARGET)


def _huff_path(build):
    return PurePosixPath(build['plugins'][huff.PLUGIN]['library']['path']).with_name(huff.TARGET)


def _selfstar_path(build):
    return PurePosixPath(build['plugins'][selfstar.PLUGIN]['library']['path']).with_name(selfstar.TARGET)


def _suite_definition(suite):
    require(suite in {'linear-v1', *TYPED_SUITES}, 'unknown linear suite')
    routes = {(n,route):method for n,(route,method) in ROUTES.items()}
    policy, methods = POLICY, {**METHODS}
    if suite in TYPED_SUITES:
        policy = typed.POLICY
        routes.update({(n,route):method for n,(route,method) in typed.ROUTES.items()})
        methods.update(typed.METHODS)
    if suite in XZ_SUITES:
        policy = xz.POLICY
        routes[(39,xz.METHOD)] = xz.METHOD
        methods[xz.METHOD] = {'plugin':xz.METHOD,'options':{}}
    if suite in PCODEC_SUITES:
        policy = pco.POLICY
        routes.update(pco.ROUTES)
        methods.update(pco.METHODS)
    if suite in WRAPPED_SUITES:
        policy = pages.POLICY
        routes.update(pages.ROUTES)
    if suite in UNIFIED_SUITES:
        from .batch_execution import METHOD, PLUGIN
        policy = UNIFIED_POLICY
        routes[7,'tv-batch'] = PLUGIN
        methods[PLUGIN] = METHOD
    if suite in ORDERED_SUITES:
        policy = ORDERED_POLICY
        routes.update(selfstar.ROUTES)
        methods[selfstar.PLUGIN] = {'plugin':selfstar.PLUGIN,'options':{}}
    if suite in ENTROPY_SUITES:
        policy = ENTROPY_POLICY
        routes.update(huff.ROUTES)
        methods[huff.PLUGIN] = {'plugin':huff.PLUGIN,'options':{}}
    if suite in SPRINTZ_SUITES:
        policy = SPRINTZ_POLICY
        routes.update(sprintz.ROUTES)
        methods[sprintz.PLUGIN] = sprintz.ABI_METHOD
    if suite in ACCESS_SUITES:
        policy = ACCESS_POLICY
        routes.update(access.ROUTES)
    if suite in STREAM_SUITES:
        policy = STREAM_POLICY
        routes.update(stream.ROUTES)
    if suite in INTMULT_SUITES:
        policy = INTMULT_POLICY
        routes.update(intmult.ROUTES)
    if suite in GORILLA_STATE_SUITES:
        policy = GORILLA_STATE_POLICY
        routes.update(state.ROUTES)
    if suite in LZBENCH_SESSION_SUITES:
        policy = LZBENCH_SESSION_POLICY
        routes.update(sessions.ROUTES)
    if suite in LZBENCH_PROFILE_SUITES:
        policy = LZBENCH_PROFILES_POLICY
        routes.update(profiles.ROUTES)
    if suite in ALP_DECODE_SUITES:
        policy = ALP_DECODE_POLICY
        routes[decode.ROUTE] = decode.METHOD
    if suite in ZFP_NATIVE_SUITES:
        policy = ZFP_NATIVE_POLICY
        routes.update(zfp.ROUTES)
    if suite in PBEPLA_NATIVE_SUITES:
        policy = PBEPLA_NATIVE_POLICY
        routes.update(pbepla.ROUTES)
        methods[pbepla.PLUG] = pbepla.DEFAULT_METHOD
    if suite in CORAD_INFERENCE_SUITES:
        policy = CORAD_INFERENCE_POLICY
        routes.update(corad.ROUTES)
        methods[corad.METHOD] = corad.DEFAULT_METHOD
    if suite in CORAD_TRAINING_SUITES:
        policy = CORAD_TRAINING_POLICY
        routes.update(training.ROUTES)
    return policy, routes, methods


def wants_titchy_direct(plan, slot):
    return plan.get('suite') in TYPED_SUITES and slot['method'] == typed.TITCHY and slot['expected_status'] == 0


def wants_xz_direct(plan, slot):
    return plan.get('suite') in XZ_SUITES and slot['method'] == xz.METHOD and slot['expected_status'] == 0


def wants_pcodec_direct(plan, slot):
    return plan.get('suite') in PCODEC_SUITES and slot['method'] in pco.METHODS


def binding_key(suite, selection, route, check):
    return f'{selection}/{route}/{check}' if suite in XZ_SUITES else check


def fenv_binding_key(suite):
    return binding_key(suite, 9, ROUTES[9][0], FENV_CHECK)


def batch_limits(plan, slot):
    if plan.get('suite') in LZBENCH_PROFILE_SUITES and profiles.is_profile(slot):
        return slot['limits']
    limits = plan['limits']
    cap = plan.get('method_address_space_bytes', {}).get(slot.get('method'))
    if cap is not None:
        limits = {**limits,'address_space_bytes':cap}
    if plan.get('suite') in UNIFIED_SUITES and slot.get('method')=='gorilla-tv':
        limits = {**limits,'file_bytes':plan['gorilla_file_bytes']}
    if plan.get('suite') in SPRINTZ_SUITES and sprintz.is_sprintz(slot):
        cap = sprintz.file_limit(slot)
        require(cap<=limits['file_bytes'],'Sprintz per-slot ceiling exceeds suite file limit')
        limits = {**limits,'file_bytes':cap}
    if plan.get('suite') in ACCESS_SUITES and access.is_access(slot):
        require(access.FILE_LIMIT<=limits['file_bytes'], 'Titchy access ceiling exceeds suite limit')
        limits = {**limits,'file_bytes':access.FILE_LIMIT}
    if plan.get('suite') in STREAM_SUITES and stream.is_stream(slot):
        require(stream.FILE_LIMIT<=limits['file_bytes'], 'Titchy stream ceiling exceeds suite limit')
        limits = {**limits,'file_bytes':stream.FILE_LIMIT}
    if plan.get('suite') in INTMULT_SUITES and intmult.is_intmult(slot):
        require(intmult.FILE_LIMIT<=limits['file_bytes'],'pcodec IntMult ceiling exceeds suite limit')
        limits = {**limits,'file_bytes':intmult.FILE_LIMIT}
    if plan.get('suite') in GORILLA_STATE_SUITES and state.is_state(slot):
        require(state.CAP<=limits['file_bytes'],'Gorilla state ceiling exceeds suite limit')
        limits = {**limits,'file_bytes':state.CAP}
    if plan.get('suite') in PBEPLA_NATIVE_SUITES and pbepla.is_pbepla(slot):
        limits = pbepla.limit(slot,limits)
    if plan.get('suite') in CORAD_INFERENCE_SUITES and corad.is_corad(slot):
        limits = corad.limit(plan)
    if plan.get('suite') in CORAD_TRAINING_SUITES and training.is_training(slot):
        limits = training.limits(plan)
    return limits


def _check_method_limits(plan, suite, *, replay=False):
    overrides = plan.get('method_address_space_bytes')
    if suite in UNIFIED_SUITES:
        require(plan.get('gorilla_file_bytes')==16384 and plan['gorilla_file_bytes']<=plan['limits']['file_bytes'],
                'Gorilla per-file ceiling differs from the C11 batch contract')
    else:
        require('gorilla_file_bytes' not in plan, 'unexpected Gorilla limit')
    if suite in XZ_SUITES:
        if replay and suite == EXTENDED_XZ and 'method_address_space_bytes' not in plan:
            return  # Archived first XZ attempt used the 128 MiB default and failed three slots.
        methods = {xz.METHOD,'xz-session'} if suite in LZBENCH_SESSION_SUITES else {xz.METHOD}
        require(isinstance(overrides,dict) and set(overrides)==methods and
                all(type(v) is int and v > plan['limits']['address_space_bytes'] for v in overrides.values()),
                'XZ suite requires a distinct bounded XZ address space')
        for method in methods:
            validate_limits(batch_limits(plan,{'method':method}))
    else:
        require('method_address_space_bytes' not in plan, 'suite does not allow method address-space overrides')


def compile_linear_batch(root, build, direct_control, fenv_control=None, *, suite="linear-v1", titchy_control=None,
                         xz_control=None, pcodec_control=None, wrapped_driver=None, gorilla_control=None, selfstar_control=None,
                         huff0_control=None, sprintz_control=None, titchy_access_control=None, titchy_stream_control=None,
                         huff0_portable_build=None):
    from .batch_execution import (CONTRACT_CODE, DIRECT_SOURCE, DIRECT_TARGET, DIRECT_TOOL, PLUGIN,
                                   _check_native_link, cross_binding_key, gorilla_inputs)

    policy_path, routes, methods = _suite_definition(suite)
    policy = load_json(local_file(root, policy_path))
    keys = {'schema','routes','limits','max_shared_decoder_bytes','max_batch_bytes','verification'}
    if suite in XZ_SUITES:
        keys.add('method_address_space_bytes')
    if suite in UNIFIED_SUITES:
        keys.add('gorilla_file_bytes')
    require(set(policy) == keys and
            policy['schema'] == 'bmk.linear-batch-execution-policy/1' and policy['verification'] == 'artifact_each' and
            policy['routes'] == [{'selection':n, 'route':r} for n,r in routes], 'invalid linear batch policy')
    validate_limits(policy['limits'])
    _check_method_limits(policy,suite)
    cap = policy['max_batch_bytes']
    require(type(cap) is int and 66064 <= cap <= policy['limits']['file_bytes'] and
            type(policy['max_shared_decoder_bytes']) is int and 0 < policy['max_shared_decoder_bytes'] <= 32 << 20,
            'invalid linear batch capacity')
    require(set(build['plugins']) == methods.keys(), 'linear batch build must bind exactly the selected suite plugins')
    require(direct_control is not None and PurePosixPath(direct_control) == _control_path(build),
            'linear batch requires the Zstd direct control alongside the selected plugin')
    tools = {ZSTD_TOOL: {'path': direct_control, 'sha256': digest(local_file(root, direct_control))}}
    if fenv_control is not None:
        require(PurePosixPath(fenv_control) == _fenv_path(build), 'ALP fenv tool must be alongside the ALP plugin')
        tools[FENV_TOOL] = {'path':fenv_control, 'sha256':digest(local_file(root,fenv_control))}
    if suite in TYPED_SUITES:
        require(titchy_control is not None and PurePosixPath(titchy_control) == _titchy_path(build) and fenv_control is not None,
                'extended batch requires Titchy direct and ALP fenv tool bindings')
        tools[typed.TITCHY_TOOL] = {'path':titchy_control, 'sha256':digest(local_file(root,titchy_control))}
    else:
        require(titchy_control is None, 'Titchy direct tool is not part of linear-v1')
    if suite in XZ_SUITES:
        require(xz_control is not None and PurePosixPath(xz_control) == _xz_path(build),
                'extended-v2 requires the XZ direct control alongside the selected plugin')
        tools[xz.TOOL] = {'path':xz_control,'sha256':digest(local_file(root,xz_control))}
    else:
        require(xz_control is None, 'XZ direct control is not part of this suite')
    if suite in PCODEC_SUITES:
        require(pcodec_control is not None and PurePosixPath(pcodec_control) == _pcodec_path(build),
                'suite requires the direct pcodec control alongside both selected plugins')
        tools[pco.TOOL] = {'path':pcodec_control,'sha256':digest(local_file(root,pcodec_control))}
    else:
        require(pcodec_control is None, 'pcodec direct control is not part of this suite')
    if suite in WRAPPED_SUITES:
        require(wrapped_driver is not None and PurePosixPath(wrapped_driver) == _pcodec_path(build,pages.TARGET),
                'extended-v4 requires the wrapped pcodec driver alongside the same library')
        tools[pages.TOOL] = {'path':wrapped_driver,'sha256':digest(local_file(root,wrapped_driver))}
    else:
        require(wrapped_driver is None, 'pcodec wrapped driver is not part of this suite')
    if suite in UNIFIED_SUITES:
        require(gorilla_control is not None and PurePosixPath(gorilla_control)==
                PurePosixPath(build['plugins'][PLUGIN]['library']['path']).with_name(DIRECT_TARGET),
                'unified batch requires the direct C control from the Gorilla build')
        tools[DIRECT_TOOL] = {'path':gorilla_control,'sha256':digest(local_file(root,gorilla_control))}
    else:
        require(gorilla_control is None, 'Gorilla direct control is not part of this suite')
    if suite in GORILLA_STATE_SUITES:
        path = state.work_path(build).as_posix()
        tools[state.TOOL] = {'path':path,'sha256':digest(local_file(root,path))}
    if suite in ORDERED_SUITES:
        require(selfstar_control is not None and PurePosixPath(selfstar_control)==_selfstar_path(build),
                'ordered batch requires the SElf* direct driver from the same build')
        tools[selfstar.TOOL] = {'path':selfstar_control,'sha256':digest(local_file(root,selfstar_control))}
    else:
        require(selfstar_control is None, 'SElf* direct driver is not part of this suite')
    if suite in ENTROPY_SUITES:
        require(huff0_control is not None and PurePosixPath(huff0_control)==_huff_path(build),
                'Huff0 direct driver must be alongside its ABI plugin')
        tools[huff.TOOL] = {'path':huff0_control,'sha256':digest(local_file(root,huff0_control))}
    else:
        require(huff0_control is None, 'unexpected Huff0 native driver')
    if suite in SPRINTZ_SUITES:
        require(sprintz_control is not None and PurePosixPath(sprintz_control)==_sprintz_path(build),
                'Sprintz native driver must be alongside its ABI plugin')
        tools[sprintz.TOOL] = {'path':sprintz_control,'sha256':digest(local_file(root,sprintz_control))}
    else:
        require(sprintz_control is None,'unexpected Sprintz native driver')
    if suite in ACCESS_SUITES:
        require(titchy_access_control is not None and PurePosixPath(titchy_access_control)==_access_path(build),
                'Titchy access driver must be alongside the C batch library')
        tools[access.TOOL] = {'path':titchy_access_control,'sha256':digest(local_file(root,titchy_access_control))}
    else:
        require(titchy_access_control is None,'unexpected Titchy access driver')
    if suite in STREAM_SUITES:
        require(titchy_stream_control is not None and PurePosixPath(titchy_stream_control)==_stream_path(build),
                'Titchy stream driver must be alongside the C library')
        tools[stream.TOOL] = {'path':titchy_stream_control,'sha256':digest(local_file(root,titchy_stream_control))}
    else:
        require(titchy_stream_control is None,'unexpected Titchy stream driver')
    if suite in LZBENCH_SESSION_SUITES:
        path = sessions.tool_path(build).as_posix()
        tools[sessions.TOOL] = {'path':path,'sha256':digest(local_file(root,path))}
    if suite in LZBENCH_PROFILE_SUITES:
        for name,path in profiles.tool_paths(build).items():
            tools[name] = {'path':path.as_posix(),'sha256':digest(local_file(root,path.as_posix()))}
    if suite in ALP_DECODE_SUITES:
        path = decode.tool_path(build).as_posix()
        tools[decode.TOOL] = {'path':path,'sha256':digest(local_file(root,path))}
    if suite in ZFP_NATIVE_SUITES:
        for name,path in zfp.tool_paths(build).items():
            tools[name] = {'path':path.as_posix(),'sha256':digest(local_file(root,path.as_posix()))}
    if suite in PBEPLA_NATIVE_SUITES:
        for name,path in pbepla.tool_paths(build).items():
            tools[name] = {'path':path.as_posix(),'sha256':digest(local_file(root,path.as_posix()))}
    if suite in CORAD_INFERENCE_SUITES:
        path = corad.tool_path(build).as_posix()
        tools[corad.TOOL] = {'path':path,'sha256':digest(local_file(root,path))}
    if suite in CORAD_TRAINING_SUITES:
        path = training.tool_path(build).as_posix()
        tools[training.TOOL] = {'path':path,'sha256':digest(local_file(root,path))}
    recovery = plan_recovery(root, build, methods, tools=tools)
    _check_tools(recovery)
    require((huff0_portable_build is not None)==(suite==bmi2.SUITE),'Huff0 portable build required only for extended-v20')
    portable = None
    if huff0_portable_build is not None:
        archive = load_json(local_file(root,'third_party/sources.lock.json'))['sources']['FiniteStateEntropy']['archive']['sha256']
        portable = bmi2.plan_control(root.resolve(),recovery,huff.TOOL,huff0_portable_build,archive)
    if suite in UNIFIED_SUITES:
        _check_native_link(recovery)
    config_ids = {p:resolve_worker(root, build, p, m['options'])['configuration_id'] for p,m in methods.items()}
    shared = sum(r['bytes'] for r in recovery['files'].values())
    if portable:
        shared += sum(r['bytes'] for r in portable['decoder']['files'].values())
    require(shared <= policy['max_shared_decoder_bytes'], 'linear decoder closure exceeds budget')
    products, by_case = linear_inputs(root, cap)
    def merge(extra, extra_cases):
        require(not products.keys() & extra.keys() and not by_case.keys() & extra_cases.keys(), 'duplicate batch case identity')
        products.update(extra)
        by_case.update(extra_cases)
    if suite in TYPED_SUITES:
        merge(*typed.typed_inputs(root, cap))
    if suite in XZ_SUITES:
        merge(*xz.xz_inputs(root))
    if suite in PCODEC_SUITES:
        merge(*pco.pcodec_inputs(root))
    if suite in WRAPPED_SUITES:
        merge(*pages.pcodec_page_inputs(root))
    if suite in UNIFIED_SUITES:
        merge(*gorilla_inputs(root))
    if suite in ORDERED_SUITES:
        merge(*selfstar.selfstar_inputs(root))
    if suite in ENTROPY_SUITES:
        merge(*huff.huff0_inputs(root, compare_bmi2=suite==bmi2.SUITE))
    if suite in SPRINTZ_SUITES:
        merge(*sprintz.sprintz_inputs())
    if suite in ACCESS_SUITES:
        merge(*access.access_inputs(root))
    if suite in STREAM_SUITES:
        merge(*stream.stream_inputs(root))
    if suite in INTMULT_SUITES:
        merge(*intmult.execution_inputs(root))
    if suite in GORILLA_STATE_SUITES:
        merge(*state.state_inputs(root))
    if suite in LZBENCH_SESSION_SUITES:
        merge(*sessions.execution_inputs(root))
    if suite in LZBENCH_PROFILE_SUITES:
        merge(*profiles.plan_slots(root))
    if suite in ALP_DECODE_SUITES:
        merge(*decode.plan_slots(root))
    if suite in ZFP_NATIVE_SUITES:
        merge(*zfp.plan_slots(root))
    if suite in PBEPLA_NATIVE_SUITES:
        merge(*pbepla.plan_slots(root))
    if suite in CORAD_INFERENCE_SUITES:
        merge(*corad.plan_slots(root))
    if suite in CORAD_TRAINING_SUITES:
        merge(*training.plan_slots(root))
    admission = plan_native_admission(root)
    selected = {r['route_contract_id']:r for r in admission['routes'] if (r['selection'],r['route']) in routes}
    require(len(selected) == len(routes), 'linear batch route closure differs')
    bindings = {}
    for o in admission['obligations']:
        if o['route_contract_id'] not in selected:
            continue
        context = selected[o['route_contract_id']]
        key = binding_key(suite,context['selection'],context['route'],o['check'])
        require(key not in bindings, 'ambiguous linear batch obligation')
        if o['kind']=='conditional':
            if suite==bmi2.SUITE and bmi2.supports_condition(o):
                ids = bmi2.condition_slots(o,(row for row,_ in products.values()))
            elif suite in LZBENCH_PROFILE_SUITES and profiles.supports_condition(o):
                ids = profiles.condition_slots(o,(row for row,_ in products.values()))
            elif suite in ALP_DECODE_SUITES and decode.supports_condition(o):
                ids = decode.condition_slots(o,(row for row,_ in products.values()))
            elif suite in ZFP_NATIVE_SUITES and zfp.supports_condition(o):
                ids = zfp.condition_slots(o,(row for row,_ in products.values()))
            else:
                # Keep all other runtime conditions pending, even on bound routes.
                continue
        else:
            require(o['kind']=='required','unknown linear batch obligation kind')
            ids = []
            for c in o['planned_case_inputs']:
                source, slots = by_case[c['case_id']]
                require(source == c['bundle_id'], 'linear execution input bundle differs')
                ids.extend(slots)
        if (context['selection'],context['route'])==corad.ROUTE:
            ids = list(dict.fromkeys(ids))  # One common lane proves multiple named cases.
        require(ids and len(ids) == len(set(ids)), 'invalid linear obligation product set')
        bindings[key] = {'obligation_id':o['obligation_id'], 'route_contract_id':o['route_contract_id'], 'product_slots':ids}
    slots = [row for row, _ in products.values()]
    frames = [r for r in slots if 'protocol' not in r]
    wrapped = [r for r in slots if r.get('protocol')==pages.PROTOCOL]
    ordered = [r for r in slots if selfstar.is_selfstar(r)]
    entropy = [r for r in slots if huff.is_huff0(r)]
    fire = [r for r in slots if sprintz.is_sprintz(r)]
    readers = [r for r in slots if access.is_access(r)]
    streams = [r for r in slots if stream.is_stream(r)]
    multiples = [r for r in slots if intmult.is_intmult(r)]
    lifecycle = [r for r in slots if state.is_state(r)]
    byte_sessions = [r for r in slots if sessions.is_session(r)]
    native_profiles = [r for r in slots if profiles.is_profile(r)]
    decode_slots = [r for r in slots if decode.is_decode(r)]
    zfp_slots = [r for r in slots if zfp.is_zfp(r)]
    pbepla_slots = [r for r in slots if pbepla.is_pbepla(r)]
    corad_slots = [r for r in slots if corad.is_corad(r)]
    training_slots = [r for r in slots if training.is_training(r)]
    require(all(max([huff.input_bytes(r),*r['parts'].values()])<=cap for r in entropy), 'Huff0 byte budget exceeded')
    require(set.union(*(set(r['product_slots']) for r in bindings.values())) == set(products) and
            all(max([r['max_frame_bytes'], *r['original']['column_bytes'], r['original']['schema_bytes']]) <= cap for r in frames) and
            all(max([r['original']['bytes'], *r['parts'].values()]) <= cap for r in [*wrapped,*ordered]),
            'linear product closure or byte limits differ')
    logs = sum(1 if r['expected_status'] else 2+len(r['reject_decodes'])+2*r['upstream_zstd'] for r in frames)
    logs += sum(len(r['operations']) for r in wrapped) + sum(len(selfstar.operations(r)) for r in ordered) + sum(len(huff.operations(r)) for r in entropy)
    sources = (*CONTRACT_CODE, ZSTD_SOURCE, 'src/tsbench/planner/linear_batch.py',
               'src/tsbench/qualification/linear_batch.py', 'src/tsbench/planner/alp.py',
               'src/tsbench/planner/lzbench.py', 'src/tsbench/qualification/alp_wire.py', 'src/tsbench/qualification/lzbench.py')
    if fenv_control is not None:
        control_slots = bindings[fenv_binding_key(suite)]['product_slots']
        require(len(control_slots) == 1 and products[control_slots[0]][0]['original']['columns'] == [{'dtype':10,'count':1029}],
                'ALP rounding control input differs')
        logs += len(control_slots)
        sources = (*sources,FENV_SOURCE)
    body = {'schema': MIXED_SCHEMA if suite in ZFP_NATIVE_SUITES else SCHEMA, 'purpose': 'native_admission_execution_candidate', 'runnable': True,
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False,
            'verification': 'artifact_each', 'policy_id': content_id(policy), 'limits': policy['limits'],
            'admission_plan_id': admission['plan_content_id'], 'admission_coverage': admission['coverage'],
            'route_contracts': selected, 'obligation_bindings': bindings, 'unbound_controls': {} if fenv_control is not None else PENDING,
            'slots': slots, 'methods': methods, 'configuration_ids': config_ids, 'build': build, 'decoder': recovery,
            'direct_control': {'tool_refs':tools, 'protocol':'exact_upstream_ZSTD_compress_level3'},
            'code': {name:digest(local_file(root,name)) for name in sources}, 'launchers':launcher_lock(),
            'retention_bounds': {'serialized_products_bytes':sum(r['max_frame_bytes'] for r in frames)+
                                                            sum(sum(r['parts'].values()) for r in [*wrapped,*ordered,*entropy,*fire,*readers,*streams,*multiples,*lifecycle,*byte_sessions,*native_profiles,*decode_slots,*zfp_slots,*pbepla_slots,*corad_slots,*training_slots]),
                                 'control_payload_bytes':66000, 'operation_logs_bytes':2*logs*policy['limits']['file_bytes'],
                                 'shared_decoder_bytes':shared, 'excludes':'plan_ledger_seal_and_filesystem_overhead'}}
    if portable:
        body[bmi2.KEY] = portable
        body['code'].update({p:digest(local_file(root,p)) for p in bmi2.SOURCES})
    if suite in TYPED_SUITES:
        ref_slots = [r for r in slots if wants_titchy_direct({'suite':suite},r)]
        body['suite'] = suite
        body['code'].update({name:digest(local_file(root,name)) for name in typed.SOURCES})
        body['retention_bounds']['control_payload_bytes'] += sum(
            r['max_frame_bytes']-32-r['original']['schema_bytes'] for r in ref_slots)
        body['retention_bounds']['operation_logs_bytes'] += 2*len(ref_slots)*policy['limits']['file_bytes']
    if suite in XZ_SUITES:
        body['method_address_space_bytes'] = policy['method_address_space_bytes']
        body['code'].update({name:digest(local_file(root,name)) for name in xz.SOURCES})
        body['retention_bounds']['operation_logs_bytes'] += 2*sum(wants_xz_direct(body,r) for r in slots)*policy['limits']['file_bytes']
    if suite in PCODEC_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in pco.SOURCES})
        body['retention_bounds']['operation_logs_bytes'] += 2*sum(wants_pcodec_direct(body,r) for r in slots)*policy['limits']['file_bytes']
    if suite in WRAPPED_SUITES:
        body['protocol_methods'] = protocol_methods(suite)
        body['code'].update({name:digest(local_file(root,name)) for name in pages.SOURCES})
        require(all(p in body['code'] for p in pages.SOURCES), 'wrapped control code closure incomplete')
    if suite in ORDERED_SUITES:
        for path in selfstar.SOURCES:
            body['code'][path] = digest(local_file(root,path))
        selfstar.check_selfstar_slots(body)
    if suite in ENTROPY_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in huff.SOURCES})
        body['retention_bounds']['control_payload_bytes'] += 1024*sum(r['method']==huff.SHARED for r in entropy)
    if suite in SPRINTZ_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in sprintz.SOURCES})
        for r in fire:
            limits = batch_limits(body,r)
            validate_limits(limits)
            body['retention_bounds']['operation_logs_bytes'] += 2*len(sprintz.operations(r))*limits['file_bytes']
    if suite in ACCESS_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in access.SOURCES})
        for r in readers:
            limits = batch_limits(body,r)
            validate_limits(limits)
            require(max([r['original']['bytes'],*r['parts'].values()])<=limits['file_bytes'],'Titchy access retention exceeds limit')
            body['retention_bounds']['operation_logs_bytes'] += 2*len(access.operations(r))*limits['file_bytes']
    if suite in STREAM_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in stream.SOURCES})
        for r in streams:
            limits = batch_limits(body,r)
            validate_limits(limits)
            require(max([r['original']['bytes'],*r['parts'].values()])<=limits['file_bytes'],'Titchy stream retention exceeds limit')
            body['retention_bounds']['operation_logs_bytes'] += 2*len(stream.operations(r))*limits['file_bytes']
    if suite in INTMULT_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in intmult.SOURCES})
        for r in multiples:
            limits = batch_limits(body,r)
            validate_limits(limits)
            require(max([r['original']['bytes'],*r['parts'].values()])<=limits['file_bytes'],'pcodec IntMult retention exceeds limit')
            body['retention_bounds']['operation_logs_bytes'] += 2*len(intmult.operations(r))*limits['file_bytes']
    if suite in GORILLA_STATE_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in state.SOURCES})
        for r in lifecycle:
            limits = batch_limits(body,r)
            validate_limits(limits)
            require(max([16*r['original']['rows'],*r['parts'].values()])<=limits['file_bytes'],'Gorilla lifecycle retention exceeds limit')
            body['retention_bounds']['operation_logs_bytes'] += 2*len(state.operations(r))*limits['file_bytes']
    if suite in LZBENCH_SESSION_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in sessions.SOURCES})
        for r in byte_sessions:
            limits = batch_limits(body,r)
            validate_limits(limits)
            require(max([sessions.input_bytes(r),*r['parts'].values()])<=limits['file_bytes'],
                    'lzbench session retention exceeds limit')
            body['retention_bounds']['operation_logs_bytes'] += 2*len(sessions.operations(r))*limits['file_bytes']
    if suite in LZBENCH_PROFILE_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in profiles.SOURCES})
        for r in native_profiles:
            limits = batch_limits(body,r)
            validate_limits(limits,file_ceiling=profiles.FILE_CEILING)
            require(max([profiles.input_bytes(r),*r['parts'].values()])<=limits['file_bytes'],
                    'lzbench profile retention exceeds limit')
            body['retention_bounds']['operation_logs_bytes'] += 2*len(profiles.operations(r))*limits['file_bytes']
    if suite in ALP_DECODE_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in decode.SOURCES})
        require(all(r['parts']['frame']<=min(cap,policy['limits']['file_bytes']) for r in decode_slots),
                'ALP backend retention exceeds limit')
        body['retention_bounds']['operation_logs_bytes'] += 2*sum(len(decode.operations(r)) for r in decode_slots)*policy['limits']['file_bytes']
    if suite in ZFP_NATIVE_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in zfp.SOURCES})
        zfp.check_slots(body)
        body['retention_bounds']['operation_logs_bytes'] += 2*sum(len(zfp.operations(r)) for r in zfp_slots)*policy['limits']['file_bytes']
    if suite in PBEPLA_NATIVE_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in pbepla.SOURCES})
        pbepla.check_slots(body)
        body['retention_bounds']['operation_logs_bytes'] += 2*sum(
            len(pbepla.steps(r))*batch_limits(body,r)['file_bytes'] for r in pbepla_slots)
    if suite in CORAD_INFERENCE_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in corad.SOURCES})
        corad.check_slots(body)
        validate_limits(corad.limit(body))
        body['retention_bounds']['operation_logs_bytes'] += 2*sum(
            len(corad.steps(r))*corad.limit(body)['file_bytes'] for r in corad_slots)
    if suite in CORAD_TRAINING_SUITES:
        body['code'].update({name:digest(local_file(root,name)) for name in training.SOURCES})
        training.check_slots(body)
        validate_limits(training.limits(body,training.PYTHON))
        body['retention_bounds']['operation_logs_bytes'] += 2*sum(
            len(training.steps(r))*training.FILE_CEILING for r in training_slots)
    if suite in UNIFIED_SUITES:
        from .batch_binding import compile_binding_view

        body['gorilla_file_bytes'] = policy['gorilla_file_bytes']
        cross = bindings[cross_binding_key(body)]['product_slots']
        gorilla = [r for r in frames if r['method']==PLUGIN]
        require(all(max(r['max_frame_bytes'],r['original']['schema_bytes'],*r['original']['column_bytes'])<=
                    body['gorilla_file_bytes'] for r in gorilla) and all(not products[i][0]['expected_status'] for i in cross),
                'Gorilla product or cross-control exceeds its scope')
        body['retention_bounds']['control_payload_bytes'] += sum(max_payload(products[i][0]['original']['columns'][0]['count']) for i in cross)
        body['retention_bounds']['operation_logs_bytes'] += 6*len(cross)*body['gorilla_file_bytes']
        path = 'src/tsbench/planner/batch_binding.py'
        body['code'].update({p:digest(local_file(root,p)) for p in (DIRECT_SOURCE,path)})
        body['admission_definition'] = admission
        body['case_products'] = {cid:{'bundle_id':bundle,'product_slots':ids} for cid,(bundle,ids) in by_case.items()}
        body['execution_binding'] = compile_binding_view(body,routes)
    return {**body, 'plan_content_id': content_id(body)}, {row['product_slot']: sample for row,sample in products.values()}


def check_linear_batch(plan):
    tools = plan['direct_control']['tool_refs']
    suite = plan.get('suite', 'linear-v1')
    require(plan['schema']==(MIXED_SCHEMA if suite in ZFP_NATIVE_SUITES else SCHEMA),'batch quality schema differs from suite')
    _, routes, methods = _suite_definition(suite)
    _check_method_limits(plan,suite,replay=True)
    fenv = FENV_TOOL in tools
    expected_tools = {ZSTD_TOOL}
    if fenv:
        expected_tools.add(FENV_TOOL)
    if suite in TYPED_SUITES:
        expected_tools.add(typed.TITCHY_TOOL)
        require(fenv and PurePosixPath(tools[typed.TITCHY_TOOL]['path']) == _titchy_path(plan['build']),
                'invalid extended batch control paths')
    if suite in XZ_SUITES:
        expected_tools.add(xz.TOOL)
        require(xz.TOOL in tools and PurePosixPath(tools[xz.TOOL]['path']) == _xz_path(plan['build']),
                'invalid XZ batch control path')
    if suite in PCODEC_SUITES:
        expected_tools.add(pco.TOOL)
        require(pco.TOOL in tools and PurePosixPath(tools[pco.TOOL]['path']) == _pcodec_path(plan['build']),
                'invalid pcodec batch control path')
    if suite in WRAPPED_SUITES:
        protocols = {pages.PROTOCOL, *([selfstar.PROTOCOL] if suite in ORDERED_SUITES else [])}
        if suite in ENTROPY_SUITES:
            protocols.add(huff.PROTOCOL)
        if suite in SPRINTZ_SUITES:
            protocols.add(sprintz.PROTOCOL)
        if suite in ACCESS_SUITES:
            protocols.add(access.PROTOCOL)
        if suite in STREAM_SUITES:
            protocols.add(stream.PROTOCOL)
        if suite in INTMULT_SUITES:
            protocols.add(intmult.PROTOCOL)
        if suite in GORILLA_STATE_SUITES:
            protocols.add(state.PROTOCOL)
        if suite in LZBENCH_SESSION_SUITES:
            protocols.add(sessions.PROTOCOL)
        if suite in LZBENCH_PROFILE_SUITES:
            protocols.add(profiles.PROTOCOL)
        if suite in ALP_DECODE_SUITES:
            protocols.add(decode.PROTOCOL)
        if suite in ZFP_NATIVE_SUITES:
            protocols.add(zfp.PROTOCOL)
        if suite in PBEPLA_NATIVE_SUITES:
            protocols.add(pbepla.PROTOCOL)
        if suite in CORAD_INFERENCE_SUITES:
            protocols.add(corad.PROTOCOL)
        if suite in CORAD_TRAINING_SUITES:
            protocols.add(training.PROTOCOL)
        require(all('protocol' not in s or s['protocol'] in protocols for s in plan['slots']), 'unknown product protocol')
        expected_tools.add(pages.TOOL)
        require(pages.TOOL in tools and PurePosixPath(tools[pages.TOOL]['path']) == _pcodec_path(plan['build'],pages.TARGET) and
                plan.get('protocol_methods') == protocol_methods(suite), 'invalid wrapped driver binding')
        pages.check_wrapped_slots(plan)
    else:
        require('protocol_methods' not in plan and all('protocol' not in s for s in plan['slots']),
                'unexpected wrapped product protocol')
    if suite in ORDERED_SUITES:
        expected_tools.add(selfstar.TOOL)
        require(selfstar.TOOL in tools and PurePosixPath(tools[selfstar.TOOL]['path'])==_selfstar_path(plan['build']),
                'SElf* driver path differs')
        selfstar.check_selfstar_slots(plan)
    else:
        require(not any(selfstar.is_selfstar(s) for s in plan['slots']), 'unexpected SElf* protocol')
    if suite in ENTROPY_SUITES:
        expected_tools.add(huff.TOOL)
        require(huff.TOOL in tools and PurePosixPath(tools[huff.TOOL]['path'])==_huff_path(plan['build']),
                'Huff0 direct driver path differs')
        huff.check_slots(plan)
    if suite in SPRINTZ_SUITES:
        expected_tools.add(sprintz.TOOL)
        require(sprintz.TOOL in tools and PurePosixPath(tools[sprintz.TOOL]['path'])==_sprintz_path(plan['build']),
                'Sprintz native driver path differs')
        sprintz.check_slots(plan)
    if suite in ACCESS_SUITES:
        expected_tools.add(access.TOOL)
        require(access.TOOL in tools and PurePosixPath(tools[access.TOOL]['path'])==_access_path(plan['build']),
                'Titchy native access driver path differs')
        access.check_slots(plan)
    if suite in STREAM_SUITES:
        expected_tools.add(stream.TOOL)
        require(stream.TOOL in tools and PurePosixPath(tools[stream.TOOL]['path'])==_stream_path(plan['build']),
                'Titchy native stream driver path differs')
        stream.check_slots(plan)
    if suite in INTMULT_SUITES:
        intmult.check_slots(plan)
    if suite in GORILLA_STATE_SUITES:
        expected_tools.add(state.TOOL)
        require(state.TOOL in tools and PurePosixPath(tools[state.TOOL]['path'])==state.work_path(plan['build']),
                'Gorilla native observer path differs')
        state.check_slots(plan)
    if suite in LZBENCH_SESSION_SUITES:
        expected_tools.add(sessions.TOOL)
        require(sessions.TOOL in tools and PurePosixPath(tools[sessions.TOOL]['path'])==sessions.tool_path(plan['build']),
                'lzbench session tool path differs')
        sessions.check_slots(plan)
    if suite in LZBENCH_PROFILE_SUITES:
        for name,path in profiles.tool_paths(plan['build']).items():
            expected_tools.add(name)
            require(name in tools and PurePosixPath(tools[name]['path'])==path,'lzbench profile tool path differs')
        profiles.check_slots(plan)
    if suite in ALP_DECODE_SUITES:
        expected_tools.add(decode.TOOL)
        require(decode.TOOL in tools and PurePosixPath(tools[decode.TOOL]['path'])==decode.tool_path(plan['build']),
                'ALP backend tool path differs')
        decode.check_slots(plan)
    if suite in ZFP_NATIVE_SUITES:
        for name,path in zfp.tool_paths(plan['build']).items():
            expected_tools.add(name)
            require(name in tools and PurePosixPath(tools[name]['path'])==path,'ZFP native tool path differs')
        zfp.check_slots(plan)
    if suite in PBEPLA_NATIVE_SUITES:
        for name,path in pbepla.tool_paths(plan['build']).items():
            expected_tools.add(name)
            require(name in tools and PurePosixPath(tools[name]['path'])==path,'PBEPLA native tool path differs')
        pbepla.check_slots(plan)
    if suite in CORAD_INFERENCE_SUITES:
        expected_tools.add(corad.TOOL)
        require(corad.TOOL in tools and PurePosixPath(tools[corad.TOOL]['path'])==corad.tool_path(plan['build']),
                'CORAD inference native tool path differs')
        corad.check_slots(plan)
        validate_limits(corad.limit(plan))
    if suite in CORAD_TRAINING_SUITES:
        expected_tools.add(training.TOOL)
        require(training.TOOL in tools and PurePosixPath(tools[training.TOOL]['path'])==training.tool_path(plan['build']),
                'CORAD training native tool path differs')
        training.check_slots(plan)
        validate_limits(training.limits(plan,training.PYTHON))
    if suite in UNIFIED_SUITES:
        from .batch_binding import compile_binding_view
        from .batch_execution import DIRECT_TOOL, DIRECT_TARGET, PLUGIN

        expected_tools.add(DIRECT_TOOL)
        require(DIRECT_TOOL in tools and PurePosixPath(tools[DIRECT_TOOL]['path'])==
                PurePosixPath(plan['build']['plugins'][PLUGIN]['library']['path']).with_name(DIRECT_TARGET),
                'unified batch Gorilla control moved')
    else:
        require(not {'admission_definition','case_products','execution_binding'} & plan.keys(), 'unexpected execution binding view')
    require(plan['direct_control']['protocol'] == 'exact_upstream_ZSTD_compress_level3' and set(tools) == expected_tools and
            PurePosixPath(tools[ZSTD_TOOL]['path']) == _control_path(plan['build']) and plan['methods'] == methods and
            plan['unbound_controls'] == ({} if fenv else PENDING), 'invalid linear batch method or control')
    if suite in TYPED_SUITES:
        require({(r['selection'], r['route']) for r in plan['route_contracts'].values()} == routes.keys(),
                'extended batch route set differs')
    if fenv:
        require(PurePosixPath(tools[FENV_TOOL]['path']) == _fenv_path(plan['build']), 'invalid fenv control path')
    check_recovery(plan['decoder'], plan['build'], methods, tools=tools)
    _check_tools(plan['decoder'])
    require((bmi2.KEY in plan)==(suite==bmi2.SUITE),'missing or unexpected Huff0 portable closure')
    if suite==bmi2.SUITE:
        route, = [r for r in plan['route_contracts'].values() if (r['selection'],r['route'])==(29,huff.PLUGIN)]
        bmi2.check_control(plan[bmi2.KEY],plan['decoder'],huff.TOOL,route['source_identity']['archive_sha256'],plan['code'][bmi2.SOURCE])
        require(plan['retention_bounds']['shared_decoder_bytes']==sum(r['bytes'] for spec in
                (plan['decoder'],plan[bmi2.KEY]['decoder']) for r in spec['files'].values()),'Huff0 closure retention bound differs')
    if suite in UNIFIED_SUITES:
        from .batch_execution import _check_native_link
        _check_native_link(plan['decoder'])
        require(plan['execution_binding']==compile_binding_view(plan,routes), 'execution binding changed')
