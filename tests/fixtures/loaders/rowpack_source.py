"""Test-only source adapter: one header followed by dense row-major 64-bit words."""
from tsbench.assets import require
from tsbench.ingress import Batch, names

MAGIC = b'TSBROW01'


def probe_source(assets, spec, options):
    require(set(assets)=={'records'}, 'rowpack requires the records asset')
    data = assets['records']
    require(data.startswith(MAGIC), 'rowpack source format version differs')
    payload = memoryview(data)[len(MAGIC):]
    require(payload.nbytes==8*spec['rows']*len(names(spec)), 'rowpack byte count differs from schema')
    return payload


def resolve_schema(handle, spec, options):
    return spec


def read_batches(handle, spec, options, batch_rows):
    cols = len(names(spec))
    big = options.get('byte_order','little')=='big'
    for low in range(0,spec['rows'],batch_rows):
        count = min(batch_rows,spec['rows']-low)
        out = [bytearray() for _ in range(cols)]
        for row in range(low,low+count):
            for i,col in enumerate(out):
                start = 8*(row*cols+i)
                word = bytes(handle[start:start+8])
                col.extend(word[::-1] if big else word)
        yield Batch(count,tuple(bytes(c) for c in out))


def close(handle):
    handle.release()
