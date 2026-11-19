"""Recompute ordered SElf* artifact/phase accounting and check real decoder transcripts.

The staged C library decodes in fresh processes during the run. Offline
recomputation checks wire structure, prefix bits and the frozen input oracle;
it does not implement or rerun SElf* entropy decoding.
"""
import re

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..planner.selfstar import (BITLEN, BLOCK, NATIVE_MAX_COUNT, PLUGIN, case_inputs, fixture, ref, retained_paths,
                                schema_bytes, sha)
from .probe_build import verify_probe_build_lock
from .selfstar_wire import leading_bits, read_frame, read_record


def _exact(actual, expected, message):
    require(canonical_bytes(actual)==canonical_bytes(expected),message)


def _progress(rows, schedule, count, bits, capacity):
    counts = [0]
    for step in (*schedule,count):
        if counts[-1] == count:
            break
        counts.append(min(count,counts[-1]+step))
    require(isinstance(rows,list) and len(rows)==len(counts) and all(isinstance(r,dict) for r in rows),
            'SElf* live progress closure differs')
    last = -1
    for row,n in zip(rows,counts,strict=True):
        seen = row.get('bits')
        require(type(seen) is int and last < seen < bits <= capacity*8 and (n>0 or seen==0),
                'SElf* live bits are not increasing within the completed block and workspace')
        _exact(row,{'count':n,'bits':seen,'deferred_values':0,'phase':1},'SElf* live state differs')
        last = seen
    return last


def _reader(count, final_bits, before):
    return {'before_sentinel':{'bits':before,'count':count,'deferred_values':0,'phase':2},
            'complete_bits':final_bits,'next_block_before_drain_status':5}


def _limits(report, bundle, read):
    require(isinstance(report,dict) and report.keys()=={str(r['width']) for r in bundle['limits']},
            'SElf* native limit width closure differs')
    for spec in bundle['limits']:
        width, path = spec['width'],spec['artifact']
        _exact(spec['input'],ref(f'frozen:f{width}-native-max',fixture(width,NATIVE_MAX_COUNT)),
               'SElf* maximum native input identity differs')
        row, wire = report[str(width)],read(path)
        require(isinstance(row,dict),'SElf* native limit observation missing')
        at,(count,bits,_) = read_record(wire,0,NATIVE_MAX_COUNT,width)
        require(at==len(wire),'SElf* native limit artifact has trailing bytes')
        prog = row.get('max_block_progress')
        workspace = bundle['native_workspace_bytes']
        before = _progress(prog,bundle['incremental']['add_schedule'],count,bits,workspace)
        _exact(row,{'artifact':ref(path,wire),'minimum_count':1,'maximum_count':count,'statuses':bundle['rejections']['native'],
                    'max_block_progress':prog,'max_reader':_reader(count,bits,before),'max_after_rejected_extra_add':prog[-1],
                    'one_byte_workspace_reset_restores':True,'workspace_bytes':workspace},
               'SElf* limit, reader or reset observation differs')


def _order(state, spec, records, bundle, read):
    require(isinstance(state,dict) and isinstance(state.get('live'),list),'SElf* ordered state observation missing')
    schedule, capacity = bundle['incremental']['add_schedule'],bundle['native_workspace_bytes']
    width = spec['width']
    odd = list(range(1,len(records),2))
    require(len(state['live'])==len(odd),'SElf* alternating native calls do not cover the planned blocks')
    for i,row in zip(odd,state['live'],strict=True):
        count,bits,_ = records[i]
        require(isinstance(row,dict),'SElf* live block observation missing')
        prog = row.get('before_finish')
        before = _progress(prog,schedule,count,bits,capacity)
        _exact(row,{'block_index':i,'before_finish':prog,'reader':_reader(count,bits,before)},
               'SElf* add/finish and reader end boundary differs')
    count,bits,body = records[1]
    snapshot,fresh = (read(spec[key]) for key in ('snapshot','fresh_second'))
    end,(_,prefix_n,prefix) = read_record(snapshot,0,count,width)
    require(end==len(snapshot) and prefix_n<bits and prefix==leading_bits(body,prefix_n) and
            prefix_n==state['live'][0]['before_finish'][-1]['bits'],'SElf* unfinished block is not the witnessed bit prefix')
    end,(_,fresh_n,fresh_body) = read_record(fresh,0,count,width)
    require(end==len(fresh) and (fresh_n,fresh_body)!=(bits,body),'SElf* fresh block cannot witness learned-state difference')
    _exact(state,{'block_counts':[x[0] for x in records],'skip_prefix_status':3,'skip_prefix_is_exact':False,
                  'fresh_second_bit_length':fresh_n,'fresh_second_block_sha256':sha(fresh_body),
                  'learned_second_block_sha256':sha(body),'same_bitstream_after_reset':True,'replay_bit_exact':True,
                  'replayed_prefix_for_second_block':{'values':records[0][0],'native_bytes':len(records[0][2]),
                                                       'framing_bytes':BITLEN.size},
                  'snapshot':ref(spec['snapshot'],snapshot),'fresh_second':ref(spec['fresh_second'],fresh),
                  'before_finish_snapshot':{'snapshot_bits':prefix_n,'values_staged_before_failed_completion':count,
                                             'terminal_status':3},'live':state['live']},
           'SElf* ordered replay, snapshot or reset transcript differs')


def _object(row, spec, width, name, plain, bundle, read):
    item = width//8
    count = len(plain)//item
    ident = spec['artifact'][:-4]
    require(isinstance(row,dict),'SElf* case report missing')
    _exact((spec['case'],spec['width'],spec['count'],spec['ordered'],spec['input']),
           (name,width,count,count>BLOCK,ref('frozen:'+ident,plain)),'SElf* frozen input identity differs')
    schema, wire = schema_bytes(width,name),read(spec['artifact'])
    records = read_frame(wire,width,count,schema)
    state = {}
    if spec['ordered']:
        _order(row.get('learning_and_lifecycle'),spec,records,bundle,read)
        state['learning_and_lifecycle'] = row['learning_and_lifecycle']
    if name == 'weather-co2-heldout':
        state['window'] = bundle['window']
    lengths = [bits for _,bits,_ in records]
    native_bytes = sum(len(body) for _,_,body in records)
    statuses = {**bundle['rejections']['frame'],**({'nonzero-block-padding':5} if any(n%8 for n in lengths) else {})}
    seen = {'backend':'selfstar-c-scalar','threads':1,'mode':'batch','fallback':False,'blocks':len(records),
            'block_values':BLOCK,'block_header_bytes':BITLEN.size*len(records),'native_bits':sum(lengths),
            'native_payload_bytes':native_bytes}
    restored = [{'restored_sha256':sha(plain[i*BLOCK*item:(i*BLOCK+n)*item]),'count':n,'complete_bits':b}
                for i,(n,b,_) in enumerate(records)]
    _exact(row,{'case':name,'width':width,'count':count,'input_sha256':sha(plain),'artifact_sha256':sha(wire),
                'native_block_sha256':[sha(x[2]) for x in records],'native_bit_lengths':lengths,
                'schema_bytes':len(schema),'artifact_bytes':len(wire),'block_header_bytes':seen['block_header_bytes'],
                'native_payload_bytes':native_bytes,'rejected_artifacts':statuses,'direct_native_sha256':sha(wire),
                'worker_encode':{**seen,'operation':'encode'},'worker_decode':{**seen,'operation':'decode'},
                'restored_sha256':sha(plain),'restored_schema_sha256':sha(schema),
                'detached_live':{'restored_sha256':sha(plain),'blocks':restored},**state},
           'SElf* worker/native parity, detached restore, rejections or byte accounting differs')


def verify_selfstar(bundle, build, driver, out, *, sealed_paths=None):
    require(bundle['bundle_id']==content_id({k:v for k,v in bundle.items() if k!='bundle_id'}),'SElf* bundle identity differs')
    require(sealed_paths is None or retained_paths(bundle)|{bundle['evidence_path']}<=sealed_paths,'SElf* evidence is not sealed')
    report = load_json(local_file(out,bundle['evidence_path']))
    require(isinstance(report,dict) and isinstance(report.get('diagnostic_id'),str) and
            re.fullmatch('[a-f0-9]{32}',report['diagnostic_id']),'SElf* evidence identity differs')
    skip = {'diagnostic_id','build','cases','native_block_limits'}
    _exact({k:v for k,v in report.items() if k not in skip},
           {'schema':'bmk.m0-selfstar-control/2','config_id':bundle['config_id'],'bundle_id':bundle['bundle_id'],
            'probe_sha256':driver,'input_rejections':bundle['rejections']['input'],
            'formal_performance':False,'formal_qualification':False},'SElf* report config, driver or input rejection differs')
    verify_probe_build_lock(report.get('build'),build,PLUGIN,dependency_count=1)

    def read(name):
        path = local_file(out,name)
        require(path.stat().st_size<=bundle['data_artifact_max_bytes'],'SElf* retained artifact exceeds bound')
        return path.read_bytes()

    weather_name = bundle['weather']['path']
    weather = read(weather_name)
    _exact(ref(weather_name,weather),bundle['weather'],'SElf* retained weather input differs')
    rows = report.get('cases')
    require(isinstance(rows,list) and len(rows)==len(bundle['objects'])==9,'SElf* object observation count differs')
    for row,spec,(width,name,plain) in zip(rows,bundle['objects'],case_inputs(bundle['fixtures'],weather),strict=True):
        _object(row,spec,width,name,plain,bundle,read)
    _limits(report.get('native_block_limits'),bundle,read)
