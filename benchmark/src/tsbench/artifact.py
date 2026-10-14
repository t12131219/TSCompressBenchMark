"""A bounded, self-describing wire format; no pickle or encoder state."""
from dataclasses import dataclass
import hashlib
import json
import math
import struct
import numpy as np
from .data import canonical_json, DTYPES

PREFIX = struct.Struct('<8sHI')
MAGIC = b'TSB4OBJ\0'
WIRE_VERSION = 2
MAX_DESCRIPTOR_BYTES = 16 * 1024**2
MAX_DECODE_BYTES = 2 * 1024**3
MAX_PARTS = 65536


def pack_bundle(descriptor, body):
    protected = {key:value for key,value in descriptor.items() if key != 'descriptor_sha256'}
    protected['descriptor_sha256'] = hashlib.sha256(canonical_json(protected)).hexdigest()
    header = canonical_json(protected)
    if len(header)>MAX_DESCRIPTOR_BYTES: raise ValueError('descriptor too large')
    return PREFIX.pack(MAGIC,WIRE_VERSION,len(header))+header+body


def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError('duplicate JSON key')
        d[k]=v
    return d


def read_bundle_prefix(wire):
    if not isinstance(wire,bytes) or len(wire)<PREFIX.size: raise ValueError('truncated prefix')
    magic,version,n=PREFIX.unpack_from(wire)
    if magic!=MAGIC or version not in {1,WIRE_VERSION}: raise ValueError('unknown wire format')
    if n>MAX_DESCRIPTOR_BYTES or n>len(wire)-PREFIX.size: raise ValueError('invalid descriptor length')
    def reject(value): raise ValueError(f'non-finite JSON {value}')
    d=json.loads(wire[PREFIX.size:PREFIX.size+n].decode('utf-8'),object_pairs_hook=_pairs,parse_constant=reject)
    if not isinstance(d,dict): raise ValueError('descriptor must be an object')
    checksum=d.get('descriptor_sha256')
    if version==WIRE_VERSION or checksum is not None:
        content={key:value for key,value in d.items() if key!='descriptor_sha256'}
        if not isinstance(checksum,str) or checksum!=hashlib.sha256(canonical_json(content)).hexdigest():
            raise ValueError('descriptor checksum mismatch')
    return d,wire[PREFIX.size+n:]


def checked_array(desc):
    if not isinstance(desc,dict) or desc.get('dtype') not in DTYPES: raise ValueError('invalid dtype')
    shape=desc.get('shape')
    if not isinstance(shape,list) or not 1<=len(shape)<=8 or any(type(x) is not int or x<0 or x>2**31 for x in shape):
        raise ValueError('invalid shape')
    if desc.get('order') not in {'C','F'}: raise ValueError('invalid array order')
    n=math.prod(shape)*np.dtype(desc['dtype']).itemsize
    if n>MAX_DECODE_BYTES: raise ValueError('decompressed object exceeds limit')
    return n


def validate_descriptor(desc,body):
    if desc.get('schema_version') != 'tsbench.object/1': raise ValueError('unknown object schema')
    if not isinstance(desc.get('schema'),dict): raise ValueError('missing object schema')
    components=desc.get('components')
    if not isinstance(components,list) or not 1<=len(components)<=64: raise ValueError('invalid component list')
    names=set(); intervals=[]; total=0; parts_n=0
    for c in components:
        if not isinstance(c,dict) or not isinstance(c.get('name'),str) or not c['name'] or c['name'] in names: raise ValueError('invalid component name')
        names.add(c['name']); total+=checked_array(c)
        parts=c.get('parts')
        if not isinstance(parts,list) or not parts: raise ValueError('component needs payload parts')
        parts_n+=len(parts)
        for part in parts:
            checked_array(part)
            if not isinstance(part.get('codec'),str) or not isinstance(part.get('params'),dict): raise ValueError('invalid decoder configuration')
            start,n=part.get('offset'),part.get('length')
            if type(start) is not int or type(n) is not int or start<0 or n<0 or start+n>len(body): raise ValueError('payload interval out of bounds')
            payload=body[start:start+n]
            if hashlib.sha256(payload).hexdigest()!=part.get('sha256'): raise ValueError('payload checksum mismatch')
            intervals.append((start,start+n))
    if total>MAX_DECODE_BYTES or parts_n>MAX_PARTS: raise ValueError('object exceeds decode limit')
    end=0
    for start,stop in sorted(intervals):
        if start!=end: raise ValueError('payload intervals overlap or contain unaccounted bytes')
        end=stop
    if end!=len(body): raise ValueError('unaccounted body bytes')
    return components


@dataclass(frozen=True)
class EncodedObject:
    wire: bytes
    @property
    def stored_bytes(self): return len(self.wire)
    @property
    def descriptor(self): return read_bundle_prefix(self.wire)[0]
    @property
    def sha256(self): return 'sha256:'+hashlib.sha256(self.wire).hexdigest()
    @property
    def payload_bytes(self):
        d,body=read_bundle_prefix(self.wire)
        return len(body)
