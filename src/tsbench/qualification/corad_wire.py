"""Pure-Python reconstruction of bounded, development-scope CRD1 payloads."""
import math
import struct

from ..assets import ContractError, require
from ..planner.corad_deployment import NATIVE as HEADER


def interpret(frame: bytes):
    """Return recovered bytes, independently parsed byte counts and embedded model arrays."""
    try:
        return _interpret(frame)
    except (struct.error, OverflowError) as exc:
        raise ContractError('truncated or invalid CRD1 fields') from exc


def _interpret(frame):
    magic, rows, cols, width, atoms, nzmax, threshold, total = HEADER.unpack_from(frame)
    require(magic == b'CRD1' and total == len(frame) and 0 < cols <= 64 and rows * cols <= 16384 and
            1 <= width <= 128 and 1 <= atoms <= 512 and 0 < nzmax <= min(32,width,atoms) and -1 <= threshold <= 1,
            'invalid CRD1 descriptor')
    count = atoms * width
    flat = struct.unpack_from(f'<{count+2*cols}d',frame,HEADER.size)
    mean, scale = flat[count::2], flat[count+1::2]
    require(all(map(math.isfinite,flat)) and all(v > 0 for v in scale), 'invalid CRD1 dictionary or statistics')
    cursor = model_end = HEADER.size+8*len(flat)
    out = [[] for _ in range(cols)]
    coded, references, first_reference = 0, 0, None
    for _ in range(rows//width):
        z, refs = [], []
        for j in range(cols):
            n, = struct.unpack_from('<H',frame,cursor)
            cursor += 2
            values, ref = [0.]*width, None
            if n == 65535:
                ref, = struct.unpack_from('<H',frame,cursor)
                require(ref < cols and ref != j,'invalid CRD1 reference')
                first_reference = first_reference or (cursor,j)
                cursor += 2
                references += 1
            else:
                require(n <= nzmax,'invalid CRD1 coefficient count')
                last = -1
                for _ in range(n):
                    atom, coefficient = struct.unpack_from('<Hd',frame,cursor)
                    require(last < atom < atoms and math.isfinite(coefficient) and coefficient != 0,'invalid CRD1 coefficient')
                    last, cursor = atom, cursor+10
                    for k in range(width):
                        values[k] += coefficient*flat[atom*width+k]
                coded += 1
            z.append(values)
            refs.append(ref)
        for j,ref in enumerate(refs):
            require(ref is None or refs[ref] is None,'chained CRD1 reference')
            out[j].extend(v*scale[j]+mean[j] for v in z[j if ref is None else ref])
    sparse_end = cursor
    tail = rows % width
    for col in out:
        col.extend(struct.unpack_from(f'<{tail}d',frame,cursor))
        cursor += tail*8
    require(cursor == len(frame) and all(len(c) == rows and all(map(math.isfinite,c)) for c in out),
            'CRD1 reconstructed length or finiteness differs')
    raw = b''.join(struct.pack(f'<{rows}d',*column) for column in out)
    return raw, {'rows':rows,'columns':cols,'embedded_model_bytes':model_end-HEADER.size,'header_bytes':HEADER.size,
                 'tricklet_record_bytes':sparse_end-model_end,'tail_bytes':cursor-sparse_end,'sparse_records':coded,
                 'references':references,'first_reference':first_reference,'mean':mean,'scale':scale}, frame[HEADER.size:model_end]


def quality(original, restored, columns):
    require(len(original) == len(restored) == len(columns) and bool(columns), 'CORAD metric column count differs')
    rows = len(original[0])//8
    require(all(len(a)==len(b)==rows*8 for a,b in zip(original,restored,strict=True)), 'CORAD metric row count differs')
    if not rows:
        return []
    out = []
    for name, src, dst in zip(columns,original,restored,strict=True):
        errors = [y-x for (x,),(y,) in zip(struct.iter_unpack('<d',src),struct.iter_unpack('<d',dst),strict=True)]
        maximum = max(map(abs,errors))
        try:
            rmse = math.sqrt(math.fsum(e*e for e in errors)/rows)
        except OverflowError as exc:
            raise ContractError('CORAD original-domain metric overflow') from exc
        require(math.isfinite(maximum) and math.isfinite(rmse), 'CORAD original-domain metric not finite')
        out.append({'column':name,'max_abs_error':maximum,'rmse':rmse})
    return out
