#!/usr/bin/env python3
"""Differential checks of the ordered SElf* block format and live lifecycle."""
from contextlib import contextmanager
import ctypes as c
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest
from tsbench.planner.selfstar import (ALGORITHM, BITLEN, BLOCK, DTYPE_ID, HEADER, MAGIC, NAN, NATIVE_MAX_COUNT,
                                      NATIVE_WORKSPACE, PLUGIN, WEATHER, case_inputs, fixture, plan_selfstar,
                                      ref, retained_paths, schema_bytes, sha)
from tsbench.qualification.selfstar_wire import read_frame
from tsbench.runtime import create_build_lock, resolve_worker


OK, INVALID, CAPACITY, CORRUPT, STATE = 0, 1, 2, 3, 5


class Progress(c.Structure):
    _fields_ = [('count',c.c_size_t),('bits',c.c_size_t),('deferred_values',c.c_size_t),('phase',c.c_int)]


class Native:
    def __init__(self, path):
        self.lib = c.CDLL(str(path))
        ptr, size, status = c.c_void_p,c.c_size_t,c.c_int
        self.create = self.fn('create',ptr,c.c_int,c.c_int)
        self.destroy = self.fn('destroy',None,ptr)
        self.reset = self.fn('reset',status,ptr)
        self.encode = self.fn('encode',status,ptr,ptr,size,ptr,size,c.POINTER(size))
        self.decode = self.fn('decode',status,ptr,ptr,size,size,ptr,size)
        self.begin = self.fn('begin',status,ptr,ptr,size)
        self.add = self.fn('add',status,ptr,ptr,size)
        self.finish = self.fn('finish',status,ptr,c.POINTER(size))
        self.read_begin = self.fn('read_begin',status,ptr,ptr,size,size,size)
        self.next = self.fn('next',status,ptr,ptr,c.POINTER(c.c_int))
        self.progress = self.fn('progress',status,ptr,c.POINTER(Progress))

    def fn(self,name,res,*args):
        f = getattr(self.lib,'sf_c_'+name)
        f.restype,f.argtypes = res,args
        return f

    @contextmanager
    def context(self,width):
        ctx = self.create(ALGORITHM,width)
        assert ctx
        try:
            yield ctx
        finally:
            self.destroy(ctx)

    def typed(self,data,width):
        return ((c.c_float if width == 32 else c.c_double)*(len(data)//(width//8))).from_buffer_copy(data)

    def state(self,ctx):
        p = Progress()
        assert self.progress(ctx,c.byref(p)) == OK
        return dict(count=p.count, bits=p.bits, deferred_values=p.deferred_values, phase=p.phase)

    def pack(self,ctx,width,data,expected=OK):
        values = self.typed(data,width)
        out,bits = c.create_string_buffer(NATIVE_WORKSPACE),c.c_size_t()
        assert self.encode(ctx,values,len(values),out,len(out),c.byref(bits)) == expected
        if expected == OK:
            assert 0 < bits.value <= 200000
            return bits.value,out.raw[:(bits.value+7)//8]

    def unpack(self,ctx,width,record,count):
        bits,payload = record
        out = (c.c_float if width == 32 else c.c_double) * count
        out = out()
        status = self.decode(ctx,payload,len(payload),bits,out,count)
        return status,bytes(out)

    def live_pack(self,ctx,width,data,schedule):
        out,bits = c.create_string_buffer(NATIVE_WORKSPACE),c.c_size_t()
        assert self.begin(ctx,out,len(out)) == OK
        count,item = 0,width//8
        progress = [self.state(ctx)]
        assert progress[-1] == dict(count=0,bits=0,deferred_values=0,phase=1)
        for length in (*schedule,len(data)//item):
            n = min(length,len(data)//item-count)
            if not n:
                break
            expected_count = count+n
            values = self.typed(data[count*item:expected_count*item],width)
            assert self.add(ctx,values,n) == OK
            progress.append(self.state(ctx))
            assert progress[-1] == dict(count=expected_count,bits=progress[-1]['bits'],deferred_values=0,phase=1)
            assert progress[-1]['bits'] > progress[-2]['bits']
            count = expected_count
        assert count*item == len(data)
        before_bits = progress[-1]['bits']
        before_finish = out.raw[:(before_bits+7)//8]
        assert self.finish(ctx,c.byref(bits)) == OK
        assert self.state(ctx) == dict(count=count,bits=bits.value,deferred_values=0,phase=0)
        assert bits.value > before_bits  # sentinel not observable before finish
        return (bits.value,out.raw[:(bits.value+7)//8]),progress,(before_bits,before_finish)

    def drain(self,ctx,width,record,n):
        bits,payload = record
        value,has = (c.c_float if width == 32 else c.c_double)(),c.c_int()
        buf = c.create_string_buffer(payload,len(payload))
        assert self.read_begin(ctx,buf,len(payload),bits,n) == OK
        raw = bytearray()
        for _ in range(n):
            assert self.next(ctx,c.byref(value),c.byref(has)) == OK and has.value == 1
            raw.extend(bytes(value))
        before = self.state(ctx)
        assert before['phase'] == 2 and before['count'] == n and before['bits'] < bits
        assert self.read_begin(ctx,buf,len(payload),bits,n) == STATE
        assert self.next(ctx,c.byref(value),c.byref(has)) == OK and has.value == 0
        assert self.state(ctx) == dict(count=n,bits=bits,deferred_values=0,phase=0)
        return bytes(raw),{'before_sentinel':before,'complete_bits':bits,'next_block_before_drain_status':STATE}

    def live_unpack(self,ctx,width,record,expected):
        raw,result = self.drain(ctx,width,record,len(expected)//(width//8))
        assert raw == expected
        return result


    def incomplete_block(self,ctx,width,record,expected):
        bits,payload = record
        typ = c.c_float if width == 32 else c.c_double
        value,has = typ(),c.c_int()
        n = len(expected)//c.sizeof(value)
        buf = c.create_string_buffer(payload,len(payload))
        assert self.read_begin(ctx,buf,len(payload),bits,n) == OK
        # A snapshot after all add() calls (with exact side metadata) can expose
        # all sample values, yet the native block cannot complete or advance.
        for i in range(n):
            assert self.next(ctx,c.byref(value),c.byref(has)) == OK and has.value == 1
            assert bytes(value) == expected[i*c.sizeof(value):(i+1)*c.sizeof(value)]
        assert self.next(ctx,c.byref(value),c.byref(has)) == CORRUPT
        assert self.next(ctx,c.byref(value),c.byref(has)) == STATE
        return {'snapshot_bits':bits,'values_staged_before_failed_completion':n,'terminal_status':CORRUPT}


def verify_native(api,width,blocks,schedule):
    counts = [len(b)//(width//8) for b in blocks]
    with api.context(width) as enc:
        records = [api.pack(enc,width,block) for block in blocks]
        assert api.reset(enc) == OK
        assert [api.pack(enc,width,block) for block in blocks] == records
    with api.context(width) as enc, api.context(width) as dec:
        observed, partial = [], None
        for i,(block,record,count) in enumerate(zip(blocks,records,counts)):
            # Both directions alternate live and batch at valid boundaries.
            if i % 2:
                made,progress,before_finish = api.live_pack(enc,width,block,schedule)
                if i == 1:
                    partial = before_finish
                step = api.live_unpack(dec,width,record,block)
                observed.append({'block_index':i,'before_finish':progress,'reader':step})
            else:
                made = api.pack(enc,width,block)
                assert api.unpack(dec,width,record,count) == (OK,block)
            assert made == record
        # Replay after reset requires all prefix blocks, not original input or a model sidecar.
        assert api.reset(dec) == OK
        for block,record,count in zip(blocks,records,counts):
            assert api.unpack(dec,width,record,count) == (OK,block)
    with api.context(width) as dec:
        status,_ = api.unpack(dec,width,records[1],counts[1])
        assert status == CORRUPT, 'frozen second block unexpectedly accepted without prefix'
        assert api.reset(dec) == OK
        assert api.unpack(dec,width,records[0],counts[0]) == (OK,blocks[0])
        assert api.unpack(dec,width,records[1],counts[1]) == (OK,blocks[1])
        assert api.reset(dec) == OK
        assert api.unpack(dec,width,records[0],counts[0]) == (OK,blocks[0])
        before_finish_rejection = api.incomplete_block(dec,width,partial,blocks[1])
    with api.context(width) as enc:
        fresh_encoder = api.pack(enc,width,blocks[1])
        assert fresh_encoder != records[1]
    return records,{'block_counts':counts,'skip_prefix_status':status,'skip_prefix_is_exact':False,
                    'fresh_second_bit_length':fresh_encoder[0],'fresh_second_block_sha256':sha(fresh_encoder[1]),
                    'learned_second_block_sha256':sha(records[1][1]),
                    'same_bitstream_after_reset':True,'replay_bit_exact':True,
                    'replayed_prefix_for_second_block':{'values':counts[0],'native_bytes':len(records[0][1]),'framing_bytes':4},
                    'before_finish_snapshot':before_finish_rejection,'live':observed},partial,fresh_encoder


def native_limits(api,width,schedule):
    item, maximum = width//8, NATIVE_MAX_COUNT
    data = fixture(width,maximum+1)
    src = data[:maximum*item]
    statuses = {}
    with api.context(width) as ctx:
        for name,raw in [('empty',b''),(str(maximum+1),data),
                         *[(tag,b.to_bytes(item,'little')) for tag,b in zip(('qnan','snan'),NAN[width],strict=True)]]:
            api.pack(ctx,width,raw,INVALID)
            statuses['batch-'+name] = INVALID
        max_block = api.pack(ctx,width,src)
        assert api.reset(ctx) == OK
        record,progress,_ = api.live_pack(ctx,width,src,schedule)
        assert max_block == record
    with api.context(width) as ctx:
        reader = api.live_unpack(ctx,width,max_block,src)
    with api.context(width) as ctx:
        out,bits = c.create_string_buffer(NATIVE_WORKSPACE),c.c_size_t()
        values = api.typed(data,width)
        assert api.begin(ctx,out,len(out)) == OK
        def expect(name,result,status):
            assert result == status
            statuses[name] = result
        expect('live-empty-finish',api.finish(ctx,c.byref(bits)),INVALID)
        expect('live-single-add-1001',api.add(ctx,values,maximum+1),INVALID)
        for tag,b in zip(('qnan','snan'),NAN[width],strict=True):
            expect('live-'+tag,api.add(ctx,api.typed(b.to_bytes(item,'little'),width),1),INVALID)
        assert api.state(ctx) == dict(count=0,bits=0,deferred_values=0,phase=1)
        assert api.add(ctx,values,maximum) == OK
        max_state = api.state(ctx)
        expect('live-cumulative-1001',api.add(ctx,api.typed(data[-item:],width),1),INVALID)
        assert api.state(ctx) == max_state == progress[-1]
        assert api.finish(ctx,c.byref(bits)) == OK
        assert (bits.value,out.raw[:(bits.value+7)//8]) == max_block
        assert api.reset(ctx) == OK
        assert api.begin(ctx,out,1) == OK
        expect('live-capacity',api.add(ctx,values,8),CAPACITY)
        expect('finish-after-capacity',api.finish(ctx,c.byref(bits)),STATE)
        assert api.reset(ctx) == OK
        single = api.pack(ctx,width,data[:item])
    with api.context(width) as ctx:
        api.live_unpack(ctx,width,single,data[:item])
    return {'minimum_count':1,'maximum_count':maximum,'statuses':statuses,'max_block_progress':progress,
            'max_reader':reader,'max_after_rejected_extra_add':max_state,'one_byte_workspace_reset_restores':True,
            'workspace_bytes':NATIVE_WORKSPACE}, max_block


def batch_case(root,run,api,spec,width,name,data,natives=None,metadata=None):
    item = width//8
    blocks = [data[i:i+BLOCK*item] for i in range(0,len(data),BLOCK*item)]
    if natives is None:
        with api.context(width) as ctx:
            natives = [api.pack(ctx,width,b) for b in blocks]
    total = len(data)//item
    dtype, schema = DTYPE_ID[width],schema_bytes(width,name)
    payload = b''.join(BITLEN.pack(bits)+body for bits,body in natives)

    def frame(content,number=total,tag=dtype):
        return HEADER.pack(MAGIC,tag,number,len(schema),len(content))+schema+content

    (root/'input').write_bytes(data)
    (root/'schema').write_bytes(schema)
    info = json.loads(run('encode',{},dtype,'input','schema','frame').stdout)
    full = (root/'frame').read_bytes()
    assert full == frame(payload)
    (root/'input').unlink(); (root/'schema').unlink()
    desc,got = map(json.loads,run('decode',{},'frame','decoded','schema.out').stdout.splitlines())
    assert desc == {'dtype':dtype,'count':total}
    restored, restored_schema = (root/'decoded').read_bytes(), (root/'schema.out').read_bytes()
    assert restored == data and restored_schema == schema
    (root/spec['artifact']).write_bytes(full)
    live = json.loads(run_worker(root,[sys.executable,'-I','-B',__file__,'--detached-live',str(api.lib._name),
                                     spec['artifact'],str(width),str(total),name]).stdout)
    assert live['restored_sha256'] == sha(data)
    assert live['blocks'] == [{'restored_sha256':sha(r),'count':len(r)//item,'complete_bits':int(b)}
                             for r,(b,_) in zip(blocks,natives,strict=True)]
    (root/'decoded').unlink(); (root/'schema.out').unlink()
    expected = {'backend':'selfstar-c-scalar','threads':1,'mode':'batch','fallback':False,'blocks':len(natives),
                'block_values':BLOCK,'block_header_bytes':4*len(natives),'native_bits':sum(bits for bits,_ in natives),
                'native_payload_bytes':sum(len(b) for _,b in natives)}
    assert info == {**expected,'operation':'encode'} and got == {**expected,'operation':'decode'}
    invalid = {'frame-truncated':full[:-1],'block-truncated':frame(payload[:-1]),
               'zero-bit-length':frame(BITLEN.pack(0)+payload[4:]),'oversize-bit-length':frame(BITLEN.pack(0xffffffff)+payload[4:]),
               'trailing-byte':frame(payload+b'\x00'),'zero-values':frame(payload,0),'unsupported-dtype':frame(payload,5)}
    for bits,body in natives:
        if bits % 8:
            start = payload.index(BITLEN.pack(bits)+body) + 4 + len(body)-1
            bad = payload[:start]+bytes([payload[start]|1])+payload[start+1:]
            invalid['nonzero-block-padding'] = frame(bad)
            break
    rejected = {}
    for label,bad in invalid.items():
        (root/'frame').write_bytes(bad)
        rejected[label] = reject(run('decode',{},'frame','decoded','schema.out',check=False),5,root,'decoded','schema.out')
    (root/'frame').unlink()
    return {'case':name,'width':width,'count':total,'input_sha256':sha(data),'artifact_sha256':sha(full),
            'native_block_sha256':[sha(b) for _,b in natives],'native_bit_lengths':[bits for bits,_ in natives],
            'schema_bytes':len(schema),'artifact_bytes':len(full),'block_header_bytes':expected['block_header_bytes'],
            'native_payload_bytes':expected['native_payload_bytes'],'rejected_artifacts':rejected,
            'direct_native_sha256':sha(frame(payload)),'worker_decode':got,'worker_encode':info,
            'restored_sha256':sha(restored),'restored_schema_sha256':sha(restored_schema),'detached_live':live,
            **(metadata or {})}


def reject(proc,status,root,*outputs):
    assert proc.returncode == 3 and proc.stderr.startswith(f'plugin status {status}:'.encode()), proc.stderr
    assert not any((root/p).exists() for p in outputs)
    return status


def detached_live(library,path,width,total,name):
    # This process receives no original values or external learned model: ordered
    # finalized records and bound schema are sufficient to reconstruct state.
    records = read_frame(Path(path).read_bytes(),width,total,schema_bytes(width,name))
    api, restored, blocks = Native(library), bytearray(), []
    with api.context(width) as ctx:
        for count,bits,payload in records:
            raw,transcript = api.drain(ctx,width,(bits,payload),count)
            restored.extend(raw)
            blocks.append({'restored_sha256':sha(raw),'count':count,'complete_bits':transcript['complete_bits']})
    print(canonical_bytes({'restored_sha256':sha(restored),'blocks':blocks}).decode())


def main(worker,module,library,report):
    bundle, weather = plan_selfstar(ROOT)
    schedule = bundle['incremental']['add_schedule']
    with tempfile.TemporaryDirectory(prefix='tsbench-selfstar-moved-') as temp:
        root = Path(temp)
        for name in ('catalog','schemas','plugins','include','cmake','tools','third_party'):
            shutil.copytree(ROOT/name,root/name)
        for file in (worker,module,library):
            shutil.copy2(file,root/file.name)
        lock = create_build_lock(root,worker.name,{PLUGIN:module.name})
        binding = resolve_worker(root,lock,PLUGIN,{})
        api = Native(root/library.name)

        def run(op,options,*args,check=True):
            return run_worker(root,[binding['worker'],op,binding['library'],PLUGIN,canonical_bytes(options).decode(),*map(str,args)],check=check)

        observations, limits = [],{}
        for spec in bundle['limits']:
            width = spec['width']
            row,(bits,body) = native_limits(api,width,schedule)
            record = BITLEN.pack(bits)+body
            (root/spec['artifact']).write_bytes(record)
            limits[str(width)] = {**row,'artifact':ref(spec['artifact'],record)}
        for spec,(width,name,data) in zip(bundle['objects'],case_inputs(bundle['fixtures'],weather),strict=True):
            state,natives = {},None
            if spec['ordered']:
                size=BLOCK*(width//8)
                blocks = [data[i:i+size] for i in range(0,len(data),size)]
                natives,mechanism,snapshot,fresh = verify_native(api,width,blocks,schedule)
                for key,(bits,body) in [('snapshot',snapshot),('fresh_second',fresh)]:
                    raw = BITLEN.pack(bits)+body
                    (root/spec[key]).write_bytes(raw)
                    mechanism[key] = ref(spec[key],raw)
                state['learning_and_lifecycle'] = mechanism
            if name == 'weather-co2-heldout':
                state['window'] = bundle['window']
            observations.append(batch_case(root,run,api,spec,width,name,data,natives,state))
        (root/'schema').write_bytes(b'{}')
        statuses = {}
        for width in bundle['fixtures']['widths']:
            item = width//8
            for tag,b in zip(('qnan','snan'),NAN[width],strict=True):
                # NaN after 512 valid values must not emit a partial successful object.
                (root/'input').write_bytes(fixture(width,BLOCK)+b.to_bytes(item,'little'))
                statuses[f'f{width}-{tag}-tail'] = reject(run('encode',{},DTYPE_ID[width],'input','schema','frame',check=False),2,root,'frame')
        (root/'input').write_bytes(b'')
        statuses['empty'] = reject(run('encode',{},DTYPE_ID[64],'input','schema','frame',check=False),2,root,'frame')
        (root/'input').write_bytes(b'\0'*4)
        statuses['unsupported-dtype'] = reject(run('encode',{},5,'input','schema','frame',check=False),1,root,'frame')
        statuses['unsupported-block-option'] = reject(run('encode',{'block_values':1000},DTYPE_ID[32],'input','schema','frame',check=False),3,root,'frame')
        (root/WEATHER).write_bytes(weather)
        retained = {name:(root/name).read_bytes() for name in retained_paths(bundle)}
    document = {'schema':'bmk.m0-selfstar-control/2','diagnostic_id':uuid.uuid4().hex,'config_id':bundle['config_id'],
                'bundle_id':bundle['bundle_id'],'probe_sha256':digest(Path(__file__)),'build':lock,'native_block_limits':limits,
                'cases':observations,'input_rejections':statuses,'formal_performance':False,'formal_qualification':False}
    with tempfile.TemporaryDirectory(dir=report.parent,prefix='.selfstar-report-') as temp:
        temp = Path(temp)
        for name,data in retained.items():
            (temp/name).write_bytes(data)
        path = temp/'report.json'
        path.write_bytes(canonical_bytes(document)+b'\n')
        for name in retained:
            (temp/name).replace(report.parent/name)
        path.replace(report)


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--detached-live':
        library,path,width,total,name = sys.argv[2:]
        detached_live(library,path,int(width),int(total),name)
    else:
        main(*(Path(p).resolve() for p in sys.argv[1:]))
