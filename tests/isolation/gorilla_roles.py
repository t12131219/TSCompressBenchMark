"""One frozen differential run for Gorilla's derived T-only and V-only codecs."""
import argparse
from collections import Counter
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.application.restore import _restore
from tsbench.application.smoke import write_new
from tsbench.planner.gorilla import EMPTY_SCHEMA, SCHEMA, columns, oracle, plan_gorilla, sha
from tsbench.plugins import discover, resolve
from tsbench.qualification.gorilla import decode_chunk
from tsbench.recovery import DIRECTORY, check_recovery, plan_recovery, stage_recovery
from tsbench.runtime import SCHEMA as WORKER_LOCK_SCHEMA

HEADER = struct.Struct('<8sIQIQ')
ORIGIN = 'catalog/selections/gorilla_role_derivations.json'
ROLES = {'timestamp': ('gorilla-t-derived', 7, b'BMKGT1\0\0'), 'value': ('gorilla-v-derived', 10, b'BMKGV1\0\0')}
REJECTIONS = {'over-limit-t':7, 'over-limit-v':7, 'wrong-unit':1, 'wrong-type-t':1, 'wrong-type-v':1,
              'unsupported-option':3, 'tv-input-to-t':1, 'tv-input-to-v':1,
              'v-frame-to-t':5, 't-frame-to-v':5, 'truncated-t':5, 'trailing-v':5,
              'bad-inner-count':5, 'nonzero-pad-t':5, 'reuse-before-window-v':5, 'overflow-varint-t':5}


def fixtures():
    parent, pairs = plan_gorilla(ROOT)
    # Exercise the exact asymmetric endpoints of all small delta buckets,
    # the 64-bit escape, initial negative/large delta, and XOR window reuse.
    mask = (1 << 64) - 1
    vals = [0, (1 << 63) - 1, (1 << 63) - 2, (1 << 63) - 2, 1, 1, 3, 0, mask,
            0x7ff8000000000017, 0x8000000000000000, 1, 0, 0, 3]
    dod = [0, 8192, -8191, -8192, 65536, -65535, -65536, 524288, -524287, -524288,
           0, (1 << 63) - 1, -1]
    t = [-4, -70]
    delta = t[1] - t[0]
    for dd in dod:
        delta = (delta + dd) & mask
        unsigned = (t[-1] + delta) & mask
        t.append(unsigned - ((unsigned >> 63) << 64))
    pairs['bucket-and-window-boundaries'] = list(zip(t, vals, strict=True))
    rng = random.Random(11278)
    pairs['max-width-512'] = [(rng.getrandbits(64) - (1 << 63), rng.getrandbits(64)) for _ in range(512)]
    return parent, pairs


def _ref(out, file):
    return {'path': file.relative_to(out).as_posix(), 'bytes': file.stat().st_size, 'sha256': digest(file)}


def schemas(rows):
    return {'timestamp': SCHEMA if rows else EMPTY_SCHEMA, 'value': b'{"role":"value","dtype":"f64"}'}


def freeze(worker, libs, native, run_id):
    parent, pairs = fixtures()
    derivation = load_json(local_file(ROOT, ORIGIN))
    lock = load_json(local_file(ROOT, 'third_party/sources.lock.json'))
    selection = next(e for e in lock['selections'] if e['number']==derivation['upstream_selection'])
    require((selection['number'],selection['target'],selection['selection_id'],selection['source_id'])==
            (7,'gorilla_c',derivation['upstream_selection_id'],derivation['source_id']), 'wrong Gorilla selection')
    frozen = lock['sources'][selection['source_id']]
    ref = frozen['source_manifest']
    members = load_json(verify_asset(ROOT,ref))['files']
    require(next(f['sha256'] for f in members if f['path']==derivation['parent_member'])==derivation['parent_member_sha256'] and
            frozen['archive']['sha256']==derivation['archive_sha256'], 'derivation not bound to frozen archive and member')
    verify_asset(ROOT,frozen['archive'])
    ids = {row[0] for row in ROLES.values()}
    registry = discover(ROOT,selected=ids)
    methods = {}
    for role,(plugin,dtype,magic) in ROLES.items():
        binding = resolve(ROOT,plugin,{},registry=registry)
        inspect = subprocess.run(['/usr/bin/readelf','-Wd',str(libs[role])],env={'LC_ALL':'C'},
                                 check=True,capture_output=True,text=True,timeout=10).stdout
        needed = [s.split('[',1)[1].split(']',1)[0] for s in inspect.splitlines() if '(NEEDED)' in s]
        require(needed and set(needed)<={'libc.so.6','libstdc++.so.6','libgcc_s.so.1'}, 'derived module links an undeclared library')
        require(registry[plugin]['manifest']['roles']==[role] and registry[plugin]['manifest']['format_id']==derivation['routes'][plugin]['format'],
                'role or wire identity differs from derivation')
        methods[role] = {'plugin':plugin, 'dtype':dtype, 'magic_hex':magic.hex(), 'options':binding['options'],
                         'configuration_id':binding['configuration_id'], 'manifest_id':binding['manifest_id'],
                         'format_id':registry[plugin]['manifest']['format_id'],'abi_version':registry[plugin]['manifest']['abi_version'],
                         'source_hashes':registry[plugin]['source_hashes'], 'dso_sha256':digest(libs[role]),'needed':needed}
    by_name = {row['name']:row for row in parent['fixtures']}
    cases = []
    for name, values in pairs.items():
        row = {**oracle(values),'name':name,'lineage':by_name.get(name,{}).get('lineage',{}),
               'schema_sha256':{k:sha(b) for k,b in schemas(len(values)).items()}}
        cases.append(row)
    def binding(file):
        return {'path':file.name,'sha256':digest(file)}
    build_payload = {'schema':WORKER_LOCK_SCHEMA,'worker':binding(worker),'plugins':{m['plugin']:{
        'library':binding(libs[role]),'dependencies':[],'manifest_id':m['manifest_id'],
        'options_schema_id':registry[m['plugin']]['options_schema_id']} for role,m in methods.items()}}
    build_lock = {**build_payload,'build_id':content_id(build_payload)}
    recovery = plan_recovery(worker.parent,build_lock,build_lock['plugins'])
    body = {'schema':'bmk.dev-gorilla-role-plan/1','run_id':run_id,'derivation':derivation,'build':build_lock,'recovery':recovery,
            'worker_sha256':digest(worker), 'native_oracle_dso_sha256':digest(native),'parent_probe_bundle_id':parent['bundle_id'],
            'cases':cases,'methods':methods,'rejections':REJECTIONS,'schedule':[[c['name'],role] for c in cases for role in ROLES],
            'verification':'artifact_each','qualification_granted':False}
    return {**body,'plan_id':content_id(body)}, pairs


def frame_parts(data, method, rows):
    require(len(data)>=HEADER.size, 'truncated role wrapper')
    magic,dtype,count,n_schema,n_payload = HEADER.unpack_from(data)
    require(magic.hex()==method['magic_hex'] and dtype==method['dtype'] and count==rows and
            HEADER.size+n_schema+n_payload==len(data), 'role wrapper schema, shape or lengths differ')
    return data[HEADER.size:HEADER.size+n_schema],data[HEADER.size+n_schema:]


def record_decode(worker, dso, method, frame, log_dir):
    # New workdir contains no original T/V or TV oracle; the worker only gets
    # this role library and retained frame. Missing output is a failed verification.
    with tempfile.TemporaryDirectory(prefix='gorilla-role-decode-') as d:
        cwd = Path(d)
        decoder, adapter, artifact = (cwd/f.name for f in (worker,dso,frame))
        for src,dst in ((worker,decoder),(dso,adapter),(frame,artifact)):
            shutil.copy2(src,dst)
        restored, meta = cwd/'restored.bin', cwd/'schema.json'
        proc = run_worker(cwd,[decoder,'decode',adapter,method['plugin'],'{}',artifact,restored,meta])
        shape, execution = [parse_json(line) for line in proc.stdout.decode().splitlines()]
        write_new(log_dir/'decode.json', {'shape':shape,'execution':execution})
        return restored.read_bytes(), meta.read_bytes(), shape


def bad_cases(worker, libs, plan, out):
    observed = {}
    with tempfile.TemporaryDirectory(prefix='gorilla-role-negative-') as d:
        cwd = Path(d)
        a,b,s,encoded,restored,metadata = (cwd/x for x in ('a','b','schema','encoded','restored','metadata'))
        a.write_bytes(b'\0'*8); b.write_bytes(b'\0'*8); s.write_bytes(SCHEMA)
        t,v = ('timestamp','value')
        def call(name, role, op, args, opts='{}'):
            for path in (encoded,restored,metadata):
                path.unlink(missing_ok=True)
            proc = run_worker(cwd,[worker,op,libs[role],plan['methods'][role]['plugin'],opts,*args],check=False)
            text = proc.stderr.decode().strip()
            code = REJECTIONS[name]
            require(proc.returncode==3 and text.startswith(f'plugin status {code}:') and
                    not any(f.exists() for f in (encoded,restored,metadata)), f'wrong rejection {name}: {text}')
            observed[name] = {'status':code,'returncode':proc.returncode,'diagnostic':text,'output_written':False}
        def encode(name, role, dtype, opts='{}'):
            call(name,role,'encode',[str(dtype),a,s,encoded],opts)
        encode('wrong-type-t',t,10); encode('wrong-type-v',v,7)
        encode('unsupported-option',t,7,'{"unexpected":true}')
        for role,letter in ((t,'t'),(v,'v')):
            call('tv-input-to-'+letter,role,'encode-columns',[s,encoded,'7',a,'10',b])
        s.write_bytes(b'{"time_unit":"s"}'); encode('wrong-unit',t,7)
        s.write_bytes(SCHEMA); a.write_bytes(b'\0'*8*513)
        encode('over-limit-t',t,7); encode('over-limit-v',v,10)
        artifact = cwd/'artifact'
        tf = (out/'time-wrap-and-float-bits'/t/'frame.bmk').read_bytes()
        vf = (out/'time-wrap-and-float-bits'/v/'frame.bmk').read_bytes()
        def decode(name, role, blob):
            artifact.write_bytes(blob)
            call(name,role,'decode',[artifact,restored,metadata])
        decode('v-frame-to-t',t,vf); decode('t-frame-to-v',v,tf)
        decode('truncated-t',t,tf[:-1]); decode('trailing-v',v,vf+b'\0')
        idx = HEADER.size + len(SCHEMA)
        decode('bad-inner-count',t,tf[:idx]+b'\0\1'+tf[idx+2:])
        def wrap(role, rows, payload):
            schema = schemas(rows)[role]
            method = plan['methods'][role]
            return HEADER.pack(bytes.fromhex(method['magic_hex']),method['dtype'],rows,len(schema),len(payload))+schema+payload
        # 3 equal timestamps: 8+8+1 bits. Flip one terminal padding bit.
        decode('nonzero-pad-t',t,wrap(t,3,b'\0\3\0\0\1'))
        decode('reuse-before-window-v',v,wrap(v,2,b'\0\2'+bytes(8)+b'\x80'))
        decode('overflow-varint-t',t,wrap(t,1,b'\0\1'+b'\x80'*9+b'\x02'))
    return observed


def run(worker, t_lib, v_lib, native, output):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gorilla_tv_control import Native
    libs = {'timestamp':t_lib, 'value':v_lib}
    run_id = uuid.uuid4().hex
    output.mkdir(parents=True, exist_ok=True)
    out = output/run_id
    out.mkdir()
    with tempfile.TemporaryDirectory(prefix='bmk-gorilla-role-closure-') as directory:
        staging = Path(directory)
        for path in (worker,t_lib,v_lib):
            shutil.copy2(path,staging/path.name)
        copied = {role:staging/path.name for role,path in libs.items()}
        plan,pairs = freeze(staging/worker.name,copied,native,run_id)
        stage_recovery(staging,out,plan['recovery'])
    write_new(out/'plan.json',plan)
    reference = Native(native)
    observations = []
    for case in plan['cases']:
        name, rows = case['name'], case['rows']
        folder = out/name
        folder.mkdir()
        native_frame = reference.compress(pairs[name])
        (folder/'oracle.xor').write_bytes(native_frame)
        projection = {}
        decoded, _ = decode_chunk(native_frame,rows,projection=projection)
        require(oracle(decoded)==oracle(pairs[name]),'native differential oracle differs')
        for role,raw in zip(ROLES,columns(pairs[name]),strict=True):
            target = folder/role
            target.mkdir()
            schema = schemas(rows)[role]
            method = plan['methods'][role]
            with tempfile.TemporaryDirectory(prefix='gorilla-role-encode-') as d:
                cwd = Path(d)
                src,meta = cwd/'one-column.bin',cwd/'schema.json'
                src.write_bytes(raw); meta.write_bytes(schema)
                frame = target/'frame.bmk'
                proc = run_worker(cwd,[worker,'encode',libs[role],method['plugin'],'{}',str(method['dtype']),src,meta,frame])
                (target/'encode.json').write_bytes(proc.stdout)
            read_schema, payload = frame_parts(frame.read_bytes(),method,rows)
            require(read_schema==schema and payload==projection[role][0], 'derived tokens differ from native role projection')
            restored, restored_schema, shape = record_decode(worker,libs[role],method,frame,target)
            require((restored,restored_schema,shape)==(raw,schema,{'dtype':method['dtype'],'count':rows}), 'role restore differs')
            observations.append({'case':name,'role':role,'status':'verified','original_bytes':len(raw),
                                 'frame':_ref(out,frame),'payload_bytes':len(payload),'role_token_bits':projection[role][1],
                                 'restored_values_sha256':sha(restored),'restored_schema_sha256':sha(restored_schema)})
    write_new(out/'observations.json',{'slots':observations,'rejections':bad_cases(worker,libs,plan,out)})
    refs = [_ref(out,f) for f in sorted(out.rglob('*')) if f.is_file()]
    seal = {'schema':'bmk.dev-gorilla-role-seal/1','plan_id':plan['plan_id'],'files':refs}
    write_new(out/'completion.json',{**seal,'seal_id':content_id(seal)})
    result = report(out)
    write_new(out/'report.json',result)
    return result


def report(out):
    seal = load_json(local_file(out,'completion.json'))
    require(seal['schema']=='bmk.dev-gorilla-role-seal/1' and
            content_id({k:v for k,v in seal.items() if k!='seal_id'})==seal['seal_id'], 'invalid Gorilla role seal')
    sealed = {r['path']:r for r in seal['files']}
    require(len(sealed)==len(seal['files']), 'duplicate Gorilla role evidence')
    for ref in sealed.values():
        require(verify_asset(out,ref).stat().st_size==ref['bytes'], 'bad Gorilla role evidence byte count')
    plan = load_json(local_file(out,'plan.json'))
    require(plan['schema']=='bmk.dev-gorilla-role-plan/1' and plan['qualification_granted'] is False and
            content_id({k:v for k,v in plan.items() if k!='plan_id'})==plan['plan_id']==seal['plan_id'], 'invalid role plan')
    journal = load_json(local_file(out,'observations.json'))
    cases = plan['cases']
    planned = [[c['name'],r] for c in cases for r in ROLES]
    require(len({c['name'] for c in cases})==len(cases) and plan['schedule']==planned and
            [[r['case'],r['role']] for r in journal['slots']]==planned, 'incomplete Gorilla role schedule')
    by_key = {(r['case'],r['role']):r for r in journal['slots']}
    expected_files = {'plan.json','observations.json'}
    build = plan['build']
    require(content_id({k:v for k,v in build.items() if k!='build_id'})==build['build_id'] and
            build['worker']['sha256']==plan['worker_sha256'] and
            build['plugins'].keys()=={val[0] for val in ROLES.values()}, 'role worker lock differs')
    recovery = plan['recovery']
    check_recovery(recovery,build,build['plugins'])
    for rel,ref in recovery['files'].items():
        name = DIRECTORY+'/'+rel
        require(sealed.get(name)=={'path':name,'bytes':ref['bytes'],'sha256':ref['sha256']}, 'role dependency not sealed')
        expected_files.add(name)
    for case in cases:
        name, rows = case['name'], case['rows']
        path = f'{name}/oracle.xor'
        projected = {}
        pairs, _ = decode_chunk(local_file(out,path).read_bytes(),rows,projection=projected)
        require(all(case[k]==v for k,v in oracle(pairs).items()),'native projection differs from frozen input')
        expected_files.add(path)
        for role, field in (('timestamp','milliseconds_sha256'),('value','value_sha256')):
            path = f'{name}/{role}/frame.bmk'
            enc = f'{name}/{role}/encode.json'
            dec = f'{name}/{role}/decode.json'
            expected_files.update((path,enc,dec))
            method = plan['methods'][role]
            plugin, dtype, magic = ROLES[role]
            require((method['plugin'],method['dtype'],method['magic_hex'])==(plugin,dtype,magic.hex()) and
                    method['dso_sha256']==build['plugins'][plugin]['library']['sha256'] and method['options']=={},
                    'method differs from role or DSO lock')
            schema, payload = frame_parts(local_file(out,path).read_bytes(),method,rows)
            decoded = load_json(local_file(out,dec))
            encoded = load_json(local_file(out,enc))
            require(decoded['shape']=={'dtype':method['dtype'],'count':rows} and
                    encoded=={**decoded['execution'],'operation':'encode'} and decoded['execution']['operation']=='decode' and
                    encoded['backend']==f"gorilla-{'t' if role=='timestamp' else 'v'}-c11-derived",
                    'actual worker protocol differs from role contract')
            require(sha(schema)==case['schema_sha256'][role] and payload==projected[role][0], 'wrong role tokens or schema')
            expected = {'case':name,'role':role,'status':'verified','original_bytes':rows*8,'frame':sealed[path],
                        'payload_bytes':len(payload),'role_token_bits':projected[role][1],
                        'restored_values_sha256':case[field],'restored_schema_sha256':sha(schema)}
            require(by_key[name,role]==expected,'role evidence accounting or restored bits differ')
    require(expected_files==sealed.keys() and plan['rejections']==REJECTIONS and
            journal['rejections'].keys()==REJECTIONS.keys(), 'role evidence or rejection set differs')
    for label,code in REJECTIONS.items():
        row = journal['rejections'][label]
        require(row['status']==code and row['returncode']==3 and row['output_written'] is False and
                row['diagnostic'].startswith(f'plugin status {code}:'), 'role rejection outcome differs')
    return {'schema':'bmk.dev-gorilla-role-report/1','run_id':plan['run_id'],'plan_id':plan['plan_id'],'seal_id':seal['seal_id'],
            'statuses':dict(Counter(s['status'] for s in journal['slots'])),'rejected_cases':len(REJECTIONS),
            'slots':journal['slots'],'rejections':journal['rejections'],'qualification_granted':False}


def restore(out):
    audited = report(out)
    plan = load_json(local_file(out,'plan.json'))
    cases = {case['name']:case for case in plan['cases']}
    checks = []
    for row in audited['slots']:
        role = row['role']
        case = cases[row['case']]
        method = plan['methods'][role]
        source = {'count':case['rows'],'dtype':method['dtype'],'bytes':row['original_bytes'],
                  'raw_sha256':row['restored_values_sha256'],'schema_sha256':row['restored_schema_sha256']}
        artifact = verify_asset(out,row['frame'])
        spec = plan['recovery']
        other_plugins = {path for plugin,path in spec['plugins'].items() if plugin!=method['plugin']}
        isolated = {**spec,'files':{path:ref for path,ref in spec['files'].items() if path not in other_plugins}}
        decoded = _restore(out/DIRECTORY,isolated,method,artifact,source,5)
        checks.append({'case':row['case'],'role':role,'artifact':row['frame'],**decoded})
    return {'schema':'bmk.dev-gorilla-role-restore/1','run_id':audited['run_id'],'seal_id':audited['seal_id'],
            'isolation':'files_only_bubblewrap', 'restored_slots':len(checks),'slots':checks,'qualification_granted':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--report',type=Path)
    mode.add_argument('--restore',type=Path)
    parser.add_argument('paths',type=Path,nargs='*')
    args = parser.parse_args()
    from tsbench.assets import canonical_bytes
    if args.report is not None and not args.paths:
        result = report(args.report)
    elif args.restore is not None and not args.paths:
        result = restore(args.restore)
    elif args.report is None and args.restore is None and len(args.paths)==5:
        result = run(*(p.resolve() for p in args.paths))
    else:
        parser.error('pass WORKER T_LIB V_LIB TV_LIB OUTPUT, or --report/--restore RUN_DIR')
    sys.stdout.buffer.write(canonical_bytes(result)+b'\n')


if __name__=='__main__':
    main()
