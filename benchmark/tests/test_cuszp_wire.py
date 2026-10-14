"""Malformed persisted GPU archives must fail before any CUDA decode launch."""
import hashlib
import struct
import numpy as np
import pytest
from tsbench.bridges.cuszp import HEADER_BYTES, GPUError, Library, canonical_error_bound, pack, unpack


def valid_payload(n=33):
    rates=bytearray(((n+32767)//32768)*1024)
    rates[0]=2
    return bytes(rates)+bytes(12)


def replace_prefix(wire,offset,value):
    wire=bytearray(wire);wire[offset:offset+len(value)]=value
    wire[64:96]=hashlib.sha256(wire[:64]).digest()
    return bytes(wire)


@pytest.mark.parametrize('dtype',['<f4','<f8'])
def test_wire_restores_independent_configuration(dtype):
    wire=pack(valid_payload(),dtype,33,0.125)
    metadata,payload=unpack(wire)
    assert metadata=={'dtype':dtype,'count':33,'error_bound':0.125,'mode':'FIXED','payload_bytes':1036}
    assert payload==valid_payload() and len(wire)==HEADER_BYTES+1036


@pytest.mark.parametrize('offset',[12,64,HEADER_BYTES+1025])
def test_metadata_and_payload_corruption_rejected(offset):
    wire=bytearray(pack(valid_payload(),'<f4',33,0.125));wire[offset]^=1
    with pytest.raises(GPUError):unpack(wire)


def test_truncated_payload_rejected_even_with_repaired_checksums():
    payload=valid_payload()[:-1]
    prefix=struct.pack('<4sBBBBQdQ32s',b'CSP1',1,4,0,0,33,0.125,len(payload),hashlib.sha256(payload).digest())
    with pytest.raises(GPUError,match='rate table/length'):unpack(prefix+hashlib.sha256(prefix).digest()+payload)


def test_invalid_width_and_padding_rejected():
    payload=bytearray(valid_payload());payload[0]=31
    with pytest.raises(GPUError,match='width'):pack(payload,'<f4',33,0.125)
    payload=bytearray(valid_payload());payload[2]=1
    with pytest.raises(GPUError,match='padding'):pack(payload,'<f4',33,0.125)


@pytest.mark.parametrize('n',[0,16777217])
def test_wire_length_domain_rejected(n):
    with pytest.raises(GPUError):pack(valid_payload(),'<f4',n,0.125)


def test_single_element_zero_payload_keeps_rate_table():
    payload=bytes(1024)
    assert unpack(pack(payload,'<f4',1,0.125))[1]==payload


def test_f32_bound_canonicalized_downward_not_upward():
    requested=0.1
    actual=canonical_error_bound('<f4',requested)
    assert actual<=requested and actual==float(np.float32(actual))
    assert canonical_error_bound('<f8',requested)==requested


def test_unsupported_wire_version_rejected_with_valid_metadata_digest():
    wire=pack(valid_payload(),'<f4',33,0.125)
    with pytest.raises(GPUError,match='header'):unpack(replace_prefix(wire,4,b'\x02'))


@pytest.mark.parametrize('count',[True,33.0,'33'])
def test_noninteger_counts_rejected(count):
    with pytest.raises(GPUError):pack(valid_payload(),'<f4',count,0.125)


@pytest.mark.parametrize('bound',[True,np.bool_(False),'0.1'])
def test_boolean_or_string_bounds_rejected(bound):
    with pytest.raises(GPUError):canonical_error_bound('<f4',bound)


def test_transferred_owner_released_when_info_fails():
    library=object.__new__(Library);calls=[]
    def broken_info(owner,kind):raise GPUError(4,'context error after output transfer')
    library.info=broken_info;library.call=lambda *args:calls.append(args)
    with pytest.raises(GPUError,match='context error'):library.transferred_info('opaque-owner','payload')
    assert calls==[('release_payload','opaque-owner')]
