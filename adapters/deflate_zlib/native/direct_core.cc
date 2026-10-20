#include "../../../native/include/tsbench_core_bytes.hpp"
#include "zlib.h"
#include <climits>

namespace {
using namespace tsbench_bytes;
struct DeflateCore : Context {
    z_stream stream{};
    bool initialized=false;
    DeflateCore(const tsbench_core_config& config,bool decoding):Context(config,decoding) {
        if(bytes>UINT_MAX)throw Unsupported("zlib input exceeds its uInt API");
        int status;
        if(decoder)status=inflateInit2(&stream,15); // RFC1950 header carries actual window.
        else {
            Parameters p(config.parameters_json);
            int level=static_cast<int>(p.integer("compression_level",0,9));
            int window=static_cast<int>(p.integer("window_bits",9,15));
            status=deflateInit2(&stream,level,Z_DEFLATED,window,8,Z_DEFAULT_STRATEGY);
        }
        require(status==Z_OK,"zlib context initialization failed");initialized=true;
    }
    ~DeflateCore()override { if(initialized) { if(decoder)inflateEnd(&stream);else deflateEnd(&stream); } }
};
}
TSBENCH_BYTE_COMMON_API(DeflateCore)
extern "C" uint32_t tsbench_core_storage(void) { return 3; }
extern "C" int tsbench_core_bound(void* raw,const uint8_t*,size_t n,size_t* bound) {
    auto c=static_cast<DeflateCore*>(raw);return guard(c,[&]{
        encoding(c,n);require(bound,"null zlib bound");auto size=deflateBound(&c->stream,static_cast<uLong>(n));
        if(!size || size>UINT_MAX)throw Unsupported("zlib bound exceeds uInt");
        *bound=static_cast<size_t>(size);
    });
}
extern "C" int tsbench_core_encode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<DeflateCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);encoding(c,n);
        if(cap==0 || cap>UINT_MAX)throw Capacity("zlib output capacity is outside uInt");
        require(deflateReset(&c->stream)==Z_OK,"zlib deflate reset failed");
        auto& s=c->stream;s.next_in=const_cast<Bytef*>(source(in));s.avail_in=static_cast<uInt>(n);
        s.next_out=out;s.avail_out=static_cast<uInt>(cap);
        for(;;) {
            auto before_in=s.total_in,before_out=s.total_out;int status=deflate(&s,Z_FINISH);
            if(status==Z_STREAM_END)break;
            if(!s.avail_out)throw Capacity("zlib output is too small");
            require(status==Z_OK && (s.total_in!=before_in || s.total_out!=before_out),"zlib deflate/finish failed");
        }
        require(s.avail_in==0,"zlib encoder did not consume complete input");
        caller_result(out,static_cast<size_t>(s.total_out),cap,result);
    });
}
extern "C" int tsbench_core_decode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<DeflateCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);decoding(c,cap);
        if(n>UINT_MAX)throw Unsupported("zlib compressed input exceeds uInt");
        require(inflateReset(&c->stream)==Z_OK,"zlib inflate reset failed");
        auto& s=c->stream;uint8_t dummy=0;s.next_in=const_cast<Bytef*>(source(in));s.avail_in=static_cast<uInt>(n);
        s.next_out=destination(out,dummy);s.avail_out=c->bytes?static_cast<uInt>(c->bytes):1U;
        for(;;) {
            auto before_in=s.total_in,before_out=s.total_out;int status=inflate(&s,Z_FINISH);
            if(status==Z_STREAM_END)break;
            if(!s.avail_out)throw Capacity("zlib output exceeds task bytes");
            require(status==Z_OK && (s.total_in!=before_in || s.total_out!=before_out),"zlib corrupt/truncated stream");
        }
        require(s.avail_in==0 && s.total_out==c->bytes,"zlib trailing stream or decoded length mismatch");
        caller_result(out,c->bytes,cap,result);
    });
}
