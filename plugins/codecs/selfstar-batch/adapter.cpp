#include "linear_frame.hpp"
#include "selfstar.h"

#include <cfenv>
#include <cstdio>

namespace wire = tsbench::linear;
struct bmk_context {
    const char *operation{}, *error{""};
    size_t blocks{}, bits{}, native_bytes{};
};

namespace {
constexpr char id[] = "selfstar-batch";
constexpr wire::Magic magic{'B','M','K','S','E','L',1,0};
constexpr size_t block_values = 512, prefix = 4;
using Native = std::unique_ptr<sf_c, decltype(&sf_c_destroy)>;

// Frozen SElf*: at most 16 bits for a beta code and 12 control bits per
// XOR word. Include the sentinel and both optional position tables.
constexpr size_t block_bound_bits(size_t count, size_t width) noexcept {
    return (count + 1) * (width * 8 + 28) + 395;
}
constexpr size_t bytes_for(size_t bits) noexcept { return (bits + 7) / 8; }
constexpr size_t block_bound(size_t count, size_t width) noexcept {
    return prefix + bytes_for(block_bound_bits(count, width));
}
constexpr size_t frame_bound(size_t count, size_t width) noexcept {
    return count / block_values * block_bound(block_values,width) +
        (count % block_values ? block_bound(count % block_values,width) : 0);
}
static_assert(frame_bound(wire::logical_limit / 4, 4) + wire::header <= 2 * wire::logical_limit);
static_assert(frame_bound(wire::logical_limit / 8, 8) + wire::header <= 2 * wire::logical_limit);

bool supported(uint32_t dtype) noexcept { return dtype == BMK_F32 || dtype == BMK_F64; }
bool options(const uint8_t *p,uint64_t n) noexcept {
    wire::Options json(p,n);
    return json.token("{") && json.token("}") && json.done();
}
bmk_status fail(bmk_context *ctx,bmk_status status,const char *message) noexcept {
    if (ctx) { *ctx = {}; ctx->error = message; }
    return status;
}
bmk_status check(const bmk_object_view *object,wire::Input &input) noexcept {
    const auto rc = wire::view(object,wire::logical_limit,input);
    if (rc != BMK_OK) return rc;
    if (!supported(input.dtype) || std::fegetround() != FE_TONEAREST) return BMK_UNSUPPORTED;
    return input.count ? BMK_OK : BMK_BAD_INPUT;
}
bmk_status probe(const bmk_object_view *object,const uint8_t *p,uint64_t n,bmk_blob *out) noexcept {
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    wire::Input input;
    const auto status = check(object,input);
    if (status != BMK_OK) return status;
    return wire::text(out,"{\"mode\":\"batch\",\"threads\":1,\"block_values\":512,\"state\":\"ordered-per-object\"}");
}
bmk_status create(const bmk_host_v1 *host,const uint8_t *p,uint64_t n,bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    *out = new (std::nothrow) bmk_context;
    return *out ? BMK_OK : BMK_NO_MEMORY;
}
bmk_status reset(bmk_context *ctx,uint32_t kind) noexcept {
    if (!ctx || kind != 0) return fail(ctx,BMK_UNSUPPORTED,"unsupported reset");
    return fail(ctx,BMK_OK,"");
}

template<class T, sf_dtype dtype>
bmk_status pack(bmk_context *ctx,const wire::Input &input,bmk_blob *out) noexcept {
    Native native(sf_c_create(SF_SELF_STAR,dtype),sf_c_destroy);
    if (!native) return fail(ctx,BMK_NO_MEMORY,"SElf* encoder allocation failed");
    const size_t bound = frame_bound(input.count,sizeof(T));
    std::unique_ptr<uint8_t[]> data(new (std::nothrow) uint8_t[wire::header + input.schema_size + bound]);
    if (!data) return fail(ctx,BMK_NO_MEMORY,"SElf* frame allocation failed");
    auto *payload = data.get() + wire::header + input.schema_size;
    size_t used = 0, blocks = 0, total_bits = 0;
    std::array<T,block_values> values; // Native reads a typed aligned float array.
    for (size_t off = 0; off < input.count;) {
        const size_t count = std::min(block_values,input.count-off);
        const size_t cap = block_bound(count,sizeof(T)) - prefix;
        auto *dest = payload + used + prefix;
        std::memcpy(values.data(),input.values + off*sizeof(T),count*sizeof(T));
        std::memset(dest,0,cap); // Frozen bit writer updates partial bytes in place.
        size_t bits = 0;
        const auto rc = sf_c_encode(native.get(),values.data(),count,dest,cap,&bits);
        if (rc != SF_OK) return fail(ctx,rc == SF_INVALID ? BMK_BAD_INPUT : BMK_INTERNAL,sf_status_string(rc));
        if (!bits || bits > block_bound_bits(count,sizeof(T))) return fail(ctx,BMK_INTERNAL,"SElf* bit length outside bound");
        wire::put(payload+used,prefix,bits);
        used += prefix + bytes_for(bits); total_bits += bits; ++blocks; off += count;
    }
    const auto status = wire::encode_header(magic,input,bound,used,std::move(data),out);
    if (status != BMK_OK) return fail(ctx,status,"SElf* envelope creation failed");
    *ctx = {"encode","",blocks,total_bits,used-blocks*prefix};
    return BMK_OK;
}

bmk_status encode(bmk_context *ctx,const bmk_object_view *object,bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid context or output");
    wire::Input input;
    const auto status = check(object,input);
    if (status != BMK_OK) return fail(ctx,status,"SElf* requires nonempty dense f32/f64 V and FE_TONEAREST");
    return input.dtype == BMK_F32 ? pack<float,SF_F32>(ctx,input,out) : pack<double,SF_F64>(ctx,input,out);
}

template<class T, sf_dtype dtype>
bmk_status unpack(bmk_context *ctx,const wire::Frame &frame,bmk_owned_object *out) noexcept {
    if (frame.payload_size > frame_bound(frame.count,sizeof(T)) ||
        frame.payload_size < ((frame.count+block_values-1)/block_values)*(prefix+1))
        return fail(ctx,BMK_CORRUPT,"SElf* payload outside frame bounds");
    Native native(sf_c_create(SF_SELF_STAR,dtype),sf_c_destroy);
    if (!native) return fail(ctx,BMK_NO_MEMORY,"SElf* decoder allocation failed");
    auto object = wire::allocate(frame);
    if (!object) return fail(ctx,BMK_NO_MEMORY,"SElf* output allocation failed");
    size_t used = 0, blocks = 0, total_bits = 0;
    std::array<T,block_values> values;
    for (size_t off = 0; off < frame.count;) {
        if (frame.payload_size-used < prefix) return fail(ctx,BMK_CORRUPT,"truncated SElf* bit length");
        const size_t count = std::min(block_values,frame.count-off);
        const size_t bits = wire::get(frame.payload+used,prefix), bytes = bytes_for(bits);
        used += prefix;
        if (!bits || bits > block_bound_bits(count,sizeof(T)) || bytes > frame.payload_size-used)
            return fail(ctx,BMK_CORRUPT,"invalid SElf* block size");
        const auto rc = sf_c_decode(native.get(),frame.payload+used,bytes,bits,values.data(),count);
        if (rc != SF_OK) return fail(ctx,BMK_CORRUPT,sf_status_string(rc));
        std::memcpy(object->buffer.get()+off*sizeof(T),values.data(),count*sizeof(T));
        used += bytes; total_bits += bits; ++blocks; off += count;
    }
    if (used != frame.payload_size) return fail(ctx,BMK_CORRUPT,"trailing SElf* payload");
    wire::decoded(out,frame,std::move(object));
    *ctx = {"decode","",blocks,total_bits,used-blocks*prefix};
    return BMK_OK;
}

bmk_status decode(bmk_context *ctx,const uint8_t *p,uint64_t n,bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid context or output");
    wire::Frame frame;
    const auto status = wire::read(magic,p,n,wire::logical_limit,frame);
    if (status != BMK_OK) return fail(ctx,status,"invalid SElf* envelope");
    if (!supported(frame.dtype) || !frame.count) return fail(ctx,BMK_CORRUPT,"invalid SElf* frame dtype or count");
    if (std::fegetround() != FE_TONEAREST) return fail(ctx,BMK_UNSUPPORTED,"SElf* requires FE_TONEAREST");
    return frame.dtype == BMK_F32 ? unpack<float,SF_F32>(ctx,frame,out) : unpack<double,SF_F64>(ctx,frame,out);
}
bmk_status info(bmk_context *ctx,bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    char text[384];
    const int len = std::snprintf(text,sizeof(text),"{\"backend\":\"selfstar-c-scalar\",\"mode\":\"batch\",\"threads\":1,"
        "\"fallback\":false,\"operation\":\"%s\",\"blocks\":%zu,\"native_bits\":%zu,\"native_payload_bytes\":%zu,"
        "\"block_header_bytes\":%zu,\"block_values\":512}",ctx->operation,ctx->blocks,ctx->bits,ctx->native_bytes,ctx->blocks*prefix);
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
