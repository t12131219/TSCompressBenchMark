#include "linear_frame.hpp"
#include "zfp_native.h"

namespace wire = tsbench::linear;
struct bmk_context {
    const char *info{};
    const char *error{""};
};
namespace {
constexpr char id[] = "zfp-reversible";
constexpr wire::Magic magic{'B','M','K','Z','F','P',1,0};
constexpr char encode_info[] = R"({"backend":"zfp-c11-serial","entry":"zn_encode","mode":"batch","quality":"reversible","threads":1,"operation":"encode"})";
constexpr char decode_info[] = R"({"backend":"zfp-c11-serial","entry":"zn_decode","mode":"batch","quality":"reversible","threads":1,"operation":"decode"})";
constexpr size_t payload_limit = 2 * wire::logical_limit - wire::header;
using Context = std::unique_ptr<zn_context, decltype(&zn_destroy)>;

bool valid_options(const uint8_t *p, uint64_t n) noexcept {
    wire::Options json(p,n);
    return json.token("{") && json.token("}") && json.done();
}
bool supported(uint32_t dtype) noexcept {
    return dtype == BMK_I32 || dtype == BMK_I64 || dtype == BMK_F32 || dtype == BMK_F64;
}
bmk_status fail(bmk_context *ctx, bmk_status code, const char *why) noexcept {
    if (ctx) { ctx->info = nullptr; ctx->error = why; }
    return code;
}
bmk_status native_error(bmk_context *ctx, zn_status rc, bool decoding) noexcept {
    const auto status = rc == ZN_NOMEM ? BMK_NO_MEMORY : decoding ? BMK_CORRUPT : BMK_INTERNAL;
    return fail(ctx,status,zn_error(rc));
}
bmk_status check_input(const bmk_object_view *object, wire::Input &in) noexcept {
    const auto status = wire::view(object,wire::logical_limit,in);
    if (status != BMK_OK) return status;
    return supported(in.dtype) && in.count ? BMK_OK : BMK_UNSUPPORTED;
}
bmk_status probe(const bmk_object_view *object, const uint8_t *p, uint64_t n, bmk_blob *out) noexcept {
    if (!valid_options(p,n)) return BMK_BAD_OPTIONS;
    wire::Input in;
    const auto status = check_input(object,in);
    return status == BMK_OK ? wire::text(out,encode_info) : status;
}
bmk_status create(const bmk_host_v1 *host, const uint8_t *p, uint64_t n, bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    if (!valid_options(p,n)) return BMK_BAD_OPTIONS;
    *out = new (std::nothrow) bmk_context;
    return *out ? BMK_OK : BMK_NO_MEMORY;
}
bmk_status reset(bmk_context *ctx, uint32_t kind) noexcept {
    if (!ctx || kind != 0) return fail(ctx,BMK_UNSUPPORTED,"unsupported reset");
    return fail(ctx,BMK_OK,"");
}
// Use typed, aligned storage; the ABI's borrowed span may be byte-aligned.
// memcpy preserves the original IEEE bits, including NaN payloads.
template<typename T, zn_type type>
bmk_status pack(bmk_context *ctx, const wire::Input &in, bmk_blob *out) noexcept {
    const auto cfg = zn_config_1d(type,in.count);
    zn_context *raw = nullptr;
    const auto rc = zn_create(&cfg,&raw);
    Context native(raw,zn_destroy);
    if (rc != ZN_OK) return native_error(ctx,rc,false);
    std::unique_ptr<T[]> input(new (std::nothrow) T[in.count]);
    if (!input) return fail(ctx,BMK_NO_MEMORY,"aligned ZFP input allocation failed");
    std::memcpy(input.get(),in.values,in.bytes);
    size_t used = 0;
    const auto status = zn_encode(native.get(),input.get(),in.bytes,&used);
    if (status != ZN_OK) return native_error(ctx,status,false);
    if (!used || used % 8 || used > zn_capacity(native.get())) return fail(ctx,BMK_INTERNAL,"invalid native ZFP length");
    if (used > payload_limit) return fail(ctx,BMK_RESOURCE_LIMIT,"ZFP exceeds worker transport bound");
    std::unique_ptr<uint8_t[]> data(new (std::nothrow) uint8_t[wire::header + in.schema_size + used]);
    if (!data) return fail(ctx,BMK_NO_MEMORY,"ZFP frame allocation failed");
    std::memcpy(data.get() + wire::header + in.schema_size,zn_data(native.get()),used);
    const auto packed = wire::encode_header(magic,in,used,used,std::move(data),out);
    if (packed != BMK_OK) return fail(ctx,packed,"ZFP envelope creation failed");
    ctx->info = encode_info; ctx->error = "";
    return BMK_OK;
}
bmk_status encode(bmk_context *ctx, const bmk_object_view *object, bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Input in;
    const auto status = check_input(object,in);
    if (status != BMK_OK) return fail(ctx,status,"ZFP reversible needs one nonempty dense i32/i64/f32/f64 column");
    switch (in.dtype) {
    case BMK_I32: return pack<int32_t,ZN_I32>(ctx,in,out);
    case BMK_I64: return pack<int64_t,ZN_I64>(ctx,in,out);
    case BMK_F32: return pack<float,ZN_F32>(ctx,in,out);
    default: return pack<double,ZN_F64>(ctx,in,out);
    }
}
template<typename T, zn_type type>
bmk_status unpack(bmk_context *ctx, const wire::Frame &f, bmk_owned_object *out) noexcept {
    const auto cfg = zn_config_1d(type,f.count);
    zn_context *raw = nullptr;
    const auto rc = zn_create(&cfg,&raw);
    Context native(raw,zn_destroy);
    if (rc != ZN_OK) return native_error(ctx,rc,true);
    if (f.payload_size > zn_capacity(native.get())) return fail(ctx,BMK_CORRUPT,"ZFP payload exceeds native bound");
    std::unique_ptr<T[]> vals(new (std::nothrow) T[f.count]);
    if (!vals) return fail(ctx,BMK_NO_MEMORY,"aligned ZFP output allocation failed");
    // The frozen raw codec requires trusted payloads with matching metadata.
    // These envelope checks are not a validator for arbitrary raw ZFP input.
    const auto status = zn_decode(native.get(),f.payload,f.payload_size,vals.get(),f.bytes);
    if (status != ZN_OK) return native_error(ctx,status,true);
    auto object = wire::allocate(f);
    if (!object) return fail(ctx,BMK_NO_MEMORY,"decoded object allocation failed");
    std::memcpy(object->buffer.get(),vals.get(),f.bytes);
    wire::decoded(out,f,std::move(object));
    ctx->info = decode_info; ctx->error = "";
    return BMK_OK;
}
bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Frame f;
    const auto status = wire::read(magic,p,n,wire::logical_limit,f);
    if (status != BMK_OK) return fail(ctx,status,"invalid ZFP envelope");
    if (!supported(f.dtype) || !f.count || f.payload_size % 8) return fail(ctx,BMK_CORRUPT,"invalid ZFP shape, dtype or word length");
    if (f.payload_size > payload_limit) return fail(ctx,BMK_RESOURCE_LIMIT,"ZFP exceeds worker transport bound");
    switch (f.dtype) {
    case BMK_I32: return unpack<int32_t,ZN_I32>(ctx,f,out);
    case BMK_I64: return unpack<int64_t,ZN_I64>(ctx,f,out);
    case BMK_F32: return unpack<float,ZN_F32>(ctx,f,out);
    default: return unpack<double,ZN_F64>(ctx,f,out);
    }
}
bmk_status info(bmk_context *ctx, bmk_blob *out) noexcept {
    return ctx && ctx->info ? wire::text(out,ctx->info) : BMK_BAD_INPUT;
}
bmk_status error_text(bmk_context *ctx, char *out, uint64_t n) noexcept {
    return ctx ? wire::error(out,n,ctx->error) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
const bmk_plugin_v1 abi{sizeof(abi),BMK_ABI_V1,id,probe,create,reset,encode,decode,info,error_text,destroy,wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &abi : nullptr; }
