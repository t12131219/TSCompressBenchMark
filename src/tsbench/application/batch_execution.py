"""Execute and audit a frozen batch candidate; no timing or qualification is awarded."""
from collections import Counter
from pathlib import Path
import re
import tempfile
import uuid

from ..assets import ContractError, canonical_bytes, content_id, load_json, require, verify_asset
from ..planner.batch_execution import (CROSS_SCHEMA, DIRECT_TOOL, check_batch_execution,
                                       compile_batch_suite, cross_binding_key, direct_path, is_gorilla_slot,
                                       requires_cross as _requires_cross)
from ..planner.linear_batch import (FENV_TOOL, LINEAR_SCHEMAS, MIXED_SCHEMA, ACCESS_SUITES, STREAM_SUITES, INTMULT_SUITES, GORILLA_STATE_SUITES, LZBENCH_SESSION_SUITES, LZBENCH_PROFILE_SUITES, ALP_DECODE_SUITES, ZFP_NATIVE_SUITES, PBEPLA_NATIVE_SUITES, CORAD_INFERENCE_SUITES, CORAD_TRAINING_SUITES, ENTROPY_SUITES, ORDERED_SUITES, SPRINTZ_SUITES, UNIFIED_SUITES, ZSTD_TOOL, batch_limits, fenv_binding_key,
                                    wants_pcodec_direct, wants_titchy_direct, wants_xz_direct)
from ..planner.pcodec import SOURCE as PCO_SOURCE
from ..planner.pcodec_batch import TOOL as PCO_TOOL
from ..planner.pcodec_pages import TOOL as WRAPPED_TOOL
from ..planner.typed_batch import TITCHY_TOOL
from ..planner import huff0_bmi2 as bmi2
from ..planner.huff0_execution import TOOL as HUFF_TOOL, is_huff0
from ..planner.sprintz_execution import TOOL as SPRINTZ_TOOL, is_sprintz
from ..planner.titchy_execution import TOOL as ACCESS_TOOL, is_access
from ..planner.selfstar_execution import TOOL as SELFSTAR_TOOL, is_selfstar
from ..planner.xz_batch import TOOL as XZ_TOOL
from ..planner.gorilla import HEADER, columns, max_payload, sha
from ..qualification.gorilla import decode_chunk
from ..qualification.linear_batch import check_info, inspect_linear, mutations, parts, wrap
from ..qualification.pcodec_batch import direct_observation as pcodec_direct_observation
from ..qualification.pcodec_pages import is_wrapped
from ..qualification.typed_batch import titchy_direct_observation
from ..qualification.xz_batch import direct_observation as xz_direct_observation
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import invoke_isolated_tool, invoke_isolated_worker, launcher_lock
from . import pcodec_pages as wrapped
from . import selfstar_execution as selfstar
from . import huff0_execution as huff
from . import sprintz_execution as sprintz
from . import titchy_execution as access
from . import titchy_stream as stream
from . import pcodec_intmult as intmult
from ..planner.pcodec_intmult import is_intmult
from ..planner.gorilla_state import is_state
from . import gorilla_state as lifecycle
from ..planner.lzbench_session import is_session
from . import lzbench_session as byte_session
from ..planner.lzbench_profiles import is_profile
from . import lzbench_profiles as native_profiles
from ..planner.alp_decode import is_decode
from . import alp_decode
from ..planner.zfp_execution import is_zfp
from . import zfp_execution, pbepla_execution
from ..planner.pbepla_execution import is_pbepla
from ..planner.corad_execution import is_corad, QUALITY_CHECK as CORAD_QUALITY_CHECK
from . import corad_execution, corad_training_execution
from ..planner.corad_training_execution import is_training
from ..planner.titchy_stream import TOOL as STREAM_TOOL, is_stream
from .restore import _diagnostic
from .smoke import _line, _ref, _rows, _worker_json, write_new

LEDGER = 'ledger.jsonl'
ENCODE, DECODE = 'encode-columns', 'decode-columns'
NATIVE_ENCODE, NATIVE_DECODE, CROSS_DECODE = 'native-encode', 'native-decode', 'native-to-abi-decode'
UPSTREAM_ENCODE, UPSTREAM_DECODE = 'upstream-encode', 'upstream-to-abi-decode'
FENV_OP = 'alp-fenv-negative'
TITCHY_OP = 'titchy-direct-encode-and-capacity'
XZ_OP = 'xz-direct-parity-and-budget'
PCO_OP = 'pcodec-direct-standalone-control'
INPUT_STATUS = {1:'BMK_UNSUPPORTED=1', 2:'BMK_BAD_INPUT=2', 3:'BMK_BAD_OPTIONS=3', 7:'BMK_RESOURCE_LIMIT=7'}
PLAN, SEAL = 'plan.json', 'seal.json'


def _seal_schema(plan):
    return 'bmk.native-batch-seal/1' if plan['schema']==MIXED_SCHEMA else 'bmk.lossless-batch-seal/1'


def _inspect(path, slot, original=None):
    if not is_gorilla_slot(slot):
        require(0 < path.stat().st_size <= slot['max_frame_bytes'], 'linear frame outside declared bound')
        return inspect_linear(path.read_bytes(), slot, original)
    source = slot['original']
    n = source['columns'][0]['count']
    start = HEADER.size + source['schema_bytes']
    require(start + 2 <= path.stat().st_size <= slot['max_frame_bytes'], 'Gorilla frame outside declared bound')
    wire = path.read_bytes()
    require(HEADER.unpack_from(wire) == (b'BMKGTV\x01\0', source['schema_bytes'], n, len(wire)-start) and
            sha(wire[HEADER.size:start]) == source['schema_sha256'], 'Gorilla envelope header or schema differs')
    payload = wire[start:]
    pairs, bits = decode_chunk(payload, n)
    require([sha(col) for col in columns(pairs)] == source['column_sha256'], 'native XOR original-domain bits differ')
    return {'native_payload_bytes': len(payload), 'native_payload_sha256': sha(payload), 'native_bits': bits}


def _expect_files(output, paths):
    require({p.name for p in output.iterdir()} == set(paths) and
            all(p.is_file() and not p.is_symlink() for p in output.iterdir()),
            'missing or undeclared isolated worker output')


def _method(plan, slot):
    if plan['schema'] not in LINEAR_SCHEMAS:
        return plan['method']
    resolved = plan['methods'][slot['method']]
    if 'negative_options' in slot:
        require(slot['expected_status'] in INPUT_STATUS, 'options injection only allowed for a frozen rejection')
        return {**resolved,'options':slot['negative_options']}
    return resolved


def _column_names(slot):
    return ('t', 'v') if is_gorilla_slot(slot) else ('v',)


def _decode_inputs(slot):
    return ['/inputs/frame', '/out/schema', *(f'/out/{c}' for c in _column_names(slot))]


def _restore(bundle, plan, slot, artifact, work, logs, cancelled, operations=None, *, label=DECODE):
    source = slot['original']
    names = _column_names(slot)
    output, operation = invoke_isolated_worker(bundle, plan['decoder'], _method(plan, slot), batch_limits(plan,slot), work, logs,
                                              DECODE, {'frame': artifact}, _decode_inputs(slot), cancelled, label=label)
    if operations is not None:
        operations.append(operation)
    require(operation['status'] == 'completed', 'isolated restoration did not complete: ' + operation['reason'])
    _expect_files(output, ('schema', *names))
    require([(output / name).stat().st_size for name in (*names, 'schema')] ==
            [*source['column_bytes'], source['schema_bytes']], 'isolated restore output sizes differ')
    shape, _ = _worker_json(logs / (label + '.stdout'), 2)
    require(shape == {'columns': source['columns']}, 'isolated restored shape differs')
    schema = (output / 'schema').read_bytes()
    values = [(output / name).read_bytes() for name in names]
    observed = {'columns': shape['columns'], 'schema_bytes': len(schema), 'schema_sha256': sha(schema),
                'column_bytes': [len(v) for v in values], 'column_sha256': [sha(v) for v in values]}
    require(observed == source, 'isolated restored raw columns or schema differ')
    return observed




def _native_call(bundle, plan, slot, work, logs, label, inputs, args, cancelled, operations):
    output, operation = invoke_isolated_tool(bundle, plan['decoder'], DIRECT_TOOL, batch_limits(plan,slot), work, logs,
                                            label, inputs, args, cancelled)
    if operations is not None:
        operations.append(operation)
    require(operation['status'] == 'completed', f'{label} did not complete: ' + operation['reason'])
    count, = _worker_json(logs / (label + '.stdout'), 1)
    require(count == {'rows': slot['original']['columns'][0]['count']}, f'{label} row count differs')
    return output


def _native_encode(run, plan, slot, inputs, logs, cancelled, operations):
    with tempfile.TemporaryDirectory(prefix='tsbench-native-encode-control-') as tmp:
        out = _native_call(run / DIRECTORY, plan, slot, Path(tmp), logs, NATIVE_ENCODE,
                           {k: inputs[k] for k in ('t', 'v')}, ['encode', '/inputs/t', '/inputs/v', '/out/payload'],
                           cancelled, operations)
        _expect_files(out, ('payload',))
        payload = out / 'payload'
        require(2 <= payload.stat().st_size <= max_payload(slot['original']['columns'][0]['count']),
                'direct C payload outside frozen bound')
        target = run / 'controls' / (slot['product_slot'] + '.xor')
        with target.open('xb') as stream:
            stream.write(payload.read_bytes())
        return _ref(run, target)


def _cross_restore(bundle, plan, slot, artifact, control, logs, cancelled, operations=None):
    source = slot['original']
    wire, native = artifact.read_bytes(), control.read_bytes()
    start = HEADER.size + source['schema_bytes']
    require(wire[start:] == native, 'direct C and plugin XORChunk bytes differ')
    with tempfile.TemporaryDirectory(prefix='tsbench-cross-restore-') as tmp:
        work = Path(tmp)
        extracted = work / 'abi-payload'
        extracted.write_bytes(wire[start:])
        decode_work = work / 'native'
        decode_work.mkdir()
        output = _native_call(bundle, plan, slot, decode_work, logs, NATIVE_DECODE, {'payload': extracted},
                              ['decode', '/inputs/payload', '/out/t', '/out/v'], cancelled, operations)
        _expect_files(output, ('t', 'v'))
        paths = [output / name for name in ('t', 'v')]
        native_columns = {'column_bytes': [x.stat().st_size for x in paths],
                          'column_sha256': [sha(x.read_bytes()) for x in paths]}
        require(all(native_columns[k] == source[k] for k in native_columns), 'direct C restored raw columns differ')
        # Use the reference bytes, not the plugin's payload, as this decoder's input.
        n = source['columns'][0]['count']
        wrapped = work / 'reference-frame'
        wrapped.write_bytes(HEADER.pack(b'BMKGTV\x01\0', source['schema_bytes'], n, len(native)) +
                            wire[HEADER.size:start] + native)
        abi_work = work / 'abi'
        abi_work.mkdir()
        from_native = _restore(bundle, plan, slot, wrapped, abi_work, logs, cancelled, operations, label=CROSS_DECODE)
    return {'abi_to_native': native_columns, 'native_to_abi': from_native}


def _upstream_encode(run, plan, slot, raw, logs, cancelled, operations):
    with tempfile.TemporaryDirectory(prefix='tsbench-upstream-zstd-') as tmp:
        out, op = invoke_isolated_tool(run / DIRECTORY, plan['decoder'], ZSTD_TOOL, plan['limits'], Path(tmp), logs,
                                       UPSTREAM_ENCODE, {'raw':raw}, ['encode','/inputs/raw','/out/payload'], cancelled)
        operations.append(op)
        require(op['status'] == 'completed', 'upstream Zstd encode did not complete: ' + op['reason'])
        count, = _worker_json(logs / (UPSTREAM_ENCODE+'.stdout'), 1)
        require(count == {'rows':slot['original']['column_bytes'][0]}, 'upstream Zstd source byte count differs')
        _expect_files(out, ('payload',))
        payload = out / 'payload'
        require(6 <= payload.stat().st_size <= 66000, 'upstream Zstd payload exceeds declared bound')
        path = run / 'controls' / (slot['product_slot']+'.zst')
        with path.open('xb') as stream:
            stream.write(payload.read_bytes())
        return _ref(run,path)


def _upstream_restore(bundle, plan, slot, artifact, control, logs, cancelled, operations=None):
    schema, _ = parts(artifact.read_bytes(), slot)
    wire = wrap(slot,schema,control.read_bytes())
    wire_info = inspect_linear(wire, slot, upstream=True)
    with tempfile.TemporaryDirectory(prefix='tsbench-upstream-restore-') as tmp:
        path = Path(tmp)/'upstream-frame'
        path.write_bytes(wire)
        observed = _restore(bundle,plan,slot,path,Path(tmp),logs,cancelled,operations,label=UPSTREAM_DECODE)
    return {'payload_validation':wire_info,'restored':observed}


def _rejected_decodes(bundle, plan, slot, artifact, logs, cancelled, operations=None):
    results = {}
    for name, changed in mutations(artifact.read_bytes(), slot).items():
        with tempfile.TemporaryDirectory(prefix='tsbench-mutated-decode-') as tmp:
            work = Path(tmp)
            path = work/'invalid-frame'
            path.write_bytes(changed)
            output, op = invoke_isolated_worker(bundle,plan['decoder'],_method(plan,slot),batch_limits(plan,slot),work,logs,
                                                 DECODE,{'frame':path},_decode_inputs(slot),cancelled,label=name)
            if operations is not None:
                operations.append(op)
            status = _decode_status(slot,name)
            require(_rejected_log(op, logs, name, status), f'{name} did not yield expected decoder status {status}')
            _expect_files(output, ())
            results[name] = {'sha256':sha(changed), 'bytes':len(changed), 'plugin_status':status}
    return results



def _decode_status(slot, name):
    return slot.get('reject_statuses', {}).get(name, 5)

def _rejected_log(op, logs, name, status):
    return (op['status'] == 'failed' and op['returncode'] == 3 and op['pid'] is not None and
            _diagnostic(logs / (name+'.stderr')).startswith(f'plugin status {status}: ') and
            (logs / (name+'.stdout')).stat().st_size == 0)


def _requires_fenv(plan, slot):
    return (plan['schema'] in LINEAR_SCHEMAS and FENV_TOOL in plan['direct_control']['tool_refs'] and
            slot['product_slot'] in plan['obligation_bindings'][fenv_binding_key(plan.get('suite'))]['product_slots'])


def _fenv_log(logs, slot):
    observed, = _worker_json(logs / (FENV_OP+'.stdout'),1)
    reject = {'status':1,'written':0,'rounding_diagnostic_matches':1}
    require(observed == {'before':0, 'changed':0x400, 'after':0, 'rows':slot['original']['columns'][0]['count'],
                         'encode':reject,'decode':reject}, 'ALP native fenv rejection differs')
    return observed


def _fenv(bundle, plan, slot, raw, artifact, logs, cancelled, operations=None):
    _, payload = parts(artifact.read_bytes(),slot)
    with tempfile.TemporaryDirectory(prefix='tsbench-alp-fenv-') as tmp:
        work = Path(tmp)
        frame = work/'payload'
        frame.write_bytes(payload)
        output, op = invoke_isolated_tool(bundle,plan['decoder'],FENV_TOOL,plan['limits'],work,logs,FENV_OP,
                                          {'raw':raw,'payload':frame},['/inputs/raw','/inputs/payload'],cancelled)
        if operations is not None:
            operations.append(op)
        require(op['status'] == 'completed', 'ALP fenv tool did not complete: ' + op['reason'])
        _expect_files(output, ())
    return {'observation':_fenv_log(logs,slot), 'native_payload_sha256':sha(payload),
            'original_sha256':slot['original']['column_sha256'][0]}


def _titchy_control(bundle, plan, slot, original, artifact, inspection, logs, cancelled, operations=None):
    with tempfile.TemporaryDirectory(prefix='tsbench-titchy-control-') as tmp:
        output, op = invoke_isolated_tool(bundle,plan['decoder'],TITCHY_TOOL,plan['limits'],Path(tmp),logs,TITCHY_OP,
            {'raw':original},[str(inspection['wire']['width']),'/inputs/raw','/out/payload'],cancelled)
        if operations is not None:
            operations.append(op)
        require(op['status'] == 'completed', 'Titchy direct tool did not complete: '+op['reason'])
        _expect_files(output, ('payload',))
        path = output/'payload'
        require(0 < path.stat().st_size <= inspection['wire']['native_bound'], 'direct Titchy payload outside bound')
        data = path.read_bytes()
        require(data == parts(artifact.read_bytes(),slot)[1], 'direct C11 and plugin Titchy payload differ')
        diag, = _worker_json(logs/(TITCHY_OP+'.stdout'),1)
        require(diag == titchy_direct_observation(slot,inspection,len(data)), 'Titchy native capacity evidence differs')
        return data


def _xz_direct_log(slot, wire, logs):
    diag, = _worker_json(logs/(XZ_OP+'.stdout'),1)
    require(canonical_bytes(diag) == canonical_bytes(xz_direct_observation(slot)), 'XZ direct invocation observation differs')
    guard = mutations(wire,slot).get('oversize_dictionary')
    return {'observation':diag,
            'original_sha256':slot['original']['column_sha256'][0],
            'native_payload_sha256':sha(parts(wire,slot)[1]),
            'dictionary_guard_sha256':sha(parts(guard,slot)[1]) if guard is not None else None}


def _xz_control(bundle, plan, slot, original, artifact, logs, cancelled, operations=None):
    wire = artifact.read_bytes()
    with tempfile.TemporaryDirectory(prefix='tsbench-xz-control-') as tmp:
        work = Path(tmp)
        inputs = {'raw':original,'payload':work/'payload'}
        inputs['payload'].write_bytes(parts(wire,slot)[1])
        guard = mutations(wire,slot).get('oversize_dictionary')
        if guard is not None:
            inputs['guard'] = work/'guard'
            inputs['guard'].write_bytes(parts(guard,slot)[1])
        output, op = invoke_isolated_tool(bundle,plan['decoder'],XZ_TOOL,batch_limits(plan,slot),work,logs,XZ_OP,
            inputs,[f'/inputs/{name}' for name in inputs],cancelled)
        if operations is not None:
            operations.append(op)
        require(op['status'] == 'completed', 'XZ direct control did not complete: '+op['reason'])
        _expect_files(output, ())
    return _xz_direct_log(slot,wire,logs)


def _pcodec_direct_log(slot, payload, logs):
    observation, = _worker_json(logs/(PCO_OP+'.stdout'),1)
    want = pcodec_direct_observation(slot,len(payload) if payload is not None else None)
    require(canonical_bytes(observation) == canonical_bytes(want), 'pcodec direct invocation observation differs')
    return {'observation':observation,'original_sha256':slot['original']['column_sha256'][0],
            'native_payload_sha256':sha(payload) if payload is not None else None}


def _pcodec_control(bundle, plan, slot, original, artifact, logs, cancelled, operations=None):
    payload = parts(artifact.read_bytes(),slot)[1] if artifact is not None else None
    with tempfile.TemporaryDirectory(prefix='tsbench-pcodec-control-') as tmp:
        work = Path(tmp)
        inputs = {'raw':original}
        if payload is not None:
            inputs['payload'] = work/'payload'
            inputs['payload'].write_bytes(payload)
        lane = 'source' if slot['method'] == PCO_SOURCE else 'native'
        output, op = invoke_isolated_tool(bundle,plan['decoder'],PCO_TOOL,batch_limits(plan,slot),work,logs,PCO_OP,
            inputs,[lane,str(slot['wire_checks']['native_type']),*(f'/inputs/{name}' for name in inputs)],cancelled)
        if operations is not None:
            operations.append(op)
        require(op['status'] == 'completed', 'pcodec direct control did not complete: '+op['reason'])
        _expect_files(output, ())
    return _pcodec_direct_log(slot,payload,logs)


def _encode(bundle, plan, slot, work, logs, inputs, cancelled):
    args = ['/inputs/schema', '/out/frame']
    for name, col in zip(_column_names(slot), slot['original']['columns'], strict=True):
        args.extend((str(col['dtype']), f'/inputs/{name}'))
    return invoke_isolated_worker(bundle,plan['decoder'],_method(plan,slot),batch_limits(plan,slot),
                                  work,logs,ENCODE,inputs,args,cancelled)


def _case(run, plan, slot, sample, cancelled):
    sid = slot['product_slot']
    row = {'product_slot': sid, 'status': 'cancelled', 'reason': 'cancelled before product', 'operations': [],
           'artifact': None, 'payload_validation': None, 'restored': None}
    cross = _requires_cross(plan, slot)
    linear = plan['schema'] in LINEAR_SCHEMAS
    fenv = _requires_fenv(plan, slot)
    direct_titchy = wants_titchy_direct(plan,slot)
    direct_xz = wants_xz_direct(plan,slot)
    direct_pco = wants_pcodec_direct(plan,slot)
    if linear:
        row.update(control_payload=None, upstream_restored=None, decoder_rejections=None)
        if fenv:
            row['fenv_control'] = None
        if direct_xz:
            row['xz_control'] = None
        if direct_pco:
            row['pcodec_control'] = None
    if plan['schema'] == CROSS_SCHEMA or (linear and is_gorilla_slot(slot)):
        row.update(control_payload=None, cross_restored=None)
    if cancelled():
        return row
    logs = run / 'logs' / sid
    logs.mkdir()
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-native-product-') as tmp:
            work = Path(tmp)
            source = work / 'source'
            source.mkdir()
            inputs = {name: source / name for name in ('schema', *_column_names(slot))}
            for path, data in zip(inputs.values(), (sample.schema, *sample.columns), strict=True):
                path.write_bytes(data)
            output, operation = _encode(run / DIRECTORY,plan,slot,work,logs,inputs,cancelled)
            row['operations'].append(operation)
            if slot['expected_status']:
                expected = slot['expected_status']
                require(_rejected_log(operation,logs,ENCODE,expected), 'encode did not yield expected '+INPUT_STATUS[expected])
                _expect_files(output, ())
                if direct_pco:
                    row['pcodec_control'] = _pcodec_control(run / DIRECTORY,plan,slot,inputs['v'],None,logs,cancelled,row['operations'])
                row.update(status='expected_rejection', reason=INPUT_STATUS[expected])
                return row
            require(operation['status'] == 'completed', 'encode did not complete: ' + operation['reason'])
            _expect_files(output, ('frame',))
            staged = output / 'frame'
            require(staged.stat().st_size <= slot['max_frame_bytes'], 'encoded product exceeded frozen per-product capacity')
            artifact = run / 'products' / (sid + '.bmk')
            with artifact.open('xb') as stream:
                stream.write(staged.read_bytes())
            row['artifact'] = _ref(run, artifact)
            row['payload_validation'] = _inspect(artifact, slot, sample.columns[0] if linear else None)
            if fenv:
                row['fenv_control'] = _fenv(run / DIRECTORY,plan,slot,inputs['v'],artifact,logs,cancelled,row['operations'])
            if direct_xz:
                row['xz_control'] = _xz_control(run / DIRECTORY,plan,slot,inputs['v'],artifact,logs,cancelled,row['operations'])
            if direct_pco:
                row['pcodec_control'] = _pcodec_control(run / DIRECTORY,plan,slot,inputs['v'],artifact,logs,cancelled,row['operations'])
            if direct_titchy:
                data = _titchy_control(run / DIRECTORY,plan,slot,inputs['v'],artifact,row['payload_validation'],logs,cancelled,
                                       row['operations'])
                path = run/'controls'/(sid+'.tchy')
                with path.open('xb') as stream:
                    stream.write(data)
                row['control_payload'] = _ref(run,path)
            if cross:
                row['control_payload'] = _native_encode(run, plan, slot, inputs, logs, cancelled, row['operations'])
            elif linear and slot['upstream_zstd']:
                row['control_payload'] = _upstream_encode(run,plan,slot,inputs['v'],logs,cancelled,row['operations'])
        # The encoding directory (including materialized input columns) is now gone.
        with tempfile.TemporaryDirectory(prefix='tsbench-native-restore-') as tmp:
            row['restored'] = _restore(run / DIRECTORY, plan, slot, artifact, Path(tmp), logs, cancelled, row['operations'])
        if cross:
            row['cross_restored'] = _cross_restore(run / DIRECTORY, plan, slot, artifact, run / row['control_payload']['path'],
                                                    logs, cancelled, row['operations'])
        if linear and not is_gorilla_slot(slot):
            _check_linear_logs(slot, row, logs)
            if slot['reject_decodes']:
                row['decoder_rejections'] = _rejected_decodes(run / DIRECTORY,plan,slot,artifact,logs,cancelled,row['operations'])
            if slot['upstream_zstd']:
                row['upstream_restored'] = _upstream_restore(run / DIRECTORY,plan,slot,artifact,run / row['control_payload']['path'],
                                                            logs,cancelled,row['operations'])
        row.update(status='verified', reason='')
    except (ContractError, OSError, UnicodeError) as exc:
        last = row['operations'][-1] if row['operations'] else {}
        status = last.get('status')
        if status not in {'cancelled', 'timeout', 'crash', 'dependency_failed', 'file_limit_signal', 'sandbox_failed'}:
            status = 'validation_failed' if status == 'completed' else 'execution_failed'
        row.update(status=status, reason=str(exc))
    return row


def _files(run):
    files = {}
    for path in run.rglob('*'):
        require(not path.is_symlink() and (path.is_file() or path.is_dir()), 'unexpected nonregular batch evidence')
        if path.is_file() and path != run / SEAL:
            ref = _ref(run, path)
            files[ref['path']] = ref
    return files


def run_batch_execution(root: Path, plan: dict, results: Path, *, cancelled=lambda: False) -> dict:
    check_batch_execution(plan)
    linear = plan['schema'] in LINEAR_SCHEMAS
    direct = plan['direct_control']['tool_refs'][ZSTD_TOOL]['path'] if linear else direct_path(plan)
    fenv = plan['direct_control']['tool_refs'].get(FENV_TOOL, {}).get('path') if linear else None
    titchy = plan['direct_control']['tool_refs'].get(TITCHY_TOOL, {}).get('path') if linear else None
    xz = plan['direct_control']['tool_refs'].get(XZ_TOOL, {}).get('path') if linear else None
    pcodec = plan['direct_control']['tool_refs'].get(PCO_TOOL, {}).get('path') if linear else None
    page_driver = plan['direct_control']['tool_refs'].get(WRAPPED_TOOL, {}).get('path') if linear else None
    suite = plan.get('suite', 'linear-v1') if linear else 'gorilla'
    gorilla = plan['direct_control']['tool_refs'][DIRECT_TOOL]['path'] if suite in UNIFIED_SUITES else None
    ordered = plan['direct_control']['tool_refs'][SELFSTAR_TOOL]['path'] if suite in ORDERED_SUITES else None
    entropy = plan['direct_control']['tool_refs'][HUFF_TOOL]['path'] if suite in ENTROPY_SUITES else None
    fire = plan['direct_control']['tool_refs'][SPRINTZ_TOOL]['path'] if suite in SPRINTZ_SUITES else None
    reader = plan['direct_control']['tool_refs'][ACCESS_TOOL]['path'] if suite in ACCESS_SUITES else None
    packet_driver = plan['direct_control']['tool_refs'][STREAM_TOOL]['path'] if suite in STREAM_SUITES else None
    portable = plan.get(bmi2.KEY)
    expected, inputs = compile_batch_suite(root, plan['build'], direct, suite, fenv, titchy, xz, pcodec, page_driver,gorilla,ordered,entropy,fire,reader,packet_driver,
                                          huff0_portable_build=portable['build_dir'] if portable else None)
    require(canonical_bytes(plan) == canonical_bytes(expected), 'batch execution plan differs from current frozen inputs or build')
    run_id = uuid.uuid4().hex
    run = results.resolve() / run_id
    require(results.is_dir(), 'batch execution results parent must already exist')
    # Stage dependency assets before publishing a new run. Pre-submit copy failures
    # cannot leave a directory that could be mistaken for an executed run.
    with tempfile.TemporaryDirectory(prefix='.batch-submit-', dir=results.resolve()) as tmp:
        staging = Path(tmp) / 'run'
        staging.mkdir()
        for name in ('products', 'logs', *(['controls'] if plan['schema'] in {CROSS_SCHEMA, *LINEAR_SCHEMAS} else [])):
            (staging / name).mkdir()
        write_new(staging / PLAN, plan)
        stage_recovery(root, staging, plan['decoder'])
        if portable:
            stage_recovery(root,staging,portable['decoder'],directory=bmi2.DIRECTORY)
        staging.rename(run)
    with (run / LEDGER).open('xb') as ledger:
        for slot in plan['slots']:
            execute = (corad_training_execution.run_slot if is_training(slot) else corad_execution.run_slot if is_corad(slot) else pbepla_execution.run_slot if is_pbepla(slot) else wrapped.run_slot if is_wrapped(slot) else selfstar.run_slot if is_selfstar(slot) else
                       huff.run_slot if is_huff0(slot) else sprintz.run_slot if is_sprintz(slot) else
                       access.run_slot if is_access(slot) else stream.run_slot if is_stream(slot) else
                       intmult.run_slot if is_intmult(slot) else lifecycle.run_slot if is_state(slot) else
                       byte_session.run_slot if is_session(slot) else
                       native_profiles.run_slot if is_profile(slot) else alp_decode.run_slot if is_decode(slot) else zfp_execution.run_slot if is_zfp(slot) else _case)
            _line(ledger, execute(run,plan,slot,inputs[slot['product_slot']],cancelled))
    seal = {'schema': _seal_schema(plan), 'run_id': run_id, 'plan_content_id': plan['plan_content_id'],
            'files': _files(run)}
    write_new(run / SEAL, {**seal, 'seal_id': content_id(seal)})
    return report_batch_execution(run)



def _completed(op):
    return op['status'] == 'completed' and op['returncode'] == 0 and op['pid'] is not None


def _check_linear_logs(slot, row, logs):
    encode, = _worker_json(logs / (ENCODE+'.stdout'), 1)
    shape, decode = _worker_json(logs / (DECODE+'.stdout'), 2)
    require(shape == {'columns':slot['original']['columns']}, 'linear decode shape differs')
    check_info(slot,row['payload_validation']['wire'],encode,decode)


def _linear_order(plan, slot):
    pcodec = [PCO_OP] if wants_pcodec_direct(plan,slot) else []
    return [ENCODE,*pcodec] if slot['expected_status'] else [ENCODE,
        *([FENV_OP] if _requires_fenv(plan,slot) else []),
        *([TITCHY_OP] if wants_titchy_direct(plan,slot) else []),
        *([XZ_OP] if wants_xz_direct(plan,slot) else []),
        *pcodec,
        *([UPSTREAM_ENCODE] if slot['upstream_zstd'] else []), DECODE, *slot['reject_decodes'],
        *([UPSTREAM_DECODE] if slot['upstream_zstd'] else [])]


def _verify_linear(plan, row, slot, run, ref, control):
    logs = run / 'logs' / row['product_slot']
    _check_linear_logs(slot,row,logs)
    op_map = {op['operation']:op for op in row['operations']}
    artifact = run / ref['path']
    if _requires_fenv(plan,slot):
        require(row['fenv_control'] == {'observation':_fenv_log(logs,slot),
                                        'native_payload_sha256':row['payload_validation']['native_payload_sha256'],
                                        'original_sha256':slot['original']['column_sha256'][0]}, 'ALP fenv ledger differs')
    else:
        require(row.get('fenv_control') is None, 'unexpected ALP fenv ledger')
    if slot['reject_decodes']:
        expected = mutations(artifact.read_bytes(),slot)
        require(row['decoder_rejections'] == {name:{'sha256':sha(data), 'bytes':len(data), 'plugin_status':_decode_status(slot,name)}
                for name,data in expected.items()}, 'linear rejection evidence differs from derived inputs')
        require(all(_rejected_log(op_map[name],logs,name,_decode_status(slot,name)) for name in expected), 'linear rejection logs differ')
    else:
        require(row['decoder_rejections'] is None, 'unexpected decode negatives')
    if wants_titchy_direct(plan,slot):
        inspection = row['payload_validation']
        require(control is not None and control['sha256'] == inspection['native_payload_sha256'] and
                control['bytes'] == inspection['native_payload_bytes'], 'retained direct Titchy payload differs')
        diag, = _worker_json(logs/(TITCHY_OP+'.stdout'),1)
        require(diag == titchy_direct_observation(slot,inspection,control['bytes']), 'retained Titchy capacity evidence differs')
    if wants_xz_direct(plan,slot):
        require(row['xz_control'] == _xz_direct_log(slot,artifact.read_bytes(),logs), 'retained XZ direct evidence differs')
    else:
        require(row.get('xz_control') is None, 'unexpected XZ direct evidence')
    if wants_pcodec_direct(plan,slot):
        require(row['pcodec_control'] == _pcodec_direct_log(slot,parts(artifact.read_bytes(),slot)[1],logs),
                'retained pcodec direct evidence differs')
    else:
        require(row.get('pcodec_control') is None, 'unexpected pcodec direct evidence')
    if slot['upstream_zstd']:
        require(control is not None, 'missing upstream payload')
        schema, _ = parts(artifact.read_bytes(),slot)
        info = inspect_linear(wrap(slot,schema,(run/control['path']).read_bytes()),slot,upstream=True)
        require(row['upstream_restored'] == {'payload_validation':info, 'restored':slot['original']},
                'Zstd upstream restore evidence differs')
        count, = _worker_json(logs / (UPSTREAM_ENCODE+'.stdout'), 1)
        shape, decoded = _worker_json(logs / (UPSTREAM_DECODE+'.stdout'), 2)
        require(count == {'rows':slot['original']['column_bytes'][0]} and shape == {'columns':slot['original']['columns']} and
                decoded['operation'] == 'decode' and decoded['backend'] == 'ln-zstd-baseline' and decoded['threads'] == 1,
                'Zstd upstream encode/decode event differs')
    else:
        require(row['upstream_restored'] is None, 'unexpected upstream recovery evidence')

def _replay(run):
    seal, plan = load_json(run / SEAL), load_json(run / PLAN)
    check_batch_execution(plan)
    require(seal.get('schema') == _seal_schema(plan) and
            re.fullmatch(r'[a-f0-9]{32}', seal['run_id']) is not None and
            seal['plan_content_id'] == plan['plan_content_id'] and
            seal.get('seal_id') == content_id({k:v for k,v in seal.items() if k != 'seal_id'}) and
            seal['files'] == _files(run), 'batch evidence seal differs')
    closures = {DIRECTORY:plan['decoder']}
    if bmi2.KEY in plan:
        closures[bmi2.DIRECTORY] = plan[bmi2.KEY]['decoder']
    packaged = {path:{'path':path,'bytes':row['bytes'],'sha256':row['sha256']} for directory,spec in closures.items()
                for key,row in spec['files'].items() for path in [f'{directory}/{key}']}
    allowed = {PLAN, LEDGER, *packaged}
    require(all(seal['files'].get(k) == v for k,v in packaged.items()), 'batch recovery package differs')
    ledger = _rows(run / LEDGER)
    require(len(plan['slots']) == len(ledger) and len(ledger) == len({r['product_slot'] for r in ledger}),
            'batch ledger slot count or uniqueness differs')
    successes = set()
    linear = plan['schema'] in LINEAR_SCHEMAS
    for slot, row in zip(plan['slots'], ledger, strict=True):
        sid, state = row['product_slot'], row['status']
        require(re.fullmatch(r'[a-f0-9]{64}', sid) is not None and sid == slot['product_slot'], 'batch ledger order differs')
        if is_training(slot):
            if corad_training_execution.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_corad(slot):
            if corad_execution.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_pbepla(slot):
            if pbepla_execution.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_wrapped(slot):
            if wrapped.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_selfstar(slot):
            if selfstar.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_huff0(slot):
            if huff.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_sprintz(slot):
            if sprintz.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_access(slot):
            if access.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_stream(slot):
            if stream.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_intmult(slot):
            if intmult.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_state(slot):
            if lifecycle.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_session(slot):
            if byte_session.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_profile(slot):
            if native_profiles.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_decode(slot):
            if alp_decode.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        if is_zfp(slot):
            if zfp_execution.inspect_evidence(run,plan,slot,row,seal['files'],allowed):
                successes.add(sid)
            continue
        ops = row['operations']
        required_cross = _requires_cross(plan, slot)
        if plan.get('suite') in UNIFIED_SUITES:
            order = [o['label'] for o in plan['execution_binding']['drivers'][sid]['operations']]
        else:
            order = _linear_order(plan, slot) if linear else ([ENCODE, NATIVE_ENCODE, DECODE, NATIVE_DECODE, CROSS_DECODE]
                    if required_cross else ([ENCODE] if slot['expected_status'] == 7 else [ENCODE, DECODE]))
        negatives = slot['reject_decodes'] if linear else ()
        logs_root = run / 'logs' / sid
        def matches(op):
            name = op['operation']
            if name == ENCODE and slot['expected_status']:
                return _rejected_log(op,logs_root,ENCODE,slot['expected_status'])
            return _rejected_log(op, logs_root, name, _decode_status(slot,name)) if name in negatives else _completed(op)
        require([op['operation'] for op in ops] == order[:len(ops)] and
                all(matches(op) for op in ops[:-1]), 'batch operation order differs')
        for op in ops:
            logs = {f"logs/{sid}/{op['operation']}.{ext}" for ext in ('stdout', 'stderr')}
            allowed.update(logs)
            require(all(seal['files'][p]['bytes'] <= batch_limits(plan,slot)['file_bytes'] for p in logs if p in seal['files']) and
                    (op['pid'] is None or logs <= seal['files'].keys()), 'batch worker output logs missing or too large')
        ref = row['artifact']
        if ref is not None:
            name = f'products/{sid}.bmk'
            require(ref['path'] == name and seal['files'].get(name) == ref and slot['expected_status'] == 0 and
                    ops and ops[0]['status'] == 'completed', 'invalid batch artifact reference')
            allowed.add(name)
        native = row.get('control_payload')
        cross_observed = row.get('cross_restored')
        if native is not None:
            titchy = wants_titchy_direct(plan,slot)
            suffix = 'xor' if required_cross else 'tchy' if titchy else 'zst'
            name = f'controls/{sid}.{suffix}'
            ctrl = required_cross or (linear and (slot['upstream_zstd'] or titchy))
            lo, hi = ((38,slot['max_frame_bytes']-32-slot['original']['schema_bytes']) if titchy else
                      (2,max_payload(slot['original']['columns'][0]['count'])) if required_cross else (6,66000))
            require(ctrl and len(ops) >= 2 and _completed(ops[1]) and native['path'] == name and
                    seal['files'].get(name) == native and lo <= native['bytes'] <= hi,
                    'invalid retained direct payload reference')
            allowed.add(name)
        if row['restored'] is not None:
            require(ref is not None and any(op['operation'] == DECODE and op['status'] == 'completed' for op in ops) and
                    row['restored'] == slot['original'] and row['payload_validation'] == _inspect(run / ref['path'], slot),
                    'restoration observation does not match retained artifact and original domain')
            shape, _ = _worker_json(run / 'logs' / sid / (DECODE + '.stdout'), 2)
            require(shape == {'columns': slot['original']['columns']}, 'retained decoder shape differs')
        if state == 'verified':
            require(row['restored'] is not None and len(ops) == len(order) and all(matches(op) for op in ops),
                    'verified batch did not complete its required operations')
            if linear and not is_gorilla_slot(slot):
                _verify_linear(plan,row,slot,run,ref,native)
            elif required_cross:
                source = slot['original']
                want = {'abi_to_native': {k: source[k] for k in ('column_bytes', 'column_sha256')}, 'native_to_abi': source}
                require(native is not None and native['sha256'] == row['payload_validation']['native_payload_sha256'] and
                        cross_observed == want, 'retained direct C cross evidence differs')
                logs = run / 'logs' / sid
                for op in (NATIVE_ENCODE, NATIVE_DECODE):
                    count, = _worker_json(logs / (op + '.stdout'), 1)
                    require(count == {'rows': source['columns'][0]['count']}, 'retained direct C row count differs')
                shape, _ = _worker_json(logs / (CROSS_DECODE + '.stdout'), 2)
                require(shape == {'columns': source['columns']}, 'cross decoder shape differs')
            else:
                require(cross_observed is None, 'unexpected direct C cross observation')
            successes.add(sid)
        elif state == 'expected_rejection':
            expected = slot['expected_status']
            direct_pco = wants_pcodec_direct(plan,slot)
            require(expected in INPUT_STATUS and row['reason'] == INPUT_STATUS[expected] and ref is None and
                    row['restored'] is None and row['payload_validation'] is None and cross_observed is None and
                    len(ops) == (2 if direct_pco else 1) and all(matches(op) for op in ops),
                    'rejection does not match required worker evidence')
            if direct_pco:
                require(row['pcodec_control'] == _pcodec_direct_log(slot,None,logs_root), 'retained pcodec f16 refusal differs')
            else:
                require(row.get('pcodec_control') is None, 'unexpected pcodec direct rejection evidence')
            successes.add(sid)
        else:
            require(state in {'cancelled', 'timeout', 'crash', 'dependency_failed', 'file_limit_signal', 'sandbox_failed',
                              'validation_failed', 'execution_failed'} and row['reason'] and cross_observed is None and
                    (row['restored'] is None or required_cross or linear),
                    'invalid nonpassing batch terminal')
    if plan.get('suite') in PBEPLA_NATIVE_SUITES:
        pbepla_execution.check_same_run(plan,ledger,successes)
    require(seal['files'].keys() <= allowed, 'extra undeclared batch evidence')
    totals = {'serialized_products_bytes': sum(ref['bytes'] for key,ref in seal['files'].items() if key.startswith('products/')),
              'operation_logs_bytes': sum(ref['bytes'] for key,ref in seal['files'].items() if key.startswith('logs/')),
              'shared_decoder_bytes': sum(ref['bytes'] for ref in packaged.values())}
    if plan['schema'] in {CROSS_SCHEMA, *LINEAR_SCHEMAS}:
        totals['control_payload_bytes'] = sum(ref['bytes'] for key,ref in seal['files'].items() if key.startswith('controls/'))
    require(all(num <= plan['retention_bounds'][k] for k,num in totals.items()), 'retained evidence exceeds frozen capacity')
    return seal, plan, ledger, totals, successes


def report_batch_execution(run: Path) -> dict:
    seal, plan, ledger, totals, successes = _replay(run)
    checks = {}
    alp_decode_suite = plan.get('suite') in ALP_DECODE_SUITES
    required_checks = []
    conditional_checks = []
    by_product = {row['product_slot']:row for row in ledger} if alp_decode_suite else {}
    for name, binding in plan['obligation_bindings'].items():
        passed = set(binding['product_slots']) <= successes
        # An independent format reader is one direction, not a same-run direct-C encoder/decoder parity control.
        checks[name] = {**binding, 'state': ('incomplete_direct_c_cross_control' if name == cross_binding_key(plan) and
                       DIRECT_TOOL not in (plan.get('direct_control') or {}).get('tool_refs',{})
                       else 'verified_candidate') if passed else 'missing_or_failed_products'}
        if passed and name in plan.get('unbound_controls', {}):
            checks[name].update(state='incomplete_required_control', reason=plan['unbound_controls'][name])
        if passed and name==f'80/corad-inference/{CORAD_QUALITY_CHECK}':
            sid, = binding['product_slots']
            if not by_product[sid]['corad']['quality_comparable']:
                checks[name].update(state='quality_rejected',reason='predeclared_heldout_original_domain_bounds_exceeded')
        if alp_decode_suite:
            ob = plan['execution_binding']['bound_obligations'][binding['obligation_id']]
            if 'condition_case' not in ob:
                required_checks.append(name)
            else:
                conditional_checks.append(name)
                if passed and ob['condition_case']['bundle_key']=='alp':
                    sid, = binding['product_slots']
                    checks[name]['state'] = alp_decode.condition_state(ob['condition_case']['criteria'],by_product[sid])
                if passed and ob['check']==bmi2.CHECK:
                    checks[name].update(huff.condition_evidence([by_product[s] for s in binding['product_slots']]))
    version = 3 if plan['schema'] in LINEAR_SCHEMAS else 2 if plan['schema'] == CROSS_SCHEMA else 1
    report = {'schema': f'bmk.lossless-batch-execution-report/{version}', 'run_id': seal['run_id'], 'seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], 'planned_products': len(ledger),
            'terminal_counts': dict(Counter(row['status'] for row in ledger)), 'retained_bytes': totals,
            'obligation_evidence': checks, 'all_product_expectations_met': len(successes) == len(ledger),
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}
    if version == 3:
        methods = {**plan['methods'],**plan.get('protocol_methods',{})}
        report['methods'] = {name:dict(Counter(row['status'] for slot,row in zip(plan['slots'],ledger,strict=True)
                            if slot['method'] == name)) for name in methods}
        report['all_candidate_obligations_evidenced'] = all(c['state'] == 'verified_candidate' for c in checks.values())
    if plan.get('suite') in UNIFIED_SUITES:
        view = plan['execution_binding']
        report['schema'] = ('bmk.native-batch-execution-report/1' if plan['schema']==MIXED_SCHEMA
                            else 'bmk.lossless-batch-execution-report/4')
        report['execution_scope'] = {'admission_plan_id':view['admission_plan_id'],
            'bound_routes':view['bound_routes'],'total_routes':view['total_routes'],
            'bound_obligations':len(view['bound_obligations']),'unbound_obligations':len(view['unbound_obligations']),
            'all_native_bindings_complete':False}
        if plan.get('suite') in LZBENCH_PROFILE_SUITES:
            n = sum('condition_case' in o for o in view['bound_obligations'].values())
            report['execution_scope'].update(bound_required_obligations=len(view['bound_obligations'])-n,
                                             bound_conditional_obligations=n)
    if plan.get('suite') in CORAD_INFERENCE_SUITES:
        row, = [r for sl,r in zip(plan['slots'],ledger,strict=True) if is_corad(sl)]
        report['corad_inference'] = None if row['corad'] is None else {
            k:row['corad'][k] for k in ('functional_restoration','quality_comparable','quality_gate')}
    if plan.get('suite') in CORAD_TRAINING_SUITES:
        report['corad_training'] = {s['method']:None if r['training'] is None else {
            'models':r['training']['inference'],'model_quality_policy':r['training']['model_quality_policy'],
            'deployment_overwritten':r['training']['deployment_overwritten']}
            for s,r in zip(plan['slots'],ledger,strict=True) if is_training(s)}
        report['execution_scope']['all_native_bindings_complete'] = not view['unbound_obligations']
    if alp_decode_suite:
        report['all_candidate_required_obligations_evidenced'] = all(checks[k]['state']=='verified_candidate' for k in required_checks)
        report['execution_scope']['bound_conditional_states'] = dict(Counter(checks[k]['state'] for k in conditional_checks))
    return report


def audit_batch_execution(run: Path) -> dict:
    seal, plan, ledger, _, successes = _replay(run)
    require(launcher_lock() == plan['launchers'], 'batch audit launchers differ from the frozen environment')
    restored, replayed_pcodec_rejections, wrapped_products, selfstar_products, huff_products = [], [], [], [], []
    sprintz_products, access_products, stream_products = [], [], []
    intmult_products, intmult_rejections, gorilla_state_products, session_products = [], [], [], []
    profile_products, alp_products, zfp_products = [], [], []
    pbepla_products, pbepla_rejections, corad_products, training_products = [], [], [], []
    pcodec_negatives = [(slot,row) for slot,row in zip(plan['slots'],ledger,strict=True)
                        if wants_pcodec_direct(plan,slot) and row['status'] == 'expected_rejection']
    bundle = run / DIRECTORY
    for slot, row in zip(plan['slots'], ledger, strict=True):
        if is_training(slot):
            if row['product_slot'] in successes:
                training_products.append(corad_training_execution.audit_slot(run,plan,slot,row))
            continue
        if is_corad(slot):
            if row['product_slot'] in successes:
                corad_products.append(corad_execution.audit_slot(run,plan,slot,row))
            continue
        if is_pbepla(slot):
            if row['product_slot'] in successes:
                (pbepla_products if row['status']=='verified' else pbepla_rejections).append(
                    pbepla_execution.audit_slot(run,plan,slot,row))
            continue
        if is_intmult(slot):
            if row['status']=='verified':
                intmult_products.append(intmult.audit_slot(run,plan,slot,row))
            elif row['status']=='expected_rejection':
                intmult_rejections.append(intmult.audit_slot(run,plan,slot,row))
            continue
        if row['status'] != 'verified':
            continue
        if is_state(slot):
            gorilla_state_products.append(lifecycle.audit_slot(run,plan,slot,row))
            continue
        if is_session(slot):
            session_products.append(byte_session.audit_slot(run,plan,slot,row))
            continue
        if is_profile(slot):
            profile_products.append(native_profiles.audit_slot(run,plan,slot,row))
            continue
        if is_decode(slot):
            alp_products.append(alp_decode.audit_slot(run,plan,slot,row))
            continue
        if is_zfp(slot):
            zfp_products.append(zfp_execution.audit_slot(run,plan,slot,row))
            continue
        if is_wrapped(slot):
            wrapped_products.append(wrapped.restore_slot(run,plan,slot,row))
            continue
        if is_selfstar(slot):
            selfstar_products.append(selfstar.restore_slot(run,plan,slot,row))
            continue
        if is_huff0(slot):
            huff_products.append(huff.restore_slot(run,plan,slot,row))
            continue
        if is_sprintz(slot):
            sprintz_products.append(sprintz.restore_slot(run,plan,slot,row))
            continue
        if is_access(slot):
            access_products.append(access.restore_slot(run,plan,slot,row))
            continue
        if is_stream(slot):
            stream_products.append(stream.restore_slot(run,plan,slot,row))
            continue
        with tempfile.TemporaryDirectory(prefix='tsbench-batch-audit-') as tmp:
            work = Path(tmp)
            frame = verify_asset(run, row['artifact'])
            result = _restore(run / DIRECTORY, plan, slot, frame, work, work, lambda: False)
            row_result = {'product_slot': slot['product_slot'], 'artifact': row['artifact'], 'restored': result}
            if plan['schema'] in LINEAR_SCHEMAS:
                row_result['method'] = slot['method']
                if wants_titchy_direct(plan,slot):
                    replay = _titchy_control(run / DIRECTORY,plan,slot,work/'out'/'v',frame,row['payload_validation'],work,lambda:False)
                    control = verify_asset(run,row['control_payload'])
                    require(replay == control.read_bytes(), 'replayed direct Titchy payload differs')
                    row_result['titchy_direct_payload'] = row['control_payload']
                if wants_xz_direct(plan,slot):
                    replay = _xz_control(run / DIRECTORY,plan,slot,work/'out'/'v',frame,work,lambda:False)
                    require(replay == row['xz_control'], 'replayed XZ direct evidence differs')
                    row_result['xz_control'] = replay
                if wants_pcodec_direct(plan,slot):
                    replay = _pcodec_control(bundle,plan,slot,work/'out'/'v',frame,work,lambda:False)
                    require(replay == row['pcodec_control'], 'replayed pcodec direct evidence differs')
                    row_result['pcodec_control'] = replay
                    if slot['method'] == PCO_SOURCE:
                        for denied, evidence in pcodec_negatives:
                            if denied['original'] != result:
                                continue
                            sub = work/'negative'; sub.mkdir()
                            inputs = {n:work/'out'/n for n in ('schema','v')}
                            out, op = _encode(bundle,plan,denied,sub,sub,inputs,lambda:False)
                            require(_rejected_log(op,sub,ENCODE,denied['expected_status']), 'replayed pcodec ABI f16 refusal differs')
                            _expect_files(out, ())
                            native = _pcodec_control(bundle,plan,denied,inputs['v'],None,sub,lambda:False)
                            require(native == evidence['pcodec_control'], 'replayed pcodec native f16 refusal differs')
                            replayed_pcodec_rejections.append({'product_slot':denied['product_slot'],
                                'recovered_input_slot':slot['product_slot'], 'abi_status':denied['expected_status'], 'native':native})
                if _requires_fenv(plan,slot):
                    fenv = _fenv(run / DIRECTORY,plan,slot,work/'out'/'v',frame,work,lambda:False)
                    require(fenv == row['fenv_control'], 'replayed ALP fenv negative differs')
                    row_result['fenv_control'] = fenv
                if slot['reject_decodes']:
                    negatives = _rejected_decodes(run / DIRECTORY,plan,slot,frame,work,lambda:False)
                    require(negatives == row['decoder_rejections'], 'replayed malformed decode rejections differ')
                    row_result['decoder_rejections'] = negatives
                if slot['upstream_zstd']:
                    control = verify_asset(run,row['control_payload'])
                    from_upstream = _upstream_restore(run / DIRECTORY,plan,slot,frame,control,work,lambda:False)
                    require(from_upstream == row['upstream_restored'], 'replayed upstream recovery differs')
                    row_result.update(control_payload=row['control_payload'], upstream_restored=from_upstream)
            if _requires_cross(plan, slot):
                control = verify_asset(run, row['control_payload'])
                cross = _cross_restore(run / DIRECTORY, plan, slot, frame, control, work, lambda: False)
                require(cross == row['cross_restored'], 'replayed cross recovery differs')
                row_result.update(control_payload=row['control_payload'], cross_restored=cross)
        restored.append(row_result)
    report = {'schema': 'bmk.lossless-batch-restore-audit/1', 'run_id': seal['run_id'], 'seal_id': seal['seal_id'],
              'recovery_id': plan['decoder']['recovery_id'], 'restored_products': len(restored), 'products': restored,
              'qualification_granted': False}
    if plan['schema'] == CROSS_SCHEMA:
        report.update(schema='bmk.lossless-batch-restore-audit/2',
                      cross_restored_products=sum('cross_restored' in row for row in restored))
    elif plan['schema'] in LINEAR_SCHEMAS:
        report.update(schema='bmk.lossless-batch-restore-audit/3',
                      upstream_restored_products=sum('upstream_restored' in row for row in restored),
                      rejected_decode_cases=sum(len(row.get('decoder_rejections', {})) for row in restored))
        if FENV_TOOL in plan['direct_control']['tool_refs']:
            report['fenv_replayed_products'] = sum('fenv_control' in row for row in restored)
        if TITCHY_TOOL in plan['direct_control']['tool_refs']:
            report['titchy_direct_replayed_products'] = sum('titchy_direct_payload' in row for row in restored)
        if XZ_TOOL in plan['direct_control']['tool_refs']:
            report['xz_direct_replayed_products'] = sum('xz_control' in row for row in restored)
        if PCO_TOOL in plan['direct_control']['tool_refs']:
            denied = [slot['product_slot'] for slot,_ in pcodec_negatives]
            require(len(set(denied)) == len(replayed_pcodec_rejections) and set(denied) ==
                    {obs['product_slot'] for obs in replayed_pcodec_rejections}, 'missing matching recovered pcodec rejection source')
            report['pcodec_direct_replayed_products'] = sum('pcodec_control' in row for row in restored)
            report['pcodec_input_rejections'] = replayed_pcodec_rejections
        if WRAPPED_TOOL in plan['direct_control']['tool_refs']:
            report['wrapped_products'] = wrapped_products
            report['wrapped_detached_pages'] = sum(len(p['restored']['detached']) for p in wrapped_products)
            report['restored_products'] += len(wrapped_products)
        if plan.get('suite') in ORDERED_SUITES:
            report['selfstar_ordered_products'] = selfstar_products
            report['restored_products'] += len(selfstar_products)
        if plan.get('suite') in ENTROPY_SUITES:
            report['huff0_products'] = huff_products
            report['restored_products'] += len(huff_products)
        if plan.get('suite') in SPRINTZ_SUITES:
            report['sprintz_products'] = sprintz_products
            report['restored_products'] += len(sprintz_products)
            report['sprintz_query_replayed_products'] = sum(r['query_replayed'] for r in sprintz_products)
        if plan.get('suite') in ACCESS_SUITES:
            report['titchy_access_products'] = access_products
            report['restored_products'] += len(access_products)
        if plan.get('suite') in STREAM_SUITES:
            report['titchy_stream_products'] = stream_products
            report['restored_products'] += len(stream_products)
        if plan.get('suite') in INTMULT_SUITES:
            report['pcodec_intmult_products'] = intmult_products
            report['pcodec_intmult_input_rejections'] = intmult_rejections
            report['restored_products'] += len(intmult_products)
        if plan.get('suite') in GORILLA_STATE_SUITES:
            report['gorilla_state_products'] = gorilla_state_products
            report['restored_products'] += len(gorilla_state_products)
        if plan.get('suite') in LZBENCH_SESSION_SUITES:
            report['lzbench_session_products'] = session_products
            report['restored_products'] += len(session_products)
        if plan.get('suite') in LZBENCH_PROFILE_SUITES:
            report['lzbench_profile_products'] = profile_products
            report['restored_products'] += len(profile_products)
        if plan.get('suite') in ALP_DECODE_SUITES:
            report['alp_decode_backend_products'] = alp_products
            report['restored_products'] += len(alp_products)
        if plan.get('suite') in ZFP_NATIVE_SUITES:
            report['schema'] = 'bmk.native-batch-restore-audit/1'
            report['zfp_native_products'] = zfp_products
            report['restored_products'] += len(zfp_products)
        if plan.get('suite') in PBEPLA_NATIVE_SUITES:
            report['pbepla_products'] = pbepla_products
            report['replayed_pbepla_rejections'] = pbepla_rejections
            report['restored_products'] += len(pbepla_products)
        if plan.get('suite') in CORAD_INFERENCE_SUITES:
            report['corad_inference_products'] = corad_products
            report['restored_products'] += len(corad_products)
        if plan.get('suite') in CORAD_TRAINING_SUITES:
            report['corad_training_products'] = training_products
            report['restored_products'] += len(training_products)
    return report
