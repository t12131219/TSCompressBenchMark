#!/usr/bin/env python3
"""Check ALP Auto's emitted ALN1 branches, and separate dispatch from actual work."""
import ctypes as c
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from integration.direct_control import AlpDirect, DecodeStats, EncodeStats, fn
from tsbench.assets import canonical_bytes, digest
from tsbench.runtime import create_build_lock, resolve_worker

from tsbench.planner.alp import (AVX512, DIR, HEADER, ID, METHOD, RG, SPECIAL, SPECIAL_POS, V, REAL, plan_alp, sha)
from tsbench.qualification.alp import verify_alp
from tsbench.qualification.alp_wire import analyze, corrupt_positions

COUNT = 'scalar_vectors falp_scalar_vectors native_falp_simd_counter rd_vectors raw_vectors'.split()


class Native(AlpDirect):
    def __init__(self, library):
        super().__init__(library)
        lib = c.CDLL(str(library))
        self.built = fn(lib,'alpn_backend_built',c.c_int,c.c_int,c.c_uint)
        self.version = fn(lib,'alpn_version',c.c_char_p)
        self.last_error = fn(lib,'alpn_last_error',c.c_char_p)

    def pack(self,values,width):
        n = len(values)//(width//8)
        bound = self.bound(n,width)
        assert bound
        written, stats, out = c.c_size_t(),EncodeStats(),c.create_string_buffer(bound)
        assert self.compress(values,n,width,0,out,bound,c.byref(written),c.byref(stats)) == 0
        assert 0 < written.value <= bound
        return out.raw[:written.value],{k:getattr(stats,k) for k,_ in stats._fields_}

    def restore(self,payload,values,width,request,available):
        n = len(values)//(width//8)
        written, st, out = c.c_size_t(999),DecodeStats(),c.create_string_buffer(max(1,len(values)))
        rc = self.decode(payload,len(payload),n,out,n,c.byref(written),ID[request],c.byref(st))
        if not available:
            assert rc == 1 and not written.value and b'unavailable' in self.last_error()
            return None
        assert rc == 0 and written.value == n and out.raw[:len(values)] == values
        return {'backend':self.backend(st.effective_backend).decode(),**{k:getattr(st,k) for k in COUNT}}

    def check_fenv(self,payload,sample):
        # Called only by Linux x86-64 CTest; glibc fenv.h defines this value.
        lib = c.CDLL(None)
        get = fn(lib,'fegetround',c.c_int)
        change = fn(lib,'fesetround',c.c_int,c.c_int)
        before = get()
        assert before == 0
        b, n = c.create_string_buffer(100000), c.c_size_t(3)
        try:
            assert change(0x400) == 0
            record = {'before':before, 'changed':get()}
            for op, call, args in (
                ('encode', self.compress, (sample,len(sample)//8,64,0,b,len(b),c.byref(n),None)),
                ('decode', self.decode, (payload,len(payload),len(sample)//8,b,len(sample)//8,c.byref(n),0,None)),
            ):
                n.value = 999
                record[op] = {'status':call(*args), 'written':n.value, 'message':self.last_error().decode()}

        finally:
            assert change(before) == 0
        return {**record, 'after':get()}


def expect_status(root,r,status,*outputs):
    assert r.returncode == 3 and r.stderr.startswith(f'plugin status {status}:'.encode()), r
    assert not any((root/p).exists() for p in outputs)


def batch_case(root,run,api,case,raw,capability,requests,evidence):
    width,label,n = case['width'],case['label'],case['count']
    dtype = 9 if width == 32 else 10
    schema = case['schema'].encode('ascii')
    (root/'input').write_bytes(raw); (root/'schema').write_bytes(schema)
    payload, native = api.pack(raw,width)
    positions = []
    analysis = analyze(payload,raw,width,positions=positions)
    for key in native:
        assert analysis[key] == native[key]
    if label == 'mixed-decimal-raw':
        assert analysis['coded_decimal_vectors'] == analysis['raw_vectors'] == 1
        assert analysis['special_exception_bits'] == [{'index':i,'bits':hex(v)} for i,v in zip(SPECIAL_POS,SPECIAL[width],strict=True)]
    if label == 'decimal-then-rd-rowgroup':
        assert analysis['rowgroup_rows'] == [RG,2*V] and analysis['coded_decimal_vectors'] == 100
    def make(wire=payload):
        return HEADER.pack(b'BMKALP\1\0',dtype,n,len(schema),len(wire))+schema+wire
    enc = json.loads(run('encode',{},dtype,'input','schema','frame').stdout)
    full = (root/'frame').read_bytes()
    assert full == make() and {k:enc[k] for k in native} == native
    assert enc['threads'] == 1 and enc['backend'] == 'alpn-auto-encoder'
    assert enc['fallback'] == bool(analysis['raw_vectors'])
    (evidence/case['frame']).write_bytes(full)
    (root/'input').unlink(); (root/'schema').unlink()
    outcomes = []
    for req in requests:
        available = capability[req]['available']
        control = api.restore(payload,raw,width,req,available)
        cmd = run('decode',{'decode_backend':req},'frame','decoded','schema.out',check=available)
        if not available:
            expect_status(root,cmd,1,'decoded','schema.out')
            outcomes.append({'request':req,'state':'rejected_unavailable','reason':capability[req]['reason'],'abi_status':1})
            continue
        desc, seen = map(json.loads,cmd.stdout.splitlines())
        assert desc == {'dtype':dtype,'count':n}
        restored = (root/'decoded').read_bytes(); restored_schema = (root/'schema.out').read_bytes()
        assert restored == raw and restored_schema == schema
        (root/'decoded').unlink(); (root/'schema.out').unlink()
        assert seen['requested_backend'] == req and seen['simd_counter_scope'] == 'avx2-only' and seen['threads'] == 1
        assert {k:seen[k] for k in control} == control
        assert seen['falp_avx2_vectors'] == seen['native_falp_simd_counter']
        assert seen['raw_vectors'] == analysis['raw_vectors'] and seen['rd_vectors'] == analysis['coded_rd_vectors']
        counters = {'scalar-unfused':'scalar_vectors','falp-scalar':'falp_scalar_vectors','falp-avx2':'falp_avx2_vectors'}
        executed = seen['backend']
        if req == 'falp-auto':
            assert executed == next(b for b in (AVX512,'falp-avx2','falp-scalar') if capability[b]['available'])
        else:
            assert executed == req
        dec = analysis['coded_decimal_vectors']
        assert all(seen[key] == (dec if key == counters.get(executed) else 0) for key in counters.values())
        direct_counter = seen[counters[executed]] if executed in counters else None
        outcomes.append({'request':req,'dispatch':executed,'state':'restored_bit_exact',
                         'decimal_vectors_in_wire':dec,'native_decimal_kernel_vectors':direct_counter,
                         'native_execution_confirmation':('no_decimal_work_in_wire' if not dec else
                             'measured_counter' if direct_counter is not None else 'dispatch_only_no_native_counter'),
                         'rd_vectors':seen['rd_vectors'],'raw_vectors':seen['raw_vectors'],
                         'restored':{'dtype':desc['dtype'],'count':desc['count'],'input_sha256':sha(restored),
                                     'schema_sha256':sha(restored_schema)}})
    for bad in (full[:-1],make(payload[:-1]),make(payload+b'\0')):
        (root/'frame').write_bytes(bad)
        expect_status(root,run('decode',{},'frame','decoded','schema.out',check=False),5,'decoded','schema.out')
    side_info = {}
    if label == 'mixed-decimal-raw':
        for name, (offset, bad) in corrupt_positions(payload, positions).items():
            wire = make(bad)
            (root/'frame').write_bytes(wire)
            outcome = run('decode',{},'frame','decoded','schema.out',check=False)
            expect_status(root,outcome,5,'decoded','schema.out')
            assert b'invalid exception position' in outcome.stderr, outcome.stderr
            side_info[name] = {'payload_offset':offset,'frame_sha256':sha(wire),'abi_status':5,
                               'diagnostic':outcome.stderr.decode().strip()}
    (root/'frame').unlink()
    return {'case':label,'width':width,'count':n,'input_bytes':len(raw),'input_sha256':sha(raw),
            'native_bytes':len(payload),'native_sha256':sha(payload),'envelope_bytes':len(full),
            'envelope_sha256':sha(full),'schema_bytes':len(schema),'wire':analysis,'backends':outcomes,
            'rejected_artifacts':3,'side_info':side_info,**({'window':case['window']} if 'window' in case else {})}


def main(worker,module,library,out):
    assert out.name == DIR
    bundle, raw = plan_alp(ROOT)
    with tempfile.TemporaryDirectory(prefix='tsbench-alp-moved-', dir=out.parent) as temp:
        stage = Path(temp)
        evidence = stage / DIR
        evidence.mkdir()
        root = stage / 'work'
        root.mkdir()
        build = {p.name:digest(p) for p in (worker,module,library)}
        for name in ('catalog','schemas','plugins','include','cmake','tools','third_party'):
            shutil.copytree(ROOT/name,root/name)
        for f in (worker,module,library):
            shutil.copy2(f,root/f.name)
        lock = create_build_lock(root,worker.name,{METHOD:module.name})
        binding = resolve_worker(root,lock,METHOD,{})
        api = Native(root/library.name)
        def run(op,options,*args,check=True):
            return run_worker(root,[binding['worker'],op,binding['library'],METHOD,canonical_bytes(options).decode(),*map(str,args)],check=check)
        support, observations = {}, []
        for width in (32,64):
            caps = support[str(width)] = {}
            for backend,name in ID.items():
                built,available = bool(api.built(name,width)),bool(api.available(name,width))
                assert not available or built
                if width == 64 and backend == AVX512:
                    # This probe targets the supported Linux x86-64 build. A CPU
                    # without AVX512 must not hide a build that dropped the backend.
                    assert built, 'Linux x86-64 ALP build lost its f64 AVX512BW decoder'
                reason = ('platform_not_selected' if backend in ('falp-neon','falp-sve') else
                          'width_unsupported' if width == 32 and backend in ('falp-avx2',AVX512) else
                          'not_built' if not built else 'runtime_unavailable' if not available else None)
                assert available == (reason is None)
                caps[backend] = {'built_for_width':built,'available':available,'reason':reason}
                if width == 64 and backend == AVX512:
                    caps[backend]['runtime_state'] = 'available' if available else 'pending_supported_runtime'
        for case in bundle['fixtures']:
            values = raw[case['name']]
            observations.append(batch_case(root,run,api,case,values,support[str(case['width'])],bundle['requests'],evidence))
            if case['label'] == REAL:
                (evidence/bundle['raw_weather']).write_bytes(values)
                frame = (evidence/case['frame']).read_bytes()
                original = frame[HEADER.size + len(case['schema']):]
                fenv = api.check_fenv(original,values)
        driver = digest(Path(__file__))
        ffi = digest(ROOT/'tests/integration/direct_control.py')
        document = {'schema':'bmk.m0-alp-control/2','config_id':bundle['config_id'],'bundle_id':bundle['bundle_id'],
                    'case_ids':[c['case_id'] for c in bundle['cases']],
                    'definitions':{'probe_sha256':driver,'ffi_sha256':ffi},'build':lock,'native_version':api.version().decode(),
                    'formal_performance':False,'formal_qualification':False,'backend_conditions':support,'cases':observations,'fenv':fenv}
        (stage/bundle['evidence_path']).write_bytes(canonical_bytes(document)+b'\n')
        verify_alp(bundle,build,driver,stage,ffi_sha256=ffi)
        out.mkdir(exist_ok=True)
        for name in bundle['binary'] + ['report.json']:
            (evidence/name).replace(out/name)


if __name__ == '__main__':
    main(*(Path(p).resolve() for p in sys.argv[1:]))
