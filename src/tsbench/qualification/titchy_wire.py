"""Independent readers for the bounded TCHY v2 and TSTR/TSC1 development artifacts."""
import struct

from ..assets import require
from ..planner.titchy_native import pack

TCHY = struct.Struct('<4sBBBBHIQQII')
INDEX = struct.Struct('<QIQI')
SPLIT = struct.Struct('<BBHI')
TSTR = struct.Struct('<5sBBHQI')
TSTR_RECORD = struct.Struct('<HI')
TSC1 = struct.Struct('<4sBBHBxHdQ4x')


class Bits:
    def __init__(self, data, count):
        pad = (-count) % 8
        require(len(data) * 8 == count + pad and (not pad or data[-1] & ((1 << pad)-1) == 0),
                'Titchy bit length or padding differs')
        self.data = data
        self.nbits = count
        self.pos = 0

    def read(self, n):
        end = self.pos + n
        require(end <= self.nbits, 'truncated Titchy bits')
        if not n:
            return 0
        begin_byte = self.pos // 8
        end_byte = (end + 7) // 8
        value = (int.from_bytes(self.data[begin_byte:end_byte], 'big') >> ((-end) % 8)) & ((1 << n) - 1)
        self.pos = end
        return value


def _pair(reader, dictionary, lid, ld, width, chunk):
    ident = reader.read(lid)
    require(ident < len(dictionary), 'Titchy dictionary reference out of bounds')
    values = list(dictionary[ident])
    quota, extra = divmod(ld, chunk)
    for bit in range(quota + bool(extra)):
        first = 0 if bit < quota else chunk - extra
        for lane in range(first, chunk):
            values[lane] = (values[lane] & ~(1 << bit)) | (reader.read(1) << bit)
    return values


def native_bound(n, width, chunk, split):
    chunks = (n + chunk - 1) // chunk
    splits = (chunks + split - 1) // split
    return 38 + 33*splits + ((width*chunk+7)//8)*chunks + (chunks*(32+255)+7)//8


def decode_tchy(wire, width, n, policy):
    require(len(wire) >= TCHY.size, 'Titchy header truncated')
    magic, version, bits, chunk, endian, split, threshold, active, count, nb, ns = TCHY.unpack_from(wire)
    require((magic, version, bits, chunk, endian, split, threshold, active, count) ==
            (b'TCHY', 2, width, policy['chunk'], policy['endian'], policy['split'], policy['threshold_ppm'],
             policy['active_bytes'], n), 'Titchy batch configuration or count differs')
    nc = (n + chunk - 1) // chunk
    cb = width*chunk
    bs = (cb+7)//8
    start = TCHY.size+ns*INDEX.size
    pos = start+nb*bs
    require(ns == (nc+split-1)//split and 0 <= nb <= nc and bool(nb) == bool(nc) and pos <= len(wire),
            'invalid Titchy batch index or dictionary extent')
    dictionary = []
    for i in range(nb):
        r = Bits(wire[start+i*bs:start+(i+1)*bs], cb)
        dictionary.append(tuple(r.read(width) for _ in range(chunk)))
    out, splits = [], []
    for s in range(ns):
        first, chunks, offset, length = INDEX.unpack_from(wire, TCHY.size+s*INDEX.size)
        require(first == s*split and chunks == min(split, nc-first) and offset == pos and
                SPLIT.size <= length <= len(wire)-pos, 'invalid Titchy split index')
        lid, ld, record_chunks, payload_len = SPLIT.unpack_from(wire, pos)
        require(record_chunks == chunks and payload_len == length-SPLIT.size and lid <= 32 and ld <= min(255, cb),
                'invalid Titchy split parameters')
        r = Bits(wire[pos+SPLIT.size:pos+length], chunks*(lid+ld))
        for _ in range(chunks):
            out.extend(_pair(r, dictionary, lid, ld, width, chunk))
        splits.append({'first_chunk': first, 'chunks': chunks, 'offset': offset, 'bytes': length})
        pos += length
    # The batch ABI promises only the reported logical prefix; verify its extent.
    require(pos == len(wire) and len(out) == nc*chunk, 'Titchy trailing data or logical count differs')
    return pack(out[:n], width), splits


def decode_tstr(wire, config, spec, policy):
    require(len(wire) >= TSTR.size and len(config) == TSC1.size, 'Titchy stream metadata length differs')
    m, width, chunk, split, endian, target, threshold, active = TSC1.unpack(config)
    magic, b, ch, sp, count, npackets = TSTR.unpack_from(wire)
    require((m, width, chunk, split, endian, target, threshold, active) ==
            (b'TSC1', 64, policy['chunk'], policy['split'], policy['endian'], spec['chunks_per_packet'],
             policy['threshold_ppm']/1_000_000, spec['max_active_bytes']) and
            config == TSC1.pack(m, width, chunk, split, endian, target, threshold, active) and
            (magic, b, ch, sp, count) == (b'TSTR\1', width, chunk, split, spec['count']),
            'Titchy stream parameters or logical count differ')
    cb = width*chunk
    nchunks = (count+chunk-1)//chunk
    require(0 < npackets <= nchunks, 'Titchy stream packet count outside bounds')
    pos, dictionary, values, packets, params = TSTR.size, [], [], [], None
    for _ in range(npackets):
        require(pos+TSTR_RECORD.size < len(wire), 'truncated Titchy stream record')
        chunks, n = TSTR_RECORD.unpack_from(wire, pos)
        pos += TSTR_RECORD.size
        require(1 <= chunks <= target and 1 <= n <= len(wire)-pos and len(values)//chunk+chunks <= nchunks,
                'Titchy stream packet extent differs')
        payload = wire[pos:pos+n]
        with_params = bool(payload[0] & 128)
        nb = payload[0] & 127
        header = 3 if with_params else 1
        require(len(payload) >= header and (with_params or params is not None), 'missing Titchy packet parameters')
        if with_params:
            params = tuple(payload[1:3])
        lid, ld = params
        require(lid <= 32 and ld <= cb and len(dictionary)+nb <= nchunks, 'invalid Titchy packet metadata')
        r = Bits(payload[header:], nb*cb + chunks*(lid+ld))
        for _ in range(nb):
            dictionary.append(tuple(r.read(width) for _ in range(chunk)))
        for _ in range(chunks):
            values.extend(_pair(r, dictionary, lid, ld, width, chunk))
        packets.append({'chunks': chunks, 'bytes': n, 'new_bases': nb, 'parameters': with_params})
        pos += n
    require(pos == len(wire) and len(values) == nchunks*chunk and not any(values[count:]),
            'Titchy stream trailing data or nonzero/incomplete padded tail')
    return pack(values[:count], width), packets
