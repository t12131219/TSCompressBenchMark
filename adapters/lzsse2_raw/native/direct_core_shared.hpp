#pragma once
#include "../../../native/include/tsbench_core_bytes.hpp"

#define TSBENCH_LZSSE_JOIN_(a,b) a##b
#define TSBENCH_LZSSE_JOIN(a,b) TSBENCH_LZSSE_JOIN_(a,b)
#define TSBENCH_LZSSE(name) TSBENCH_LZSSE_JOIN(TSBENCH_LZSSE_PREFIX,name)

namespace {
using namespace tsbench_bytes;
struct LzsseCore : Context {
    TSBENCH_LZSSE(_OptimalParseState)* parse=nullptr;
    unsigned level=12;
    LzsseCore(const tsbench_core_config& config,bool decoder):Context(config,decoder) {
        if(bytes>INT32_MAX)throw Unsupported("LZSSE native positions require at most INT32_MAX bytes");
#if defined(__x86_64__) || defined(__i386__)
        if(!__builtin_cpu_supports("sse4.1"))throw Unsupported("LZSSE requires SSE4.1");
#else
        throw Unsupported("LZSSE direct implementation requires x86 SSE4.1");
#endif
        if(!decoder) {
            Parameters p(config.parameters_json);
            require(p.integer("compression_level")==12 && !p.boolean("content_checksum"),
                    "unregistered LZSSE level/checksum variant");
            parse=TSBENCH_LZSSE(_MakeOptimalParseState)(std::max<size_t>(1,bytes));
            require(parse,"LZSSE parse workspace allocation failed");
        }
    }
    ~LzsseCore()override {if(parse)TSBENCH_LZSSE(_FreeOptimalParseState)(parse);}
};
}
TSBENCH_BYTE_COMMON_API(LzsseCore)
extern "C" uint32_t tsbench_core_storage(void) { return 3; }
extern "C" int tsbench_core_bound(void* raw,const uint8_t*,size_t n,size_t* bound) {
    auto c=static_cast<LzsseCore*>(raw);return guard(c,[&]{encoding(c,n);require(bound,"null LZSSE bound");*bound=add(8,n);});
}
extern "C" int tsbench_core_encode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<LzsseCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);encoding(c,n);
        if(cap<add(8,n))throw Capacity("LZSSE destination below native input-length bound");
        put64(out,n);
        // Workspace allocation can be reused; every match-finder reset and
        // optimal-parse/model pass remains inside the real native API call.
        auto used=TSBENCH_LZSSE(_CompressOptimalParse)(c->parse,source(in),n,out+8,cap-8,c->level);
        require((used>0 || n==0) && used<=n,"native LZSSE compression failed");
        caller_result(out,add(8,used),cap,result);
    });
}
extern "C" int tsbench_core_decode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<LzsseCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);decoding(c,cap);
        require(n>=8 && get64(in)==c->bytes,"LZSSE complete-stream length differs from task");
        size_t compressed=n-8;
        // The native format uses equality of compressed and decoded sizes for
        // raw blocks. Its SIMD stream needs an initial prefix/control/tail.
        require(compressed<=c->bytes,"LZSSE payload exceeds its native bound");
        if(compressed!=c->bytes)require(compressed>=TSBENCH_LZSSE_MINIMUM && c->bytes>=32,
                                       "truncated LZSSE SIMD stream");
        uint8_t dummy=0;
        auto used=TSBENCH_LZSSE(_Decompress)(in+8,compressed,destination(out,dummy),c->bytes);
        require(used==c->bytes,"native LZSSE decoded length differs from complete stream");
        caller_result(out,used,cap,result);
    });
}

#undef TSBENCH_LZSSE
#undef TSBENCH_LZSSE_JOIN
#undef TSBENCH_LZSSE_JOIN_
