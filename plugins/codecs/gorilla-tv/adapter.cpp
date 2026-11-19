#include "linear_frame.hpp"
#include "gorilla.h"

namespace wire = tsbench::linear;
struct bmk_context { const char *operation{}; const char *reason{""}; };

namespace {
constexpr size_t chunk_rows = 512, tv_header = 24;
constexpr wire::Magic magic{'B','M','K','G','T','V',1,0};
constexpr std::array<uint32_t, 2> types{BMK_I64, BMK_F64};

bool options(const uint8_t *p, uint64_t n) noexcept {
    wire::Options json(p, n);
    return json.token("{") && json.token("}") && json.done();
}
bool milliseconds(const uint8_t *p, uint64_t n) noexcept {
    wire::Options json(p, n);
    return json.token("{") && json.token("\"time_unit\"") && json.token(":") &&
           json.token("\"ms\"") && json.token("}") && json.done();
}
bmk_status inspect(const bmk_object_view *object, wire::Input (&cols)[2]) noexcept {
    if (!object || object->struct_size < sizeof(*object)) return BMK_BAD_INPUT;
    if (object->column_count != 2) return BMK_UNSUPPORTED;
    if (!object->columns || (object->schema_bytes && !object->schema_json)) return BMK_BAD_INPUT;
    if (object->schema_bytes > wire::schema_limit) return BMK_RESOURCE_LIMIT;
    if (!milliseconds(object->schema_json, object->schema_bytes)) return BMK_UNSUPPORTED;
    auto single = *object;
    single.column_count = 1;
    for (size_t i = 0; i < types.size(); ++i) {
        single.columns = object->columns + i;
        const auto status = wire::view(&single, chunk_rows * 8, cols[i]);
        if (status != BMK_OK) return status;
        if (cols[i].dtype != types[i]) return BMK_UNSUPPORTED;
    }
    return cols[0].count == cols[1].count ? BMK_OK : BMK_BAD_INPUT;
}
bmk_status fail(bmk_context *ctx, bmk_status status, const char *why) noexcept {
    if (ctx) { ctx->operation = nullptr; ctx->reason = why; }
    return status;
}
bmk_status probe(const bmk_object_view *input, const uint8_t *p, uint64_t n, bmk_blob *out) noexcept {
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    wire::Input cols[2];
    const auto status = inspect(input, cols);
    if (status != BMK_OK) return status;
    return wire::text(out, "{\"mode\":\"batch\",\"role\":\"timestamp_value\",\"time_unit\":\"ms\",\"max_rows\":512}");
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
    return !ctx || kind ? fail(ctx,BMK_UNSUPPORTED,"unsupported reset") : fail(ctx,BMK_OK,"");
}
bmk_status encode(bmk_context *ctx, const bmk_object_view *input, bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid context or output");
    wire::Input cols[2];
    const auto status = inspect(input, cols);
    if (status != BMK_OK) return fail(ctx,status,"expected equal dense i64(ms) and f64 columns of at most 512 rows");
    const auto &t = cols[0], &v = cols[1];
    std::array<g_sample, chunk_rows> samples;
    for (size_t i = 0; i < t.count; ++i) {
        std::memcpy(&samples[i].timestamp, t.values + 8*i, 8);
        std::memcpy(&samples[i].bits, v.values + 8*i, 8);
    }
    g_buffer native{};
    const auto rc = g_compress(samples.data(), t.count, &native);
    const std::unique_ptr<uint8_t, decltype(&g_free)> guard(native.data, g_free);
    if (rc != G_OK) return fail(ctx,rc == G_NOMEM ? BMK_NO_MEMORY : BMK_INTERNAL,g_strerror(rc));
    size_t bound = 0;
    if (g_compress_bound(t.count, &bound) != G_OK || native.size < 2 || native.size > bound || !native.data)
        return fail(ctx,BMK_INTERNAL,"invalid native chunk size");
    const auto total = tv_header + t.schema_size + native.size;
    std::unique_ptr<uint8_t[]> frame(new (std::nothrow) uint8_t[total]);
    if (!frame) return fail(ctx,BMK_NO_MEMORY,"allocation failed");
    std::memcpy(frame.get(), magic.data(), magic.size());
    wire::put(frame.get() + 8, 4, t.schema_size);
    wire::put(frame.get() + 12, 4, t.count);
    wire::put(frame.get() + 16, 8, native.size);
    std::memcpy(frame.get() + tv_header, t.schema, t.schema_size);
    std::memcpy(frame.get() + tv_header + t.schema_size, native.data, native.size);
    wire::blob(out, std::move(frame), total, total);
    ctx->operation = "encode"; ctx->reason = "";
    return BMK_OK;
}
struct Storage { bmk_array_view columns[2]{}; std::unique_ptr<uint8_t[]> bytes; };
void release(bmk_owned_object *out) noexcept {
    delete static_cast<Storage *>(out->owner);
    *out = {}; out->struct_size = sizeof(*out);
}
bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid context or output");
    if (!p || n < tv_header || std::memcmp(p, magic.data(), magic.size()))
        return fail(ctx,BMK_CORRUPT,"invalid TV envelope");
    const auto schema = wire::get(p + 8, 4), count = wire::get(p + 12, 4), size = wire::get(p + 16, 8);
    if (schema > wire::schema_limit || count > chunk_rows) return fail(ctx,BMK_RESOURCE_LIMIT,"TV envelope exceeds bound");
    size_t bound = 0;
    if (schema > n - tv_header || size != n - tv_header - schema || size < 2 ||
        g_compress_bound(count, &bound) != G_OK || size > bound || !milliseconds(p + tv_header, schema))
        return fail(ctx,BMK_CORRUPT,"invalid TV lengths or semantics");
    const auto *payload = p + tv_header + schema;
    if (uint64_t(payload[0])*256 + payload[1] != count) return fail(ctx,BMK_CORRUPT,"native and envelope counts differ");
    g_array decoded{};
    const auto rc = g_decompress(payload, size, count, &decoded);
    const std::unique_ptr<g_sample, decltype(&g_free)> guard(decoded.data, g_free);
    if (rc != G_OK) return fail(ctx,rc == G_NOMEM ? BMK_NO_MEMORY : BMK_CORRUPT,g_strerror(rc));
    if (decoded.count != count || (count && !decoded.data)) return fail(ctx,BMK_CORRUPT,"decoded count differs");
    std::unique_ptr<Storage> result(new (std::nothrow) Storage);
    if (!result) return fail(ctx,BMK_NO_MEMORY,"allocation failed");
    const size_t bytes = count * 8;
    result->bytes.reset(new (std::nothrow) uint8_t[2 * bytes + schema]);
    if (!result->bytes) return fail(ctx,BMK_NO_MEMORY,"allocation failed");
    auto *storage = result->bytes.get();
    auto *schema_out = storage + 2 * bytes;
    for (size_t i = 0; i < count; ++i) {
        std::memcpy(storage + 8*i, &decoded.data[i].timestamp, 8);
        std::memcpy(storage + bytes + 8*i, &decoded.data[i].bits, 8);
    }
    for (size_t i = 0; i < types.size(); ++i) {
        auto &col = result->columns[i];
        col.struct_size = sizeof(col); col.dtype = types[i]; col.rank = 1;
        col.storage = storage + i*bytes; col.storage_bytes = bytes;
        col.shape[0] = count; col.strides_bytes[0] = 8;
    }
    std::memcpy(schema_out, p + tv_header, schema);
    auto *owner = result.release();
    *out = {sizeof(*out), 0, {sizeof(bmk_object_view), 2, owner->columns, schema_out, schema}, owner, release};
    ctx->operation = "decode"; ctx->reason = "";
    return BMK_OK;
}
bmk_status info(bmk_context *ctx, bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    return wire::text(out,ctx->operation[0] == 'e' ?
        "{\"backend\":\"gorilla-c11\",\"mode\":\"batch\",\"threads\":1,\"blocks\":1,\"operation\":\"encode\"}" :
        "{\"backend\":\"gorilla-c11\",\"mode\":\"batch\",\"threads\":1,\"blocks\":1,\"operation\":\"decode\"}");
}
bmk_status error(bmk_context *ctx, char *out, uint64_t n) noexcept {
    return ctx ? wire::error(out,n,ctx->reason) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
const bmk_plugin_v1 api{sizeof(api),BMK_ABI_V1,"gorilla-tv",probe,create,reset,encode,decode,info,error,destroy,wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &api : nullptr; }
