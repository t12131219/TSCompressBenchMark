#pragma once
#include "../../../native/include/tsbench_core_bytes.hpp"
#include "lzss_raw_codec.h"

namespace {
using namespace tsbench_bytes;
struct LzssCore : Context {
    LzssCore(const tsbench_core_config& config,bool decoder):Context(config,decoder) {
        if(bytes>UINT32_MAX)throw Unsupported("LZSS exceeds its registered uint32 work limit");
        if(!decoder) {
            Parameters p(config.parameters_json);
            require(p.integer("ei")==10 && p.integer("ej")==4 && p.integer("initial_byte")==32,
                    "unsupported EI10/EJ4/C32 LZSS configuration");
        }
    }
};
size_t lzss_complete_bound(size_t n) { return add(8,add(n,add(n,7)/8)); }
}
TSBENCH_BYTE_COMMON_API(LzssCore)
extern "C" uint32_t tsbench_core_storage(void) { return 3; }
extern "C" int tsbench_core_bound(void* raw,const uint8_t*,size_t n,size_t* bound) {
    auto c=static_cast<LzssCore*>(raw);return guard(c,[&]{encoding(c,n);require(bound,"null LZSS bound");*bound=lzss_complete_bound(n);});
}
extern "C" int tsbench_core_encode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<LzssCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);encoding(c,n);
        if(cap<lzss_complete_bound(n))throw Capacity("LZSS destination below literal worst-case bound");
        put64(out,n);auto used=tscb_lzss_raw::encode(source(in),n,out+8);
        require(used<=cap-8,"LZSS encoder exceeded capacity");caller_result(out,add(8,used),cap,result);
    });
}
extern "C" int tsbench_core_decode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<LzssCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);decoding(c,cap);
        require(n>=8 && get64(in)==c->bytes,"LZSS complete-stream length differs from task");
        require(tscb_lzss_raw::decode_checked(in+8,n-8,out,c->bytes),"LZSS token coverage or zero padding is invalid");
        caller_result(out,c->bytes,cap,result);
    });
}
