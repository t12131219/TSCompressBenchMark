#include "linear_frame.hpp"
#include "lzbench_native.h"
#include "lzma.h"
#include <cstdio>

namespace wire = tsbench::linear;
struct bmk_context {
    ln_context *native{};
    const char *operation{};
    const char *reason{""};
    unsigned blocks{};
};
namespace {
constexpr wire::Magic magic{'B','M','K','X','Z',0,1,0};
constexpr int preset = 6;

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

// The generic legacy decoder accepts concatenated streams and ignores their
// Check. Admit only the shape emitted by this baseline: one XZ stream with
// Check=None and one block (zero for empty input), with no stream padding.
// The native decoder still checks the block and Index while restoring values.
bool baseline_shape(const wire::Frame &f) noexcept {
    constexpr size_t min_index = 8, checksum = 4, stream = LZMA_STREAM_HEADER_SIZE;
    if (f.payload_size < 2*stream + min_index) return false;
    const size_t footer_at = f.payload_size - stream;
    lzma_stream_flags header{}, footer{};
    if (lzma_stream_header_decode(&header,f.payload) != LZMA_OK ||
        lzma_stream_footer_decode(&footer,f.payload+footer_at) != LZMA_OK ||
        lzma_stream_flags_compare(&header,&footer) != LZMA_OK || header.check != LZMA_CHECK_NONE ||
        footer.backward_size < min_index || footer.backward_size > footer_at-stream) return false;
    const size_t index_size = static_cast<size_t>(footer.backward_size) - checksum;
    const size_t index_at = footer_at - static_cast<size_t>(footer.backward_size);
    const auto *index = f.payload + index_at;
    if (index[0] || wire::get(index+index_size,checksum) != lzma_crc32(index,index_size,0)) return false;
    size_t pos = 1;
    lzma_vli blocks{}, unpadded{}, bytes{};
    if (lzma_vli_decode(&blocks,nullptr,index,&pos,index_size) != LZMA_OK || blocks != (f.bytes ? 1u : 0u))
        return false;
    if (blocks && (lzma_vli_decode(&unpadded,nullptr,index,&pos,index_size) != LZMA_OK ||
                   lzma_vli_decode(&bytes,nullptr,index,&pos,index_size) != LZMA_OK || !unpadded)) return false;
    const size_t block_region = index_at-stream;
    return bytes == f.bytes && unpadded <= block_region && ((unpadded+3)&~lzma_vli{3}) == block_region &&
           index_size-pos <= 3 && std::all_of(index+pos,index+index_size,[](uint8_t v){ return v == 0; });
}

bmk_status probe(const bmk_object_view *obj, const uint8_t *p, uint64_t n, bmk_blob *out) noexcept {
    wire::Input in;
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    const auto rc = wire::view(obj,LN_MAX_BLOCK,in);
    return rc != BMK_OK ? rc : wire::text(out,"{\"mode\":\"batch\",\"max_input_bytes\":65536,\"threads\":1}");
}
bmk_status create(const bmk_host_v1 *host, const uint8_t *p, uint64_t n, bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    std::unique_ptr<bmk_context> ctx(new (std::nothrow) bmk_context);
    if (!ctx) return BMK_NO_MEMORY;
    const auto rc = ln_create(LN_XZ,preset,&ctx->native);
    if (rc != LN_OK) return map(rc,false);
    *out = ctx.release();
    return BMK_OK;
}
bmk_status reset(bmk_context *ctx, uint32_t kind) noexcept {
    if (!ctx || kind != 0) return fail(ctx,BMK_UNSUPPORTED,"unsupported reset");
    // ln_compress and ln_decompress each create and end their own XZ stream.
    return fail(ctx,BMK_OK,"");
}
bmk_status encode(bmk_context *ctx, const bmk_object_view *obj, bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Input in;
    const auto rc = wire::view(obj,LN_MAX_BLOCK,in);
    if (rc != BMK_OK) return fail(ctx,rc,"XZ needs one dense column up to 65536 bytes");
    const size_t bound = ln_compress_bound(LN_XZ,in.bytes);
    if (!bound) return fail(ctx,BMK_INTERNAL,"native bound unavailable");
    std::unique_ptr<uint8_t[]> data(new (std::nothrow) uint8_t[wire::header + in.schema_size + bound]);
    if (!data) return fail(ctx,BMK_NO_MEMORY,"frame allocation failed");
    size_t used{};
    const auto rc_native = ln_compress(ctx->native,in.values,in.bytes,data.get()+wire::header+in.schema_size,bound,&used);
    if (rc_native != LN_OK) return fail(ctx,map(rc_native,false),"native ln_compress failed");
    const auto packed = wire::encode_header(magic,in,bound,used,std::move(data),out);
    if (packed != BMK_OK) return fail(ctx,packed,"native length outside bound");
    ctx->operation = "encode"; ctx->blocks = in.bytes ? 1 : 0; ctx->reason = "";
    return BMK_OK;
}
bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Frame f;
    const auto rc = wire::read(magic,p,n,LN_MAX_BLOCK,f);
    if (rc != BMK_OK) return fail(ctx,rc,"invalid XZ envelope");
    if (f.payload_size > ln_compress_bound(LN_XZ,LN_MAX_BLOCK))
        return fail(ctx,BMK_RESOURCE_LIMIT,"oversize XZ stream");
    if (!baseline_shape(f)) return fail(ctx,BMK_CORRUPT,"XZ stream outside baseline shape");
    auto object = wire::allocate(f);
    if (!object) return fail(ctx,BMK_NO_MEMORY,"decoded allocation failed");
    size_t got{};
    const auto native = ln_decompress(ctx->native,f.payload,f.payload_size,object->buffer.get(),f.bytes,f.bytes,&got);
    if (native != LN_OK) return fail(ctx,map(native,true),"native ln_decompress failed");
    if (got != f.bytes) return fail(ctx,BMK_CORRUPT,"decoded byte count mismatch");
    wire::decoded(out,f,std::move(object));
    ctx->operation = "decode"; ctx->blocks = f.bytes ? 1 : 0; ctx->reason = "";
    return BMK_OK;
}
bmk_status info(bmk_context *ctx, bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    char json[192];
    const int n = std::snprintf(json,sizeof(json),"{\"backend\":\"ln-xz-baseline\",\"mode\":\"batch\",\"threads\":1,"
        "\"fallback\":false,\"blocks\":%u,\"check\":\"none\",\"operation\":\"%s\"%s}",ctx->blocks,ctx->operation,
        ctx->operation[0]=='e' ? ",\"preset\":6" : "");
    return n < 0 || static_cast<size_t>(n) >= sizeof(json) ? BMK_INTERNAL : wire::text(out,{json,static_cast<size_t>(n)});
}
bmk_status error_text(bmk_context *ctx,char *dst,uint64_t n) noexcept {
    return ctx ? wire::error(dst,n,ctx->reason) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { if (ctx) { ln_destroy(ctx->native); delete ctx; } }
const bmk_plugin_v1 abi{sizeof(abi),BMK_ABI_V1,"xz-baseline",probe,create,reset,encode,decode,info,error_text,destroy,wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &abi : nullptr; }
