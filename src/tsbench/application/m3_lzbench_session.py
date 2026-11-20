"""Verify every frozen whole-object session using a fresh native decoder process."""
import filecmp
import shutil
import subprocess

from ..assets import digest, local_file, parse_json, require
from ..planner.m3_lzbench_session import DRIVER, INPUT_SPAN, OUTPUT_SPAN, RETAIN_BYTES, input_size

CONFIG = {'zstd': {'level': 3, 'workers': 0, 'checksum': 1},
          'xz': {'preset': 1, 'block_size': 32768, 'check': 4, 'filter0': 3, 'filter0_distance': 4,
                 'threads': 1, 'memory_limit': 64 << 20}}


def observation(doc, source_bytes, output_bytes):
    keys = ('calls', 'finish_calls', 'zero_input_finish_calls', 'partial_input_calls', 'full_output_calls',
            'first_output_call', 'first_output_after_consumed_bytes', 'first_output_bytes', 'first_output_driver_wall_ns')
    require(doc['input_bytes']==source_bytes and doc['output_bytes']==output_bytes and source_bytes>0 and output_bytes>0 and
            all(type(doc[k]) is int and doc[k]>=0 for k in keys) and
            doc['calls'] >= max((source_bytes+INPUT_SPAN-1)//INPUT_SPAN,(output_bytes+OUTPUT_SPAN-1)//OUTPUT_SPAN) and
            1<=doc['finish_calls']<=doc['calls'] and 0<=doc['zero_input_finish_calls']<=doc['finish_calls'] and
            doc['partial_input_calls']<=doc['calls'] and doc['full_output_calls']*OUTPUT_SPAN<=output_bytes and
            1<=doc['first_output_call']<=doc['calls'] and doc['first_output_after_consumed_bytes']<=source_bytes and
            0<doc['first_output_bytes']<=min(OUTPUT_SPAN,output_bytes), 'lzbench native session accounting differs')
    work = doc['jobs']
    require(work.keys()=={'jobs','worker_threads','caller_jobs'} and all(type(x) is int and x>=0 for x in work.values()) and
            work['caller_jobs']+work['worker_threads']<=work['jobs'] and isinstance(doc['effective_parameters'],dict),
            'lzbench native worker-hook evidence differs')


def invoke(exe, codec, direction, source, dest, cap):
    result = subprocess.run([str(exe), codec, direction, str(source), str(dest), str(cap)],
                            cwd=dest.parent, env={'LC_ALL':'C'}, capture_output=True, text=True, timeout=300)
    require(result.returncode==0 and not result.stderr,
            f'lzbench {codec} {direction}: {result.stderr.strip() or result.returncode}')
    doc = parse_json(result.stdout,'lzbench corpus native session observation')
    observation(doc,source.stat().st_size,dest.stat().st_size)
    return doc


def run_session(root, plan, item, entry, staged, work, run):
    size = input_size(item,entry)
    raw, = staged['paths']
    require(raw.stat().st_size==size,'lzbench staged V bytes differ from frozen extent')
    codec = item['route'].split('-')[0]
    exe = local_file(root,plan['build']['lzbench_session']['executable']['path'])
    folder = work/'native-session'; folder.mkdir()
    wire, recovered = folder/'native.frame',folder/'restored.bin'
    encode = invoke(exe,codec,'encode',raw,wire,size+size//10+65536)
    decode = invoke(exe,codec,'decode',wire,recovered,size)
    require(filecmp.cmp(raw,recovered,shallow=False),'lzbench detached native session restoration differs bitwise')
    source_hash, wire_hash = digest(raw), digest(wire)
    retained = None
    if wire.stat().st_size<=RETAIN_BYTES:
        rel = f"retained/{item['work_item_id']}/native.frame"
        path = run/rel; path.parent.mkdir(parents=True,exist_ok=False)
        shutil.copyfile(wire,path)
        retained = {'path':rel,'bytes':wire.stat().st_size,'sha256':wire_hash}
    return {'driver':DRIVER,'codec':codec,'configuration':CONFIG[codec], 'entry':'lzbench_native::session::process',
            'span_bytes':{'input':INPUT_SPAN,'output':OUTPUT_SPAN},'continuous_sessions_per_direction':1,
            'source':{'bytes':size,'sha256':source_hash},'recovered':{'bytes':size,'sha256':source_hash},
            'frame':{'bytes':wire.stat().st_size,'sha256':wire_hash}, 'retained_frame':retained,
            'encode':encode,'decode':decode,'decode_arguments':'frame_plus_output_extent_without_original_input',
            'wall_scope':'driver_loop_including_span_file_io_not_codec_only', 'timing_admitted':False}
