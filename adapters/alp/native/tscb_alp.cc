#include "tscb_native_timing.h"

#include "alp/encoder.hpp"
#include "alp/rd.hpp"
#include "fastlanes/ffor.hpp"
#include "fastlanes/unffor.hpp"

#include <algorithm>
#include <array>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <new>
#include <type_traits>
#include <vector>

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer{};
    uint64_t input_bytes{};
    uint64_t stream_bytes{};
    bool updated{};
    bool finalized{};
    char last_error[256]{};
    char accounting_json[256]{};
};

namespace {

constexpr uint64_t kMaxElements = 16ULL * 1024ULL * 1024ULL;
constexpr uint32_t kVectorSize = 1024;
constexpr uint32_t kRowgroupSize = 102400;

#if TSCB_ALP_RD
constexpr uint8_t kScheme = 1;
constexpr char kConfig[] = "{\"algorithm\":\"alp-rd\"}";
constexpr char kManifest[] =
    "{\"abi_version\":1,\"algorithm\":\"alp-rd\",\"library\":\"cwida/ALP@31ca0ed1\","
    "\"scheme\":\"FORCED_ALP_RD\",\"vector_size\":1024,\"rowgroup_size\":102400,"
    "\"isa\":\"SCALAR_FASTLANES_FALLBACK\",\"threading\":\"SINGLE_THREAD\"}";
#else
constexpr uint8_t kScheme = 0;
constexpr char kConfig[] = "{\"algorithm\":\"alp\"}";
constexpr char kManifest[] =
    "{\"abi_version\":1,\"algorithm\":\"alp\",\"library\":\"cwida/ALP@31ca0ed1\","
    "\"scheme\":\"FORCED_DECIMAL_ALP_NO_RD_FALLBACK\",\"vector_size\":1024,"
    "\"rowgroup_size\":102400,\"isa\":\"SCALAR_FASTLANES_FALLBACK\","
    "\"threading\":\"SINGLE_THREAD\"}";
#endif

void set_error(tscb_codec_handle_v1* handle, const char* message) {
    if (handle) std::snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
}

bool valid_buffer(const tscb_buffer_v1* buffer) {
    return buffer && buffer->dtype == TSCB_DTYPE_BYTES_V1 && buffer->rank == 1 &&
           buffer->used_bytes <= buffer->capacity_bytes &&
           (buffer->used_bytes == 0 || buffer->data);
}

bool overlaps(const tscb_buffer_v1* input, const tscb_buffer_v1* output) {
    const auto a = reinterpret_cast<uintptr_t>(input->data);
    const auto b = reinterpret_cast<uintptr_t>(output->data);
    return input->used_bytes && output->capacity_bytes &&
           (a <= b ? b - a < input->used_bytes : a - b < output->capacity_bytes);
}

struct Writer {
    std::vector<uint8_t> bytes;

    template <typename T> void integer(T value) {
        using U = std::make_unsigned_t<T>;
        U bits{};
        std::memcpy(&bits, &value, sizeof(bits));
        for (size_t i = 0; i < sizeof(bits); ++i) {
            bytes.push_back(static_cast<uint8_t>(bits >> (i * 8)));
        }
    }

    void raw(const void* data, size_t size) {
        const auto* begin = static_cast<const uint8_t*>(data);
        bytes.insert(bytes.end(), begin, begin + size);
    }
};

struct Reader {
    const uint8_t* data;
    size_t size;
    size_t offset{};

    template <typename T> bool integer(T& value) {
        if (size - offset < sizeof(T)) return false;
        using U = std::make_unsigned_t<T>;
        U bits{};
        for (size_t i = 0; i < sizeof(T); ++i) {
            bits |= static_cast<U>(data[offset++]) << (i * 8);
        }
        std::memcpy(&value, &bits, sizeof(value));
        return true;
    }

    bool raw(void* target, size_t length) {
        if (length > size - offset) return false;
        if (length) std::memcpy(target, data + offset, length);
        offset += length;
        return true;
    }
};

struct InputView {
    uint8_t width{};
    uint16_t columns{};
    uint64_t rows{};
    const uint8_t* payload{};
};

bool parse_input(const tscb_buffer_v1* input, InputView& view) {
    if (!valid_buffer(input) || input->used_bytes < 16) return false;
    Reader reader{static_cast<const uint8_t*>(input->data), static_cast<size_t>(input->used_bytes)};
    std::array<char, 4> magic{};
    uint8_t reserved{};
    uint64_t expected{};
    if (!reader.raw(magic.data(), magic.size()) || std::memcmp(magic.data(), "TAI1", 4) ||
        !reader.integer(view.width) || !reader.integer(reserved) ||
        !reader.integer(view.columns) || !reader.integer(view.rows) || reserved ||
        (view.width != 4 && view.width != 8) || view.columns == 0 ||
        view.rows > kMaxElements ||
        view.rows > kMaxElements / view.columns) return false;
    expected = view.rows * view.columns * view.width;
    if (expected != input->used_bytes - 16) return false;
    view.payload = static_cast<const uint8_t*>(input->data) + 16;
    return true;
}

template <typename T>
bool encode_typed(const InputView& input, Writer& writer, const bool rd_only) {
    using ST = typename alp::inner_t<T>::st;
    using UT = typename alp::inner_t<T>::ut;
    writer.raw(rd_only ? "ARD1" : "ALP1", 4);
    writer.integer<uint8_t>(1);
    writer.integer<uint8_t>(sizeof(T));
    writer.integer<uint8_t>(rd_only ? 1 : 0);
    writer.integer<uint8_t>(0);
    writer.integer<uint32_t>(input.columns);
    writer.integer<uint64_t>(input.rows);
    writer.integer<uint32_t>(kVectorSize);

    std::array<T, kVectorSize> values{};
    std::array<T, kVectorSize> sample{};
    std::array<T, kVectorSize> exceptions{};
    std::array<uint16_t, kVectorSize> rd_exceptions{};
    std::array<uint16_t, kVectorSize> positions{};
    std::array<ST, kVectorSize> encoded{};
    std::array<ST, kVectorSize> packed{};
    std::array<UT, kVectorSize> right{};
    std::array<UT, kVectorSize> packed_right{};
    std::array<uint16_t, kVectorSize> left{};
    std::array<uint16_t, kVectorSize> packed_left{};

    const uint64_t groups = (input.rows + kRowgroupSize - 1) / kRowgroupSize;
    const uint64_t vectors_total = (input.rows + kVectorSize - 1) / kVectorSize;
    for (uint16_t column = 0; column < input.columns; ++column) {
        writer.integer<uint32_t>(static_cast<uint32_t>(groups));
        const auto* column_data = reinterpret_cast<const T*>(
            input.payload + static_cast<uint64_t>(column) * input.rows * sizeof(T));
        uint64_t row = 0;
        for (uint64_t group = 0; group < groups; ++group) {
            const uint32_t logical = static_cast<uint32_t>(
                std::min<uint64_t>(kRowgroupSize, input.rows - row));
            const uint16_t vector_count = static_cast<uint16_t>((logical + kVectorSize - 1) / kVectorSize);
            const size_t padded = static_cast<size_t>(vector_count) * kVectorSize;
            std::vector<T> rowgroup(padded, T{});
            std::memcpy(rowgroup.data(), column_data + row, static_cast<size_t>(logical) * sizeof(T));
            alp::state<T> state;
            if (rd_only) {
                alp::rd_encoder<T>::init(rowgroup.data(), 0, padded, sample.data(), state);
            } else {
                alp::encoder<T>::init(rowgroup.data(), 0, padded, sample.data(), state);
                if (state.scheme != alp::Scheme::ALP || state.best_k_combinations.empty()) return false;
            }
            writer.integer<uint32_t>(logical);
            writer.integer<uint16_t>(vector_count);
            if (rd_only) {
                writer.integer<uint8_t>(state.right_bit_width);
                writer.integer<uint8_t>(state.left_bit_width);
                writer.integer<uint8_t>(state.actual_dictionary_size);
                writer.integer<uint8_t>(0);
                for (uint8_t i = 0; i < state.actual_dictionary_size; ++i) {
                    writer.integer<uint16_t>(state.left_parts_dict[i]);
                }
            }
            for (uint16_t vector = 0; vector < vector_count; ++vector) {
                const uint16_t count = static_cast<uint16_t>(
                    std::min<uint32_t>(kVectorSize, logical - static_cast<uint32_t>(vector) * kVectorSize));
                std::memcpy(values.data(), rowgroup.data() + static_cast<size_t>(vector) * kVectorSize,
                            kVectorSize * sizeof(T));
                writer.integer<uint16_t>(count);
                uint16_t exception_count{};
                if (rd_only) {
                    alp::rd_encoder<T>::encode(values.data(), rd_exceptions.data(), positions.data(),
                                               &exception_count, right.data(), left.data(), state);
                    ffor::ffor(right.data(), packed_right.data(), state.right_bit_width,
                               &state.right_for_base);
                    ffor::ffor(left.data(), packed_left.data(), state.left_bit_width,
                               &state.left_for_base);
                    writer.integer<uint16_t>(exception_count);
                    writer.raw(packed_right.data(), static_cast<size_t>(state.right_bit_width) * 128);
                    writer.raw(packed_left.data(), static_cast<size_t>(state.left_bit_width) * 128);
                    for (uint16_t i = 0; i < exception_count; ++i) {
                        writer.integer<uint16_t>(positions[i]);
                        writer.integer<uint16_t>(rd_exceptions[i]);
                    }
                } else {
                    alp::encoder<T>::encode(values.data(), exceptions.data(), positions.data(),
                                            &exception_count, encoded.data(), state);
                    ST base{};
                    alp::encoder<T>::analyze_ffor(encoded.data(), state.bit_width, &base);
                    ffor::ffor(encoded.data(), packed.data(), state.bit_width, &base);
                    writer.integer<uint8_t>(state.exp);
                    writer.integer<uint8_t>(state.fac);
                    writer.integer<uint8_t>(state.bit_width);
                    writer.integer<uint8_t>(0);
                    writer.integer<uint16_t>(exception_count);
                    writer.integer<ST>(base);
                    writer.raw(packed.data(), static_cast<size_t>(state.bit_width) * 128);
                    for (uint16_t i = 0; i < exception_count; ++i) {
                        writer.integer<uint16_t>(positions[i]);
                        writer.raw(&exceptions[i], sizeof(T));
                    }
                }
            }
            row += logical;
        }
    }
    return vectors_total <= std::numeric_limits<uint32_t>::max();
}

template <typename T>
bool decode_typed(Reader& reader, uint16_t columns, uint64_t rows, bool rd_only,
                  uint8_t* output, uint64_t output_size) {
    using ST = typename alp::inner_t<T>::st;
    using UT = typename alp::inner_t<T>::ut;
    if (output_size != rows * columns * sizeof(T)) return false;
    std::array<T, kVectorSize> decoded{};
    std::array<T, kVectorSize> exceptions{};
    std::array<uint16_t, kVectorSize> rd_exceptions{};
    std::array<uint16_t, kVectorSize> positions{};
    std::array<ST, kVectorSize> packed{};
    std::array<ST, kVectorSize> unpacked{};
    std::array<UT, kVectorSize> packed_right{};
    std::array<UT, kVectorSize> right{};
    std::array<uint16_t, kVectorSize> packed_left{};
    std::array<uint16_t, kVectorSize> left{};
    for (uint16_t column = 0; column < columns; ++column) {
        uint32_t group_count{};
        if (!reader.integer(group_count) || group_count != (rows + kRowgroupSize - 1) / kRowgroupSize) return false;
        uint64_t row = 0;
        for (uint32_t group = 0; group < group_count; ++group) {
            uint32_t logical{};
            uint16_t vector_count{};
            alp::state<T> state;
            if (!reader.integer(logical) || !reader.integer(vector_count) || logical == 0 ||
                logical > kRowgroupSize || logical > rows - row ||
                vector_count != (logical + kVectorSize - 1) / kVectorSize) return false;
            if (rd_only) {
                uint8_t reserved{};
                if (!reader.integer(state.right_bit_width) || !reader.integer(state.left_bit_width) ||
                    !reader.integer(state.actual_dictionary_size) || !reader.integer(reserved) || reserved ||
                    state.right_bit_width > sizeof(T) * 8 || state.left_bit_width > 4 ||
                    state.actual_dictionary_size == 0 || state.actual_dictionary_size > 8) return false;
                for (uint8_t i = 0; i < state.actual_dictionary_size; ++i) {
                    if (!reader.integer(state.left_parts_dict[i])) return false;
                }
                state.right_for_base = 0;
                state.left_for_base = 0;
            }
            for (uint16_t vector = 0; vector < vector_count; ++vector) {
                uint16_t count{};
                if (!reader.integer(count) || count == 0 || count > kVectorSize ||
                    count != std::min<uint32_t>(kVectorSize, logical - static_cast<uint32_t>(vector) * kVectorSize))
                    return false;
                if (rd_only) {
                    uint16_t exception_count{};
                    if (!reader.integer(exception_count) || exception_count > kVectorSize ||
                        !reader.raw(packed_right.data(), static_cast<size_t>(state.right_bit_width) * 128) ||
                        !reader.raw(packed_left.data(), static_cast<size_t>(state.left_bit_width) * 128)) return false;
                    for (uint16_t i = 0; i < exception_count; ++i) {
                        if (!reader.integer(positions[i]) || !reader.integer(rd_exceptions[i]) ||
                            positions[i] >= kVectorSize || (i && positions[i] <= positions[i - 1])) return false;
                    }
                    uint16_t exception_count_copy = exception_count;
                    unffor::unffor(packed_right.data(), right.data(), state.right_bit_width,
                                   &state.right_for_base);
                    unffor::unffor(packed_left.data(), left.data(), state.left_bit_width,
                                   &state.left_for_base);
                    alp::rd_encoder<T>::decode(decoded.data(), right.data(), left.data(),
                                               rd_exceptions.data(), positions.data(),
                                               &exception_count_copy, state);
                } else {
                    uint8_t reserved{};
                    uint16_t exception_count{};
                    ST base{};
                    if (!reader.integer(state.exp) || !reader.integer(state.fac) ||
                        !reader.integer(state.bit_width) || !reader.integer(reserved) || reserved ||
                        state.exp > alp::Constants<T>::MAX_EXPONENT ||
                        state.fac > (std::is_same_v<T, float> ? 9 : alp::Constants<T>::MAX_EXPONENT) ||
                        state.bit_width > sizeof(T) * 8 || !reader.integer(exception_count) ||
                        exception_count > kVectorSize || !reader.integer(base) ||
                        !reader.raw(packed.data(), static_cast<size_t>(state.bit_width) * 128)) return false;
                    for (uint16_t i = 0; i < exception_count; ++i) {
                        if (!reader.integer(positions[i]) || positions[i] >= kVectorSize ||
                            (i && positions[i] <= positions[i - 1]) ||
                            !reader.raw(&exceptions[i], sizeof(T))) return false;
                    }
                    unffor::unffor(packed.data(), unpacked.data(), state.bit_width, &base);
                    alp::decoder<T>::decode(unpacked.data(), state.fac, state.exp, decoded.data());
                    alp::decoder<T>::patch_exceptions(decoded.data(), exceptions.data(), positions.data(),
                                                       &exception_count);
                }
                std::memcpy(output + (static_cast<uint64_t>(column) * rows + row +
                            static_cast<uint64_t>(vector) * kVectorSize) * sizeof(T),
                            decoded.data(), static_cast<size_t>(count) * sizeof(T));
            }
            row += logical;
        }
        if (row != rows) return false;
    }
    return reader.offset == reader.size;
}

}  // namespace

extern "C" {

TSCB_NATIVE_TIMING_API

uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }

tscb_status_v1 tscb_get_manifest_json(const char** json, uint64_t* length) {
    if (!json || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = kManifest;
    *length = sizeof(kManifest) - 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(const char* config_json, uint64_t config_length,
                           tscb_codec_handle_v1** handle) {
    if (!config_json || !handle || config_length != sizeof(kConfig) - 1 ||
        std::memcmp(config_json, kConfig, sizeof(kConfig) - 1))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *handle = new (std::nothrow) tscb_codec_handle_v1{};
    return *handle ? TSCB_STATUS_OK_V1 : TSCB_STATUS_CODEC_ERROR_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* handle) {
    delete handle;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1* handle, uint32_t reset_mode) {
    if (!handle || reset_mode) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    const int timing = handle->native_timer.enabled;
    *handle = tscb_codec_handle_v1{};
    return tscb_set_native_timing(handle, timing ? 1u : 0u);
}

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* handle,
                                   const tscb_buffer_v1* input, uint64_t* bound) {
    InputView view;
    if (!handle || !bound || !parse_input(input, view)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    const uint64_t vectors = (view.rows + kVectorSize - 1) / kVectorSize;
    const uint64_t total_vectors = vectors * view.columns;
    if (total_vectors > (std::numeric_limits<uint64_t>::max() - 4096) / 20000 ||
        input->used_bytes > (std::numeric_limits<uint64_t>::max() - 4096 - total_vectors * 20000) / 3)
        return TSCB_STATUS_UNSUPPORTED_V1;
    *bound = input->used_bytes * 3 + total_vectors * 20000 + 4096;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1* handle, const tscb_buffer_v1* input,
                             tscb_buffer_v1* output) {
    InputView view;
    if (!handle || !valid_buffer(output) || !parse_input(input, view) ||
        handle->updated || handle->finalized || overlaps(input, output))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    Writer writer;
    bool ok = false;
    try {
        TSCB_TIME_CODEC(handle->native_timer, encode_ns,
            ok = view.width == 4 ? encode_typed<float>(view, writer, kScheme == 1)
                                 : encode_typed<double>(view, writer, kScheme == 1));
    } catch (const std::bad_alloc&) {
        set_error(handle, "ALP allocation failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (!ok) {
        set_error(handle, "input rowgroup selects ALP_RD; forced ALP identity forbids fallback");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    if (writer.bytes.size() > output->capacity_bytes) return TSCB_STATUS_DST_TOO_SMALL_V1;
    if (!writer.bytes.empty()) std::memcpy(output->data, writer.bytes.data(), writer.bytes.size());
    output->used_bytes = writer.bytes.size();
    handle->input_bytes = input->used_bytes - 16;
    handle->stream_bytes = writer.bytes.size();
    handle->updated = true;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* handle, tscb_buffer_v1* output) {
    if (!handle || !valid_buffer(output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!handle->updated) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (handle->finalized) return TSCB_STATUS_CODEC_ERROR_V1;
    output->used_bytes = 0;
    handle->finalized = true;
    std::snprintf(handle->accounting_json, sizeof(handle->accounting_json),
                  "{\"input_bytes\":%" PRIu64 ",\"alp_frame_bytes\":%" PRIu64
                  ",\"native_input_descriptor_bytes\":16,\"finalize_calls\":1}",
                  handle->input_bytes, handle->stream_bytes);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* handle, const tscb_buffer_v1* input,
                               tscb_buffer_v1* output) {
    if (!handle || !valid_buffer(input) || !valid_buffer(output) || overlaps(input, output) ||
        input->used_bytes < 24) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    Reader reader{static_cast<const uint8_t*>(input->data), static_cast<size_t>(input->used_bytes)};
    std::array<char, 4> magic{};
    uint8_t version{}, width{}, scheme{}, reserved{};
    uint32_t columns{}, vector_size{};
    uint64_t rows{};
    if (!reader.raw(magic.data(), magic.size()) ||
        std::memcmp(magic.data(), kScheme ? "ARD1" : "ALP1", 4) ||
        !reader.integer(version) || !reader.integer(width) || !reader.integer(scheme) ||
        !reader.integer(reserved) || !reader.integer(columns) || !reader.integer(rows) ||
        !reader.integer(vector_size) || version != 1 || scheme != kScheme || reserved ||
        (width != 4 && width != 8) || columns == 0 || vector_size != kVectorSize ||
        rows > kMaxElements || columns > kMaxElements || rows > kMaxElements / columns)
        return TSCB_STATUS_CODEC_ERROR_V1;
    const uint64_t expected = rows * columns * width;
    if (expected > output->capacity_bytes) return TSCB_STATUS_DST_TOO_SMALL_V1;
    bool ok = false;
    TSCB_TIME_CODEC(handle->native_timer, decode_ns,
        ok = width == 4 ? decode_typed<float>(reader, columns, rows, kScheme == 1,
                                              static_cast<uint8_t*>(output->data), expected)
                        : decode_typed<double>(reader, columns, rows, kScheme == 1,
                                               static_cast<uint8_t*>(output->data), expected));
    if (!ok) {
        set_error(handle, "malformed ALP frame");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = expected;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1* handle, const char*, uint64_t,
                          char*, uint64_t, uint64_t* used) {
    if (used) *used = 0;
    set_error(handle, "ALP adapter does not support random access");
    return TSCB_STATUS_UNSUPPORTED_V1;
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1* handle,
                                        const char** json, uint64_t* length) {
    if (!handle || !json || !length || !handle->finalized)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = handle->accounting_json;
    *length = std::strlen(*json);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* handle,
                                   const char** message, uint64_t* length) {
    if (!handle || !message || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message = handle->last_error;
    *length = std::strlen(*message);
    return TSCB_STATUS_OK_V1;
}

}  // extern "C"
