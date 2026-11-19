"""Bounded ALN1 layout, raw bytes and exception sidecar inspection (not general decode)."""
from ..assets import ContractError, require
from ..planner.alp import V, RG, SPECIAL, SPECIAL_POS


class Reader:
    """Independent accounting parser for locally generated ALN1 artifacts."""
    def __init__(self, raw):
        self.raw,self.at = raw,0

    def take(self, n):
        left,self.at = self.at,self.at+n
        require(self.at <= len(self.raw), 'invalid or mismatched ALN1 structure')
        return self.raw[left:self.at]

    def word(self, n=1):
        return int.from_bytes(self.take(n),'little')

    def var(self):
        u = 0
        for i in range(10):
            b = self.word()
            require(i != 9 or b <= 1, 'ALN1 varint overflows uint64')
            u |= (b&127) << (7*i)
            if not (b&128):
                require(i == 0 or b, 'invalid or mismatched ALN1 structure')
                return u
        raise ContractError('unterminated length')


def analyze(payload, original, width, *, positions=None, count=None):
    r = Reader(payload)
    require(r.take(4) == b'ALN1' and r.word() == width, 'invalid or mismatched ALN1 structure')
    item = width//8
    n = r.var()
    require((original is not None and n*item == len(original)) or
            (original is None and type(count) is int and n == count), 'invalid or mismatched ALN1 structure')
    totals = dict(alp_groups=0,rd_groups=0,raw_groups=0,coded_vectors=0,raw_vectors=0)
    schemes, branch_counts, special_restored_from_sidecar = [], {'decimal':0,'rd':0,'raw':0}, []
    group_rows = []
    for start in range(0,n,RG):
        rows = min(n-start,RG)
        group_rows.append(rows)
        scheme = r.word()
        require(scheme in (0,1,2), 'invalid or mismatched ALN1 structure')
        schemes.append(('raw','decimal','rd')[scheme])
        if scheme == 0:
            totals['raw_groups'] += 1
            add = (rows+V-1)//V
            totals['raw_vectors'] += add
            branch_counts['raw'] += add
            raw = r.take(rows*item)
            require(original is None or raw == original[start*item:(start+rows)*item], 'invalid or mismatched ALN1 structure')
            continue
        totals['alp_groups' if scheme == 1 else 'rd_groups'] += 1
        if scheme == 2:
            right,left,k = (r.word() for _ in range(3))
            require(width-16 <= right < width and 1 <= left <= 3 and 1 <= k <= 1<<left, 'invalid or mismatched ALN1 structure')
            dictionary = [r.word(2) for _ in range(k)]
            require(all(x < 1<<(width-right) for x in dictionary), 'invalid or mismatched ALN1 structure')
        for i in range(start,start+rows,V):
            size = min(V,start+rows-i)
            kind = r.word()
            require(kind in (0,1), 'invalid or mismatched ALN1 structure')
            if not kind:
                totals['raw_vectors'] += 1
                branch_counts['raw'] += 1
                raw = r.take(size*item)
                require(original is None or raw == original[i*item:(i+size)*item], 'invalid or mismatched ALN1 structure')
                continue
            totals['coded_vectors'] += 1
            branch_counts['decimal' if scheme == 1 else 'rd'] += 1
            if scheme == 1:
                bits,exp,fac = (r.word() for _ in range(3))
                require(bits <= width and fac <= exp, 'invalid or mismatched ALN1 structure')
                e = r.var()
                r.take(item+128*bits)  # packed body and frame of reference
            else:
                e = r.var()
                r.take(128*(right+left))
            require(e <= V, 'invalid or mismatched ALN1 structure')
            prev = -1
            for _ in range(e):
                value = r.word(item if scheme == 1 else 2)
                if positions is not None:
                    positions.append((scheme, r.at))
                pos = r.word(2)
                require(prev < pos < V, 'invalid or mismatched ALN1 structure')
                prev = pos
                if scheme == 1 and pos < size:
                    off = (i+pos)*item
                    require(original is None or value == int.from_bytes(original[off:off+item],'little'),
                            'invalid or mismatched ALN1 structure')
                    if i+pos in SPECIAL_POS and value in SPECIAL[width]:
                        special_restored_from_sidecar.append({'index':i+pos,'bits':hex(value)})
    require(r.at == len(payload), 'invalid or mismatched ALN1 structure')
    require(sum(branch_counts.values()) == (n+V-1)//V, 'invalid or mismatched ALN1 structure')
    return {'rowgroup_kinds':schemes,'rowgroup_rows':group_rows,'coded_decimal_vectors':branch_counts['decimal'],
            'coded_rd_vectors':branch_counts['rd'],'special_exception_bits':special_restored_from_sidecar,**totals}



def corrupt_positions(payload, positions):
    """Target real decimal exception records, preserving envelope and payload length."""
    decimal = [pos for scheme, pos in positions if scheme == 1]
    require(len(decimal) >= 2, 'missing ALN1 decimal sidecar to corrupt')
    a, b = decimal[:2]  # mixed fixture has exactly one coded decimal vector
    return {
        'exception_out_of_range': (a, payload[:a] + V.to_bytes(2,'little') + payload[a+2:]),
        'duplicate_exception_position': (b, payload[:b] + payload[a:a+2] + payload[b+2:]),
    }
