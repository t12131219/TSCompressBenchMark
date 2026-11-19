#include "linear_frame.hpp"
#include "titchy.h"

namespace wire = tsbench::linear;
struct bmk_context {
    const char *info{};
    const char *error{""};
};
namespace {
constexpr char id[] = "titchy-batch";
constexpr wire::Magic magic{'B','M','K','T','C','H',1,0};
constexpr size_t native_header = 38, max_values = 1000000;
constexpr char encode_info[] = R"({"backend":"titchy-c11","entry":"titchy_c_encode","mode":"batch","threads":1,"operation":"encode"})";
constexpr char decode_info[] = R"({"backend":"titchy-c11","entry":"titchy_c_decode","mode":"batch","threads":1,"operation":"decode"})";

unsigned width(uint32_t dtype) noexcept {
    switch (dtype) {
    case BMK_U8: case BMK_U16: case BMK_U32: case BMK_U64: return wire::width(dtype);
    default: return 0;
    }
}
constexpr titchy_config config(unsigned item) noexcept {
    return {static_cast<uint8_t>(8 * item),4,1000,0,.25,UINT64_MAX};
}
bool valid_options(const uint8_t *p, uint64_t n) noexcept {
    wire::Options json(p,n);
    return json.token("{") && json.token("}") && json.done();
}
bmk_status fail(bmk_context *ctx, bmk_status status, const char *reason) noexcept {
    if (ctx) { ctx->info = nullptr; ctx->error = reason; }
    return status;
}
bmk_status native_error(bmk_context *ctx, int rc, bool decoding) noexcept {
    switch (rc) {
    case TITCHY_MEMORY: return fail(ctx,BMK_NO_MEMORY,"native Titchy allocation failed");
    case TITCHY_CAPACITY: return fail(ctx,decoding ? BMK_CORRUPT : BMK_INTERNAL,"native bounds disagreed with frozen format");
    case TITCHY_STREAM: return fail(ctx,BMK_CORRUPT,"native Titchy container rejected");
    case TITCHY_INVALID: return fail(ctx,decoding ? BMK_CORRUPT : BMK_BAD_INPUT,"native Titchy invalid arguments");
    default: return fail(ctx,BMK_INTERNAL,"unknown native Titchy status");
    }
}
bmk_status check_input(const bmk_object_view *obj, wire::Input &in, unsigned &item) noexcept {
    const auto status = wire::view(obj,wire::logical_limit,in);
    if (status != BMK_OK) return status;
    item = width(in.dtype);
    if (!item) return BMK_UNSUPPORTED;
    return in.count > max_values ? BMK_RESOURCE_LIMIT : BMK_OK;
}
bmk_status probe(const bmk_object_view *obj, const uint8_t *p, uint64_t n, bmk_blob *out) noexcept {
    if (!valid_options(p,n)) return BMK_BAD_OPTIONS;
    wire::Input in;
    unsigned item;
    const auto status = check_input(obj,in,item);
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
bmk_status encode(bmk_context *ctx, const bmk_object_view *obj, bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Input in;
    unsigned item;
    const auto status = check_input(obj,in,item);
    if (status != BMK_OK) return fail(ctx,status,"Titchy needs one dense unsigned column and at most 1000000 samples");
    const auto cfg = config(item);
    const size_t bound = titchy_bound(in.count,&cfg);
    if (!bound) return fail(ctx,BMK_INTERNAL,"native bound unavailable");
    std::unique_ptr<uint64_t[]> samples(in.count ? new (std::nothrow) uint64_t[in.count] : nullptr);
    std::unique_ptr<uint8_t[]> artifact(new (std::nothrow) uint8_t[wire::header + in.schema_size + bound]);
    if ((in.count && !samples) || !artifact) return fail(ctx,BMK_NO_MEMORY,"Titchy work buffer allocation failed");
    for (size_t i = 0; i < in.count; ++i) samples[i] = wire::get(in.values + i * item,item);
    size_t used = 0;
    const int rc = titchy_c_encode(samples.get(),in.count,&cfg,artifact.get() + wire::header + in.schema_size,bound,&used);
    if (rc != TITCHY_OK) return native_error(ctx,rc,false);
    const auto packed = wire::encode_header(magic,in,bound,used,std::move(artifact),out);
    if (packed != BMK_OK) return fail(ctx,packed,"native length outside bound");
    ctx->info = encode_info; ctx->error = "";
    return BMK_OK;
}
bool matches(const wire::Frame &f, unsigned item) noexcept {
    // Bind the outer dtype/count and method parameters to the native TCHY v2
    // header before allocating values. Full container validation remains native.
    const auto *p = f.payload;
    return f.payload_size >= native_header && std::memcmp(p,"TCHY\2",5) == 0 &&
           p[5] == item * 8 && p[6] == 4 && p[7] == 0 && wire::get(p+8,2) == 1000 &&
           wire::get(p+10,4) == 250000 && wire::get(p+14,8) == UINT64_MAX && wire::get(p+22,8) == f.count;
}
bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    wire::Frame f;
    const auto status = wire::read(magic,p,n,wire::logical_limit,f);
    if (status != BMK_OK) return fail(ctx,status,"invalid Titchy envelope");
    if (f.count > max_values) return fail(ctx,BMK_RESOURCE_LIMIT,"sample count exceeds Titchy limit");
    const auto item = width(f.dtype);
    if (!item || !matches(f,item)) return fail(ctx,BMK_CORRUPT,"Titchy header differs from method or envelope");
    const auto cfg = config(item);
    if (f.payload_size > titchy_bound(f.count,&cfg)) return fail(ctx,BMK_CORRUPT,"Titchy payload exceeds proved bound");
    std::unique_ptr<uint64_t[]> samples(f.count ? new (std::nothrow) uint64_t[f.count] : nullptr);
    if (f.count && !samples) return fail(ctx,BMK_NO_MEMORY,"Titchy work buffer allocation failed");
    size_t got = 0;
    const int rc = titchy_c_decode(f.payload,f.payload_size,samples.get(),f.count,f.count,&got);
    if (rc != TITCHY_OK) return native_error(ctx,rc,true);
    if (got != f.count) return fail(ctx,BMK_CORRUPT,"native count mismatch");
    auto object = wire::allocate(f);
    if (!object) return fail(ctx,BMK_NO_MEMORY,"decoded object allocation failed");
    for (size_t i = 0; i < f.count; ++i) wire::put(object->buffer.get() + i * item,item,samples[i]);
    wire::decoded(out,f,std::move(object));
    ctx->info = decode_info; ctx->error = "";
    return BMK_OK;
}
bmk_status info(bmk_context *ctx, bmk_blob *out) noexcept {
    return ctx && ctx->info ? wire::text(out,ctx->info) : BMK_BAD_INPUT;
}
bmk_status error_text(bmk_context *ctx, char *dst, uint64_t n) noexcept {
    return ctx ? wire::error(dst,n,ctx->error) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
const bmk_plugin_v1 abi{sizeof(abi),BMK_ABI_V1,id,probe,create,reset,encode,decode,info,error_text,destroy,wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &abi : nullptr; }
