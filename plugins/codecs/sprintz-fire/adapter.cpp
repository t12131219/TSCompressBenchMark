#include "linear_frame.hpp"
#include "native_profile.hpp"
#include <charconv>
#include <string>

namespace wire = tsbench::linear;
using namespace tsbench::sprintz_fire;

struct bmk_context {
    std::unique_ptr<sf::Codec> native;
    sf::Config config = profile;
    const char *operation{};
    const char *reason{""};
};

namespace {
#ifdef BMK_SPRINTZ_GROUP
constexpr wire::Magic magic{'B','M','K','S','P','G',1,0};
constexpr char plugin_id[] = "sprintz-fire-u16-group";
#else
constexpr wire::Magic magic{'B','M','K','S','P','R',1,0};
constexpr char plugin_id[] = "sprintz-fire";
#endif
constexpr size_t max_sfb1 = 32 + 4 * max_bytes;

int lanes(const uint8_t *p, uint64_t n) noexcept {
#ifdef BMK_SPRINTZ_GROUP
    if (!p || n > wire::schema_limit) return 0;
    std::string_view text(reinterpret_cast<const char *>(p), static_cast<size_t>(n));
    auto spaces = [&] {
        auto start = text.find_first_not_of(" \n\t\r");
        text.remove_prefix(start == text.npos ? text.size() : start);
    };
    auto token = [&](std::string_view s) {
        spaces();
        if (text.substr(0, s.size()) != s) return false;
        text.remove_prefix(s.size());
        return true;
    };
    if (!token("{") || !token("\"lanes\"") || !token(":")) return 0;
    spaces();
    if (text.empty() || text.front() < '1' || text.front() > '9') return 0;
    int count = 0;
    const auto result = std::from_chars(text.data(), text.data()+text.size(), count);
    if (result.ec != std::errc{} || count < 3 || count > 128) return 0;
    text.remove_prefix(result.ptr-text.data());
    const bool closed = token("}");
    spaces();
    return closed && text.empty() ? count : 0;
#else
    wire::Options json(p, n);
    return json.token("{") && json.token("}") && json.done() ? profile.ndims : 0;
#endif
}
bool aligned(size_t count, int ndims) noexcept {
#ifdef BMK_SPRINTZ_GROUP
    return count % ndims == 0;
#else
    // The historical four-lane plugin permits a partial last row.
    (void)count; (void)ndims;
    return true;
#endif
}
bmk_status fail(bmk_context *ctx, bmk_status code, const char *why) noexcept {
    if (ctx) { ctx->operation = nullptr; ctx->reason = why; }
    return code;
}
bmk_status probe(const bmk_object_view *obj, const uint8_t *p, uint64_t n, bmk_blob *out) noexcept {
    const int dims = lanes(p,n);
    if (!dims) return BMK_BAD_OPTIONS;
    if (!supported_host()) return BMK_UNSUPPORTED;
    wire::Input input;
    const auto status = wire::view(obj, max_bytes, input);
    if (status != BMK_OK) return status;
    if (input.dtype != BMK_U16) return BMK_UNSUPPORTED;
    if (!aligned(input.count,dims)) return BMK_BAD_INPUT;
#ifdef BMK_SPRINTZ_GROUP
    try {
        return wire::text(out, "{\"mode\":\"batch\",\"max_input_bytes\":65536,\"threads\":1,\"lanes\":"+std::to_string(dims)+"}");
    } catch (...) { return BMK_NO_MEMORY; }
#else
    return wire::text(out, "{\"mode\":\"batch\",\"max_input_bytes\":65536,\"threads\":1,\"lanes\":4}");
#endif
}
bmk_status create(const bmk_host_v1 *host, const uint8_t *p, uint64_t n, bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out = nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    const int dims = lanes(p,n);
    if (!dims) return BMK_BAD_OPTIONS;
    if (!supported_host()) return BMK_UNSUPPORTED;
    try {
        auto ctx = std::make_unique<bmk_context>();
        ctx->config.ndims = dims;
        ctx->native = std::make_unique<sf::Codec>(ctx->config, max_bytes);
        *out = ctx.release();
        return BMK_OK;
    } catch (const std::bad_alloc &) { return BMK_NO_MEMORY; }
    catch (...) { return BMK_INTERNAL; }
}
bmk_status reset(bmk_context *ctx, uint32_t kind) noexcept {
    if (!ctx || kind) return fail(ctx, BMK_UNSUPPORTED, "unsupported reset");
    // Independent SFB1 blocks: the frozen kernel clears reusable scratch
    // in each call, so no predictor state needs to cross a reset.
    return fail(ctx, BMK_OK, "");
}
bmk_status encode(bmk_context *ctx, const bmk_object_view *obj, bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx, BMK_BAD_INPUT, "invalid output or context");
    wire::Input input;
    const auto status = wire::view(obj, max_bytes, input);
    if (status != BMK_OK || input.dtype != BMK_U16)
        return fail(ctx, status == BMK_OK ? BMK_UNSUPPORTED : status, "Sprintz needs one dense u16 lane stream up to 65536 bytes");
    if (!aligned(input.count,ctx->config.ndims)) return fail(ctx, BMK_BAD_INPUT, "incomplete u16 lane row");
    try {
        const auto payload = ctx->native->encode(input.values, input.bytes);
        if (payload.size() > max_sfb1 - 32) return fail(ctx, BMK_INTERNAL, "native payload outside bound");
        const auto frame = sf::frame(ctx->config, input.values, input.bytes, payload);
        auto container = std::make_unique<uint8_t[]>(wire::header + input.schema_size + frame.size());
        std::memcpy(container.get() + wire::header + input.schema_size, frame.data(), frame.size());
        const auto packed = wire::encode_header(magic, input, frame.size(), frame.size(), std::move(container), out);
        if (packed != BMK_OK) return fail(ctx, packed, "cannot serialize SFB1 envelope");
        ctx->operation = "encode"; ctx->reason = "";
        return BMK_OK;
    } catch (const std::bad_alloc &) { return fail(ctx, BMK_NO_MEMORY, "allocation failed"); }
    catch (...) { return fail(ctx, BMK_INTERNAL, "native Sprintz encode failed"); }
}
bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return fail(ctx, BMK_BAD_INPUT, "invalid output or context");
    wire::Frame frame;
    const auto status = wire::read(magic, p, n, max_bytes, frame);
    if (status != BMK_OK) return fail(ctx, status, "invalid Sprintz envelope");
    if (frame.dtype != BMK_U16) return fail(ctx, BMK_CORRUPT, "Sprintz envelope dtype mismatch");
    if (!aligned(frame.count,ctx->config.ndims)) return fail(ctx, BMK_CORRUPT, "incomplete u16 lane row");
    if (frame.payload_size > max_sfb1) return fail(ctx, BMK_RESOURCE_LIMIT, "oversize SFB1 block");
    try {
        size_t original_bytes = 0;
        uint32_t crc = 0;
        const auto payload = sf::unframe(ctx->config, frame.payload, frame.payload_size, original_bytes, crc, max_bytes);
        if (original_bytes != frame.bytes) return fail(ctx, BMK_CORRUPT, "SFB1 original length differs from envelope");
        const auto raw = ctx->native->decode(payload.data(), payload.size(), original_bytes);
        if (raw.size() != frame.bytes || sf::crc32(raw.data(), raw.size()) != crc)
            return fail(ctx, BMK_CORRUPT, "SFB1 decoded length or checksum differs");
        auto output = wire::allocate(frame);
        if (!output) return fail(ctx, BMK_NO_MEMORY, "allocation failed");
        if (!raw.empty()) std::memcpy(output->buffer.get(), raw.data(), raw.size());
        wire::decoded(out, frame, std::move(output));
        ctx->operation = "decode"; ctx->reason = "";
        return BMK_OK;
    } catch (const std::bad_alloc &) { return fail(ctx, BMK_NO_MEMORY, "allocation failed"); }
    catch (...) { return fail(ctx, BMK_CORRUPT, "invalid native SFB1 frame or payload"); }
}
bmk_status info(bmk_context *ctx, bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
#ifdef BMK_SPRINTZ_GROUP
    try {
        return wire::text(out, std::string("{\"operation\":\"")+ctx->operation+
            "\",\"mode\":\"batch\",\"threads\":1,\"path\":\"generic_rle\",\"algorithm\":\"fire\","
            "\"required_isa\":[\"avx2\",\"bmi1\",\"bmi2\",\"lzcnt\",\"popcnt\"],\"lanes\":"+
            std::to_string(ctx->config.ndims)+"}");
    } catch (...) { return BMK_NO_MEMORY; }
#else
    return wire::text(out, ctx->operation[0] == 'e'
        ? "{\"operation\":\"encode\",\"threads\":1,\"path\":\"generic_rle\",\"algorithm\":\"fire\",\"lanes\":4}"
        : "{\"operation\":\"decode\",\"threads\":1,\"path\":\"generic_rle\",\"algorithm\":\"fire\",\"lanes\":4}");
#endif
}
bmk_status error(bmk_context *ctx, char *out, uint64_t n) noexcept {
    return wire::error(out, n, ctx ? ctx->reason : "invalid context");
}
void destroy(bmk_context *ctx) noexcept { delete ctx; }
const bmk_plugin_v1 api{sizeof(api), BMK_ABI_V1, plugin_id, probe, create, reset, encode, decode,
                        info, error, destroy, wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) { return version == BMK_ABI_V1 ? &api : nullptr; }
