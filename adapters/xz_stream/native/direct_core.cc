#include "../../../native/include/tsbench_core_bytes.hpp"
extern "C" {
#include "lzma.h"
}

namespace {
using namespace tsbench_bytes;
struct XzCore : Context {
    uint32_t preset=6;
    XzCore(const tsbench_core_config& config,bool decoder):Context(config,decoder) {
        if(!decoder)preset=static_cast<uint32_t>(Parameters(config.parameters_json).integer("compression_level",0,9));
    }
};
}
TSBENCH_BYTE_COMMON_API(XzCore)
extern "C" uint32_t tsbench_core_storage(void) { return 3; }
extern "C" int tsbench_core_bound(void* raw,const uint8_t*,size_t n,size_t* bound) {
    auto c=static_cast<XzCore*>(raw);return guard(c,[&]{
        encoding(c,n);require(bound,"null XZ bound");*bound=lzma_stream_buffer_bound(n);
        if(!*bound)throw Unsupported("XZ native bound overflow");
    });
}
extern "C" int tsbench_core_encode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<XzCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);encoding(c,n);size_t used=0;
        if(!cap)throw Capacity("XZ destination is empty");
        // This API writes the LZMA2 block, index and stream footer in one call.
        auto status=lzma_easy_buffer_encode(c->preset,LZMA_CHECK_NONE,nullptr,source(in),n,out,&used,cap);
        if(status==LZMA_BUF_ERROR)throw Capacity("XZ destination is too small");
        require(status==LZMA_OK,"lzma_easy_buffer_encode failed");caller_result(out,used,cap,result);
    });
}
extern "C" int tsbench_core_decode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<XzCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);decoding(c,cap);
        require(n>=12 && in[6]==0 && in[7]==LZMA_CHECK_NONE,"unregistered XZ stream/check variant");
        lzma_stream stream=LZMA_STREAM_INIT;
        auto initialized=lzma_stream_decoder(&stream,UINT64_C(1073741824),0);
        struct End { lzma_stream* s;~End(){lzma_end(s);} } end{&stream};
        require(initialized==LZMA_OK,"XZ decoder initialization failed");uint8_t dummy=0;
        stream.next_in=in;stream.avail_in=n;stream.next_out=destination(out,dummy);stream.avail_out=c->bytes?c->bytes:1;
        for(;;) {
            auto before_in=stream.total_in,before_out=stream.total_out;auto status=lzma_code(&stream,LZMA_FINISH);
            if(status==LZMA_STREAM_END)break;
            if(!stream.avail_out)throw Capacity("XZ output exceeds task bytes");
            require(status==LZMA_OK && (stream.total_in!=before_in || stream.total_out!=before_out),"XZ corrupt/truncated stream");
        }
        require(stream.avail_in==0 && stream.total_out==c->bytes,"XZ trailing stream or decoded length mismatch");
        caller_result(out,c->bytes,cap,result);
    });
}
