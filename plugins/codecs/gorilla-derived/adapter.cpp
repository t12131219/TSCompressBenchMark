#include "column.h"
#include "linear_frame.hpp"

namespace wire = tsbench::linear;
struct bmk_context { const char *operation{}; const char *reason{""}; };

namespace {
constexpr size_t limit = BMK_GORILLA_COLUMN_ROWS * 8;
#if BMK_GORILLA_TIMESTAMP
#define BMK_ROLE "timestamp"
#define BMK_BACKEND "gorilla-t-c11-derived"
constexpr auto plugin = "gorilla-t-derived";
constexpr uint32_t dtype = BMK_I64;
constexpr wire::Magic magic{'B','M','K','G','T','1',0,0};
#else
#define BMK_ROLE "value"
#define BMK_BACKEND "gorilla-v-c11-derived"
constexpr auto plugin = "gorilla-v-derived";
constexpr uint32_t dtype = BMK_F64;
constexpr wire::Magic magic{'B','M','K','G','V','1',0,0};
#endif

bool options(const uint8_t *p, uint64_t n) noexcept {
    wire::Options json(p,n);
    return json.token("{") && json.token("}") && json.done();
}
bool schema(const uint8_t *p, size_t n) noexcept {
#if BMK_GORILLA_TIMESTAMP
    wire::Options json(p,n);
    return json.token("{") && json.token("\"time_unit\"") && json.token(":") &&
           json.token("\"ms\"") && json.token("}") && json.done();
#else
    (void)p; (void)n;
    return true;  // Value schema is opaque and retained verbatim.
#endif
}
bmk_status inspect(const bmk_object_view *object, wire::Input &input) noexcept {
    const auto status = wire::view(object,limit,input);
    if (status != BMK_OK) return status;
    return input.dtype == dtype && schema(input.schema,input.schema_size) ? BMK_OK : BMK_UNSUPPORTED;
}
bmk_status fail(bmk_context *ctx, bmk_status status, const char *reason) noexcept {
    if (ctx) { ctx->operation = nullptr; ctx->reason = reason; }
    return status;
}
bmk_status probe(const bmk_object_view *input, const uint8_t *p, uint64_t n, bmk_blob *out) noexcept {
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    wire::Input column;
    const auto status = inspect(input,column);
    if (status != BMK_OK) return status;
    return wire::text(out,"{\"mode\":\"batch\",\"role\":\"" BMK_ROLE "\",\"max_rows\":512}");
}
bmk_status create(const bmk_host_v1 *host, const uint8_t *p, uint64_t n, bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    *out = new (std::nothrow) bmk_context;
    return *out ? BMK_OK : BMK_NO_MEMORY;
}
bmk_status reset(bmk_context *ctx, uint32_t kind) noexcept {
    if (!ctx || kind) return fail(ctx,BMK_UNSUPPORTED,"unsupported reset");
    *ctx = {};
    return BMK_OK;
}
bmk_status encode(bmk_context *ctx, const bmk_object_view *object, bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output owner");
    wire::Input input;
    const auto status = inspect(object,input);
    if (status != BMK_OK) return fail(ctx,status,"unsupported column or schema for Gorilla role");
    const auto bound = bmk_gorilla_column_bound(input.count);
    std::unique_ptr<uint8_t[]> frame(new (std::nothrow) uint8_t[wire::header + input.schema_size + bound]);
    if (!frame) return fail(ctx,BMK_NO_MEMORY,"allocation failed");
    const auto used = bmk_gorilla_column_encode(input.values,input.count,
                     frame.get() + wire::header + input.schema_size,bound);
    const auto rc = wire::encode_header(magic,input,bound,used,std::move(frame),out);
    if (rc != BMK_OK) return fail(ctx,rc,"invalid derived payload size");
    ctx->operation = "encode"; ctx->reason = "";
    return BMK_OK;
}
bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output owner");
    wire::Frame frame;
    const auto status = wire::read(magic,p,n,limit,frame);
    if (status != BMK_OK) return fail(ctx,status,"invalid Gorilla role envelope");
    if (frame.dtype != dtype || !schema(frame.schema,frame.schema_size) ||
        frame.payload_size > bmk_gorilla_column_bound(frame.count))
        return fail(ctx,BMK_CORRUPT,"Gorilla role, schema or payload bound differs");
    auto object = wire::allocate(frame);
    if (!object) return fail(ctx,BMK_NO_MEMORY,"allocation failed");
    if (!bmk_gorilla_column_decode(frame.payload,frame.payload_size,frame.count,object->buffer.get()))
        return fail(ctx,BMK_CORRUPT,"invalid Gorilla role payload");
    wire::decoded(out,frame,std::move(object));
    ctx->operation = "decode"; ctx->reason = "";
    return BMK_OK;
}
bmk_status info(bmk_context *ctx, bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    return wire::text(out,ctx->operation[0]=='e' ?
        "{\"backend\":\"" BMK_BACKEND "\",\"mode\":\"batch\",\"threads\":1,\"blocks\":1,\"operation\":\"encode\"}" :
        "{\"backend\":\"" BMK_BACKEND "\",\"mode\":\"batch\",\"threads\":1,\"blocks\":1,\"operation\":\"decode\"}");
}
bmk_status error(bmk_context *ctx, char *out, uint64_t n) noexcept {
    return ctx ? wire::error(out,n,ctx->reason) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
constexpr bmk_plugin_v1 api{sizeof(api),BMK_ABI_V1,plugin,probe,create,reset,encode,decode,info,error,destroy,wire::extension};
}

extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t v) { return v == BMK_ABI_V1 ? &api : nullptr; }
