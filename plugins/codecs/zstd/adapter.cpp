#include "linear_frame.hpp"
#include "lzbench_native.h"
#define ZSTD_STATIC_LINKING_ONLY
#include "zstd.h"

namespace wire = tsbench::linear;
struct bmk_context { ln_context *native{}; const char *operation{}; const char *reason{""}; };
namespace {
constexpr wire::Magic magic{'B','M','K','Z','S','T',1,0};
constexpr int level = 3;
bool options(const uint8_t *p, uint64_t n) noexcept {
    wire::Options json(p,n);
    return json.token("{") && json.token("}") && json.done();
}
bmk_status fail(bmk_context *ctx, bmk_status rc, const char *why) noexcept {
    if (ctx) { ctx->operation = nullptr; ctx->reason = why; }
    return rc;
}
bmk_status map(ln_status rc, bool decode) noexcept {
    switch (rc) {
    case LN_OK: return BMK_OK;
    case LN_NOMEM: return BMK_NO_MEMORY;
    case LN_UNSUPPORTED: return BMK_UNSUPPORTED;
    case LN_CODEC_ERROR: case LN_INVALID: return decode ? BMK_CORRUPT : BMK_INTERNAL;
    default: return BMK_INTERNAL;
    }
}
bmk_status probe(const bmk_object_view *obj, const uint8_t *p, uint64_t n, bmk_blob *out) noexcept {
    wire::Input in;
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    const auto rc = wire::view(obj,LN_MAX_BLOCK,in);
    return rc != BMK_OK ? rc : wire::text(out,"{\"mode\":\"batch\",\"max_input_bytes\":65536,\"threads\":1}");
}
bmk_status create(const bmk_host_v1 *host, const uint8_t *p, uint64_t n,bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    std::unique_ptr<bmk_context> ctx(new (std::nothrow) bmk_context);
    if (!ctx) return BMK_NO_MEMORY;
    const auto rc = ln_create(LN_ZSTD,level,&ctx->native);
    if (rc != LN_OK) return map(rc,false);
    *out = ctx.release();
    return BMK_OK;
}
bmk_status reset(bmk_context *ctx, uint32_t kind) noexcept {
    if (!ctx || kind != 0) return fail(ctx,BMK_UNSUPPORTED,"unsupported reset");
    ln_context *fresh = nullptr;
    const auto rc = ln_create(LN_ZSTD,level,&fresh);
    if (rc != LN_OK) return fail(ctx,map(rc,false),"Zstd context reset failed");
    ln_destroy(ctx->native); ctx->native = fresh;
    return fail(ctx,BMK_OK,"");
}
bmk_status encode(bmk_context *ctx, const bmk_object_view *obj, bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Input in;
    const auto rc = wire::view(obj,LN_MAX_BLOCK,in);
    if (rc != BMK_OK) return fail(ctx,rc,"Zstd needs one dense column up to 65536 bytes");
    const size_t bound = ln_compress_bound(LN_ZSTD,in.bytes);
    if (!bound) return fail(ctx,BMK_INTERNAL,"native bound unavailable");
    std::unique_ptr<uint8_t[]> data(new (std::nothrow) uint8_t[wire::header + in.schema_size + bound]);
    if (!data) return fail(ctx,BMK_NO_MEMORY,"frame allocation failed");
    size_t used = 0;
    const auto native = ln_compress(ctx->native,in.values,in.bytes,data.get()+wire::header+in.schema_size,bound,&used);
    if (native != LN_OK) return fail(ctx,map(native,false),"native ln_compress failed");
    const auto packed = wire::encode_header(magic,in,bound,used,std::move(data),out);
    if (packed != BMK_OK) return fail(ctx,packed,"native length outside bound");
    ctx->operation = "encode"; ctx->reason = "";
    return BMK_OK;
}
bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Frame f;
    const auto rc = wire::read(magic,p,n,LN_MAX_BLOCK,f);
    if (rc != BMK_OK) return fail(ctx,rc,"invalid Zstd envelope");
    if (f.payload_size > ln_compress_bound(LN_ZSTD,LN_MAX_BLOCK)) return fail(ctx,BMK_RESOURCE_LIMIT,"oversize compressed block");
    ZSTD_frameHeader h{};
    // The frozen generic lzbench ABI trusts caller-supplied original length. Bind
    // this route to one actual standard Zstd frame with a small bounded window.
    if (ZSTD_getFrameHeader(&h,f.payload,f.payload_size) != 0 || h.frameType != ZSTD_frame ||
        h.frameContentSize != f.bytes || h.windowSize > LN_MAX_BLOCK || h.dictID != 0 ||
        ZSTD_findFrameCompressedSize(f.payload,f.payload_size) != f.payload_size)
        return fail(ctx,BMK_CORRUPT,"invalid Zstd frame shape or trailing frame");
    auto object = wire::allocate(f);
    if (!object) return fail(ctx,BMK_NO_MEMORY,"decoded allocation failed");
    size_t got = 0;
    const auto native = ln_decompress(ctx->native,f.payload,f.payload_size,object->buffer.get(),f.bytes,f.bytes,&got);
    if (native != LN_OK) return fail(ctx,map(native,true),"native ln_decompress failed");
    if (got != f.bytes) return fail(ctx,BMK_CORRUPT,"decoded byte count mismatch");
    wire::decoded(out,f,std::move(object));
    ctx->operation = "decode"; ctx->reason = "";
    return BMK_OK;
}
bmk_status info(bmk_context *ctx, bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    return wire::text(out,ctx->operation[0]=='e' ?
        "{\"backend\":\"ln-zstd-baseline\",\"mode\":\"batch\",\"level\":3,\"threads\":1,\"fallback\":false,\"blocks\":1,\"operation\":\"encode\"}" :
        "{\"backend\":\"ln-zstd-baseline\",\"mode\":\"batch\",\"threads\":1,\"fallback\":false,\"blocks\":1,\"operation\":\"decode\"}");
}
bmk_status error_text(bmk_context *ctx,char *dst,uint64_t n) noexcept {
    return ctx ? wire::error(dst,n,ctx->reason) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { if (ctx) { ln_destroy(ctx->native); delete ctx; } }
const bmk_plugin_v1 abi{sizeof(abi),BMK_ABI_V1,"zstd",probe,create,reset,encode,decode,info,error_text,destroy,wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &abi : nullptr; }
