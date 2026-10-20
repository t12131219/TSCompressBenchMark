// Physical signed scalar stream with complete native SDSL model persistence.
// The 13-byte recovery prefix contains only algorithm identity, original scalar
// width and the normalization bias absent from native SDSL serialization.
#include "tsbench_core.hpp"
#include <memory>
#include <streambuf>
namespace {
#if TSCB_NEATS
constexpr char core_magic[] = "NDC1";
#else
constexpr char core_magic[] = "LDC1";
#endif
constexpr size_t core_prefix = 13;
struct NeatsCore : tsbench_core::State {
    size_t count{}, bytes{}, width{}; uint8_t max_bpc{16}; bool decoder{};
};
class CoreOutputBuffer final : public std::streambuf {
    char* data_; size_t capacity_, used_{};
public:
    CoreOutputBuffer(uint8_t* data, size_t capacity) : data_(reinterpret_cast<char*>(data)), capacity_(capacity) {}
    size_t size() const { return used_; }
protected:
    std::streamsize xsputn(const char* data, std::streamsize length) override {
        if (length < 0 || static_cast<uint64_t>(length) > capacity_ - used_) return 0;
        if (length) std::memcpy(data_ + used_, data, static_cast<size_t>(length));
        used_ += static_cast<size_t>(length); return length;
    }
    int_type overflow(int_type value) override {
        if (traits_type::eq_int_type(value, traits_type::eof())) return traits_type::not_eof(value);
        if (used_ == capacity_) return traits_type::eof();
        data_[used_++] = traits_type::to_char_type(value); return value;
    }
};
class CoreInputBuffer final : public std::streambuf {
public:
    CoreInputBuffer(const uint8_t* data, size_t length) {
        auto* first = reinterpret_cast<char*>(const_cast<uint8_t*>(data));
        setg(first, first, first + length);
    }
};
}
extern "C" uint32_t tsbench_core_version() { return 1; }
extern "C" uint32_t tsbench_core_storage() { return 3; }
extern "C" int tsbench_core_create(const tsbench_core_config* config, int decoder, void** result) {
    return tsbench_core::guard(nullptr, [&] {
        tsbench_core::require(config && result, "null NeaTS/LeaTS core configuration"); *result = nullptr;
        if (config->dtype != TSCB_DTYPE_I8_V1 && config->dtype != TSCB_DTYPE_I16_LE_V1 &&
            config->dtype != TSCB_DTYPE_I32_LE_V1 && config->dtype != TSCB_DTYPE_I64_LE_V1)
            throw tsbench_core::Unsupported("NeaTS/LeaTS requires signed integer input");
        auto state = std::make_unique<NeatsCore>();
        state->count = tsbench_core::elements(*config); state->bytes = tsbench_core::input_bytes(*config);
        state->width = tsbench_core::width(config->dtype); state->decoder = decoder != 0;
        if (!state->count || state->count > kMaxRows)
            throw tsbench_core::Unsupported("NeaTS/LeaTS physical scalar stream requires 1..65536 values");
        if (!decoder) {
            tsbench_core::Parameters parameters(config->parameters_json);
            if (parameters.contains("max_bpc")) state->max_bpc = parameters.integer("max_bpc", 16, 32);
            if (state->max_bpc != 16 && state->max_bpc != 32)
                throw tsbench_core::Unsupported("NeaTS/LeaTS max_bpc must be 16 or 32");
            if (parameters.contains("isa") && parameters.string("isa") != "SCALAR")
                throw tsbench_core::Unsupported("NeaTS/LeaTS core requires SCALAR");
        }
        *result = state.release();
    });
}
extern "C" int tsbench_core_destroy(void* context) { delete static_cast<NeatsCore*>(context); return 0; }
extern "C" int tsbench_core_bound(void* context, const uint8_t* input, size_t length, size_t* bound) {
    auto* state = static_cast<NeatsCore*>(context);
    return tsbench_core::guard(state, [&] {
        tsbench_core::require(state && bound && input && length == state->bytes, "NeaTS/LeaTS direct input mismatch");
        *bound = tsbench_core::add(core_prefix + 4096, tsbench_core::multiply(state->count, 128));
    });
}
extern "C" int tsbench_core_encode(void* context, const uint8_t* input, size_t length,
                                    uint8_t* output, size_t capacity, tsbench_core_result* result) {
    auto* state = static_cast<NeatsCore*>(context);
    return tsbench_core::guard(state, [&] {
        tsbench_core::require(state && !state->decoder && result && input && length == state->bytes,
                              "NeaTS/LeaTS direct input mismatch");
        if (!output || capacity < core_prefix) throw tsbench_core::Capacity("NeaTS/LeaTS output buffer too small");
        int64_t bias = read_signed(input, static_cast<uint8_t>(state->width));
        for (size_t i = 1; i < state->count; ++i)
            bias = std::min(bias, read_signed(input + i * state->width, static_cast<uint8_t>(state->width)));
        std::vector<int64_t> normalized(state->count);
        for (size_t i = 0; i < state->count; ++i) {
            const int64_t value = read_signed(input + i * state->width, static_cast<uint8_t>(state->width));
            const uint64_t delta = static_cast<uint64_t>(value) - static_cast<uint64_t>(bias);
            if (delta > static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))
                throw tsbench_core::Unsupported("NeaTS/LeaTS physical stream span exceeds signed normalization");
            normalized[i] = static_cast<int64_t>(delta);
        }
        Codec codec{state->max_bpc};
        codec.partitioning(normalized.begin(), normalized.end());
        CoreOutputBuffer buffer(output, capacity); std::ostream stream(&buffer);
        stream.write(core_magic, 4); stream.put(static_cast<char>(state->width));
        uint64_t raw_bias = static_cast<uint64_t>(bias);
        for (size_t i = 0; i < 8; ++i) stream.put(static_cast<char>(raw_bias >> (8 * i)));
        codec.serialize(stream);
        if (!stream) throw tsbench_core::Capacity("NeaTS/LeaTS serialization exceeds output capacity");
        tsbench_core::caller_result(output, buffer.size(), capacity, result);
    });
}
extern "C" int tsbench_core_decode(void* context, const uint8_t* input, size_t length,
                                    uint8_t* output, size_t capacity, tsbench_core_result* result) {
    auto* state = static_cast<NeatsCore*>(context);
    return tsbench_core::guard(state, [&] {
        tsbench_core::require(state && state->decoder && input && result && length >= core_prefix + 13 &&
            !std::memcmp(input, core_magic, 4) && input[4] == state->width,
            "NeaTS/LeaTS recovery prefix mismatch");
        if (!output || capacity < state->bytes) throw tsbench_core::Capacity("NeaTS/LeaTS decode capacity too small");
        // SDSL's initial fields encode max_bpc and uint32 count. Check these
        // before its allocation-bearing load and bound the entire native frame.
        tsbench_core::require((input[13] == 16 || input[13] == 32) && read_u32(input + 14) == state->count &&
            length <= core_prefix + 4096 + state->count * 128, "invalid NeaTS/LeaTS native model header");
        const int64_t bias = read_signed(input + 5, 8);
        CoreInputBuffer buffer(input + core_prefix, length - core_prefix); std::istream stream(&buffer);
        auto codec = Codec::load(stream);
        tsbench_core::require(stream && stream.peek() == std::char_traits<char>::eof() && codec.size() == state->count,
                              "invalid NeaTS/LeaTS native model serialization");
        std::vector<int64_t> normalized(state->count);
        codec.decompress(normalized.begin(), normalized.end());
        for (size_t i = 0; i < state->count; ++i) {
            const __int128 value = static_cast<__int128>(normalized[i]) + bias;
            tsbench_core::require(value >= std::numeric_limits<int64_t>::min() && value <= std::numeric_limits<int64_t>::max() &&
                write_signed(output + i * state->width, static_cast<uint8_t>(state->width), static_cast<int64_t>(value)),
                "NeaTS/LeaTS decoded value exceeds original dtype");
        }
        tsbench_core::caller_result(output, state->bytes, capacity, result);
    });
}
extern "C" void tsbench_core_release(tsbench_core_result* result) { tsbench_core::release(result); }
extern "C" const char* tsbench_core_error(void* context) {
    return context ? static_cast<NeatsCore*>(context)->error.c_str() : tsbench_core::last_error().c_str();
}
