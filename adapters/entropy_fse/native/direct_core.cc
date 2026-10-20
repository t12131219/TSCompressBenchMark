#include "../../../native/include/tsbench_core_bytes.hpp"
extern "C" {
#include "fse.h"
#include "huf.h"
}
#ifndef TSCB_HUFF0
#define TSCB_HUFF0 0
#endif

namespace {
using namespace tsbench_bytes;
constexpr size_t maximum_block=128*1024;
struct EntropyCore : Context {
    EntropyCore(const tsbench_core_config& config,bool decoder):Context(config,decoder) {
        if(bytes>maximum_block)throw Unsupported("FSE/HUF native block exceeds 128 KiB");
    }
};
size_t entropy_bound(size_t n) {
    size_t vendor=TSCB_HUFF0?HUF_compressBound(n):FSE_compressBound(n);
    return add(9,std::max(vendor,n));
}
bool entropy_error(size_t status) { return TSCB_HUFF0?HUF_isError(status):FSE_isError(status); }
}
TSBENCH_BYTE_COMMON_API(EntropyCore)
extern "C" uint32_t tsbench_core_storage(void) { return 3; }
extern "C" int tsbench_core_bound(void* raw,const uint8_t*,size_t n,size_t* bound) {
    auto c=static_cast<EntropyCore*>(raw);return guard(c,[&]{encoding(c,n);require(bound,"null entropy bound");*bound=entropy_bound(n);});
}
extern "C" int tsbench_core_encode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<EntropyCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);encoding(c,n);
        if(cap<entropy_bound(n))throw Capacity("entropy destination below native bound");
        put64(out+1,n);size_t compressed=0;
        if(n>=2)compressed=TSCB_HUFF0?HUF_compress(out+9,cap-9,in,n):FSE_compress(out+9,cap-9,in,n);
        require(!entropy_error(compressed),"native entropy compression failed");size_t used;
        // The native block APIs explicitly return zero for incompressible data
        // and one for a repeated symbol. The complete format records that mode.
        if(compressed>1 && compressed<n) {out[0]=2;used=add(9,compressed);}
        else if(compressed==1 && n) {out[0]=1;out[9]=in[0];used=10;}
        else {out[0]=0;if(n)std::memcpy(out+9,in,n);used=add(9,n);}
        caller_result(out,used,cap,result);
    });
}
extern "C" int tsbench_core_decode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<EntropyCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);decoding(c,cap);
        require(n>=9 && get64(in+1)==c->bytes,"entropy complete-stream length differs from task");
        const size_t decoded=c->bytes;
        if(in[0]==0) {require(n-9==decoded,"entropy raw block length differs");if(decoded)std::memcpy(out,in+9,decoded);}
        else if(in[0]==1) {require(n==10 && decoded>0,"entropy repeated-symbol block is malformed");std::memset(out,in[9],decoded);}
        else if(in[0]==2) {
            require(n>10 && decoded>0,"entropy compressed block is malformed");
            auto used=TSCB_HUFF0?HUF_decompress(out,decoded,in+9,n-9):FSE_decompress(out,decoded,in+9,n-9);
            require(!entropy_error(used) && used==decoded,"native entropy decompression failed");
        } else throw std::invalid_argument("unknown entropy block mode");
        caller_result(out,decoded,cap,result);
    });
}
