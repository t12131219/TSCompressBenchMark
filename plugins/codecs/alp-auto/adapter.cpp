#include "linear_frame.hpp"
#include "alp_native.h"
#include <cfenv>
#include <cstdio>
#include <cinttypes>

namespace wire = tsbench::linear;
struct bmk_context {
    alpn_backend requested{ALPN_SCALAR};
    const char *operation{}, *reason{""};
    char native_error[256]{};
    alpn_stats enc{};
    alpn_decode_stats dec{};
};
namespace {
constexpr wire::Magic magic{'B','M','K','A','L','P',1,0};
constexpr alpn_backend backends[]{ALPN_SCALAR,ALPN_FALP_SCALAR,ALPN_FALP_AUTO,ALPN_FALP_AVX2,ALPN_FALP_AVX512BW};
constexpr std::string_view tokens[]{"\"scalar-unfused\"","\"falp-scalar\"","\"falp-auto\"","\"falp-avx2\"","\"falp-avx512bw\""};
bool options(const uint8_t *p,uint64_t n,alpn_backend &selected) noexcept {
    wire::Options json(p,n);
    if (!json.token("{")) return false;
    if (json.token("}")) { selected = ALPN_SCALAR; return json.done(); }
    if (!json.token("\"decode_backend\"") || !json.token(":")) return false;
    for (size_t i=0;i<sizeof(backends)/sizeof(backends[0]);++i)
        if (json.token(tokens[i])) { selected = backends[i]; return json.token("}") && json.done(); }
    return false;
}
bmk_status fail(bmk_context *ctx,bmk_status code,const char *reason) noexcept {
    if (ctx) { ctx->operation = nullptr; ctx->reason = reason; }
    return code;
}
bmk_status native_fail(bmk_context *ctx,alpn_status status,bool decoding) noexcept {
    std::snprintf(ctx->native_error,sizeof(ctx->native_error),"%s",alpn_last_error());
    bmk_status rc = BMK_INTERNAL;
    if (status == ALPN_NOMEM) rc = BMK_NO_MEMORY;
    else if (status == ALPN_CORRUPT || (decoding && status == ALPN_INVALID)) rc = BMK_CORRUPT;
    else if (status == ALPN_INVALID) rc = BMK_BAD_INPUT;
    return fail(ctx,rc,ctx->native_error);
}
unsigned bits(uint32_t dtype) noexcept { return dtype == BMK_F32 ? 32 : dtype == BMK_F64 ? 64 : 0; }
bmk_status probe(const bmk_object_view *obj,const uint8_t *p,uint64_t n,bmk_blob *out) noexcept {
    alpn_backend backend;
    if (!options(p,n,backend)) return BMK_BAD_OPTIONS;
    wire::Input in;
    const auto rc = wire::view(obj,wire::logical_limit,in);
    if (rc != BMK_OK) return rc;
    const unsigned width = bits(in.dtype);
    if (!width || !alpn_backend_available(backend,width) || std::fegetround() != FE_TONEAREST) return BMK_UNSUPPORTED;
    return wire::text(out,"{\"mode\":\"batch\",\"threads\":1,\"encoding\":\"ALPN_AUTO\"}");
}
bmk_status create(const bmk_host_v1 *host,const uint8_t *p,uint64_t n,bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    alpn_backend backend;
    if (!options(p,n,backend)) return BMK_BAD_OPTIONS;
    auto *ctx = new (std::nothrow) bmk_context;
    if (!ctx) return BMK_NO_MEMORY;
    ctx->requested = backend; *out = ctx;
    return BMK_OK;
}
bmk_status reset(bmk_context *ctx,uint32_t kind) noexcept {
    if (!ctx || kind != 0) return fail(ctx,BMK_UNSUPPORTED,"unsupported reset");
    ctx->enc = {}; ctx->dec = {};
    return fail(ctx,BMK_OK,"");
}
bmk_status encode(bmk_context *ctx,const bmk_object_view *obj,bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Input in;
    const auto rc = wire::view(obj,wire::logical_limit,in);
    if (rc != BMK_OK) return fail(ctx,rc,"ALP needs one dense column up to 64 MiB");
    const auto width = bits(in.dtype);
    if (!width || std::fegetround() != FE_TONEAREST) return fail(ctx,BMK_UNSUPPORTED,"ALP needs F32/F64 and FE_TONEAREST");
    const size_t bound = alpn_compress_bound(in.count,width);
    if (!bound) return fail(ctx,BMK_INTERNAL,"native bound unavailable");
    std::unique_ptr<uint8_t[]> data(new (std::nothrow) uint8_t[wire::header + in.schema_size + bound]);
    if (!data) return fail(ctx,BMK_NO_MEMORY,"frame allocation failed");
    size_t used = 0;
    const auto native = alpn_compress(in.values,in.count,width,ALPN_AUTO,data.get()+wire::header+in.schema_size,bound,&used,&ctx->enc);
    if (native != ALPN_OK) return native_fail(ctx,native,false);
    const auto packed = wire::encode_header(magic,in,bound,used,std::move(data),out);
    if (packed != BMK_OK) return fail(ctx,packed,"native length outside bound");
    ctx->operation = "encode"; ctx->reason = "";
    return BMK_OK;
}
bmk_status decode(bmk_context *ctx,const uint8_t *p,uint64_t n,bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Frame f;
    const auto rc = wire::read(magic,p,n,wire::logical_limit,f);
    if (rc != BMK_OK) return fail(ctx,rc,"invalid ALP envelope");
    const auto width = bits(f.dtype);
    if (!width || f.payload_size > alpn_compress_bound(f.count,width)) return fail(ctx,BMK_CORRUPT,"invalid ALP payload bound");
    unsigned native_width = 0; size_t count = 0;
    const auto inspect = alpn_inspect(f.payload,f.payload_size,&native_width,&count);
    if (inspect != ALPN_OK) return native_fail(ctx,inspect,true);
    if (count != f.count || width != native_width) return fail(ctx,BMK_CORRUPT,"ALP shape disagreement");
    if (!alpn_backend_available(ctx->requested,width) || std::fegetround() != FE_TONEAREST)
        return fail(ctx,BMK_UNSUPPORTED,"ALP requested backend or FP environment unavailable");
    auto object = wire::allocate(f);
    if (!object) return fail(ctx,BMK_NO_MEMORY,"decoded allocation failed");
    size_t got = 0;
    const auto native = alpn_decompress_ex(f.payload,f.payload_size,f.count,object->buffer.get(),f.count,&got,ctx->requested,&ctx->dec);
    if (native != ALPN_OK) return native_fail(ctx,native,true);
    if (got != f.count) return fail(ctx,BMK_CORRUPT,"decoded value count mismatch");
    wire::decoded(out,f,std::move(object));
    ctx->operation = "decode"; ctx->reason = "";
    return BMK_OK;
}
bmk_status info(bmk_context *ctx,bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    char json[768];
    int n;
    if (ctx->operation[0] == 'e') {
        const auto &s = ctx->enc;
        n = std::snprintf(json,sizeof(json),"{\"backend\":\"alpn-auto-encoder\",\"mode\":\"batch\",\"threads\":1,"
            "\"fallback\":%s,\"blocks\":%" PRIu64 ",\"operation\":\"encode\",\"alp_groups\":%" PRIu64
            ",\"rd_groups\":%" PRIu64 ",\"raw_groups\":%" PRIu64 ",\"coded_vectors\":%" PRIu64 ",\"raw_vectors\":%" PRIu64 "}",
            s.raw_groups || s.raw_vectors ? "true" : "false",s.alp_groups+s.rd_groups+s.raw_groups,
            s.alp_groups,s.rd_groups,s.raw_groups,s.coded_vectors,s.raw_vectors);
    } else {
        const auto &s = ctx->dec;
        n = std::snprintf(json,sizeof(json),"{\"backend\":\"%s\",\"requested_backend\":\"%s\",\"mode\":\"batch\",\"threads\":1,"
            "\"fallback\":%s,\"operation\":\"decode\",\"scalar_vectors\":%" PRIu64 ",\"falp_scalar_vectors\":%" PRIu64
            ",\"falp_avx2_vectors\":%" PRIu64 ",\"native_falp_simd_counter\":%" PRIu64
            ",\"simd_counter_scope\":\"avx2-only\",\"rd_vectors\":%" PRIu64 ",\"raw_vectors\":%" PRIu64 "}",
            alpn_backend_name(s.effective_backend),alpn_backend_name(ctx->requested),s.raw_vectors ? "true" : "false",
            s.scalar_vectors,s.falp_scalar_vectors,s.falp_avx2_vectors,s.falp_avx2_vectors,s.rd_vectors,s.raw_vectors);
    }
    if (n < 0 || static_cast<size_t>(n) >= sizeof(json)) return BMK_INTERNAL;
    return wire::text(out,std::string_view(json,static_cast<size_t>(n)));
}
bmk_status error_text(bmk_context *ctx,char *dst,uint64_t n) noexcept {
    return ctx ? wire::error(dst,n,ctx->reason) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
const bmk_plugin_v1 abi{sizeof(abi),BMK_ABI_V1,"alp-auto",probe,create,reset,encode,decode,info,error_text,destroy,wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &abi : nullptr; }
