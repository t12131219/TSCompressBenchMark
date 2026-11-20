"""Functional parity for grouped Zstd dictionary I/O (no timing evidence)."""
import json
from hashlib import sha256
from pathlib import Path
from struct import Struct
from subprocess import run
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_lzbench_timing import _file, _ref
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.m3_zstd_dictionary import _stage
from tsbench.application.m3_zstd_dictionary_grouped import inspect_archive, stage_inputs
from tsbench.assets import digest, load_json
from tsbench.planner.m3_zstd_dictionary import LIMIT
from tsbench.qualification.lzbench import zstd_frame
from tsbench.recovery import plan_recovery, stage_recovery

HEAD, FRAME = Struct('<4sI'), Struct('<II')
FILES = ('etth1', 'dominick-dataset-1121')


def check(tool, plan_file, source_run):
    plan = load_json(plan_file)
    ledger, _ = full_run_source(plan, source_run)
    entries = _entry_map(ROOT, load_json(_file(ROOT, plan['definition']['plan'])))
    wanted = {row['dataset_id']: (row, item) for row, item in full_run_rows(plan, ledger)
              if row.get('entry_kind') is None and row['route'] == 'zstd-dictionary' and row['dataset_id'] in FILES}
    assert wanted.keys() == set(FILES)
    frozen = plan['build']['zstd_dictionary']
    tools = {'legacy': frozen['executable'], 'grouped': _ref(ROOT, tool.resolve(strict=True))}
    spec = plan_recovery(ROOT, {}, (), tools={k: {f: v[f] for f in ('path', 'sha256')} for k, v in tools.items()},
                         libraries=[frozen['dependency']])
    results = {}
    with TemporaryDirectory(prefix='tsbench-zstd-dict-grouped-') as tmp:
        base = Path(tmp)
        stage_recovery(ROOT, base, spec, directory='runtime')
        runtime = base / 'runtime'

        def call(arm, cwd, *args, reject=None):
            cmd = [str(runtime / spec['loader']), '--inhibit-cache', '--library-path', str(runtime / 'lib'),
                   str(runtime / spec['tools'][arm]), *map(str, args)]
            proc = run(cmd, capture_output=True, cwd=cwd, env={'LC_ALL': 'C'}, timeout=30, text=True)
            if reject:
                assert proc.returncode == 2 and not proc.stdout and reject in proc.stderr, proc
            else:
                assert proc.returncode == 0 and not proc.stderr, proc
                return json.loads(proc.stdout)

        for ds in FILES:
            row, item = wanted[ds]
            assert row['status'] == 'verified'
            e = row['evidence']
            work = base / ds
            work.mkdir()
            samples, train_hash, held, held_proof = _stage(ROOT, item, entries[ds], work)
            assert not set(samples) & {held}
            assert (train_hash, held_proof) == (e['train_prefix_sha256'], e['holdout'])
            cap = item['input']['training']['dictionary_capacity_bytes']
            each = e['sample_geometry']['bytes_each']
            data = b''.join(p.read_bytes() for p in samples)
            staged = stage_inputs(ROOT, item, entries[ds], work, e)
            prefix = staged['train']
            assert prefix.read_bytes() == data and staged['holdout'].read_bytes() == held.read_bytes()
            old, new = work / 'old.zdict', work / 'new.zdict'
            call('legacy', work, 'train', cap, old, *samples)
            observed = call('grouped', work, 'train', prefix, new, cap, each, len(samples))
            assert (observed['samples'], observed['sample_bytes'], observed['input_bytes']) == (len(samples), each, len(data))
            assert observed['dictionary_id'] == e['dictionary']['id']
            assert new.read_bytes() == old.read_bytes() == _file(source_run, e['dictionary']).read_bytes()
            grouped = work / 'grouped.zdg'
            raw = held.read_bytes()
            enc = call('grouped', work, 'encode', staged['holdout'], grouped, new, len(raw))
            proof = inspect_archive(grouped, e)
            assert proof['bytes'] == grouped.stat().st_size and proof['sha256'] == digest(grouped)
            assert proof['recovery_bytes'] == proof['bytes'] + new.stat().st_size
            blob = grouped.read_bytes()
            frames = e['frames']
            assert HEAD.unpack_from(blob) == (b'ZDG1', len(frames))
            assert enc['native_frame_bytes'] == e['verified_frame_bytes']
            assert enc['wrapper_bytes'] == HEAD.size + FRAME.size * len(frames)
            assert len(blob) + new.stat().st_size == e['verified_frame_bytes_plus_shared_dictionary_once'] + enc['wrapper_bytes']
            cursor = HEAD.size
            for f in frames:
                lo, hi = f['holdout_byte_range']
                n, size = FRAME.unpack_from(blob, cursor)
                cursor += FRAME.size
                assert 0 < n <= LIMIT and (n, size) == (hi-lo, f['bytes'])
                payload = blob[cursor:cursor+size]
                cursor += size
                piece, ow, ob = (work / name for name in ('slice.bin', 'frame.zst', 'roundtrip.bin'))
                piece.write_bytes(raw[lo:hi])
                call('legacy', work, 'roundtrip', 'zstd', 'frame', 3, 307, 521, LIMIT, 'reuse', 1, new, piece, ow, ob, n)
                assert payload == ow.read_bytes() and ob.read_bytes() == raw[lo:hi]
                assert sha256(payload).hexdigest() == f['sha256'] and zstd_frame(payload)['dictionary_id'] == f['dictionary_id']
            assert cursor == len(blob)
            held.unlink()
            staged['holdout'].unlink()
            (work / 'slice.bin').unlink()
            (work / 'roundtrip.bin').unlink()
            restore = work / 'restored.bin'
            dec = call('grouped', work, 'decode', grouped, restore, new, len(raw))
            assert digest(restore) == held_proof['sha256'] and restore.read_bytes() == raw
            for key in ('logical_bytes', 'native_frames', 'native_frame_bytes', 'wrapper_bytes', 'dictionary_id', 'dictionary_bytes'):
                assert dec[key] == enc[key]
            # Neither a malformed wrapper nor the wrong training artifact may publish a partial restore.
            neg, broken = work / 'rejected.bin', work / 'malformed.zdg'
            for variant, reason in ((blob[:-1], 'short'), (blob + b'\x00', 'trailing')):
                broken.write_bytes(variant)
                call('grouped', work, 'decode', broken, neg, new, len(raw), reject=reason)
                assert not neg.exists() and not neg.with_suffix('.bin.partial').exists()
            wrong = work / 'wrong.zdict'
            d = new.read_bytes()
            wrong.write_bytes(d[:4] + (observed['dictionary_id'] ^ 1).to_bytes(4, 'little') + d[8:])
            call('grouped', work, 'decode', grouped, neg, wrong, len(raw), reject='Dictionary mismatch')
            call('grouped', work, 'decode', grouped, neg, work / 'missing.zdict', len(raw), reject='file size')
            assert not neg.exists() and not neg.with_suffix('.bin.partial').exists()
            prefix.write_bytes(data + b'\x00')
            call('grouped', work, 'train', prefix, neg, cap, each, len(samples), reject='trailing')
            assert not neg.exists()
            results[ds] = {'tier': e['tier'], 'samples': len(samples), 'frames': len(frames), 'negative_controls': 5}
    return {'functional_parity': results, 'files_only_isolation': False, 'timing_admitted': False}


if __name__ == '__main__':
    print(json.dumps(check(*map(Path, sys.argv[1:])), sort_keys=True))
