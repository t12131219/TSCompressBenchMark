#!/usr/bin/env python3
"""Compare CORAD worker envelopes with independently interpreted CRD1."""
import ctypes as ct
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from corad_native_control import Config, api, blob, interpret, recorded
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest
from tsbench.corad_quality import assess
from tsbench.planner.corad_inference import METHOD, plan_corad_inference
from tsbench.qualification.corad_wire import quality
from tsbench.runtime import create_build_lock, resolve_worker

FRAME = struct.Struct('<8sIIQ')
MAGIC = b'BMKCRD\x01\x00'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def direct_encode(lib, model_bytes, values, rows):
    m = ct.c_void_p()
    assert lib.corad_model_load(model_bytes, len(model_bytes), ct.byref(m)) == 0 and m.value
    try:
        frozen, effective = Config(), Config()
        assert lib.corad_model_info(m, ct.byref(frozen)) == 0
        assert lib.corad_model_config(m, rows, frozen.nonzero, frozen.threshold, ct.byref(effective)) == 0
        raw = b''.join(values)
        tightly_packed = (ct.c_double * (len(raw)//8)).from_buffer_copy(raw)
        frame = blob(lib.corad_model_encode, m, ct.byref(effective), tightly_packed)
        return frame, recorded(effective)
    finally:
        lib.corad_model_free(m)


def wrap(schema, payload):
    return FRAME.pack(MAGIC,len(schema),0,len(payload)) + schema + payload


def main(worker, module, library, report):
    bundle, deployments, values, calibration = plan_corad_inference(ROOT)
    cols = bundle['input']['columns']
    policy = bundle['quality_policy']
    gate = {'policy_id':policy['policy_id'],'heldout':{}}
    export = {bundle['input']['path']: b''.join(values),policy['calibration']['path']:calibration}
    specs = iter(bundle['frames'])
    with tempfile.TemporaryDirectory(prefix='tsbench-corad-work-') as tmp:
        root = Path(tmp)
        for folder in ('catalog','schemas','plugins','include','cmake','tools','third_party'):
            shutil.copytree(ROOT / folder,root / folder)
        for binary in (worker,module,library):
            shutil.copy2(binary,root / binary.name)
        lock = create_build_lock(root,worker.name,{METHOD:module.name})
        bindings = [resolve_worker(root,lock,METHOD,d[3]) for d in deployments]
        decode_binding = resolve_worker(root,lock,METHOD,{})
        assert len({b['configuration_id'] for b in [*bindings,decode_binding]}) == 3
        assert not (root / 'assets').exists()
        lib = api(root / library.name)
        inputs = ['v0','v1','v2']
        outputs = ['schema-out','out0','out1','out2']

        def run(op, bind, *args, check=True):
            return run_worker(root,[bind['worker'],op,bind['library'],METHOD,
                                    canonical_bytes(bind['options']).decode(),*args],check=check)

        def enc(bind, schema, data, check=True, types=('10','10','10')):
            args = []
            for name, src, dtype in zip(inputs,data,types,strict=True):
                (root / name).write_bytes(src)
                args.extend((dtype,name))
            (root / 'schema').write_bytes(schema)
            try:
                return run('encode-columns',bind,'schema','frame',*args,check=check)
            finally:
                for name in [*inputs,'schema']:
                    (root / name).unlink()

        def dec(bind, check=True):
            assert not any((root / name).exists() for name in [*inputs,'schema','assets'])
            return run('decode-columns',bind,'frame',*outputs,check=check)

        def reject(tag, result, status, absent):
            assert result.returncode == 3 and result.stderr.startswith(f'plugin status {status}:'.encode()), (tag,result)
            assert not any((root / name).exists() for name in absent), tag
            rejections[tag] = {'status':status,'returncode':result.returncode,'no_outputs':True,
                               'diagnostic':result.stderr.decode().strip()}

        evidence, rejections, heldout = [], {}, []
        for (deployment,schema,model,_), bound in zip(deployments,bindings,strict=True):
            for _ in range(3):
                spec = next(specs)
                tag,n = spec['case'],spec['rows']
                width = spec['native_configuration']['tricklet']
                raw = [v[:n*8] for v in values]
                direct, effective = direct_encode(lib,model,raw,n)
                original, sections, embedded = interpret(direct)
                assert embedded == model[32:]
                assert sections['tail_bytes'] == (n % width)*8*len(cols)
                if tag == 'held-out':
                    assert sections['references'] > 0 and sections['sparse_records'] > 0
                encode = json.loads(enc(bound,schema,raw).stdout)
                frame = (root / 'frame').read_bytes()
                assert frame == wrap(schema,direct)
                assert encode == dict(backend='corad-c-frozen',mode='batch',operation='encode',threads=1,
                                      columns=len(cols),rows=n,tricklet=width,fallback=False,
                                      embedded_model_bytes=sections['embedded_model_bytes'],
                                      tail_rows=n % width,external_deployment_loaded=True)
                desc, detached = map(json.loads,dec(decode_binding).stdout.splitlines())
                assert desc == {'columns':[{'dtype':10,'count':n} for _ in cols]}
                assert detached == {**encode,'operation':'decode','external_deployment_loaded':False}
                assert (root / outputs[0]).read_bytes() == schema
                restored = [(root / name).read_bytes() for name in outputs[1:]]
                assert b''.join(restored) == original
                tail = sections['tail_bytes']//len(cols)
                if tail:
                    assert all(src[-tail:] == dst[-tail:] for src,dst in zip(raw,restored,strict=True))
                for name in outputs:
                    (root / name).unlink()
                pinned_info = None
                if tag == 'held-out':
                    heldout.append((schema,direct,frame,sections))
                    gate['heldout'][spec['route']] = assess(policy['bounds'],raw,restored)
                    pinned = dec(bound)
                    pinned_desc, pinned_info = map(json.loads,pinned.stdout.splitlines())
                    assert pinned_desc == desc and pinned_info == {**detached,'external_deployment_loaded':True}
                    assert [(root / name).read_bytes() for name in outputs] == [schema,*restored]
                    for name in outputs:
                        (root / name).unlink()
                (root / 'frame').unlink()
                export[spec['path']] = frame
                evidence.append({'path':spec['path'],'case':tag,'deployment_id':deployment['deployment_id'],'route':deployment['training']['route'],
                                 'encode_configuration_id':bound['configuration_id'],'decode_configuration_id':decode_binding['configuration_id'],
                                 'model_sha256':sha(model),'model_asset_bytes':len(model), 'schema_sha256':sha(schema),
                                 'schema_bytes':len(schema),'frame_header_bytes':FRAME.size,'frame_bytes':len(frame),
                                 'native_bytes':len(direct),'frame_sha256':sha(frame),'native_sha256':sha(direct),
                                 'logical_bytes':n*len(cols)*8,'columns':cols,'source_sha256':sha(b''.join(raw)),
                                 'restored_sha256':sha(b''.join(restored)),'descriptor':desc,'quality_observed':quality(raw,restored,cols),
                                 'sections':sections,'config':effective,'encode':encode,'decode':detached,'pinned_decode':pinned_info})
        schema, direct, first_frame, sections = heldout[0]
        reordered = canonical_bytes({'schema':'bmk.corad-columns/1','columns':cols[::-1],'dtype':'f64le'})
        reject('encode-without-model',enc(decode_binding,schema,values,check=False),3,['frame'])
        reject('column-order',enc(bindings[0],reordered,values[::-1],check=False),2,['frame'])
        reject('unequal-row-count',enc(bindings[0],schema,[values[0],values[1][:-8],values[2]],check=False),2,['frame'])
        reject('wrong-dtype',enc(bindings[0],schema,values,check=False,types=('8','10','10')),1,['frame'])
        reject('nonfinite',enc(bindings[0],schema,[struct.pack('<d',float('inf'))+values[0][8:],*values[1:]],check=False),2,['frame'])
        too_large = bytes((131072//len(cols)+1)*8)
        reject('encode-value-budget',enc(bindings[0],schema,[too_large]*len(cols),check=False),7,['frame'])
        (root / 'frame').write_bytes(first_frame)
        reject('wrong-expected-model',dec(bindings[1],False),5,outputs)
        (root / 'frame').write_bytes(wrap(reordered,direct))
        reject('wrong-expected-schema',dec(bindings[0],False),5,outputs)
        over = bytearray(direct)
        struct.pack_into('<I',over,4,131072//len(cols)+1)
        damaged = bytearray(direct)
        reference,j = sections['first_reference']
        struct.pack_into('<H',damaged,reference,j)
        for tag,bad,status in (('decode-value-budget',wrap(schema,over),7),('bad-reference',wrap(schema,damaged),5),
                               ('truncated',first_frame[:-1],5),('trailing-byte',first_frame+b'\0',5)):
            (root / 'frame').write_bytes(bad)
            reject(tag,dec(decode_binding,False),status,outputs)
        (root / 'frame').unlink()
    doc = {'schema':'bmk.corad-worker-control/3','diagnostic_id':uuid.uuid4().hex,'config_id':bundle['config_id'],
           'bundle_id':bundle['bundle_id'],
           'probe_sha256':digest(Path(__file__)),'source_oracle_sha256':digest(ROOT/'tests/isolation/corad_native_control.py'),
           'formal_qualification':False,'formal_performance':False,'model_quality_gate_evaluated':True,'quality_gate':gate,
           'build':lock,'deployments':[d[0] for d in deployments],'heldout_windows':bundle['window'],'cases':evidence,'rejections':rejections}
    with tempfile.TemporaryDirectory(dir=report.parent,prefix='.corad-worker-') as temp:
        for name, raw in export.items():
            staged = Path(temp)/name
            staged.write_bytes(raw)
            staged.replace(report.parent/name)
        path = Path(temp)/'result.json'
        path.write_bytes(canonical_bytes(doc)+b'\n'); path.replace(report)


if __name__ == '__main__':
    main(*(Path(arg).resolve() for arg in sys.argv[1:]))
