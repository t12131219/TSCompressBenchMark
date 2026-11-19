"""Bounded dense NPY v1/v2 reader: two explicit, homogeneous arrays, no pickle."""
import ast
from tsbench.assets import ContractError, require
from tsbench.ingress import Batch


def _array(buf, dtype, shape, fortran):
    require(buf[:6]==b'\x93NUMPY' and buf[6:8] in (b'\x01\0',b'\x02\0'), 'unsupported NPY magic or version')
    start = 10 if buf[6]==1 else 12
    size = int.from_bytes(buf[8:start],'little')
    require(1<=size<=4096 and start+size<=len(buf), 'invalid bounded NPY header size')
    header = buf[start:start+size]
    require(header.endswith(b'\n'), 'NPY header is not newline terminated')
    try:
        node = ast.parse(header.decode('ascii').strip(),mode='eval').body
        require(isinstance(node,ast.Dict) and len(node.keys)==3 and
                all(isinstance(k,ast.Constant) and type(k.value) is str for k in node.keys) and
                {k.value for k in node.keys}=={'descr','fortran_order','shape'}, 'invalid NPY header keys')
        actual = ast.literal_eval(node)
    except (SyntaxError,UnicodeError,ValueError,TypeError,RecursionError) as exc:
        raise ContractError('invalid NPY header') from exc
    require(actual['descr']==dtype and actual['fortran_order'] is fortran and type(actual['shape']) is tuple and
            all(type(n) is int for n in actual['shape']) and actual['shape']==shape,
            'NPY dtype, shape or order differs; object/structured/complex arrays unsupported')
    payload = memoryview(buf)[start+size:]
    count = shape[0]*(shape[1] if len(shape)==2 else 1)
    require(len(payload)==count*8, 'truncated or trailing NPY payload')
    return payload


def probe_source(assets, spec, options):
    require(list(assets)==['timestamp','values'], 'NPY requires ordered timestamp and values assets')
    rows, width = spec['rows'], len(spec['values'])
    return (_array(assets['timestamp'],options['timestamp_dtype'],(rows,),False),
            _array(assets['values'],options['value_dtype'],(rows,width),options['value_order']=='F'))


def resolve_schema(handle, spec, options):
    return spec


def read_batches(handle, spec, options, batch_rows):
    ticks, vals = handle
    rows,width = spec['rows'],len(spec['values'])
    def word(buf, index, dtype):
        b = bytes(buf[8*index:8*(index+1)])
        return b[::-1] if dtype.startswith('>') else b
    for start in range(0,rows,batch_rows):
        end = min(rows,start+batch_rows)
        t = b''.join(word(ticks,r,options['timestamp_dtype']) for r in range(start,end))
        f = options['value_order']=='F'
        v = tuple(b''.join(word(vals,c*rows+r if f else r*width+c,options['value_dtype']) for r in range(start,end))
                  for c in range(width))
        yield Batch(end-start,(t,*v))


def close(handle):
    for view in handle:
        view.release()
