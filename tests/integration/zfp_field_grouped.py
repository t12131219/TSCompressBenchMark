"""Check whole-column grouped ZFP against the r40 native field controller."""
import json
from pathlib import Path
from struct import Struct
from subprocess import run
import sys
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_lzbench_timing import _file, _ref
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.assets import load_json
from tsbench.corpus_ingress import read_batches
from tsbench.planner.zfp_execution import THREAD_ENV
from tsbench.recovery import plan_recovery, stage_recovery

HEAD, SIZE = Struct('<4sII'), Struct('<I')
PROFILES = ('serial', 'omp1', 'omp2')


def check(tool, source_plan):
    source = load_json(source_plan)
    entry = _entry_map(ROOT, load_json(_file(ROOT, source['definition']['plan'])))['etth1']
    frozen = source['build']['zfp_corpus']
    refs = {'legacy': frozen['executable'], 'grouped': _ref(ROOT, tool.resolve(strict=True))}
    spec = plan_recovery(ROOT, {}, (), tools={k: {x: v[x] for x in ('path', 'sha256')} for k, v in refs.items()},
                         libraries=[frozen['dependency']])
    with TemporaryDirectory(prefix='tsbench-zfg-parity-') as tmp:
        work = Path(tmp)
        stage_recovery(ROOT, work, spec, directory='runtime')
        bundle = work / 'runtime'

        def invoke(arm, place, *args, reject=None):
            cmd = [str(bundle / spec['loader']), '--inhibit-cache', '--library-path', str(bundle / 'lib'),
                   str(bundle / spec['tools'][arm]), *map(str, args)]
            p = run(cmd, cwd=place, env={'LC_ALL': 'C', **THREAD_ENV}, capture_output=True, text=True, timeout=30)
            if reject:
                assert p.returncode == 2 and reject in p.stderr, p
                return
            assert p.returncode == 0 and not p.stderr, p
            return [json.loads(x) for x in p.stdout.splitlines()]

        values = [bytearray(), bytearray()]
        for b in read_batches(ROOT, entry):
            matrix = np.frombuffer(b.values, dtype='V8').reshape(b.rows, entry['value_count'])
            for i, value in enumerate(values):
                value.extend(matrix[:, i].tobytes())
        n = entry['rows']
        assert all(len(column) == 8*n for column in values)
        raw = work / 'column-major.bin'
        original = b''.join(values)
        raw.write_bytes(original)
        frames = {}
        for profile in PROFILES:
            place = work / profile
            place.mkdir()
            archive = place / 'field.zfg'
            grouped = invoke('grouped', place, 'encode', profile, 2, n, raw, archive)
            blob = archive.read_bytes()
            assert HEAD.unpack_from(blob) == (b'ZFG1', len(values), n)
            assert len(grouped) == len(values)
            cursor = HEAD.size
            for i, col in enumerate(values):
                standalone = place / 'input'
                standalone.write_bytes(col)
                old, = invoke('legacy', place, 'field-encode', n, standalone, profile)
                standalone.unlink()
                size, = SIZE.unpack_from(blob, cursor)
                cursor += SIZE.size
                section = blob[cursor:cursor+size]
                cursor += size
                assert section == (place / 'frame').read_bytes()
                (place / 'frame').unlink()
                obs = grouped[i]
                assert obs['column'] == i and obs['call_wall_ns'] > 0 and obs['call_cpu_ns'] >= 0
                assert {k: obs[k] for k in old} == old
            assert cursor == len(blob)
            frames[profile] = (place, archive)
        raw.unlink()
        for place, archive in frames.values():
            output = place / 'restore'
            observations = invoke('grouped', place, 'decode', 'serial', len(values), n, archive, output)
            assert output.read_bytes() == original and len(observations) == 2
            assert all(x['execution'] == x['decode_execution'] == 0 and x['configured_threads'] == 1 for x in observations)
        place, archive = frames['serial']
        bad, target = place / 'broken.zfg', place / 'rejected'
        frame = archive.read_bytes()
        for altered, reason in ((frame[:-1], 'truncated'), (frame+b'\x00', 'trailing')):
            bad.write_bytes(altered)
            invoke('grouped', place, 'decode', 'serial', len(values), n, bad, target, reject=reason)
            assert not target.exists() and not target.with_suffix('.partial').exists()
    return {'dataset_id': entry['id'], 'complete_columns': len(values), 'per_column_rows': n,
            'profiles': list(PROFILES), 'native_frames_checked': len(values)*len(PROFILES),
            'files_only_isolation': False, 'timing_admitted': False}


if __name__ == '__main__':
    print(json.dumps(check(*map(Path, sys.argv[1:])), sort_keys=True))
