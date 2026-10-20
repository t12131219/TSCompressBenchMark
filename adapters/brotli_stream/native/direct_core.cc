#include "../../../native/include/tsbench_core_bytes.hpp"
#include "brotli/decode.h"
#include "brotli/encode.h"

namespace {
using namespace tsbench_bytes;
struct BrotliCore : Context {
    int quality=5, window=22;
    BrotliCore(const tsbench_core_config& config,bool decoder):Context(config,decoder) {
        if(!decoder) {
            Parameters p(config.parameters_json);
            quality=static_cast<int>(p.integer("compression_level",0,11));
            window=static_cast<int>(p.integer("window_bits",10,24));
        }
    }
};
}
TSBENCH_BYTE_COMMON_API(BrotliCore)
extern "C" uint32_t tsbench_core_storage(void) { return 3; }
extern "C" int tsbench_core_bound(void* raw,const uint8_t*,size_t n,size_t* bound) {
    auto c=static_cast<BrotliCore*>(raw);return guard(c,[&]{
        encoding(c,n);require(bound,"null Brotli bound");*bound=BrotliEncoderMaxCompressedSize(n);
        if(!*bound)throw Unsupported("Brotli input cannot be represented by its native bound");
    });
}
extern "C" int tsbench_core_encode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<BrotliCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);encoding(c,n);size_t used=cap;
        if(!cap)throw Capacity("Brotli destination is empty");
        // The one-shot API performs sampling, allocation, encoding and FINISH.
        if(!BrotliEncoderCompress(c->quality,c->window,BROTLI_MODE_GENERIC,n,source(in),&used,out)) {
            if(cap<BrotliEncoderMaxCompressedSize(n))throw Capacity("Brotli destination is too small");
            throw std::runtime_error("BrotliEncoderCompress failed");
        }
        caller_result(out,used,cap,result);
    });
}
extern "C" int tsbench_core_decode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<BrotliCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);decoding(c,cap);
        auto decoder=std::unique_ptr<BrotliDecoderState,decltype(&BrotliDecoderDestroyInstance)>(
            BrotliDecoderCreateInstance(nullptr,nullptr,nullptr),BrotliDecoderDestroyInstance);
        require(bool(decoder),"Brotli decoder allocation failed");
        size_t available_in=n,available_out=c->bytes;const uint8_t* next_in=source(in);uint8_t dummy=0;
        uint8_t* next_out=destination(out,dummy);
        auto status=BrotliDecoderDecompressStream(decoder.get(),&available_in,&next_in,&available_out,&next_out,nullptr);
        if(status==BROTLI_DECODER_RESULT_NEEDS_MORE_OUTPUT)throw Capacity("Brotli output exceeds task bytes");
        require(status==BROTLI_DECODER_RESULT_SUCCESS && available_in==0 && available_out==0,
                "Brotli stream is truncated, trailing or has the wrong decoded length");
        caller_result(out,c->bytes,cap,result);
    });
}
