"""Real RLE SDK execution with independent selection, wire and accounting expectations."""

from __future__ import annotations

import ctypes
import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.fastpfor_simple import PREFIX
from tscompbench.adapters.fastpfor_simple8b_rle import KEY, FastPFORSimple8bRLEAdapter
from tscompbench.adapters.native_timing import _NativeTiming
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, OutputCapacityError
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.ids import canonical_json_bytes
from test_fastpfor_simple import fnv, routed, split

ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (0,1,2,3,4,5,6,7,8,10,12,15,20,30,60)
COUNTS = (0,60,30,20,15,12,10,8,7,6,5,4,3,2,1)


def adapter() -> FastPFORSimple8bRLEAdapter:
    return FastPFORSimple8bRLEAdapter(
        ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2/release/libtscb_fastpfor_simple8b_rle.so",
        {"backend": "C_ABI_V1", "version": "simple8b-rle-ctypes-v1"},
    )


def oracle(values: np.ndarray, marked: bool) -> tuple[bytes, int, int, int]:
    data = [int(v) for v in values]
    words, at, value_bits, padding_bits, run_bits = [], 0, 0, 0, 0
    while at < len(data):
        run = 1
        while at + run < len(data) and data[at + run] == data[at]:
            run += 1
        if (data[at] | 1).bit_length() * run >= 60:
            run = min(run, (1 << 28) - 1)
            words.append((15 << 60) | (run << 32) | data[at])
            value_bits += 32; run_bits += 28; at += run
            continue
        for selector in range(1,15):
            part = data[at:at + COUNTS[selector]]
            width = WIDTHS[selector]
            if any(value.bit_length() > width for value in part):
                continue
            word = selector << 60
            for i,value in enumerate(part):
                for bit in range(min(width,32)):
                    if (value >> bit) & 1:
                        word |= 1 << (i * width + bit)
            words.append(word)
            value_bits += len(part) * min(width,32)
            padding_bits += 60 - len(part) * min(width,32)
            at += len(part)
            break
        else:
            raise AssertionError("uint32 source domain not represented")
    frame = struct.pack("<8s6I",b"TSCB8BR1",len(data),0,marked,len(words)*2+marked,0,0)
    if marked:
        frame += struct.pack("<I",len(data))
    frame += b"".join(struct.pack("<Q",word) for word in words)
    frame += struct.pack("<Q",fnv(frame))
    metadata = 192 + 32 * marked + 4 * len(words) + run_bits
    return frame,value_bits,padding_bits,metadata


def verify(values: np.ndarray, marked: bool) -> None:
    result = perform_roundtrip(adapter(),routed(values),{"mark_length":marked})
    info, frame = split(result.encoded.stream)
    expected,bits,padding,metadata = oracle(values,marked)
    assert frame == expected
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert not result.decoded.buffers[0].array.flags.writeable
    assert result.input_immutable and result.canary_intact and result.determinism_match
    ledger = result.encoded.ledger
    assert ledger.value_bits == bits and ledger.padding_bits == padding
    assert ledger.metadata_bits == len(canonical_json_bytes(info))*8 + metadata
    assert ledger.container_bits == 160 and ledger.checksum_bits == 320
    assert ledger.final_bits == len(result.encoded.stream)*8
    assert ledger.external_side_information_bits == ledger.timestamp_bits == 0
    assert result.timing.native_encode_wall_ns is not None and result.timing.native_decode_wall_ns is not None
    for phase in ("encode","decode"):
        telemetry = result.codec_telemetry[phase]
        assert telemetry["internal_padding_bytes"] == 0
        assert telemetry["native_payload_bytes"] == len(frame)-40
        assert telemetry["python_payload_copy_bytes"] == 0


@pytest.mark.parametrize("marked",[False,True])
@pytest.mark.parametrize("count",[0,1,2,3,7,8,9,59,60,61,119,120,121,127,128,129,239,240,241,255,256,257,4097])
def test_uint32_tail_wire_ledger_and_native_observations(marked: bool,count: int) -> None:
    verify(np.array([(i*2654435761)&0xffffffff for i in range(count)],dtype="<u4"),marked)


@pytest.mark.parametrize("marked",[False,True])
@pytest.mark.parametrize("width",range(33))
@pytest.mark.parametrize("kind",range(6))
def test_every_width_pattern_and_original_wire(marked: bool,width: int,kind: int) -> None:
    mask=(1<<width)-1
    n=129
    if kind==0: data=[0]*n
    elif kind==1: data=[mask]*n
    elif kind==2: data=[(1<<(width-1)) if width else 0]*n
    elif kind==3: data=[i&mask for i in range(n)]
    elif kind==4: data=[int(v)&mask for v in np.random.default_rng(width).integers(0,2**32,n,dtype=np.uint32)]
    else: data=[mask if i%2 else 0 for i in range(n)]
    verify(np.array(data,dtype="<u4"),marked)


@pytest.mark.parametrize("marked",[False,True])
def test_all_fifteen_selectors_and_sparse_rle_identity(marked: bool) -> None:
    seen=set()
    for selector in range(1,16):
        width=min(WIDTHS[selector],32) if selector<15 else 21
        data=([((1<<width)-1)-(i%2) for i in range(COUNTS[selector])]
              if selector<15 else [1<<20]*3)
        values=np.array(data,dtype="<u4")
        result=perform_roundtrip(adapter(),routed(values),{"mark_length":marked})
        frame=split(result.encoded.stream)[1]
        assert frame==oracle(values,marked)[0]
        seen.add(struct.unpack_from("<Q",frame,32+marked*4)[0]>>60)
    assert seen==set(range(1,16))


@pytest.mark.parametrize("marked",[False,True])
@pytest.mark.parametrize("layout",["strided","reversed","misaligned"])
def test_layout_gather_preserves_full_uint32(marked: bool,layout: str) -> None:
    data=np.array([0,1,2**31,2**32-1]*33,dtype="<u4")
    if layout=="strided": values=data[::2]
    elif layout=="reversed": values=data[::-1]
    else:
        values=np.ndarray(data.shape,dtype="<u4",buffer=bytearray(data.nbytes+1),offset=1)
        values[:]=data
    verify(values,marked)


@pytest.mark.parametrize("marked",[False,True])
def test_atomic_capacity_alias_lifecycle_reset(marked: bool) -> None:
    item=routed(np.array([0,1,2**31,2**32-1]*17,dtype="<u4"))
    stream=perform_roundtrip(adapter(),item,{"mark_length":marked}).encoded.stream
    session=adapter().create_session({"mark_length":marked})
    try:
        with pytest.raises(ExecutionContractError,match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        short=bytearray(b"\xa5"*(len(stream)-1))
        with pytest.raises(OutputCapacityError): session.compress_update(item,memoryview(short))
        assert short==b"\xa5"*len(short)
        alias=bytearray(4096)
        values=np.ndarray((68,),dtype="<u4",buffer=alias)
        values[:]=item.buffers[0].array
        before=bytes(alias)
        with pytest.raises(ExecutionContractError,match="alias"):
            session.compress_update(routed(values),memoryview(alias))
        assert bytes(alias)==before
        output=bytearray(len(stream))
        assert session.compress_update(item,memoryview(output))==len(stream)
        assert bytes(output)==stream
        with pytest.raises(ExecutionContractError,match="before finalize"):
            session.accounting(stream,item)
        assert session.finalize(memoryview(bytearray()))==0
        assert session.accounting(stream,item).final_bits==len(stream)*8
        with pytest.raises(ExecutionContractError,match="update lifecycle"):
            session.compress_update(item,memoryview(output))
        with pytest.raises(ExecutionContractError,match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        damaged=bytearray(stream);damaged[-1]^=1
        with pytest.raises(ExecutionContractError,match="object changed"):
            session.accounting(bytes(damaged),item)
        session.reset()
        assert session.native_timing()==(0,0)
        assert session.compress_update(item,memoryview(output))==len(stream)
    finally: session.close()


@pytest.mark.parametrize("marked",[False,True])
def test_timer_disable_fresh_decoder_queries_and_close(marked: bool) -> None:
    item=routed(np.full(129,2**32-1,dtype="<u4"))
    enabled=perform_roundtrip(adapter(),item,{"mark_length":marked})
    disabled=perform_roundtrip(adapter(),item,{"mark_length":marked,"native_timing":False})
    assert enabled.encoded.stream==disabled.encoded.stream
    assert disabled.timing.native_encode_wall_ns is None and disabled.timing.native_decode_wall_ns is None
    session=adapter().create_session({"mark_length":not marked})
    try:
        assert session.native_timing()==(0,0)
        for _ in range(2):
            assert session.decompress(enabled.encoded.stream).buffers[0].array.tobytes()==item.buffers[0].array.tobytes()
        totals=session.native_timing();assert session.native_timing()==totals
        session.reset();assert session.native_timing()==(0,0)
    finally: session.close();session.close()
    with pytest.raises(ExecutionContractError,match="closed"): session.native_timing()
    off=adapter().create_session({"native_timing":False})
    try:
        off.decompress(enabled.encoded.stream)
        get=off._native.library.tscb_get_native_timing
        get.argtypes=[ctypes.c_void_p,ctypes.POINTER(_NativeTiming)];get.restype=ctypes.c_uint32
        value=_NativeTiming(ctypes.sizeof(_NativeTiming),1,77,88)
        assert get(off._handle,ctypes.byref(value))==2
        assert (value.native_encode_wall_ns,value.native_decode_wall_ns)==(77,88)
    finally: off.close()


@pytest.mark.parametrize("marked",[False,True])
def test_untrusted_descriptors_native_grammar_and_all_truncations(marked: bool) -> None:
    stream=perform_roundtrip(adapter(),routed(np.arange(61,dtype="<u4")),{"mark_length":marked}).encoded.stream
    info,frame=split(stream)
    session=adapter().create_session({})
    def pack(document: dict,wire: bytes) -> bytes:
        header=canonical_json_bytes(document)
        return PREFIX.pack(b"TSCB8BC1",len(header),hashlib.sha256(header).digest())+header+wire
    try:
        for end in range(len(stream)):
            with pytest.raises(ExecutionContractError): session.decompress(stream[:end])
        for change in (
            lambda d:d.update(count=True),lambda d:d.update(count=16777217),lambda d:d.update(extra=0),
            lambda d:d.update(algorithm="simple9-u28"),lambda d:d.update(track="TIMESTAMP"),
            lambda d:d["buffer"].update(shape=[True]),lambda d:d["buffer"].update(dtype="<i8"),
            lambda d:d["parameters"].update(mark_length=1),lambda d:d["parameters"].update(codec="NONE"),
            lambda d:d.update(value_units=["a","b"]),
        ):
            document=json.loads(json.dumps(info));change(document)
            with pytest.raises(ExecutionContractError): session.decompress(pack(document,frame))
        for offset in (0,8,12,16,20,24,28):
            wire=bytearray(frame);wire[offset]^=0x80
            struct.pack_into("<Q",wire,len(wire)-8,fnv(wire[:-8]))
            with pytest.raises(ExecutionContractError): session.decompress(pack(info,bytes(wire)))
        for word in (0,15<<60,(15<<60)|(1000<<32)|1,(14<<60)|(1<<32)|1):
            wire=bytearray(frame);struct.pack_into("<Q",wire,32+marked*4,word)
            struct.pack_into("<Q",wire,len(wire)-8,fnv(wire[:-8]))
            before=session.native_timing()
            with pytest.raises(ExecutionContractError): session.decompress(pack(info,bytes(wire)))
            assert session.native_timing()==before
        with pytest.raises(ExecutionContractError): session.decompress(stream+b"\0")
        assert session.decompress(stream).buffers[0].array.tobytes()==np.arange(61,dtype="<u4").tobytes()
    finally: session.close()


@pytest.mark.parametrize("parameters",[{"mark_length":1},{"isa":"AVX2"},{"native_timing":0},{"codec":"NONE"},{"extra":0}])
def test_invalid_parameters(parameters: dict) -> None:
    with pytest.raises(ExecutionContractError): adapter().create_session(parameters)


@pytest.mark.parametrize("dtype",["<i8","<f8",">u4","<u8"])
def test_wrong_dtype_is_rejected(dtype: str) -> None:
    session=adapter().create_session({})
    try:
        with pytest.raises(ExecutionContractError): session.output_bound(routed(np.arange(3,dtype=dtype)))
    finally: session.close()


def test_invalid_routed_contract_and_native_identity() -> None:
    item=routed(np.arange(3,dtype="<u4"));session=adapter().create_session({})
    try:
        for bad in (replace(item,m=2),replace(item,n=4),replace(item,canonical_raw_bits=1),
                    replace(item,validity_reference=np.ones(3,dtype=bool)),replace(item,value_units=None),
                    replace(item,buffers=(LogicalBuffer(1,item.buffers[0].array,96),))):
            with pytest.raises(ExecutionContractError):session.output_bound(bad)
    finally: session.close()
    with pytest.raises(ExecutionContractError,match="unavailable"):
        FastPFORSimple8bRLEAdapter(ROOT/"build/no-such-rle.so",{}).create_session({})
    with pytest.raises(ExecutionContractError,match="identity"):
        FastPFORSimple8bRLEAdapter(ROOT/"build/adapters/fastpfor_simple/release/libtscb_fastpfor_simple.so",{}).create_session({})
