#include "linear_frame.hpp"
#include "tba.h"

#include <cfenv>
#include <charconv>
#include <cmath>
#include <cstdio>

namespace wire = tsbench::linear;
struct bmk_context {
    std::array<double,16> eps{};
    size_t layers{};
    tba_pbepla_info observed{};
    const char *operation{}, *error{""};
    char native_error[256]{};
};
namespace {
constexpr char id[] = "pbepla-rr";
constexpr wire::Magic magic{'B','M','K','P','B','E',1,0};
// Bound native array/segment work, not merely serialized output size.
constexpr size_t value_layer_budget = 2*1024*1024;
constexpr size_t payload_limit = 2*wire::logical_limit-wire::header;

bool options(const uint8_t *p,uint64_t n,bmk_context &ctx) noexcept {
    if (!p || n > wire::schema_limit) return false;
    std::string_view s(reinterpret_cast<const char *>(p),static_cast<size_t>(n));
    const auto space = [&]() {
        auto off = s.find_first_not_of(" \r\n\t");
        s.remove_prefix(off == s.npos ? s.size() : off);
    };
    const auto take = [&](std::string_view prefix) {
        space();
        if (s.substr(0,prefix.size()) != prefix) return false;
        s.remove_prefix(prefix.size());
        return true;
    };
    if (!take("{")) return false;
    if (take("}")) { space(); return s.empty(); }
    if (!take("\"eps\"") || !take(":") || !take("[")) return false;
    do {
        space();
        const auto digit = [&](size_t j) { return j<s.size() && s[j]>='0' && s[j]<='9'; };
        if (ctx.layers >= ctx.eps.size() || !digit(0) || (s[0]=='0' && digit(1))) return false;
        size_t end = 1;
        while (digit(end)) ++end;
        if (end<s.size() && s[end]=='.') {
            if (!digit(++end)) return false;
            while (digit(end)) ++end;
        }
        if (end<s.size() && (s[end]=='e' || s[end]=='E')) {
            ++end;
            if (end<s.size() && (s[end]=='+' || s[end]=='-')) ++end;
            if (!digit(end)) return false;
            while (digit(end)) ++end;
        }
        double value = 0;
        const auto parsed = std::from_chars(s.data(),s.data()+end,value);
        if (parsed.ec != std::errc{} || parsed.ptr != s.data()+end || !(value > 0) || !std::isfinite(2*value) ||
            (ctx.layers && value >= ctx.eps[ctx.layers-1])) return false;
        s.remove_prefix(end);
        ctx.eps[ctx.layers++] = value;
    } while (take(","));
    if (!take("]") || !take("}")) return false;
    space(); return s.empty();
}
bmk_status fail(bmk_context *ctx,bmk_status code,const char *message) noexcept {
    if (ctx) { ctx->error = message; ctx->operation = nullptr; ctx->observed = {}; }
    return code;
}
bmk_status check(const bmk_object_view *object,size_t layers,wire::Input &input) noexcept {
    if (!layers) return BMK_BAD_OPTIONS;
    const auto rc = wire::view(object,wire::logical_limit,input);
    if (rc != BMK_OK) return rc;
    if (input.dtype != BMK_F64 || std::fegetround() != FE_TONEAREST) return BMK_UNSUPPORTED;
    return input.count <= value_layer_budget/layers ? BMK_OK : BMK_RESOURCE_LIMIT;
}
bmk_status probe(const bmk_object_view *obj,const uint8_t *p,uint64_t n,bmk_blob *out) noexcept {
    bmk_context params;
    if (!options(p,n,params)) return BMK_BAD_OPTIONS;
    wire::Input input;
    const auto rc = check(obj,params.layers,input);
    return rc == BMK_OK ? wire::text(out,"{\"mode\":\"batch\",\"threads\":1,\"quality\":\"absolute-error\"}") : rc;
}
bmk_status create(const bmk_host_v1 *host,const uint8_t *p,uint64_t n,bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    bmk_context parsed;
    if (!options(p,n,parsed)) return BMK_BAD_OPTIONS;
    *out = new (std::nothrow) bmk_context(parsed);
    return *out ? BMK_OK : BMK_NO_MEMORY;
}
bmk_status reset(bmk_context *ctx,uint32_t kind) noexcept {
    return ctx && kind == 0 ? fail(ctx,BMK_OK,"") : fail(ctx,BMK_UNSUPPORTED,"unsupported reset");
}
struct Buffer { tba_buffer value{}; ~Buffer() { tba_free(&value); } };

bmk_status encode(bmk_context *ctx,const bmk_object_view *object,bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid context or output");
    wire::Input input;
    const auto rc = check(object,ctx->layers,input);
    if (rc != BMK_OK) return fail(ctx,rc,"PBEPLA-RR needs f64, FE_TONEAREST, explicit eps and in-budget value-layer count");
    std::unique_ptr<double[]> vals(input.count ? new (std::nothrow) double[input.count] : nullptr);
    if (input.count && !vals) return fail(ctx,BMK_NO_MEMORY,"aligned PBEPLA-RR input allocation failed");
    if (input.bytes) std::memcpy(vals.get(),input.values,input.bytes);
    for (size_t i = 0; i < input.count; ++i)
        if (!std::isfinite(vals[i])) return fail(ctx,BMK_BAD_INPUT,"PBEPLA-RR rejects non-finite values");
    Buffer native;
    tba_pbepla_info seen{};
    const auto params = tba_pbepla_defaults(ctx->eps.data(),ctx->layers);
    if (tba_pbepla_encode_ex(vals.get(),input.count,&params,&seen,&native.value,ctx->native_error,sizeof(ctx->native_error)))
        return fail(ctx,BMK_INTERNAL,ctx->native_error);
    const size_t size = native.value.bytes;
    if (!size || !native.value.data || native.value.count != input.count || seen.layer_present != ctx->layers)
        return fail(ctx,BMK_INTERNAL,"native PBEP representation mismatch");
    if (size > payload_limit) return fail(ctx,BMK_RESOURCE_LIMIT,"PBEP exceeds transport bound");
    std::unique_ptr<uint8_t[]> data(new (std::nothrow) uint8_t[wire::header+input.schema_size+size]);
    if (!data) return fail(ctx,BMK_NO_MEMORY,"PBEPLA-RR envelope allocation failed");
    std::memcpy(data.get()+wire::header+input.schema_size,native.value.data,size);
    const auto packed = wire::encode_header(magic,input,size,size,std::move(data),out);
    if (packed != BMK_OK) return fail(ctx,packed,"PBEPLA-RR envelope creation failed");
    ctx->error = ""; ctx->operation = "encode"; ctx->observed = seen;
    return BMK_OK;
}
bmk_status decode(bmk_context *ctx,const uint8_t *p,uint64_t n,bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid context or output");
    wire::Frame frame;
    const auto rc = wire::read(magic,p,n,wire::logical_limit,frame);
    if (rc != BMK_OK) return fail(ctx,rc,"invalid PBEPLA-RR envelope");
    if (frame.dtype != BMK_F64) return fail(ctx,BMK_CORRUPT,"non-f64 PBEP frame");
    if (std::fegetround() != FE_TONEAREST) return fail(ctx,BMK_UNSUPPORTED,"PBEPLA-RR needs FE_TONEAREST");
    if (frame.payload_size > payload_limit) return fail(ctx,BMK_RESOURCE_LIMIT,"PBEP exceeds transport bound");
    tba_pbepla_info seen{};
    if (tba_pbepla_inspect(frame.payload,frame.payload_size,&seen,ctx->native_error,sizeof(ctx->native_error)))
        return fail(ctx,BMK_CORRUPT,ctx->native_error);
    if (seen.value_count != frame.count || !seen.layer_present || seen.layer_present > 16)
        return fail(ctx,BMK_CORRUPT,"PBEP metadata disagrees with envelope");
    if (frame.count > value_layer_budget/seen.layer_present) return fail(ctx,BMK_RESOURCE_LIMIT,"PBEP value-layer budget exceeded");
    Buffer native;
    if (tba_decode(TBA_PBEPLA_RR,frame.payload,frame.payload_size,seen.layer_present,frame.count,
            &native.value,ctx->native_error,sizeof(ctx->native_error))) return fail(ctx,BMK_CORRUPT,ctx->native_error);
    if (native.value.count != frame.count || native.value.bytes != frame.bytes || (frame.bytes && !native.value.data))
        return fail(ctx,BMK_CORRUPT,"PBEP decoded length mismatch");
    auto object = wire::allocate(frame);
    if (!object) return fail(ctx,BMK_NO_MEMORY,"PBEPLA-RR output allocation failed");
    if (frame.bytes) std::memcpy(object->buffer.get(),native.value.data,frame.bytes);
    wire::decoded(out,frame,std::move(object));
    ctx->error = ""; ctx->operation = "decode"; ctx->observed = seen;
    return BMK_OK;
}
bmk_status info(bmk_context *ctx,bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    const auto &s = ctx->observed;
    char text[416];
    const int len = std::snprintf(text,sizeof(text),"{\"backend\":\"tba-pbepla-rr-port\",\"threads\":1,\"mode\":\"batch\","
        "\"fallback\":false,\"operation\":\"%s\",\"layers_stored\":%u,\"native_header_bytes\":%zu,\"native_payload_bytes\":%zu}",
        ctx->operation,s.layer_present,s.header_bytes,s.payload_bytes);
    return len >= 0 && static_cast<size_t>(len) < sizeof(text) ? wire::text(out,{text,static_cast<size_t>(len)}) : BMK_INTERNAL;
}
bmk_status error_text(bmk_context *ctx,char *out,uint64_t n) noexcept {
    return ctx ? wire::error(out,n,ctx->error) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
const bmk_plugin_v1 abi{sizeof(abi),BMK_ABI_V1,id,probe,create,reset,encode,decode,info,error_text,destroy,wire::extension};
}

extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &abi : nullptr; }
