"""Recompute PBEPLA prefix closure, exact f64 error and logical replay accounting."""
from binascii import crc32
from fractions import Fraction
from hashlib import sha256
import math
from pathlib import Path
import struct
import sys

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..planner.pbepla_progressive import REPLAY_HELPER, WORD_MAGIC, boundary_source, retained_paths, schema_bytes
from .probe_build import verify_probe_build_lock

OUTER = struct.Struct("<8sIQIQ")
MAGIC = b"BMKPBE\x01\0"
PBEP = struct.Struct("<4sBBBBQIdd")


def quality(original: bytes, restored: bytes) -> tuple[Fraction, dict]:
    require(len(original) == len(restored) and len(original) % 8 == 0, "PBEPLA restored count differs")
    maximum = Fraction(0)
    for (x,), (y,) in zip(struct.iter_unpack("<d", original), struct.iter_unpack("<d", restored), strict=True):
        require(math.isfinite(x) and math.isfinite(y), "PBEPLA nonfinite original or restored sample")
        maximum = max(maximum, abs(Fraction(x) - Fraction(y)))
    return maximum, {"max_abs_error": float(maximum) if maximum <= sys.float_info.max else None,
                     "exact_max_abs_error": str(maximum), "restored_sha256": sha256(restored).hexdigest()}


def _fields(observed, expected, label):
    require(isinstance(observed, dict) and expected.keys() <= observed.keys() and
            all(canonical_bytes(observed[k]) == canonical_bytes(v) for k, v in expected.items()), label)


def _parse_frame(frame: bytes, spec: dict, ordinal: int) -> tuple[dict, tuple, bytes, bytes]:
    name = spec["name"]
    schema = schema_bytes(name)
    base = OUTER.size + len(schema)
    k = len(spec["requested_eps"])
    min_native = PBEP.size + 9 * k + 8 * ordinal + 8
    require(len(frame) >= base + min_native and
            OUTER.unpack_from(frame) == (MAGIC, 10, spec["count"], len(schema), len(frame) - base) and
            frame[OUTER.size:base] == schema and sha256(schema).hexdigest() == spec["schema_sha256"],
            f"PBEPLA frame descriptor/schema differs: {name}/{ordinal}")
    native = frame[base:]
    magic, version, flags, declared, stored, count, delay, lo, hi = PBEP.unpack_from(native)
    require((magic, version, flags, declared, stored, count, delay) ==
            (b"PBEP", 1, spec["expected_flags"], k, ordinal, spec["count"], spec["expected_delay"]) and
            math.isfinite(lo) and math.isfinite(hi) and lo < hi,
            f"PBEPLA prefix metadata differs: {name}/{ordinal}")
    eps = list(struct.unpack_from(f"<{k}d", native, PBEP.size))
    resolutions = list(native[PBEP.size + 8 * k:PBEP.size + 9 * k])
    require(all(math.isfinite(e) and 0 < e <= r for e, r in zip(eps, spec["requested_eps"], strict=True)) and
            all(a > b for a, b in zip(eps, eps[1:])), f"PBEPLA effective bounds exceed request: {name}/{ordinal}")
    geometry = spec["geometry"] or {}
    require((not geometry.get("has_source_range") or (lo, hi) ==
             (geometry["source_min"] - 2.0 * spec["requested_eps"][0], geometry["source_max"])) and
            ("resolutions" not in geometry or resolutions == geometry["resolutions"]),
            f"PBEPLA explicit geometry differs: {name}/{ordinal}")
    bits = list(struct.unpack_from(f"<{stored}Q", native, PBEP.size + 9 * k))
    body_crc, head_crc = struct.unpack_from("<II", native, min_native - 8)
    body = native[min_native:]
    layer_bytes = [(b + 7) // 8 for b in bits]
    require(sum(layer_bytes) == len(body) and crc32(body) == body_crc and crc32(native[:min_native-4]) == head_crc,
            f"PBEPLA prefix bytes or CRC differ: {name}/{ordinal}")
    wire = {"flags": flags, "declared": declared, "stored": stored, "count": count, "delay": delay,
            "eps": eps, "resolutions": resolutions, "bits": bits, "layer_bytes": layer_bytes,
            "header_bytes": min_native, "payload_bytes": len(body)}
    return wire, (lo, hi), native, body


def _verify_progressive(spec, row, out, cap):
    name, eps = spec["name"], spec["requested_eps"]
    _fields(row, {"name": name, "input_id": spec["input_id"], "input_sha256": spec["input_sha256"],
                  "requested_eps": eps}, f"PBEPLA report input differs: {name}")
    layers = row.get("layers")
    require(isinstance(layers, list) and len(layers) == len(eps), f"PBEPLA reported layer denominator differs: {name}")
    values_file = local_file(out, spec["word_path"])
    require(values_file.stat().st_size == spec["word_bytes"], f"PBEPLA retained word count differs: {name}")
    words = values_file.read_bytes()
    width = 8 * spec["count"]
    at = len(WORD_MAGIC)
    original = words[at:at+width]
    require(words.startswith(WORD_MAGIC) and sha256(original).hexdigest() == spec["input_sha256"],
            f"PBEPLA retained original differs from frozen input: {name}")

    prefixes, qualities = [], []
    for ordinal, (path, actual) in enumerate(zip(spec["frame_paths"], layers, strict=True), 1):
        file = local_file(out, path)
        size = file.stat().st_size
        require(0 < size <= cap, f"PBEPLA frame exceeds retention bound: {path}")
        frame = file.read_bytes()
        wire, grid, native, body = _parse_frame(frame, spec, ordinal)
        prefixes.append((wire, grid, native, body))
        offset = at + ordinal * width
        maximum, q = quality(original, words[offset:offset+width])
        effective = wire["eps"][ordinal-1]
        require(maximum <= Fraction(effective), f"PBEPLA original-domain error exceeds effective bound: {name}/{ordinal}")
        qualities.append({"layer": ordinal, **q})
        _fields(actual, {"layer": ordinal, "effective_eps": effective, "prefix_sha256": sha256(native).hexdigest(),
                         "prefix_header_bytes": wire["header_bytes"], "incremental_payload_bytes": wire["layer_bytes"][-1],
                         "cumulative_payload_bytes": len(body), "detached_prefix_bytes": len(native), "worker_frame_bytes": size,
                         "frame_sha256": sha256(frame).hexdigest(), **q}, f"PBEPLA prefix report differs: {name}/{ordinal}")
        _fields(actual.get("decode_info"), {"backend": "tba-pbepla-rr-port", "threads": 1, "fallback": False,
                "operation": "decode", "mode": "batch", "layers_stored": ordinal,
                "native_header_bytes": wire["header_bytes"], "native_payload_bytes": len(body)},
                f"PBEPLA detached worker path differs: {name}/{ordinal}")
    full, full_grid, full_native, full_body = prefixes[-1]
    for wire, grid, _, body in prefixes:
        stored = wire["stored"]
        require(grid == full_grid and wire["eps"] == full["eps"] and wire["resolutions"] == full["resolutions"] and
                wire["bits"] == full["bits"][:stored] and body == full_body[:len(body)],
                f"PBEPLA is not a prefix of the retained full payload: {name}/{stored}")
    native_hash = sha256(full_native).hexdigest()
    _fields(row, {"wire": full, "native_sha256": native_hash}, f"PBEPLA full artifact report differs: {name}")
    return (full, len(full_native), native_hash, qualities)


def _verify_replay(spec, row, policy, batch):
    name = spec["name"]
    wire, native_bytes, native_hash, quality_rows = batch
    _fields(row, {"name": name, "scope": policy["scope"], "same_bytes_as_batch": policy["expect_batch_payload_identity"],
                  "payload_sha256": native_hash, "wire": wire, "quality": quality_rows},
            f"PBEPLA replay output/quality differs from bounded batch: {name}")
    count, k = spec["count"], len(spec["requested_eps"])
    passes = policy["nonempty_passes_without_retry"] if count else policy["empty_passes"]
    payload = wire["payload_bytes"]
    # Frozen cases do not allow retries; a retry is a different accounting case.
    expected = {key: passes for key in ("native_passes", "rewind_calls", "eof_passes", "first_sink_after_pass")}
    expected.update(result=0, native_numerical_retries=policy["max_numerical_retries"], native_value_count=count,
                    source_bytes_read=8 * count * passes, sink_bytes=native_bytes,
                    native_buffer_slots=k * (wire["delay"] + 2) if count else 0, temp_bytes_read=3 * payload,
                    temp_bytes_written=payload, temp_peak_live_bytes=payload, temp_seeks=3 * k if count else 0,
                    temp_files_created=k if count else 0, temp_files_closed=k if count else 0)
    _fields(row.get("io"), expected, f"PBEPLA replay accounting differs: {name}")
    require(type(row["io"].get("sink_calls")) is int and row["io"]["sink_calls"] >= 1, f"PBEPLA replay did not write: {name}")


def _exact(observed, expected, label):
    require(canonical_bytes(observed) == canonical_bytes(expected), label)


def _reject(status):
    return {'exit_status':3,'plugin_status':status,'outputs_absent':True}


def _sha(data):
    return sha256(data).hexdigest()


def _bounded(out, path, low, high):
    file = local_file(out, path)
    require(low <= file.stat().st_size <= high, f'PBEPLA evidence extent differs: {path}')
    return file.read_bytes()


def _verify_bad_layers(spec, row, out, cap):
    n, k = spec['count'], len(spec['requested_eps'])
    frame = _bounded(out, spec['frame_paths'][-1], 1, cap)
    wire, _, native, _ = _parse_frame(frame,spec,k)
    schema = schema_bytes(spec['name'])
    bad_layer = 'pbepla_rr: requested layers exceed the stored layers'
    expected_native = {'zero_layers':bad_layer,'absent_layer':bad_layer}
    if n:
        expected_native['value_budget'] = 'pbepla_rr: value count exceeds the decode limit'
    bad = {'truncated_native':native[:-1],'zero_stored_layer':native[:7]+b'\0'+native[8:]}
    if wire['payload_bytes']:
        expected_native['later_crc_even_for_layer1'] = 'pbepla_rr: payload checksum mismatch'
        bad['payload_crc'] = native[:-1] + bytes([native[-1]^1])
    _exact(row.get('native_rejects'),expected_native,'PBEPLA native negative layer transcript differs')
    _exact(row.get('worker_rejects'),{
        key:{'sha256':_sha(OUTER.pack(MAGIC,10,n,len(schema),len(payload))+schema+payload),**_reject(5)}
        for key,payload in bad.items()},'PBEPLA worker corrupt frame transcript differs')


def _verify_input_rejections(policy, observed, weather, out, cap):
    boundary = []
    for side,spec in zip(('at','over'),policy['boundary'],strict=True):
        n, k = spec['count'], len(spec['requested_eps'])
        raw = boundary_source(n)
        frame = _bounded(out,spec['frame'],1,cap)
        wire, _, _, _ = _parse_frame(frame,spec,k)
        require(_sha(raw)==spec['input_sha256'] and n*k==policy['work_limit']+(k if side=='over' else 0),
                'PBEPLA budget fixture identity differs')
        row = {'name':spec['name'],'count':n,'value_layers':n*k,'source_sha256':_sha(raw),'frame_sha256':_sha(frame)}
        if side=='at':
            restored = _bounded(out,policy['restored'],8*n,8*n)
            error,q = quality(raw,restored)
            require(error <= Fraction(wire['eps'][-1]), 'PBEPLA work-limit restoration exceeds effective eps')
            row.update(encode={'plugin_status':0},decode={'plugin_status':0,**q})
        else:
            row.update(encode=_reject(7), decode=_reject(7))
        boundary.append(row)
    source = weather['input_sha256']
    _exact(observed, {'boundary':boundary,
            'options':[{'options':o,'source_sha256':source,**_reject(3)} for o in policy['options']],
            'dtype':{'dtype':policy['reject_dtype'],'source_sha256':source,**_reject(1)},
            'nonfinite':[{'u64':bits,'source_sha256':_sha(struct.pack('<Q',bits)),**_reject(2)}
                         for bits in policy['nonfinite_u64']]}, 'PBEPLA input/eps/budget rejection transcript differs')


def _verify_replay_failures(policy, transcript, spec, out, cap):
    n, k = spec['count'], len(spec['requested_eps'])
    frame = _bounded(out,spec['frame_paths'][-1],1,cap)
    wire, _, native, _ = _parse_frame(frame,spec,k)
    payload = wire['payload_bytes']
    header = wire['header_bytes']
    partial = _bounded(out,policy['partial'],header,header)
    require(payload > 0 and partial == native[:header], 'PBEPLA sink failure did not retain only the ambient full-frame header')
    modes = policy['fault_modes']
    require(isinstance(transcript,list) and len(transcript)==len(modes),'PBEPLA replay fault census differs')
    for mode,row in zip(modes,transcript,strict=True):
        common = dict(result=-1,native_passes=0,native_buffer_slots=0,native_value_count=0,native_numerical_retries=0)
        partial_ref = None
        # Failure stats are not success totals. Validate the callback and temp-file
        # counts, plus exactly what was committed to the output before rejection.
        if mode=='sink-fail':
            error = 'output sink failed'
            partial_ref = {'bytes':header,'sha256':_sha(partial),
                           'native_layer1_rejection':'pbepla_rr: payload length does not match the header'}
            passes = rewinds = first = 3
            files, writes, reads, seeks = k,payload,2*payload+wire['layer_bytes'][0],2*k+1
            sink_calls, sink_bytes, read_rows = 2,header,3*n
        else:
            first = reads = seeks = sink_calls = sink_bytes = 0
            if mode=='changed':
                error = 'pbepla_rr: source changed during replay'
                passes = rewinds = 2
                files,read_rows = k,2*n
                io = row.get('io') if isinstance(row,dict) else None
                writes = io.get('temp_bytes_written') if isinstance(io,dict) else None
                require(type(writes) is int and 0 < writes <= payload,'PBEPLA changed-source staging bound differs')
            elif mode=='no-rewind':
                error = 'source rewind failed'
                passes,rewinds,files,writes,read_rows = 1,2,k,0,n
            else:
                require(mode=='value-limit','unknown PBEPLA replay fault')
                error = 'source value limit'
                passes,rewinds,files,writes,read_rows = 0,1,0,0,n
        _exact(row, {'case':mode,'error':error,'source_sha256':spec['input_sha256'],'max_values':n-int(mode=='value-limit'),
                     'partial_artifact':partial_ref,'io':{**common,'eof_passes':passes,'rewind_calls':rewinds,
                         'source_bytes_read':8*read_rows,'first_sink_after_pass':first,'sink_calls':sink_calls,
                         'sink_bytes':sink_bytes,'temp_files_created':files,'temp_files_closed':files,
                         'temp_bytes_read':reads,'temp_bytes_written':writes,'temp_peak_live_bytes':writes,'temp_seeks':seeks}},
               f'PBEPLA replay failure transcript differs: {mode}')


def verify_pbepla_progressive(bundle: dict, build: dict, driver_sha256: str, out: Path,
                             *, sealed_paths: set[str] | None = None) -> None:
    require(bundle["bundle_id"] == content_id({k: v for k, v in bundle.items() if k != "bundle_id"}),
            "PBEPLA bundle identity differs")
    report_path = bundle["evidence_path"]
    refs = set(retained_paths(bundle))
    require(sealed_paths is None or refs | {report_path} <= sealed_paths, "PBEPLA retained evidence is not sealed")
    found = {p.name for p in out.glob("pbepla-*") if p.suffix in {".bmk", ".f64le", ".pbep"}}
    require(found == refs, "PBEPLA artifact denominator differs")
    doc = load_json(local_file(out, report_path))
    helper = build.get(REPLAY_HELPER)
    require(helper is not None, "PBEPLA missing replay executable binding")
    policy = bundle.get('failure_policy')
    _fields(doc, {"schema": f"bmk.m0-pbepla-control/{3 if policy else 2}", "config_id": bundle["config_id"],
                  "progressive_bundle_id": bundle["bundle_id"], "cases": [c["case_id"] for c in bundle["cases"]],
                  "formal_qualification": False, "formal_performance": False, "probe_hashes": [driver_sha256, helper]},
            "PBEPLA report is not bound to frozen cases and executables")
    verify_probe_build_lock(doc.get("build"), {k: v for k, v in build.items() if k != REPLAY_HELPER},
                            bundle["method"]["plugin"], dependency_count=1)
    progressive, replay = doc.get("batch_and_prefix"), doc.get("replay")
    inputs = bundle["inputs"]
    require(isinstance(progressive, list) and len(progressive) == len(inputs) and isinstance(replay, list) and
            len(replay) == sum(spec["replay"] for spec in inputs), "PBEPLA report denominator differs")
    it = iter(replay)
    cap = bundle['retention']['max_frame_bytes']
    for spec, row in zip(inputs, progressive, strict=True):
        batch = _verify_progressive(spec, row, out, cap)
        if spec["replay"]:
            _verify_replay(spec, next(it), bundle["replay_policy"], batch)
        if policy:
            _verify_bad_layers(spec,row,out,cap)
    if policy:
        specs = {r['name']:r for r in inputs}
        _verify_input_rejections(policy,doc.get('input_rejections'),specs['weather'],out,cap)
        _verify_replay_failures(policy,doc.get('replay_failures'),specs[policy['fault_input']],out,cap)
