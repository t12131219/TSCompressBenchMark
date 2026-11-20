"""Exercise the grouped fixed-rate array worker against the frozen controller."""
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
from tsbench.application.m3_zfp import array_evidence, array_windows
from tsbench.assets import load_json
from tsbench.corpus_ingress import read_batches
from tsbench.planner.zfp_execution import THREAD_ENV
from tsbench.recovery import plan_recovery, stage_recovery

HEADER, RATES, WINDOW = Struct('<4sIII'), Struct('<II'), Struct('<III')
FILES = {'etth1': True, 'bitcoin-dataset-without-missing-values-1': False}


def pick(root, entry, geometry):
    found = [bytearray() for _ in geometry]
    for b in read_batches(root, entry):
        block = np.frombuffer(b.values, dtype='V8').reshape(b.rows, entry['value_count'])
        for result, (column, lo, hi) in zip(found, geometry, strict=True):
            a, z = max(b.start, lo), min(b.start+b.rows, hi)
            if a < z:
                result.extend(block[a-b.start:z-b.start, column].tobytes())
    assert all(len(result) == (hi-lo)*8 for result, (_,lo,hi) in zip(found, geometry, strict=True))
    return found


def records(product, shape, geometry, tag):
    assert HEADER.unpack_from(product) == (tag, *shape)
    cursor = HEADER.size
    if tag == b'ZAG1':
        assert RATES.unpack_from(product, cursor) == (18, 32)
        cursor += RATES.size
    for column, lo, hi in geometry:
        n = hi-lo
        assert WINDOW.unpack_from(product, cursor) == (column,lo,n)
        cursor += WINDOW.size
        size = 16*((n+3)//4) if tag == b'ZAG1' else n*8
        yield product[cursor:cursor+size]
        cursor += size
    assert cursor == len(product)


def check(tool, source_plan):
    plan = load_json(source_plan)
    entries = _entry_map(ROOT, load_json(_file(ROOT, plan['definition']['plan'])))
    frozen = plan['build']['zfp_corpus']
    programs = {'grouped': _ref(ROOT, tool.resolve(strict=True)), 'legacy': frozen['executable']}
    spec = plan_recovery(ROOT, {}, (), tools={k: {n: r[n] for n in ('path', 'sha256')} for k,r in programs.items()},
                         libraries=[frozen['dependency']])
    with TemporaryDirectory(prefix='tsbench-zag-parity-') as directory:
        top = Path(directory)
        stage_recovery(ROOT, top, spec, directory='runtime')
        bundle = top / 'runtime'

        def invoke(arm, place, *args, rejects=None):
            cmd = [str(bundle / spec['loader']), '--inhibit-cache', '--library-path', str(bundle / 'lib'),
                   str(bundle / spec['tools'][arm]), *map(str, args)]
            p = run(cmd, cwd=place, env={'LC_ALL': 'C', **THREAD_ENV}, capture_output=True, text=True, timeout=30)
            if rejects:
                assert p.returncode == 2 and rejects in p.stderr, p
                return []
            assert p.returncode == 0 and not p.stderr, p
            return [json.loads(x) for x in p.stdout.splitlines()]

        outcomes = {}
        for ds, first_passes in FILES.items():
            entry = entries[ds]
            item, = (x for x in plan['work_items'] if x['dataset_id'] == ds and x['route'] == 'fixed-rate-array')
            cols, rows = entry['value_count'], entry['rows']
            ranges = list(array_windows(item['input']['array_contract'], cols, rows))[:2]
            raw = pick(ROOT, entry, ranges)
            shape = (len(ranges), cols, rows)
            place = top / ds
            place.mkdir()
            source, initial, after, values0, values1 = (place / n for n in ('input.zar', 'initial.zag', 'after.zag', 'before.zav', 'after.zav'))
            body = HEADER.pack(b'ZAR1', *shape) + b''.join(WINDOW.pack(c, a, z-a) + x for (c,a,z), x in zip(ranges, raw, strict=True))
            source.write_bytes(body)
            update = invoke('grouped', place, 'update', source, initial, after)
            source.unlink()
            reopen0 = invoke('grouped', place, 'reopen', initial, values0)
            reopen1 = invoke('grouped', place, 'reopen', after, values1)
            before_group, after_group = [list(records(p.read_bytes(), shape, ranges, b'ZAG1')) for p in (initial, after)]
            original_group, restored_group = [list(records(p.read_bytes(), shape, ranges, b'ZAV1')) for p in (values0, values1)]
            checks = []
            for i, ((col, lo, hi), expected) in enumerate(zip(ranges, raw, strict=True)):
                w = place / str(i)
                w.mkdir()
                p = w / 'source.bin'
                p.write_bytes(expected)
                record, = invoke('legacy', w, 'array-update', hi-lo, p)
                p.unlink()
                for frame, key, restored, observed in ((before_group[i], 'before', original_group[i], reopen0[i]),
                                                        (after_group[i], 'after', restored_group[i], reopen1[i])):
                    q = w / key
                    assert q.read_bytes() == frame
                    actual, = invoke('legacy', w, 'array-reopen', hi-lo, q)
                    assert actual == record == {k: observed[k] for k in record}
                    assert (w/'values').read_bytes() == restored
                assert record == {k: update[i][k] for k in record} and (update[i]['column'], update[i]['row_start']) == (col,lo)
                checks.append(array_evidence(expected, before_group[i], after_group[i], original_group[i], restored_group[i]))
            assert checks[0]['quality_passed'] == first_passes
            if not first_passes:
                assert checks[0]['before']['accepted'] and not checks[0]['after']['accepted']
            bad, reject = place / 'invalid.zag', place / 'rejected'
            encoded = initial.read_bytes()
            wrong_rate = encoded[:HEADER.size] + RATES.pack(18, 31) + encoded[HEADER.size+RATES.size:]
            for data, msg in ((encoded[:-1], 'truncated'), (encoded+b'\x00', 'trailing'), (wrong_rate, 'rate differs')):
                bad.write_bytes(data)
                invoke('grouped', place, 'reopen', bad, reject, rejects=msg)
                assert not reject.exists() and not reject.with_suffix('.partial').exists()
            outcomes[ds] = {'windows': len(ranges), 'initial_and_updated_archives_match': True,
                            'first_window_quality_passed': checks[0]['quality_passed']}
    return {'preflight': outcomes, 'files_only_isolation': False, 'timing_admitted': False}


if __name__ == '__main__':
    print(json.dumps(check(*map(Path, sys.argv[1:])), sort_keys=True))
