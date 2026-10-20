#include "../../../native/include/tsbench_core_bytes.hpp"
extern "C" {
#include "bzlib.h"
}
#include <climits>

namespace {
using namespace tsbench_bytes;
struct BzipCore : Context {
    int level=9;
    BzipCore(const tsbench_core_config& config,bool decoder):Context(config,decoder) {
        if(bytes>UINT_MAX)throw Unsupported("bzip2 buffer API requires at most UINT_MAX bytes");
        if(!decoder)level=static_cast<int>(Parameters(config.parameters_json).integer("compression_level",1,9));
    }
};
size_t bzip_bound(size_t n) {
    auto result=add(n,add(n/100,601));
    if(result>UINT_MAX)throw Unsupported("bzip2 output bound exceeds unsigned int");
    return result;
}
}
TSBENCH_BYTE_COMMON_API(BzipCore)
extern "C" uint32_t tsbench_core_storage(void) { return 3; }
extern "C" int tsbench_core_bound(void* raw,const uint8_t*,size_t n,size_t* bound) {
    auto c=static_cast<BzipCore*>(raw);return guard(c,[&]{encoding(c,n);require(bound,"null bzip2 bound");*bound=bzip_bound(n);});
}
extern "C" int tsbench_core_encode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<BzipCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);encoding(c,n);
        if(!cap || cap>UINT_MAX)throw Capacity("bzip2 destination capacity is outside its API");
        unsigned used=static_cast<unsigned>(cap);
        int status=BZ2_bzBuffToBuffCompress(reinterpret_cast<char*>(out),&used,
            reinterpret_cast<char*>(const_cast<uint8_t*>(source(in))),static_cast<unsigned>(n),c->level,0,0);
        if(status==BZ_OUTBUFF_FULL)throw Capacity("bzip2 destination is too small");
        require(status==BZ_OK,"BZ2_bzBuffToBuffCompress failed");caller_result(out,used,cap,result);
    });
}
extern "C" int tsbench_core_decode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<BzipCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);decoding(c,cap);
        if(n>UINT_MAX)throw Unsupported("bzip2 compressed input exceeds unsigned int");
        bz_stream stream{};require(BZ2_bzDecompressInit(&stream,0,0)==BZ_OK,"bzip2 decoder initialization failed");
        struct End { bz_stream* s;~End(){BZ2_bzDecompressEnd(s);} } end{&stream};
        uint8_t dummy=0;stream.next_in=reinterpret_cast<char*>(const_cast<uint8_t*>(source(in)));
        stream.avail_in=static_cast<unsigned>(n);stream.next_out=reinterpret_cast<char*>(destination(out,dummy));
        stream.avail_out=c->bytes?static_cast<unsigned>(c->bytes):1U;
        int status=BZ_OK;
        for(;;) {
            auto before_in=stream.avail_in,before_out=stream.avail_out;status=BZ2_bzDecompress(&stream);
            if(status==BZ_STREAM_END)break;
            if(stream.avail_out==0)throw Capacity("bzip2 output exceeds task bytes");
            require(status==BZ_OK && (stream.avail_in!=before_in || stream.avail_out!=before_out),"bzip2 corrupt/truncated stream");
        }
        uint64_t used=(uint64_t(stream.total_out_hi32)<<32)|stream.total_out_lo32;
        require(stream.avail_in==0 && used==c->bytes,"bzip2 trailing stream or decoded length mismatch");
        caller_result(out,static_cast<size_t>(used),cap,result);
    });
}
