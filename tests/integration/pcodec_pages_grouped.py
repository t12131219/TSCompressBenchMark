"""Check PGF1 grouped I/O against both frozen single-group pcodec controls.

Usage: run with tsbench Python and the standalone grouped executable. This
functional check uses a staged ELF closure, not the files-only timing sandbox.
"""
import json
from pathlib import Path
from struct import Struct, pack
from subprocess import run
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_pcodec_page_timing import _semantic
from tsbench.application.m3_lzbench_timing import _ref
from tsbench.assets import load_json
from tsbench.recovery import plan_recovery, stage_recovery

HEAD = Struct('<8sII')
LENGTH = Struct('<I')
RAW, FRAME = b'PGF1RAW\x00', b'PGF1PAGE'
ROWS, COLS = 65537, 2


def archive(magic, records):
    return HEAD.pack(magic, COLS, ROWS) + b''.join(LENGTH.pack(len(r)) + r for r in records)


def check(tool):
    plan = load_json(ROOT / 'results/m3-real-r40-20261120/plan.json')
    frozen = plan['build']['pcodec_pages']
    refs = {'legacy': frozen['executable'], 'grouped': _ref(ROOT, tool.resolve(strict=True))}
    spec = plan_recovery(ROOT, {}, (), tools={k: {n: v[n] for n in ('path', 'sha256')} for k, v in refs.items()},
                         libraries=[frozen['dependency']])
    with TemporaryDirectory(prefix='tsbench-pcodec-grouped-fixture-') as tmp:
        work = Path(tmp)
        stage_recovery(ROOT, work, spec, directory='runtime')
        bundle = work / 'runtime'

        def invoke(program, op, lane, *args, success=True):
            child = run([str(bundle / spec['loader']), '--inhibit-cache', '--library-path', str(bundle / 'lib'),
                         str(bundle / spec['tools'][program]), op, lane, *map(str, args)],
                        capture_output=True, cwd=work, env={}, timeout=30)
            assert (child.returncode == 0) is success, (child.returncode, child.stderr)
            if success:
                assert not child.stderr
            return [json.loads(line) for line in child.stdout.splitlines()]

        # Two complete groups and two one-row tails. One full group uses zero
        # native payload pages, the other changes between consecutive rows.
        raw = [pack('<65536d', *([1.0] * 65536)), pack('<d', -0.0),
               pack('<65536d', *(j / 16 for j in range(65536))), pack('<d', -42.25)]
        (work / 'source.pgf').write_bytes(archive(RAW, raw))
        for lane in ('source', 'native'):
            frames, enc, dec = [], [], []
            for index, piece in enumerate(raw):
                source, wire, restored = (work / f'{lane}-{index}.{kind}' for kind in ('raw', 'frame', 'restored'))
                source.write_bytes(piece)
                one, = invoke('legacy', 'corpus-encode', lane, source.name, wire.name)
                frames.append(wire.read_bytes())
                enc.append(_semantic(one))
                one, = invoke('legacy', 'corpus-decode', lane, wire.name, restored.name)
                assert restored.read_bytes() == piece
                dec.append(_semantic(one))
            rows = invoke('grouped', 'encode', lane, COLS, ROWS, 'source.pgf', 'encoded.pgf')
            assert [_semantic(r) for r in rows] == enc
            assert (work / 'encoded.pgf').read_bytes() == archive(FRAME, frames)
            rows = invoke('grouped', 'decode', lane, COLS, ROWS, 'encoded.pgf', 'restored.pgf')
            assert [_semantic(r) for r in rows] == dec
            assert (work / 'restored.pgf').read_bytes() == archive(RAW, raw)
            for invalid in ((work / 'encoded.pgf').read_bytes()[:-1], (work / 'encoded.pgf').read_bytes() + b'x'):
                (work / 'invalid.pgf').write_bytes(invalid)
                invoke('grouped', 'decode', lane, COLS, ROWS, 'invalid.pgf', 'rejected.pgf', success=False)
    return {'lanes': ['source', 'native'], 'groups_per_lane': len(raw), 'rows': ROWS, 'columns': COLS,
            'byte_parity': True, 'bitwise_recovery': True, 'reject_short_and_trailing': True, 'timing_admitted': False}


if __name__ == '__main__':
    print(json.dumps(check(Path(sys.argv[1])), sort_keys=True))
