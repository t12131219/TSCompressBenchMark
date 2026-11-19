#include "linear_frame.hpp"
#include "pcodec.h"

namespace wire = tsbench::linear;
struct bmk_context {
    const char *info{};
    const char *reason{""};
};
namespace {
#ifdef BMK_PCODEC_C_NATIVE
constexpr char id[] = "pcodec-c-native-auto";
constexpr wire::Magic magic{'B','M','K','P','C','N',1,0};
constexpr char encode_info[] = R"({"backend":"c-native-auto","entry":"pc_compress_native","mode":"batch","threads":1,"operation":"encode","selected_modes":null,"fallback":null})";
constexpr auto compress = pc_compress_native;
constexpr bool has_f16 = false;
#else
constexpr char id[] = "pcodec-source-auto";
constexpr wire::Magic magic{'B','M','K','P','C','S',1,0};
constexpr char encode_info[] = R"({"backend":"rust-source-auto","entry":"pc_compress","mode":"batch","threads":1,"operation":"encode","selected_modes":null,"fallback":null})";
constexpr auto compress = pc_compress;
constexpr bool has_f16 = true;
#endif
constexpr char decode_info[] = R"({"backend":"rust-source","entry":"pc_decompress_bounded","mode":"batch","threads":1,"operation":"decode"})";
constexpr auto payload_limit = 2 * wire::logical_limit - wire::header;  // CPU worker transport bound

int type(uint32_t dtype) noexcept {
    switch (dtype) {
    case BMK_I8: return PC_I8;
    case BMK_U8: return PC_U8;
    case BMK_I16: return PC_I16;
    case BMK_U16: return PC_U16;
    case BMK_I32: return PC_I32;
    case BMK_U32: return PC_U32;
    case BMK_I64: return PC_I64;
    case BMK_U64: return PC_U64;
    case BMK_F16: return has_f16 ? PC_F16 : 0;
    case BMK_F32: return PC_F32;
    case BMK_F64: return PC_F64;
    default: return 0;
    }
}
bool options(const uint8_t *p, uint64_t n) noexcept {
    wire::Options json(p,n);
    return json.token("{") && json.token("}") && json.done();
}
bmk_status fail(bmk_context *ctx, bmk_status status, const char *reason) noexcept {
    if (ctx) { ctx->info = nullptr; ctx->reason = reason; }
    return status;
}
bmk_status native_fail(bmk_context *ctx, int code, bool decode) noexcept {
    bmk_status status = BMK_INTERNAL;
    switch (code) {
    case PC_INVALID: status = decode ? BMK_CORRUPT : BMK_BAD_INPUT; break;
    case PC_NOMEM: status = BMK_NO_MEMORY; break;
    case PC_TRUNCATED: case PC_CORRUPT: status = BMK_CORRUPT; break;
    case PC_UNSUPPORTED: status = BMK_UNSUPPORTED; break;
    case PC_LIMIT: status = BMK_RESOURCE_LIMIT; break;
    }
    return fail(ctx,status,pc_error(code));
}
bmk_status probe(const bmk_object_view *obj, const uint8_t *p, uint64_t n, bmk_blob *out) noexcept {
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    wire::Input in;
    const auto status = wire::view(obj,wire::logical_limit,in);
    if (status != BMK_OK) return status;
    if (!type(in.dtype) || !pc_source_backend_available()) return BMK_UNSUPPORTED;
    return wire::text(out,encode_info);
}
bmk_status create(const bmk_host_v1 *host, const uint8_t *p, uint64_t n, bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    if (!pc_source_backend_available()) return BMK_UNSUPPORTED;
    *out = new (std::nothrow) bmk_context;
    return *out ? BMK_OK : BMK_NO_MEMORY;
}
bmk_status reset(bmk_context *ctx, uint32_t kind) noexcept {
    if (!ctx || kind != 0) return fail(ctx,BMK_UNSUPPORTED,"unsupported reset");
    return fail(ctx,BMK_OK,"");
}
bmk_status encode(bmk_context *ctx, const bmk_object_view *obj, bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Input in;
    const auto status = wire::view(obj,wire::logical_limit,in);
    if (status != BMK_OK) return fail(ctx,status,"pcodec requires one dense typed column up to 64 MiB");
    const int t = type(in.dtype);
    if (!t) return fail(ctx,BMK_UNSUPPORTED,"dtype unsupported by selected pcodec entry");
    // Native pcodec consumes untyped bytes, including binary16 bit patterns.
    uint8_t *raw = nullptr;
    size_t used = 0;
    const auto config = pc_default_config();
    const int code = compress(in.values,in.count,t,&config,&raw,&used);
    std::unique_ptr<uint8_t,decltype(&pc_free)> owner(raw,pc_free);
    if (code != PC_OK) return native_fail(ctx,code,false);
    if (!raw || !used) return fail(ctx,BMK_INTERNAL,"missing native payload");
    if (used > payload_limit) return fail(ctx,BMK_RESOURCE_LIMIT,"pcodec payload exceeds worker transport bound");
    std::unique_ptr<uint8_t[]> data(new (std::nothrow) uint8_t[wire::header + in.schema_size + used]);
    if (!data) return fail(ctx,BMK_NO_MEMORY,"frame allocation failed");
    std::memcpy(data.get()+wire::header+in.schema_size,raw,used);
    const auto packed = wire::encode_header(magic,in,used,used,std::move(data),out);
    if (packed != BMK_OK) return fail(ctx,packed,"invalid native payload length");
    ctx->info = encode_info; ctx->reason = "";
    return BMK_OK;
}
bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Frame frame;
    const auto status = wire::read(magic,p,n,wire::logical_limit,frame);
    if (status != BMK_OK) return fail(ctx,status,"invalid pcodec envelope");
    const int t = type(frame.dtype);
    if (!t) return fail(ctx,BMK_CORRUPT,"unsupported pcodec envelope dtype");
    if (frame.payload_size > payload_limit) return fail(ctx,BMK_RESOURCE_LIMIT,"pcodec payload exceeds worker transport bound");
    void *raw = nullptr;
    size_t got = 0;
    const int code = pc_decompress_bounded(frame.payload,frame.payload_size,t,frame.count,&raw,&got);
    std::unique_ptr<void,decltype(&pc_free)> owner(raw,pc_free);
    if (code != PC_OK) return native_fail(ctx,code,true);
    if (got != frame.count || (got && !raw)) return fail(ctx,BMK_CORRUPT,"pcodec decoded count mismatch");
    auto object = wire::allocate(frame);
    if (!object) return fail(ctx,BMK_NO_MEMORY,"decoded object allocation failed");
    if (frame.bytes) std::memcpy(object->buffer.get(),raw,frame.bytes);
    wire::decoded(out,frame,std::move(object));
    ctx->info = decode_info; ctx->reason = "";
    return BMK_OK;
}
bmk_status info(bmk_context *ctx, bmk_blob *out) noexcept {
    return ctx && ctx->info ? wire::text(out,ctx->info) : BMK_BAD_INPUT;
}
bmk_status error_text(bmk_context *ctx, char *dst, uint64_t n) noexcept {
    return ctx ? wire::error(dst,n,ctx->reason) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
const bmk_plugin_v1 abi{sizeof(abi),BMK_ABI_V1,id,probe,create,reset,encode,decode,info,error_text,destroy,wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &abi : nullptr; }
