#include "linear_frame.hpp"
#include "entropy_port.hpp"

#include <cstdio>
#include <stdexcept>

namespace wire = tsbench::linear;
namespace ep = entropy_port;
struct bmk_context {
    const char *operation{}, *error{""};
    size_t raw{}, rle{}, huffman{};
};
namespace {
constexpr char id[] = "huff0-reference";
constexpr wire::Magic magic{'B','M','K','H','U','F',1,0};
constexpr size_t fec_header = 24, fec_block_header = 13;
constexpr unsigned algorithm = static_cast<unsigned>(ep::Algorithm::Huff);
static_assert(algorithm == 2 && ep::block_size == 32768);

constexpr size_t fec_bound(size_t bytes) noexcept {
    return fec_header + bytes + (bytes+ep::block_size-1)/ep::block_size*fec_block_header;
}
static_assert(fec_bound(wire::logical_limit) + wire::header <= 2*wire::logical_limit);

bmk_status fail(bmk_context *ctx,bmk_status code,const char *message) noexcept {
    if (ctx) { *ctx = {}; ctx->error = message; }
    return code;
}
bool options(const uint8_t *p,uint64_t n) noexcept {
    wire::Options json(p,n);
    return json.token("{") && json.token("}") && json.done();
}
bmk_status check(const bmk_object_view *object,wire::Input &input) noexcept {
    const auto rc = wire::view(object,wire::logical_limit,input);
    if (rc != BMK_OK) return rc;
    return input.dtype == BMK_U8 ? BMK_OK : BMK_UNSUPPORTED;
}
bmk_status probe(const bmk_object_view *object,const uint8_t *p,uint64_t n,bmk_blob *out) noexcept {
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    wire::Input input;
    const auto rc = check(object,input);
    return rc == BMK_OK ? wire::text(out,"{\"mode\":\"batch\",\"threads\":1,\"block_bytes\":32768}") : rc;
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
    return ctx && kind == 0 ? fail(ctx,BMK_OK,"") : fail(ctx,BMK_UNSUPPORTED,"unsupported reset");
}

// Audit the envelope binding and count actual block kinds. Native decode also
// checks the block map and verifies the decoded CRC. Neither turns the frozen
// upstream payload decoder into an arbitrary-untrusted-input entry point.
bool inspect(const uint8_t *payload,size_t size,size_t bytes,bmk_context &seen) noexcept {
    const size_t blocks = (bytes+ep::block_size-1)/ep::block_size;
    if (size < fec_header || size > fec_bound(bytes) || std::memcmp(payload,"FEC1",4) ||
        wire::get(payload+4,4) != algorithm || wire::get(payload+8,4) != ep::block_size ||
        wire::get(payload+12,8) != bytes || wire::get(payload+20,4) != blocks) return false;
    size_t at = fec_header, remaining = bytes;
    for (size_t i = 0; i < blocks; ++i) {
        if (size-at < fec_block_header) return false;
        const unsigned mode = payload[at];
        const size_t logical = wire::get(payload+at+1,4), stored = wire::get(payload+at+5,4);
        at += fec_block_header;
        if (logical != std::min(remaining,ep::block_size) || !stored || stored > size-at) return false;
        if (mode == 0 && stored == logical) ++seen.raw;
        else if (mode == 1 && stored == 1 && stored < logical) ++seen.rle;
        else if (mode == 2 && stored < logical) ++seen.huffman;
        else return false;
        at += stored; remaining -= logical;
    }
    return at == size && !remaining;
}
bmk_status encode(bmk_context *ctx,const bmk_object_view *object,bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid context or output");
    wire::Input input;
    const auto rc = check(object,input);
    if (rc != BMK_OK) return fail(ctx,rc,"Huff0 requires one dense u8 V column");
    try {
        ep::Bytes src, payload;
        if (input.bytes) src.assign(input.values,input.values+input.bytes);
        ep::Codec native(ep::Algorithm::Huff);
        native.encode(src,payload,true);
        bmk_context seen{"encode"};
        if (!inspect(payload.data(),payload.size(),input.bytes,seen))
            return fail(ctx,BMK_INTERNAL,"invalid FEC1 emitted by native encoder");
        std::unique_ptr<uint8_t[]> data(new uint8_t[wire::header+input.schema_size+payload.size()]);
        std::memcpy(data.get()+wire::header+input.schema_size,payload.data(),payload.size());
        const auto packed = wire::encode_header(magic,input,payload.size(),payload.size(),std::move(data),out);
        if (packed != BMK_OK) return fail(ctx,packed,"Huff0 envelope creation failed");
        *ctx = seen;
        return BMK_OK;
    } catch (const std::bad_alloc &) {
        return fail(ctx,BMK_NO_MEMORY,"Huff0 encoder allocation failed");
    } catch (...) {
        return fail(ctx,BMK_INTERNAL,"native Huff0 encode failed");
    }
}
bmk_status decode(bmk_context *ctx,const uint8_t *p,uint64_t n,bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx,BMK_BAD_INPUT,"invalid context or output");
    wire::Frame f;
    const auto rc = wire::read(magic,p,n,wire::logical_limit,f);
    if (rc != BMK_OK) return fail(ctx,rc,"invalid Huff0 envelope");
    bmk_context seen{"decode"};
    if (f.dtype != BMK_U8 || !inspect(f.payload,f.payload_size,f.bytes,seen))
        return fail(ctx,BMK_CORRUPT,"FEC1 shape or block map disagrees with envelope");
    try {
        ep::Codec native(ep::Algorithm::Huff);
        const ep::Bytes payload(f.payload,f.payload+f.payload_size);
        ep::Bytes values;
        native.decode(payload,values);
        if (values.size() != f.bytes) return fail(ctx,BMK_CORRUPT,"FEC1 decoded length mismatch");
        auto object = wire::allocate(f);
        if (!object) return fail(ctx,BMK_NO_MEMORY,"Huff0 output allocation failed");
        if (f.bytes) std::memcpy(object->buffer.get(),values.data(),f.bytes);
        wire::decoded(out,f,std::move(object));
        *ctx = seen;
        return BMK_OK;
    } catch (const std::bad_alloc &) {
        return fail(ctx,BMK_NO_MEMORY,"Huff0 decoder allocation failed");
    } catch (...) {
        return fail(ctx,BMK_CORRUPT,"native Huff0 decode or CRC check failed");
    }
}
bmk_status info(bmk_context *ctx,bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    const char *backend = ctx->operation[0] == 'e' ? "huff0-reference-encode" :
        ctx->huffman ? ep::cpu_backend() : "no-huffman-decode";
    char text[320];
    const int len = std::snprintf(text,sizeof(text),"{\"backend\":\"%s\",\"mode\":\"batch\",\"threads\":1,"
        "\"operation\":\"%s\",\"fallback\":%s,\"blocks\":%zu,\"raw_blocks\":%zu,\"rle_blocks\":%zu,\"huffman_blocks\":%zu}",
        backend,ctx->operation,ctx->raw ? "true" : "false",ctx->raw+ctx->rle+ctx->huffman,ctx->raw,ctx->rle,ctx->huffman);
    return len >= 0 && static_cast<size_t>(len) < sizeof(text) ? wire::text(out,{text,static_cast<size_t>(len)}) : BMK_INTERNAL;
}
bmk_status error_text(bmk_context *ctx,char *p,uint64_t n) noexcept {
    return ctx ? wire::error(p,n,ctx->error) : BMK_BAD_INPUT;
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
const bmk_plugin_v1 abi{sizeof(abi),BMK_ABI_V1,id,probe,create,reset,encode,decode,info,error_text,destroy,wire::extension};
}

extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &abi : nullptr; }
