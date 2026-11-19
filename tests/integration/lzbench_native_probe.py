#!/usr/bin/env python3
"""Execute seven frozen lzbench native operation-group probes as one M0 diagnostic."""
import argparse
import ctypes as c
import lzma
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import sys
import shutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import canonical_bytes, require
from tsbench.planner.lzbench import ARCHIVE, DIR, INVENTORY, dictionary_sample, plan_lzbench, probe_schema, sample, worker_input
from tsbench.qualification.lzbench import verify_lzbench, xz_advertise_dictionary

DEFINITIONS = {'cpp': 'tests/native/lzbench_contract.cpp', 'driver': 'tests/integration/lzbench_native_probe.py'}


def file_ref(path):
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": sha}


def run(executable, *args, cwd, rejection=None):
    result = subprocess.run([str(executable), *map(str, args)], cwd=cwd, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, check=False, timeout=25)
    if rejection is not None:
        require(result.returncode == 2 and rejection in result.stderr,
                f"expected {rejection!r}, received rc={result.returncode}: {result.stderr!r}")
        return {"exit_status": result.returncode, "error": result.stderr.strip()}
    require(result.returncode == 0, f"{executable.name} {args[:2]} failed: {result.stderr.strip()}")
    evidence = json.loads(result.stdout)
    return {key: value for key, value in evidence.items() if not key.endswith("_ns")}


def feature(exe, directory, op, codec, source, frame, decoded, *, size=0, dictionary="-", rejection=None,
            input_chunk=262139, output_chunk=65521, level=3, params=()):
    return run(exe, op, codec, "frame", level, input_chunk, output_chunk, 65536, "reuse", 1,
               dictionary, source, frame, decoded, size, *params, cwd=directory, rejection=rejection)


def dictionary_probe(exe, directory, evidence, spec):
    train_manifest = spec['training_samples']
    paths = []
    for i, expected in enumerate(train_manifest):
        path = directory / f'train-{i:03}.bin'
        path.write_bytes(dictionary_sample('train',i))
        require(file_ref(path) == expected, 'frozen dictionary sample differs')
        paths.append(path)
    trainer_rejected = {}
    for capacity in spec['bad_capacities']:
        invalid = directory / 'bad-capacity.zdict'
        # Capacity is validated before allocation; a single bounded sample suffices for this rejection test.
        trainer_rejected[str(capacity)] = run(exe,'train',capacity,invalid,paths[0],cwd=directory,
                                               rejection='dictionary training size')
        require(not invalid.exists(), 'rejected trainer produced a dictionary')
    dictionary = directory / spec['dictionary_path']
    trained = run(exe,'train',spec['capacity'],dictionary,*paths,cwd=directory)
    for path in paths:
        path.unlink()
    data = dictionary.read_bytes()
    require(data[:4] == b'\x37\xa4\x30\xec' and 8 <= len(data) == trained['dictionary_bytes'] <= spec['capacity'],
            'trainer did not return a bounded standard dictionary')
    dict_id = int.from_bytes(data[4:8],'little')
    require(dict_id > 1,'expected nonzero trained dictionary ID')
    wrong = directory / 'wrong-id.bin'
    wrong.write_bytes(data[:4] + (dict_id ^ 1).to_bytes(4,'little') + data[8:])
    plain, frame, decoded, copied = (directory / n for n in ('held-out.bin',spec['frame_path'],'decoded.bin','copy.zst'))
    held_out = b''.join(dictionary_sample('held-out',i) for i in range(len(spec['held_out_samples'])))
    plain.write_bytes(held_out)
    in_span,out_span = spec['span_profiles']['roundtrip']
    observed = feature(exe,directory,'roundtrip','zstd',plain,frame,decoded,dictionary=dictionary,
                       input_chunk=in_span,output_chunk=out_span)
    frame_ref = file_ref(frame)
    held_out_ref = file_ref(plain)
    require(decoded.read_bytes() == held_out,'dictionary roundtrip mismatch')
    plain.unlink()
    decoded.unlink()
    in_span,out_span = spec['span_profiles']['fresh_decode']
    recovery = feature(exe,directory,'decode','zstd',frame,copied,decoded,dictionary=dictionary,
                       size=len(held_out),input_chunk=in_span,output_chunk=out_span)
    require(decoded.read_bytes() == held_out and file_ref(copied) == frame_ref,
            'fresh process with only encoded input and dictionary differs')
    fresh = file_ref(decoded)
    for output in (copied,decoded):
        output.unlink()
    negatives = {}
    for name,supplied in (('missing','-'),('wrong_id',wrong)):
        negatives[name] = feature(exe,directory,'decode','zstd',frame,copied,decoded,size=len(held_out),
                                  dictionary=supplied,rejection='Dictionary mismatch')
        require(not copied.exists() and not decoded.exists(),f'unexpected {name} dictionary outputs')
    for path in (dictionary,frame):
        shutil.copy2(path,evidence/path.name)
    return {'training_samples':train_manifest,'sample_set_identity':{'train':'train','held_out':'held-out'},
            'training_capacity_bytes':spec['capacity'],'trainer_rejected':trainer_rejected,
            'dictionary':{**file_ref(dictionary),'id':dict_id},'held_out':held_out_ref,'encoded':frame_ref,
            'serialized_bytes_including_dictionary':len(data)+frame_ref['bytes'],
            'roundtrip':observed,'fresh_process_decode':recovery,'fresh_process_restored':fresh,
            'negative_dictionary_id':dict_id ^ 1,'rejected':negatives}


def workers_probe(exe, contract, directory, codec, evidence, library, spec):
    input_file = directory / 'workers.bin'
    size = spec['input']['bytes']
    data = worker_input(codec,size)
    input_file.write_bytes(data)
    parameter,settings,level = spec['parameter'],spec['settings'],spec['level']
    base = tuple(f'{k}={v}' for k,v in spec['base'].items())
    in_span,out_span = spec['span_profile']
    observations = {}
    for n in settings:
        frame, decoded = directory/spec['frame_paths'][str(n)], directory/f'{n}.decoded'
        seen = feature(exe,directory,'roundtrip',codec,input_file,frame,decoded,level=level,
                       params=(*base,f'{parameter}={n}'),input_chunk=in_span,output_chunk=out_span)
        require(seen['native_stream'] and seen['effective_parameters'][parameter] == n,
                f'{codec} unexpectedly changed {parameter}={n}')
        require(decoded.read_bytes() == data,f'{codec} {n} worker roundtrip mismatch')
        observations[str(n)] = {**seen,'frame':file_ref(frame)}
        decoded.unlink()
    sync = spec.get('synchronous')
    if sync:
        encode = run(contract,'xz-sync-encode',cwd=directory)
        frame = directory/sync['frame_path']
        sync_obs = {'encode':encode,'frame_path':frame.name,'frame':file_ref(frame),'decode':{}}
        shutil.copyfile(frame,evidence/frame.name)
    input_ref = file_ref(input_file)
    input_file.unlink()
    for n in settings:
        lane = observations[str(n)]
        name = spec['frame_paths'][str(n)]
        artifact = restore_ref(codec,name,size,data,directory,evidence,library)
        lane['fresh_process_restored'] = artifact['fresh_process_restore']
        lane['frame_path'] = name
    if codec == 'xz':
        # Both decoder profiles consume the exact same multi-block stream, not their own encoder artifacts.
        same = directory/spec['frame_paths']['2']
        in_span,out_span = spec['xz_same_frame_decode_spans']
        for n in settings:
            copied, decoded = directory/f'copy-{n}.frame', directory/f'cross-{n}.decoded'
            seen = feature(exe,directory,'decode','xz',same,copied,decoded,level=level,size=size,input_chunk=in_span,
                           output_chunk=out_span,params=(*base,f'threads={n}'))
            require(file_ref(copied) == file_ref(same) and decoded.read_bytes() == data,f'XZ decoder profile {n} mismatch')
            observations[str(n)]['same_multiblock_frame_decode'] = {
                **seen,'source_frame':file_ref(same),'fresh_process_restored':file_ref(decoded)}
    if sync:
        for role, name in (('own',sync['frame_path']),('shared',spec['frame_paths']['2'])):
            decoded = directory/'sync.decoded'
            seen = run(contract,'xz-sync-decode',name,cwd=directory)
            require(decoded.read_bytes() == data,f'XZ caller-synchronous {role} frame restore mismatch')
            sync_obs['decode'][role] = {**seen,'source_frame_path':name,'source_frame':file_ref(directory/name),
                                        'fresh_process_restored':file_ref(decoded)}
            decoded.unlink()
    return {'input':input_ref,'profile_parameter':parameter,'configured_base':spec['base'],'observed':observations,
            **({'synchronous':sync_obs} if sync else {})}


def upstream_restore(codec, library, path, size, output):
    # Child receives only a frame, its output quota and (for Zstd) the selected library.
    require(0 <= size <= (5<<20)+297 and 0 < path.stat().st_size <= size+65536, 'invalid detached restore bounds')
    frame = path.read_bytes()
    if codec == 'zstd':
        lib = c.CDLL(str(library))
        lib.ZSTD_decompress.argtypes = (c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t)
        lib.ZSTD_decompress.restype = c.c_size_t
        dest = c.create_string_buffer(max(1,size))
        require(lib.ZSTD_decompress(dest,size,frame,len(frame)) == size, 'upstream Zstd restore differs')
        decoded = dest.raw[:size]
    else:
        require(codec == 'xz', 'unsupported restore codec')
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=64<<20)
        decoded = dec.decompress(frame,max_length=size+1)
        require(dec.eof and not dec.unused_data and len(decoded) == size,'independent XZ restore differs')
    output.write_bytes(decoded)


def restore_ref(codec, name, size, expected, directory, evidence, library):
    frame = directory / name
    restored = directory / 'fresh-process.decoded'
    result = subprocess.run([sys.executable,'-I','-B',Path(__file__).resolve(),'--restore',codec,library,frame,
                             str(size),restored], cwd=directory, stdin=subprocess.DEVNULL,
                            capture_output=True,text=True,check=False,timeout=25)
    require(result.returncode == 0,f'detached {codec} restore failed: {result.stderr}')
    require(restored.read_bytes() == expected,f'detached {codec} original bytes differ')
    ref = {'path':name,'frame':file_ref(frame),'fresh_process_restore':file_ref(restored)}
    restored.unlink()
    shutil.copy2(frame,evidence/name)
    return ref


def restore_refs(codec, files, directory, evidence, library):
    return [restore_ref(codec,n,x['bytes'],sample(x['bytes'],x['salt']),directory,evidence,library) for n,x in files]


def main():
    if len(sys.argv) == 7 and sys.argv[1] == '--restore':
        _, _, codec, library, frame, quota, target = sys.argv
        upstream_restore(codec,Path(library),Path(frame),int(quota),Path(target))
        return
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('contract', 'feature_worker', 'library'):
        p.add_argument(arg, type=lambda value: Path(value).resolve(strict=True))
    p.add_argument('--evidence', type=Path, required=True)
    args = p.parse_args()
    out = args.evidence.resolve()
    require(out.name == DIR, 'wrong lzbench evidence directory')
    bundle = plan_lzbench(ROOT)
    archive = file_ref(ROOT / ARCHIVE)
    require(archive['sha256'] == bundle['archive_sha256'], 'unexpected source archive')
    build = {getattr(args,k).name:file_ref(getattr(args,k))['sha256'] for k in ('library','contract','feature_worker')}
    definitions = {k:file_ref(ROOT / path)['sha256'] for k,path in DEFINITIONS.items()}
    observations = []
    with tempfile.TemporaryDirectory(prefix='tsbench-lzbench-probe-',dir=out.parent) as tmp:
        stage = Path(tmp)
        evidence = stage / DIR
        evidence.mkdir()
        for codec, selection in (('zstd',40),('xz',39)):
            directory = stage / codec
            directory.mkdir()
            for entry in (e for e in bundle['groups'] if e['selection'] == selection):
                group = entry['group']
                kind = group.removeprefix(f'{codec}-')
                if kind in ('baseline','session'):
                    result = run(args.contract,kind,codec,cwd=directory)
                    if kind == 'baseline':
                        frames = bundle['baseline'] if codec == 'zstd' else bundle['xz_baseline']['frames']
                        files = [(f['frame'], f['input']) for f in frames]
                        result['artifacts'] = restore_refs(codec,files,directory,evidence,args.library)
                    if group == 'xz-baseline':
                        spec = bundle['xz_guard']
                        guard = directory / spec['frame']
                        guard.write_bytes(xz_advertise_dictionary((directory/spec['base_frame']).read_bytes(),
                                                                  spec['dictionary_property']))
                        result['guards'] = {**run(args.contract,'guards','xz',cwd=directory),'frame':file_ref(guard)}
                        shutil.copy2(guard,evidence/guard.name)
                    if kind == 'session':
                        spec = bundle['sessions'][codec]
                        files = [(name,spec['inputs'][key]) for key,name in spec['files'].items()]
                        result['artifacts'] = restore_refs(codec,files,directory,evidence,args.library)
                elif group == 'zstd-dictionary':
                    result = dictionary_probe(args.feature_worker,directory,evidence,bundle['dictionary'])
                elif kind == 'workers':
                    result = workers_probe(args.feature_worker,args.contract,directory,codec,evidence,args.library,
                                           bundle['workers'][codec])
                else:
                    raise RuntimeError(f'unmapped probe group: {group}')
                observations.append({**entry,'status':'diagnostic_verified','qualification':'not_run','observed':result})
        report = {'schema':probe_schema(bundle),'bundle_id':bundle['bundle_id'],
                  'case_ids':[x['case_id'] for x in bundle['cases']], 'source_archive':archive,
                  'inventory':file_ref(ROOT/INVENTORY),'build':build,'diagnostic_definitions':definitions,
                  'formal_performance':False,'formal_qualification':False,'observations':observations}
        (stage/bundle['evidence_path']).write_bytes(canonical_bytes(report)+b'\n')
        verify_lzbench(bundle,build,definitions,stage)
        out.mkdir(exist_ok=True)
        for name in bundle['binary'] + ['report.json']:
            (evidence/name).replace(out/name)
    print(f'M0 diagnostic: {len(observations)} native operation groups matched for Zstd/XZ; no formal qualification')


if __name__ == "__main__":
    main()
