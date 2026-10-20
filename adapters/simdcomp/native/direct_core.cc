// Direct SIMDComp uint32 codec: necessary count/layout/widths plus native bits.
// This baseline TU calls separately built SSE4.1 and AVX2 vendor objects.
#include "tsbench_core.hpp"
#include "simdcomp.h"
#include <algorithm>
#include <memory>

extern "C" {
uint32_t tsbench_simdcomp_core_avx2_width(const uint32_t*);
void tsbench_simdcomp_core_avx2_pack(const uint32_t*, void*, uint32_t, int);
void tsbench_simdcomp_core_avx2_unpack(const void*, uint32_t*, uint32_t);
}
namespace {
constexpr std::size_t header_bytes = 5;
constexpr std::size_t max_count = 16777216;
enum class Api { Length, Masked, WithoutMask };
struct SimdCoreState final : tsbench_core::State {
    bool decoder = false, avx = false;
    Api api = Api::Length;
    std::size_t count = 0, bytes = 0;
    alignas(32) std::uint32_t stage[256];
};
void cpu(bool avx) {
#if defined(__x86_64__) && defined(__GNUC__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    if (!__builtin_cpu_supports("sse4.1") || (avx && !__builtin_cpu_supports("avx2")))
        throw tsbench_core::Unsupported("SIMDComp direct core requires the declared SSE4.1/AVX2 path");
#else
    (void)avx;
    throw tsbench_core::Unsupported("SIMDComp direct core requires little-endian x86-64");
#endif
}
SimdCoreState* state(void* context) {
    tsbench_core::require(context != nullptr, "null direct SIMDComp context");
    return static_cast<SimdCoreState*>(context);
}
void disjoint(const std::uint8_t* input, std::size_t size,
              const std::uint8_t* output, std::size_t capacity) {
    if (!size || !capacity) return;
    const auto x = reinterpret_cast<std::uintptr_t>(input);
    const auto y = reinterpret_cast<std::uintptr_t>(output);
    tsbench_core::require(!(x <= y ? y-x < size : x-y < capacity),
                          "overlapping direct SIMDComp buffers");
}
std::uint32_t load32(const std::uint8_t* p) {
    std::uint32_t result = 0;
    for (unsigned i = 0; i < 4; ++i) result |= std::uint32_t(p[i]) << (8*i);
    return result;
}
void store32(std::uint8_t* p, std::uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) p[i] = static_cast<std::uint8_t>(value >> (8*i));
}
std::size_t blocks(std::size_t count, bool avx) {
    const std::size_t block = avx ? 256 : 128;
    return (count + block - 1) / block;
}
std::size_t bound(const SimdCoreState& h) {
    // Width 32 stores exact absolute uint32 bytes. Other widths may round a
    // partial four-lane tail up to one additional 16-byte SIMD word.
    return tsbench_core::add(header_bytes, tsbench_core::add(h.bytes,
        tsbench_core::add(blocks(h.count, h.avx), h.count % (h.avx ? 256 : 128) ? 15 : 0)));
}
std::size_t payload_bytes(std::size_t count, unsigned width, bool full_avx) {
    tsbench_core::require(width <= 32, "invalid direct SIMDComp width");
    if (full_avx) return static_cast<std::size_t>(width)*32;
    return static_cast<std::size_t>(simdpack_compressedbytes(static_cast<int>(count), width));
}
void input_extent(const SimdCoreState& h, const std::uint8_t* input, std::size_t size) {
    tsbench_core::require(size == h.bytes && (input || !size),
                          "direct SIMDComp input extent differs from task");
}
}
extern "C" std::uint32_t tsbench_core_version() { return 1; }
extern "C" std::uint32_t tsbench_core_storage() { return 3; }
extern "C" int tsbench_core_create(const tsbench_core_config* c, int decoder, void** output) {
    return tsbench_core::guard(nullptr, [&] {
        tsbench_core::require(c && output, "null direct SIMDComp configuration");
        *output = nullptr;
        if (c->dtype != TSCB_DTYPE_U32_LE_V1 || c->rank != 1)
            throw tsbench_core::Unsupported("SIMDComp direct core requires rank1 uint32");
        auto h = std::make_unique<SimdCoreState>();
        h->decoder = decoder != 0;
        h->count = tsbench_core::elements(*c);
        h->bytes = tsbench_core::input_bytes(*c);
        if (h->count > max_count) throw tsbench_core::Unsupported("SIMDComp count exceeds 16M values");
        const tsbench_core::Parameters p(c->parameters_json);
        if (h->decoder) {
            tsbench_core::require(p.empty() && (!c->model || !*c->model),
                                  "SIMDComp decoder must recover its layout from the stream");
        } else {
            const auto isa = p.string("isa");
            if (isa == "AVX2") h->avx = true;
            else if (isa != "SSE4_1") throw tsbench_core::Unsupported("unknown SIMDComp ISA");
            const auto api = p.string("api");
            if (api == "LENGTH") h->api = Api::Length;
            else if (api == "MASKED") h->api = Api::Masked;
            else if (api == "WITHOUTMASK") h->api = Api::WithoutMask;
            else throw tsbench_core::Unsupported("unknown SIMDComp plain API");
            if (h->avx && h->api == Api::Length)
                throw tsbench_core::Unsupported("AVX2_SOURCE_HAS_NO_LENGTH_API");
            if ((p.contains("coding") && p.string("coding") != "PLAIN") ||
                p.integer("starting_point", 0, UINT32_MAX) != 0)
                throw tsbench_core::Unsupported("registered SIMDComp direct key supports PLAIN seed0");
        }
        cpu(h->avx);
        *output = h.release();
    });
}
extern "C" int tsbench_core_destroy(void* context) {
    delete static_cast<SimdCoreState*>(context); return 0;
}
extern "C" int tsbench_core_bound(void* context, const std::uint8_t* input,
                                   std::size_t size, std::size_t* output) {
    auto* h = static_cast<SimdCoreState*>(context);
    return tsbench_core::guard(h, [&] {
        h = state(context);
        tsbench_core::require(output && !h->decoder, "invalid direct SIMDComp bound request");
        input_extent(*h, input, size);
        *output = bound(*h);
    });
}
extern "C" int tsbench_core_encode(void* context, const std::uint8_t* input,
    std::size_t size, std::uint8_t* output, std::size_t capacity, tsbench_core_result* result) {
    auto* h = static_cast<SimdCoreState*>(context);
    return tsbench_core::guard(h, [&] {
        h = state(context);
        tsbench_core::require(result && !h->decoder && output,
                              "invalid direct SIMDComp encode request");
        *result = {};
        input_extent(*h, input, size);
        disjoint(input, size, output, capacity);
        if (capacity < header_bytes) throw tsbench_core::Capacity("direct SIMDComp header capacity");
        store32(output, static_cast<std::uint32_t>(h->count));
        output[4] = h->avx ? 1 : 0;
        std::size_t at = header_bytes;
        const std::size_t block = h->avx ? 256 : 128;
        for (std::size_t start = 0; start < h->count; start += block) {
            const auto n = std::min(block, h->count-start);
            const auto* values = reinterpret_cast<const std::uint32_t*>(input + start*4);
            if (reinterpret_cast<std::uintptr_t>(values) % alignof(std::uint32_t)) {
                std::memcpy(h->stage, input + start*4, n*4); values = h->stage;
            }
            const bool full_avx = h->avx && n == 256;
            // Width selection is input-dependent algorithm work and remains in
            // each complete encode call, with no precomputed per-block tables.
            const unsigned width = full_avx ? tsbench_simdcomp_core_avx2_width(values)
                                             : maxbits_length(values, static_cast<std::uint32_t>(n));
            const auto payload = payload_bytes(n, width, full_avx);
            if (at >= capacity || payload > capacity-at-1)
                throw tsbench_core::Capacity("direct SIMDComp block capacity");
            output[at++] = static_cast<std::uint8_t>(width);
            auto* packed = output + at;
            if (full_avx) {
                tsbench_simdcomp_core_avx2_pack(values, packed, width, h->api == Api::WithoutMask);
            } else if (h->avx || h->api == Api::Length) {
                const auto* end = simdpack_length(values, n, reinterpret_cast<__m128i*>(packed), width);
                tsbench_core::require(reinterpret_cast<const std::uint8_t*>(end) == packed + payload,
                                      "SIMDComp length pack extent differs");
            } else if (n < 128) {
                const auto* end = simdpack_shortlength(values, static_cast<int>(n),
                                                      reinterpret_cast<__m128i*>(packed), width);
                tsbench_core::require(reinterpret_cast<const std::uint8_t*>(end) == packed + payload,
                                      "SIMDComp short pack extent differs");
            } else if (h->api == Api::WithoutMask) {
                simdpackwithoutmask(values, reinterpret_cast<__m128i*>(packed), width);
            } else simdpack(values, reinterpret_cast<__m128i*>(packed), width);
            at += payload;
        }
        tsbench_core::caller_result(output, at, capacity, result);
    });
}
extern "C" int tsbench_core_validate(void* context, const std::uint8_t* input, std::size_t size) {
    auto* h = static_cast<SimdCoreState*>(context);
    return tsbench_core::guard(h, [&] {
        h = state(context);
        tsbench_core::require(h->decoder && input && size >= header_bytes,
                              "invalid direct SIMDComp validation request");
        tsbench_core::require(load32(input) == h->count && input[4] <= 1,
                              "direct SIMDComp count/profile differs from task");
        const bool avx = input[4] != 0;
        cpu(avx);
        const std::size_t block = avx ? 256 : 128;
        // The driver invokes this pass outside the decode clock for each
        // immutable product. The native unpack primitive has no bounded API.
        std::size_t at = header_bytes;
        for (std::size_t start = 0; start < h->count; start += block) {
            const auto n = std::min(block, h->count-start);
            tsbench_core::require(at < size, "truncated direct SIMDComp width");
            const auto payload = payload_bytes(n, input[at++], avx && n == 256);
            tsbench_core::require(payload <= size-at, "truncated direct SIMDComp payload");
            at += payload;
        }
        tsbench_core::require(at == size, "trailing direct SIMDComp bytes");
    });
}
extern "C" int tsbench_core_decode(void* context, const std::uint8_t* input,
    std::size_t size, std::uint8_t* output, std::size_t capacity, tsbench_core_result* result) {
    auto* h = static_cast<SimdCoreState*>(context);
    return tsbench_core::guard(h, [&] {
        h = state(context);
        // The core contract requires this immutable stream to have passed
        // validate outside the clock, possibly on another decoder context.
        tsbench_core::require(result && h->decoder && input && size >= header_bytes,
                              "invalid direct SIMDComp decode request");
        *result = {};
        tsbench_core::require(load32(input) == h->count && input[4] <= 1,
                              "direct SIMDComp count/profile differs from task");
        if (capacity < h->bytes) throw tsbench_core::Capacity("direct SIMDComp decoded capacity");
        tsbench_core::require(output || !h->bytes, "null direct SIMDComp decoded output");
        disjoint(input, size, output, capacity);
        const bool avx = input[4] != 0;
        const std::size_t block = avx ? 256 : 128;
        std::size_t at = header_bytes;
        for (std::size_t start = 0; start < h->count; start += block) {
            const auto n = std::min(block, h->count-start);
            const unsigned width = input[at++];
            const bool full_avx = avx && n == 256;
            const auto payload = payload_bytes(n, width, full_avx);
            auto* values = reinterpret_cast<std::uint32_t*>(output + start*4);
            const bool staged = reinterpret_cast<std::uintptr_t>(values) % alignof(std::uint32_t) != 0;
            if (staged) values = h->stage;
            const auto* packed = input + at;
            if (full_avx) tsbench_simdcomp_core_avx2_unpack(packed, values, width);
            else {
                const auto* end = simdunpack_length(reinterpret_cast<const __m128i*>(packed), n, values, width);
                tsbench_core::require(reinterpret_cast<const std::uint8_t*>(end) == packed + payload,
                                      "SIMDComp length unpack extent differs");
            }
            if (staged) std::memcpy(output + start*4, values, n*4);
            at += payload;
        }
        tsbench_core::caller_result(output, h->bytes, capacity, result);
    });
}
extern "C" void tsbench_core_release(tsbench_core_result* result) { tsbench_core::release(result); }
extern "C" const char* tsbench_core_error(void* context) {
    return context ? static_cast<SimdCoreState*>(context)->error.c_str()
                   : tsbench_core::last_error().c_str();
}
