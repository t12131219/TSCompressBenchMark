// SPDX-License-Identifier: MIT
// TSBench binding only. The frozen Gorilla implementation is unchanged.
#include "tscb_adapter_v1.h"
#include "gorilla/gorilla.hpp"
#include <cstdio>
#include <cstring>
#include <limits>
#include <new>
#include <string_view>
#include <vector>

struct tscb_codec_handle_v1 {
    gorilla::Path path;
    bool encoded = false;
    char error[256] = {};
};
namespace {
using Status = tscb_status_v1;
Status fail(tscb_codec_handle_v1* h, Status code, const char* message) noexcept {
    if (h) std::snprintf(h->error, sizeof(h->error), "%s", message);
    return code;
}
template<class F> Status guard(tscb_codec_handle_v1* h, F&& f) noexcept {
    if (!h) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    h->error[0] = 0;
    try { return f(); }
    catch (const gorilla::Error& e) {
        Status code = TSCB_STATUS_CODEC_ERROR_V1;
        if (e.code() == gorilla::Code::Capacity) code = TSCB_STATUS_DST_TOO_SMALL_V1;
        if (e.code() == gorilla::Code::InvalidArgument) code = TSCB_STATUS_INVALID_ARGUMENT_V1;
        if (e.code() == gorilla::Code::Limit || e.code() == gorilla::Code::Unsupported) code = TSCB_STATUS_UNSUPPORTED_V1;
        return fail(h, code, e.what());
    } catch (const std::exception& e) { return fail(h, TSCB_STATUS_CODEC_ERROR_V1, e.what()); }
    catch (...) { return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "unknown C++ exception"); }
}
bool valid(const tscb_buffer_v1* b, bool input) noexcept {
    return b && b->dtype == TSCB_DTYPE_BYTES_V1 && b->rank == 1 &&
           b->strides_bytes[0] == 1 && b->reserved == 0 &&
           b->used_bytes <= b->capacity_bytes &&
           b->capacity_bytes <= std::numeric_limits<std::size_t>::max() &&
           (!b->capacity_bytes || b->data) && (!input || b->shape[0] == b->used_bytes);
}
bool overlap(const tscb_buffer_v1* a, const tscb_buffer_v1* b) noexcept {
    const auto x = reinterpret_cast<std::uintptr_t>(a->data);
    const auto y = reinterpret_cast<std::uintptr_t>(b->data);
    if (!a->used_bytes || !b->capacity_bytes) return false;
    return x <= y ? y - x < a->used_bytes : x - y < b->capacity_bytes;
}
std::uint64_t load_le(const unsigned char* p) noexcept {
    std::uint64_t v = 0;
    for (unsigned i = 0; i < 8; ++i) v |= std::uint64_t(p[i]) << (8 * i);
    return v;
}
void store_le(unsigned char* p, std::uint64_t v) noexcept {
    for (unsigned i = 0; i < 8; ++i) p[i] = static_cast<unsigned char>(v >> (8 * i));
}
Status input_count(tscb_codec_handle_v1* h, const tscb_buffer_v1* b, std::size_t& n) noexcept {
    if (!valid(b, true) || b->used_bytes % 16) return fail(h, TSCB_STATUS_INVALID_ARGUMENT_V1, "expected LE int64/uint64 pair bytes");
    n = static_cast<std::size_t>(b->used_bytes / 16);
    if (n > gorilla::max_samples) return fail(h, TSCB_STATUS_UNSUPPORTED_V1, "EncXOR count exceeds 65535");
    return TSCB_STATUS_OK_V1;
}
}
extern "C" {
uint32_t tscb_get_abi_version(void) { return 1; }
tscb_status_v1 tscb_get_manifest_json(const char** json, uint64_t* length) {
    static constexpr char manifest[] = R"({"abi_version":1,"algorithm":"gorilla-prometheus-xor","implementation":"gorilla-prometheus-xor-cpp-v1","input":"LE_I64_U64_INTERLEAVED_PAIRS","output":"PROMETHEUS_RAW_ENCXOR","max_samples":65535,"paths":["canonical","optimized"],"safe_overread_bytes":0,"streaming":false,"query":false,"random_access":false})";
    if (!json || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = manifest; *length = sizeof(manifest) - 1; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_create(const char* config, uint64_t length, tscb_codec_handle_v1** result) {
    if (!result || !config || length > 64) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    const std::string_view text(config, static_cast<std::size_t>(length));
    gorilla::Path path;
    if (text == R"({"path":"canonical"})") path = gorilla::Path::Canonical;
    else if (text == R"({"path":"optimized"})") path = gorilla::Path::Optimized;
    else return TSCB_STATUS_UNSUPPORTED_V1;
    try { *result = new tscb_codec_handle_v1{path, false, {}}; return TSCB_STATUS_OK_V1; }
    catch (...) { return TSCB_STATUS_CODEC_ERROR_V1; }
}
tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* h) { delete h; return TSCB_STATUS_OK_V1; }
tscb_status_v1 tscb_reset(tscb_codec_handle_v1* h, uint32_t mode) {
    return guard(h, [&] { if (mode) return fail(h, TSCB_STATUS_UNSUPPORTED_V1, "only fresh reset mode 0 is supported"); h->encoded = false; return TSCB_STATUS_OK_V1; });
}
tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* h, const tscb_buffer_v1* input, uint64_t* bound) {
    return guard(h, [&] { if (!bound) return TSCB_STATUS_INVALID_ARGUMENT_V1;
        std::size_t n = 0; const auto status = input_count(h, input, n); if (status) return status;
        *bound = gorilla::compress_bound(n); return TSCB_STATUS_OK_V1; });
}
tscb_status_v1 tscb_compress(tscb_codec_handle_v1* h, const tscb_buffer_v1* input, tscb_buffer_v1* output) {
    return guard(h, [&] {
        std::size_t n = 0; const auto status = input_count(h, input, n); if (status) return status;
        if (!valid(output, false) || overlap(input, output)) return fail(h, TSCB_STATUS_INVALID_ARGUMENT_V1, "invalid or overlapping output");
        if (h->encoded) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "reset required before another encode");
        if (output->capacity_bytes < gorilla::compress_bound(n)) return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "output below worst-case bound");
        const auto* bytes = static_cast<const unsigned char*>(input->data);
        std::vector<gorilla::Sample> samples(n);
        for (std::size_t i = 0; i < n; ++i) samples[i] = {gorilla::signed_bits(load_le(bytes + 16*i)), load_le(bytes + 16*i + 8)};
        const auto raw = gorilla::encode(samples.data(), n, h->path);
        if (!raw.empty()) std::memcpy(output->data, raw.data(), raw.size());
        output->used_bytes = raw.size(); h->encoded = true; return TSCB_STATUS_OK_V1;
    });
}
tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* h, tscb_buffer_v1* output) {
    return guard(h, [&] {
        if (!valid(output, false)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
        if (!h->encoded) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "encode required before finalize");
        output->used_bytes = 0; return TSCB_STATUS_OK_V1;
    });
}
tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* h, const tscb_buffer_v1* input, tscb_buffer_v1* output) {
    return guard(h, [&] {
        if (!valid(input, true) || input->used_bytes < 2 || !valid(output, false) || overlap(input, output)) return fail(h, TSCB_STATUS_INVALID_ARGUMENT_V1, "invalid decode buffers");
        const auto* bytes = static_cast<const unsigned char*>(input->data);
        const std::size_t n = std::size_t(bytes[0]) * 256 + bytes[1];
        if (input->used_bytes > gorilla::compress_bound(n)) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "raw chunk exceeds bound");
        if (output->capacity_bytes < n * 16) return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "decoded output too small");
        const auto samples = gorilla::decode(bytes, static_cast<std::size_t>(input->used_bytes), h->path, true);
        std::vector<unsigned char> decoded(n * 16);
        for (std::size_t i = 0; i < n; ++i) { store_le(decoded.data() + 16*i, static_cast<std::uint64_t>(samples[i].timestamp)); store_le(decoded.data() + 16*i + 8, samples[i].value_bits); }
        if (!decoded.empty()) std::memcpy(output->data, decoded.data(), decoded.size());
        output->used_bytes = decoded.size(); return TSCB_STATUS_OK_V1;
    });
}
tscb_status_v1 tscb_set_native_timing(tscb_codec_handle_v1* h, uint32_t) { return h ? TSCB_STATUS_UNSUPPORTED_V1 : TSCB_STATUS_INVALID_ARGUMENT_V1; }
tscb_status_v1 tscb_get_native_timing(tscb_codec_handle_v1* h, tscb_native_timing_v1*) { return h ? TSCB_STATUS_UNSUPPORTED_V1 : TSCB_STATUS_INVALID_ARGUMENT_V1; }
tscb_status_v1 tscb_query(tscb_codec_handle_v1*, const char*, uint64_t, char*, uint64_t, uint64_t*) { return TSCB_STATUS_UNSUPPORTED_V1; }
tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1*, const char**, uint64_t*) { return TSCB_STATUS_UNSUPPORTED_V1; }
tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* h, const char** message, uint64_t* length) {
    if (!h || !message || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message = h->error; *length = std::strlen(h->error); return TSCB_STATUS_OK_V1;
}
}

// Direct joint-records entry: raw LE int64 timestamp/f64-bit pairs, no C1
// envelope, Sample staging array or caller-output copy of the encoded vector.
#include "tsbench_core.hpp"
#include <memory>

namespace {
struct GorillaCoreState final : tsbench_core::State {
    gorilla::Path path = gorilla::Path::Canonical;
    bool decoder = false;
    std::size_t rows = 0, bytes = 0;
};
// Keep the native Encoder itself alive with the result so finalize()'s vector
// view survives context destruction. This also avoids its one-shot API's
// const-reference-to-vector copy; reset, append and finalize remain timed work.
struct GorillaCoreOutput final : tsbench_core::Owner {
    gorilla::Encoder encoder;
    explicit GorillaCoreOutput(gorilla::Path path) : encoder(path) {}
};
GorillaCoreState* gorilla_core_state(void* context) {
    tsbench_core::require(context != nullptr, "null direct Gorilla context");
    return static_cast<GorillaCoreState*>(context);
}
void gorilla_core_input(const GorillaCoreState& state, const std::uint8_t* input,
                        std::size_t size) {
    tsbench_core::require((input || !size) && size == state.bytes,
                          "direct Gorilla requires 16 bytes per declared T/V row");
}
}
extern "C" std::uint32_t tsbench_core_version() { return 1; }
extern "C" std::uint32_t tsbench_core_storage() { return 2; }
extern "C" int tsbench_core_create(const tsbench_core_config* c, int decoder, void** output) {
    return tsbench_core::guard(nullptr, [&] {
        tsbench_core::require(c && output, "null direct Gorilla configuration");
        *output = nullptr;
        tsbench_core::require(c->version == 1, "unknown direct Gorilla contract version");
        if (c->dtype != TSCB_DTYPE_BYTES_V1 || c->rank != 2 ||
            c->order != 0 || c->shape[1] != 2)
            throw tsbench_core::Unsupported("direct Gorilla requires C-order rank2 (rows,2) joint T/V pairs");
        if (c->shape[0] > gorilla::max_samples)
            throw tsbench_core::Unsupported("direct Gorilla count exceeds 65535");
        auto state = std::make_unique<GorillaCoreState>();
        state->decoder = decoder != 0;
        state->rows = static_cast<std::size_t>(c->shape[0]);
        state->bytes = tsbench_core::multiply(state->rows, 16);
        const tsbench_core::Parameters parameters(c->parameters_json);
        if (state->decoder) {
            tsbench_core::require(parameters.empty() && (!c->model || !*c->model),
                                  "direct Gorilla decoder must not receive encoder parameters");
            // Canonical and optimized paths implement the identical EncXOR
            // stream. The independent decoder needs no encoder-only path tag.
        } else {
            const auto path = parameters.string("path");
            if (path == "canonical") state->path = gorilla::Path::Canonical;
            else if (path == "optimized") {
#ifdef GORILLA_HAS_OPTIMIZED
                state->path = gorilla::Path::Optimized;
#else
                throw tsbench_core::Unsupported("Gorilla optimized path not built");
#endif
            } else throw tsbench_core::Unsupported("unknown direct Gorilla execution path");
        }
        *output = state.release();
    });
}
extern "C" int tsbench_core_destroy(void* context) {
    delete static_cast<GorillaCoreState*>(context); return 0;
}
extern "C" int tsbench_core_bound(void* context, const std::uint8_t* input,
                                   std::size_t size, std::size_t* bound) {
    auto* state = static_cast<GorillaCoreState*>(context);
    return tsbench_core::guard(state, [&] {
        state = gorilla_core_state(context);
        tsbench_core::require(bound && !state->decoder, "invalid direct Gorilla bound request");
        gorilla_core_input(*state, input, size);
        *bound = gorilla::compress_bound(state->rows);
    });
}
extern "C" int tsbench_core_encode(void* context, const std::uint8_t* input,
    std::size_t size, std::uint8_t*, std::size_t capacity, tsbench_core_result* result) {
    auto* state = static_cast<GorillaCoreState*>(context);
    return tsbench_core::guard(state, [&] {
        state = gorilla_core_state(context);
        tsbench_core::require(result && !state->decoder, "invalid direct Gorilla encode request");
        *result = {};
        gorilla_core_input(*state, input, size);
        auto owner = std::make_unique<GorillaCoreOutput>(state->path);
        for (std::size_t i = 0; i < state->rows; ++i)
            owner->encoder.append({gorilla::signed_bits(load_le(input + 16*i)),
                                    load_le(input + 16*i + 8)});
        const auto& encoded = owner->encoder.finalize();
        if (encoded.size() > capacity)
            throw tsbench_core::Capacity("direct Gorilla encoded output exceeds capacity");
        result->data = encoded.data(); result->size = encoded.size();
        result->capacity = encoded.capacity();
        result->owner = static_cast<tsbench_core::Owner*>(owner.release());
    });
}
extern "C" int tsbench_core_decode(void* context, const std::uint8_t* input,
    std::size_t size, std::uint8_t* output, std::size_t capacity, tsbench_core_result* result) {
    auto* state = static_cast<GorillaCoreState*>(context);
    return tsbench_core::guard(state, [&] {
        state = gorilla_core_state(context);
        tsbench_core::require(result && state->decoder && input && size >= 2,
                              "invalid direct Gorilla decode request");
        *result = {};
        const std::size_t rows = std::size_t(input[0])*256 + input[1];
        tsbench_core::require(rows == state->rows && size <= gorilla::compress_bound(rows),
                              "direct Gorilla raw count/extent differs from task");
        if (capacity < state->bytes)
            throw tsbench_core::Capacity("direct Gorilla decoded output exceeds capacity");
        tsbench_core::require(output || !state->bytes, "null direct Gorilla decoded buffer");
        if (size && capacity) {
            const auto x = reinterpret_cast<std::uintptr_t>(input);
            const auto y = reinterpret_cast<std::uintptr_t>(output);
            tsbench_core::require(!(x <= y ? y - x < size : x - y < capacity),
                                  "overlapping direct Gorilla decode buffers");
        }
        gorilla::Iterator decoder(input, size, state->path, true, gorilla::InputStorage::Borrowed);
        std::size_t written = 0;
        while (decoder.next()) {
            const auto sample = decoder.at();
            store_le(output + written, static_cast<std::uint64_t>(sample.timestamp));
            store_le(output + written + 8, sample.value_bits);
            written += 16;
        }
        tsbench_core::require(written == state->bytes, "direct Gorilla decoded count mismatch");
        tsbench_core::caller_result(output, written, capacity, result);
    });
}
extern "C" void tsbench_core_release(tsbench_core_result* result) { tsbench_core::release(result); }
extern "C" const char* tsbench_core_error(void* context) {
    return context ? static_cast<GorillaCoreState*>(context)->error.c_str()
                   : tsbench_core::last_error().c_str();
}
