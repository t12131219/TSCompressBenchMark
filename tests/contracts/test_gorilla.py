"""Independent Gorilla verifier accepts expected wire tokens and refuses dishonest evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import ContractError  # noqa: E402
from tsbench.planner.gorilla import SNAPSHOT, sha  # noqa: E402
from tsbench.qualification.gorilla import _verify_work, decode_chunk  # noqa: E402


def chunk(rows, bits):
    padded = bits + '0' * (-len(bits) % 8)
    return rows.to_bytes(2, 'big') + bytes(int(padded[i:i+8], 2) for i in range(0, len(padded), 8))


class GorillaWireTests(unittest.TestCase):
    def test_work_replay_rejects_scan_copy_and_backward_claims(self):
        wire = chunk(2, f'{0:08b}{0:064b}{10:08b}0')
        empty = b'\0\0'
        cases = [{'name':'valid','source':SNAPSHOT,'mode':'valid'},
                 {'name':'bad','source':SNAPSHOT,'mode':'trailing'},
                 {'name':'empty','source':'empty','mode':'valid'}]
        policy = {'resume':cases,'iterator':['time'],'observer':'elf-call-interposition-v1'}
        native = {'time':wire,'empty':empty}
        scripts = {'time':[['seek',5,0,[10,0]],['seek',0,0,[10,0]],['seek',11,0,None],['next',None,0,None]]}
        diagnostic = 'a'*64
        def work(calls, rows, copies=0, size=0):
            return dict(next_calls=calls,rows_scanned=rows,source_copy_calls=copies,source_bytes_copied=size)
        report = {'observer':policy['observer'],'executable_sha256':diagnostic,'resume':{
            name:{'source_sha256':sha(blob),'observed':{'status':status,'source_bytes':len(blob)+(status!=0),
                'same_snapshot_after_source_overwrite':status==0,**counts}}
            for name,blob,status,counts in [('valid',wire,0,work(3,2,1,len(wire))),('bad',wire,5,work(3,2)),
                                            ('empty',empty,0,work(1,0))]},
            'iterator':{'time':{'source_sha256':sha(wire),'observed':[
                {'status':0,'pair':[10,0],**work(2,2)},{'status':0,'pair':[10,0],**work(0,0)},
                {'status':0,'pair':None,**work(1,0)},{'status':0,'pair':None,**work(1,0)}]}}}
        _verify_work(policy,report,diagnostic,native,wire,scripts)
        for path, value in (
            (('resume','valid','observed','source_bytes_copied'),0),
            (('resume','bad','observed','source_copy_calls'),1),
            (('resume','empty','observed','rows_scanned'),1),
            (('iterator','time','observed',0,'rows_scanned'),1),
            (('iterator','time','observed',1,'pair'),[0,0]),
            (('iterator','time','observed',1,'next_calls'),1),
            (('iterator','time','observed',2,'next_calls'),0),
            (('executable_sha256',),'b'*64),
        ):
            bad = deepcopy(report)
            node = bad
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value
            with self.subTest(path=path), self.assertRaisesRegex(ContractError,'scan/copy'):
                _verify_work(policy,bad,diagnostic,native,wire,scripts)

    def test_timestamp_modulo_nonstandard_sign_edge_and_window_reuse(self):
        # T0 = -1, V0 = 0. D1=0 with a one-bit window at bit zero.
        # dd2 = +8192 at the asymmetric sign boundary; dd3=-1, no V change.
        # dd4 = 2^63 set by the 64-bit escape, then repeat value window.
        op0 = f'{1:08b}{0:064b}'
        op1 = f'{0:08b}11{31:05b}{33:06b}{1:033b}'
        op2 = f'10{8192:014b}10{1:033b}'
        op3 = f'10{16383:014b}0'
        op4 = f'1111{2**63:064b}10{1:033b}'
        bits = op0 + op1 + op2 + op3 + op4
        wire = chunk(5, bits)
        pairs, encoded_bits = decode_chunk(wire, 5)
        self.assertEqual(pairs, [(-1, 0), (-1, 1), (8191, 0), (16382, 0), (-2**63 + 24573, 1)])
        self.assertEqual(encoded_bits, 16 + len(bits))

    def test_native_role_projection_preserves_token_boundaries(self):
        # T and V tokens cross native byte boundaries in both directions.
        t = [f'{1:08b}', f'{0:08b}', f'10{8192:014b}', f'10{16383:014b}']
        v = [f'{0:064b}', f'11{31:05b}{33:06b}{1:033b}', f'10{1:033b}', '0']
        native = chunk(4, ''.join(a + b for a, b in zip(t, v, strict=True)))
        projected = {}
        pairs, bits = decode_chunk(native, 4, projection=projected)
        self.assertEqual(pairs, [(-1, 0), (-1, 1), (8191, 0), (16382, 0)])
        self.assertEqual(projected, {'timestamp': (chunk(4, ''.join(t)), sum(map(len, t))),
                                     'value': (chunk(4, ''.join(v)), sum(map(len, v)))})
        self.assertEqual(bits - 16, sum(count for _, count in projected.values()))

    def test_empty_truncated_invalid_window_varint_and_padding(self):
        self.assertEqual(decode_chunk(b'\0\0', 0), ([], 16))
        base = f'{0:08b}{0:064b}{0:08b}'
        invalid = [
            (b'\0\0\0', 0, 'count or bound'),
            (b'\0\x01\0', 1, 'truncated'),
            (chunk(2, base + '10'), 2, 'before definition'),
            (chunk(2, base + '11' + f'{31:05b}{0:06b}'), 2, 'value window'),
            (chunk(1, '10000000' * 10), 1, 'overflowing'),
            (chunk(2, base + '01'), 2, 'padding'),
        ]
        for wire, rows, reason in invalid:
            with self.subTest(reason=reason), self.assertRaisesRegex(ContractError, reason):
                decode_chunk(wire, rows)
