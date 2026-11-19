#include "linear_frame.hpp"
#include "corad.h"

#include <cmath>
#include <cstdio>

namespace wire = tsbench::linear;
namespace {
constexpr wire::Magic frame_magic{'B','M','K','C','R','D',1,0}, deploy_magic{'B','M','K','C','D','P',1,0};
constexpr size_t frame_header = 24, deploy_header = 16, native_header = 32;
constexpr size_t max_values = 131072, max_cols = 64, max_schema = 4096, max_model = 16384;
using Model = std::unique_ptr<corad_model, decltype(&corad_model_free)>;

struct Bytes {
    const uint8_t *data{};
    size_t size{};
    bool equal(const Bytes rhs) const noexcept {
        return size == rhs.size && (!size || !std::memcmp(data,rhs.data,size));
    }
};
struct Deployment {
    Model model{nullptr,corad_model_free};
    std::unique_ptr<uint8_t[]> storage;
    Bytes schema, model_bytes;
    corad_config frozen{};
};
struct Storage {
    std::array<bmk_array_view,max_cols> columns{};
    std::unique_ptr<double[]> values;
    std::unique_ptr<uint8_t[]> schema;
};
void release(bmk_owned_object *out) noexcept {
    delete static_cast<Storage *>(out->owner);
    *out = {}; out->struct_size = sizeof(*out);
}
bool token(std::string_view &text, std::string_view prefix) noexcept {
    text.remove_prefix(std::min(text.size(),text.find_first_not_of(" \t\r\n")));
    if (text.substr(0,prefix.size()) != prefix) return false;
    text.remove_prefix(prefix.size());
    return true;
}
int nibble(char c) noexcept { return c >= '0' && c <= '9' ? c-'0' : c >= 'a' && c <= 'f' ? c-'a'+10 : -1; }

bmk_status deployment(const uint8_t *options, uint64_t n, Deployment &out) noexcept {
    if (!options || !n || n > wire::schema_limit) return BMK_BAD_OPTIONS;
    std::string_view text(reinterpret_cast<const char *>(options),static_cast<size_t>(n));
    if (!token(text,"{")) return BMK_BAD_OPTIONS;
    if (token(text,"}")) return token(text,"") && text.empty() ? BMK_OK : BMK_BAD_OPTIONS;
    if (!token(text,"\"deployment\"") || !token(text,":") || !token(text,"\"")) return BMK_BAD_OPTIONS;
    const size_t chars = text.find('"');
    if (chars == text.npos || chars % 2 || chars / 2 < deploy_header ||
        chars / 2 > deploy_header + max_model + max_schema) return BMK_BAD_OPTIONS;
    out.storage.reset(new (std::nothrow) uint8_t[chars/2]);
    if (!out.storage) return BMK_NO_MEMORY;
    auto *raw = out.storage.get();
    for (size_t i = 0; i < chars / 2; ++i) {
        const int hi = nibble(text[2*i]), lo = nibble(text[2*i+1]);
        if (hi < 0 || lo < 0) return BMK_BAD_OPTIONS;
        raw[i] = static_cast<uint8_t>((hi<<4)|lo);
    }
    text.remove_prefix(chars+1);
    if (!token(text,"}") || !token(text,"") || !text.empty() ||
        std::memcmp(raw,deploy_magic.data(),deploy_magic.size())) return BMK_BAD_OPTIONS;
    const auto schema = wire::get(raw+8,4), model = wire::get(raw+12,4);
    if (!schema || schema > max_schema || model < native_header || model > max_model ||
        deploy_header+schema+model != chars/2) return BMK_BAD_OPTIONS;
    out.schema = {raw+deploy_header,static_cast<size_t>(schema)};
    out.model_bytes = {out.schema.data+schema,static_cast<size_t>(model)};
    corad_model *ptr{};
    const int rc = corad_model_load(out.model_bytes.data,out.model_bytes.size,&ptr);
    out.model.reset(ptr);
    if (rc == CORAD_MEMORY) return BMK_NO_MEMORY;
    if (rc != CORAD_OK || !ptr || corad_model_info(ptr,&out.frozen) != CORAD_OK) return BMK_BAD_OPTIONS;
    return BMK_OK;
}

bmk_status inspect(const bmk_object_view *object, const Deployment &dep,
                   std::array<wire::Input,max_cols> &inputs) noexcept {
    if (!dep.model) return BMK_BAD_OPTIONS;
    if (!object || object->struct_size < sizeof(*object) || !object->columns ||
        (object->schema_bytes && !object->schema_json)) return BMK_BAD_INPUT;
    if (object->schema_bytes > max_schema) return BMK_RESOURCE_LIMIT;
    if (object->column_count != dep.frozen.columns ||
        !dep.schema.equal({object->schema_json,static_cast<size_t>(object->schema_bytes)})) return BMK_BAD_INPUT;
    auto single = *object;
    single.column_count = 1;
    for (unsigned i = 0; i < object->column_count; ++i) {
        single.columns = object->columns+i;
        const auto rc = wire::view(&single,max_values*8/object->column_count,inputs[i]);
        if (rc != BMK_OK) return rc;
        if (inputs[i].dtype != BMK_F64) return BMK_UNSUPPORTED;
        if (inputs[i].count != inputs[0].count) return BMK_BAD_INPUT;
    }
    return BMK_OK;
}

bool describe(Bytes payload, corad_config &cfg, size_t &model_end) noexcept {
    if (payload.size < native_header || std::memcmp(payload.data,"CRD1",4)) return false;
    const uint8_t *p = payload.data;
    cfg.rows = wire::get(p+4,4); cfg.columns = wire::get(p+8,2); cfg.tricklet = wire::get(p+10,2);
    cfg.atoms = wire::get(p+12,2); cfg.nonzero = wire::get(p+14,2);
    const auto bits = wire::get(p+16,8);
    std::memcpy(&cfg.threshold,&bits,8);
    model_end = native_header + size_t(cfg.columns)*16 + size_t(cfg.tricklet)*cfg.atoms*8;
    return wire::get(p+24,8) == payload.size && model_end <= payload.size;
}

// CRD1 repeats the exact model header/arrays except row count and total length.
bool expected_model(const Deployment &dep, Bytes schema, Bytes payload, size_t model_end) noexcept {
    return dep.schema.equal(schema) && model_end == dep.model_bytes.size &&
        !std::memcmp(payload.data+8,dep.model_bytes.data+8,16) &&
        !std::memcmp(payload.data+native_header,dep.model_bytes.data+native_header,model_end-native_header);
}
}

struct bmk_context {
    Deployment dep;
    const char *operation{}, *reason{""};
    unsigned columns{}, rows{}, tricklet{};
    size_t model_bytes{};
};
namespace {
bmk_status fail(bmk_context *ctx, bmk_status rc, const char *reason) noexcept {
    if (ctx) { ctx->operation=nullptr; ctx->reason=reason; }
    return rc;
}
void report(bmk_context *ctx, const char *operation, const corad_config &c, size_t model_bytes) noexcept {
    ctx->operation=operation; ctx->reason=""; ctx->columns=c.columns; ctx->rows=c.rows;
    ctx->tricklet=c.tricklet; ctx->model_bytes=model_bytes;
}
bmk_status probe(const bmk_object_view *object, const uint8_t *p, uint64_t n, bmk_blob *out) noexcept {
    Deployment dep;
    const auto rc = deployment(p,n,dep);
    if (rc != BMK_OK) return rc;
    std::array<wire::Input,max_cols> inputs{};
    const auto status = inspect(object,dep,inputs);
    return status == BMK_OK ? wire::text(out,"{\"mode\":\"batch\",\"threads\":1,\"max_values\":131072,\"lossy\":true}") : status;
}
bmk_status create(const bmk_host_v1 *host, const uint8_t *p, uint64_t n, bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    std::unique_ptr<bmk_context> ctx(new (std::nothrow) bmk_context);
    if (!ctx) return BMK_NO_MEMORY;
    const auto rc = deployment(p,n,ctx->dep);
    if (rc != BMK_OK) return rc;
    *out = ctx.release();
    return BMK_OK;
}
bmk_status reset(bmk_context *ctx, uint32_t kind) noexcept {
    return !ctx || kind ? fail(ctx,BMK_UNSUPPORTED,"unsupported reset") : fail(ctx,BMK_OK,"");
}
bmk_status encode(bmk_context *ctx, const bmk_object_view *object, bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    std::array<wire::Input,max_cols> inputs{};
    const auto rc = inspect(object,ctx->dep,inputs);
    if (rc != BMK_OK) return fail(ctx,rc,"expected frozen deployment with ordered equal f64 columns within budget");
    auto &dep = ctx->dep;
    corad_config c{};
    if (corad_model_config(dep.model.get(),static_cast<uint32_t>(inputs[0].count),dep.frozen.nonzero,dep.frozen.threshold,&c) != CORAD_OK)
        return fail(ctx,BMK_BAD_INPUT,"invalid native configuration");
    const size_t count = size_t(c.rows)*c.columns, bound = corad_bound(&c), prefix=frame_header+dep.schema.size;
    if (!bound) return fail(ctx,BMK_INTERNAL,"invalid native bound");
    std::unique_ptr<double[]> data(count ? new (std::nothrow) double[count] : nullptr);
    std::unique_ptr<uint8_t[]> frame(new (std::nothrow) uint8_t[prefix+bound]);
    if ((count && !data) || !frame) return fail(ctx,BMK_NO_MEMORY,"allocation failed");
    for (unsigned col=0; col < c.columns && c.rows; ++col) {
        auto *dst = data.get()+size_t(col)*c.rows;
        std::memcpy(dst,inputs[col].values,inputs[col].bytes);
        if (!std::all_of(dst,dst+c.rows,[](double v){ return std::isfinite(v); }))
            return fail(ctx,BMK_BAD_INPUT,"CORAD requires finite input");
    }
    size_t used{};
    const int native = corad_model_encode(dep.model.get(),&c,data.get(),frame.get()+prefix,bound,&used);
    if (native != CORAD_OK) return fail(ctx,native == CORAD_MEMORY ? BMK_NO_MEMORY : BMK_INTERNAL,"native encode failed");
    if (used < dep.model_bytes.size || used > bound ||
        !expected_model(dep,dep.schema,{frame.get()+prefix,used},dep.model_bytes.size))
        return fail(ctx,BMK_INTERNAL,"encoded model mismatch");
    auto *p=frame.get();
    std::memcpy(p,frame_magic.data(),frame_magic.size());
    wire::put(p+8,4,dep.schema.size); wire::put(p+12,4,0); wire::put(p+16,8,used);
    std::memcpy(p+frame_header,dep.schema.data,dep.schema.size);
    wire::blob(out,std::move(frame),prefix+used,prefix+bound);
    report(ctx,"encode",c,dep.model_bytes.size-native_header);
    return BMK_OK;
}
bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid output or context");
    if (!p || n < frame_header || std::memcmp(p,frame_magic.data(),frame_magic.size()) || wire::get(p+12,4))
        return fail(ctx,BMK_CORRUPT,"invalid CORAD envelope");
    const auto metadata=wire::get(p+8,4), length=wire::get(p+16,8);
    if (metadata > max_schema) return fail(ctx,BMK_RESOURCE_LIMIT,"schema exceeds limit");
    if (!metadata || metadata > n-frame_header || length != n-frame_header-metadata || length > SIZE_MAX)
        return fail(ctx,BMK_CORRUPT,"invalid envelope lengths");
    const Bytes schema{p+frame_header,static_cast<size_t>(metadata)};
    const Bytes payload{schema.data+schema.size,static_cast<size_t>(length)};
    corad_config cfg{};
    size_t model_end{};
    if (!describe(payload,cfg,model_end)) return fail(ctx,BMK_CORRUPT,"invalid CRD1 header");
    const size_t count=size_t(cfg.rows)*cfg.columns;
    if (count > max_values || cfg.columns > max_cols || model_end > max_model)
        return fail(ctx,BMK_RESOURCE_LIMIT,"CRD1 exceeds model or value budget");
    const size_t bound=corad_bound(&cfg);
    if (!bound || payload.size > bound) return fail(ctx,BMK_CORRUPT,"CRD1 native configuration or length invalid");
    if (ctx->dep.model && !expected_model(ctx->dep,schema,payload,model_end))
        return fail(ctx,BMK_CORRUPT,"frame differs from expected model or ordered schema");
    std::unique_ptr<Storage> result(new (std::nothrow) Storage);
    if (!result) return fail(ctx,BMK_NO_MEMORY,"allocation failed");
    if (count) result->values.reset(new (std::nothrow) double[count]);
    result->schema.reset(new (std::nothrow) uint8_t[schema.size]);
    if ((count && !result->values) || !result->schema) return fail(ctx,BMK_NO_MEMORY,"allocation failed");
    size_t got{};
    const int native=corad_decode(payload.data,payload.size,result->values.get(),count,count,&got,nullptr);
    if (native != CORAD_OK || got != count)
        return fail(ctx,native == CORAD_MEMORY ? BMK_NO_MEMORY : BMK_CORRUPT,"native recovery failed");
    if (count && !std::all_of(result->values.get(),result->values.get()+count,[](double v){ return std::isfinite(v); }))
        return fail(ctx,BMK_CORRUPT,"nonfinite decoded value");
    std::memcpy(result->schema.get(),schema.data,schema.size);
    for (unsigned i=0; i<cfg.columns; ++i) {
        auto &col=result->columns[i];
        col.struct_size=sizeof(col); col.rank=1; col.dtype=BMK_F64;
        col.storage=cfg.rows ? result->values.get()+size_t(i)*cfg.rows : nullptr;
        col.storage_bytes=size_t(cfg.rows)*8; col.shape[0]=cfg.rows; col.strides_bytes[0]=8;
    }
    auto *owner=result.release();
    *out={sizeof(*out),0,{sizeof(bmk_object_view),cfg.columns,owner->columns.data(),owner->schema.get(),schema.size},owner,release};
    report(ctx,"decode",cfg,model_end-native_header);
    return BMK_OK;
}
bmk_status info(bmk_context *ctx, bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    char json[320];
    const int n=std::snprintf(json,sizeof(json),"{\"backend\":\"corad-c-frozen\",\"mode\":\"batch\",\"operation\":\"%s\","
        "\"threads\":1,\"columns\":%u,\"rows\":%u,\"tricklet\":%u,\"embedded_model_bytes\":%zu,"
        "\"tail_rows\":%u,\"external_deployment_loaded\":%s,\"fallback\":false}",ctx->operation,ctx->columns,ctx->rows,
        ctx->tricklet,ctx->model_bytes,ctx->rows%ctx->tricklet,ctx->dep.model ? "true" : "false");
    return n < 0 || static_cast<size_t>(n) >= sizeof(json) ? BMK_INTERNAL : wire::text(out,{json,static_cast<size_t>(n)});
}
bmk_status error_text(bmk_context *ctx, char *p, uint64_t n) noexcept {
    return ctx ? wire::error(p,n,ctx->reason) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
const bmk_plugin_v1 abi{sizeof(abi),BMK_ABI_V1,"corad-frozen",probe,create,reset,encode,decode,info,error_text,destroy,wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &abi : nullptr; }
