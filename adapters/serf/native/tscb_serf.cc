#include "tscb_native_timing.h"

#include "compressor/serf_qt_compressor.h"
#include "compressor/serf_xor_compressor.h"
#include "compressor_32/serf_qt_compressor_32.h"
#include "compressor_32/serf_xor_compressor_32.h"
#include "decompressor/serf_qt_decompressor.h"
#include "decompressor/serf_xor_decompressor.h"
#include "decompressor_32/serf_qt_decompressor_32.h"
#include "decompressor_32/serf_xor_decompressor_32.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <type_traits>
#include <vector>

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer{};
    uint64_t input_bytes{};
    uint64_t stream_bytes{};
    uint64_t raw_exception_blocks{};
    bool updated{};
    bool finalized{};
    char last_error[256]{};
    char accounting_json[320]{};
};

namespace {

constexpr uint64_t kMaxElements = 16ULL * 1024ULL * 1024ULL;
constexpr uint32_t kMaxBlockSize = 65535;
constexpr uint64_t kFnvOffset = 1469598103934665603ULL;
constexpr uint64_t kFnvPrime = 1099511628211ULL;

#if TSCB_SERF_XOR
constexpr char kAlgorithm[] = "serf-xor";
constexpr char kFrameMagic[] = "SRX1";
constexpr char kConfig[] = "{\"algorithm\":\"serf-xor\"}";
constexpr char kManifest[] =
    "{\"abi_version\":1,\"algorithm\":\"serf-xor\","
    "\"library\":\"Spatio-Temporal-Lab/Serf@b38450b56825\","
    "\"scheme\":\"SERF_XOR_ABSOLUTE_ERROR\",\"block_size_max\":65535,"
    "\"dtypes\":[\"float32\",\"float64\"],\"threading\":\"SINGLE_THREAD\"}";
#else
constexpr char kAlgorithm[] = "serf-qt";
constexpr char kFrameMagic[] = "SRQ1";
constexpr char kConfig[] = "{\"algorithm\":\"serf-qt\"}";
constexpr char kManifest[] =
    "{\"abi_version\":1,\"algorithm\":\"serf-qt\","
    "\"library\":\"Spatio-Temporal-Lab/Serf@b38450b56825\","
    "\"scheme\":\"SERF_QT_ABSOLUTE_ERROR\",\"block_size_max\":65535,"
    "\"dtypes\":[\"float32\",\"float64\"],\"threading\":\"SINGLE_THREAD\"}";
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

uint64_t checksum(const uint8_t* data, size_t size) {
    uint64_t result = kFnvOffset;
    for (size_t i = 0; i < size; ++i) result = (result ^ data[i]) * kFnvPrime;
    return result;
}

struct Writer {
    std::vector<uint8_t> bytes;

    template <typename T> void integer(T value) {
        using U = std::make_unsigned_t<T>;
        U bits{};
        std::memcpy(&bits, &value, sizeof(bits));
        for (size_t i = 0; i < sizeof(bits); ++i)
            bytes.push_back(static_cast<uint8_t>(bits >> (i * 8)));
    }

    void raw(const void* data, size_t size) {
        const auto* first = static_cast<const uint8_t*>(data);
        bytes.insert(bytes.end(), first, first + size);
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
        for (size_t i = 0; i < sizeof(T); ++i)
            bits |= static_cast<U>(data[offset++]) << (i * 8);
        std::memcpy(&value, &bits, sizeof(value));
        return true;
    }

    bool raw(void* target, size_t length) {
        if (length > size - offset) return false;
        if (length) std::memcpy(target, data + offset, length);
        offset += length;
        return true;
    }

    bool skip(size_t length, const uint8_t*& result) {
        if (length > size - offset) return false;
        result = data + offset;
        offset += length;
        return true;
    }
};

struct InputView {
    uint8_t width{};
    uint16_t columns{};
    uint32_t block_size{};
    uint64_t rows{};
    double error_bound{};
    int64_t adjust_digit{};
    const uint8_t* payload{};
};

bool parse_input(const tscb_buffer_v1* input, InputView& view) {
    if (!valid_buffer(input) || input->used_bytes < 36) return false;
    Reader reader{static_cast<const uint8_t*>(input->data), static_cast<size_t>(input->used_bytes)};
    std::array<char, 4> magic{};
    uint8_t reserved{};
    if (!reader.raw(magic.data(), magic.size()) || std::memcmp(magic.data(), "SRI1", 4) ||
        !reader.integer(view.width) || !reader.integer(reserved) ||
        !reader.integer(view.columns) || !reader.integer(view.block_size) ||
        !reader.integer(view.rows) || !reader.raw(&view.error_bound, sizeof(view.error_bound)) ||
        !reader.integer(view.adjust_digit) || reserved ||
        (view.width != 4 && view.width != 8) || view.columns == 0 ||
        view.block_size == 0 || view.block_size > kMaxBlockSize ||
        !std::isfinite(view.error_bound) || view.error_bound <= 0 ||
        view.rows > kMaxElements || view.rows > kMaxElements / view.columns ||
        (view.width == 4 && view.adjust_digit != 0)) return false;
    const uint64_t expected = view.rows * view.columns * view.width;
    if (expected != input->used_bytes - reader.offset) return false;
    view.payload = static_cast<const uint8_t*>(input->data) + reader.offset;
    return true;
}

template <typename T> bool finite_block(const T* values, uint32_t count) {
    for (uint32_t i = 0; i < count; ++i)
        if (!std::isfinite(values[i])) return false;
    return true;
}

template <typename T> bool qt_representable(const T* values, uint32_t count, double requested) {
    const T bound = static_cast<T>(requested) * (std::is_same_v<T, float> ? T{0.99f} : T{0.999});
    if (!std::isfinite(bound) || bound <= 0) return false;
    T previous = T{2};
    for (uint32_t i = 0; i < count; ++i) {
        const long double scaled = (static_cast<long double>(values[i]) - previous) /
                                   (2 * static_cast<long double>(bound));
        if (!std::isfinite(scaled) || scaled < -2147483647.0L || scaled > 2147483647.0L)
            return false;
        const auto q = static_cast<int64_t>(std::round(scaled));
        previous = static_cast<T>(previous + T{2} * bound * static_cast<T>(q));
        if (!std::isfinite(previous)) return false;
    }
    return true;
}

template <typename T> void write_raw_record(Writer& writer, const T* values, uint32_t count) {
    writer.integer<uint8_t>(1);
    writer.integer<uint8_t>(0);
    writer.integer<uint16_t>(0);
    writer.integer<uint32_t>(count);
    writer.integer<uint64_t>(static_cast<uint64_t>(count) * sizeof(T) * 8);
    writer.integer<uint64_t>(static_cast<uint64_t>(count) * sizeof(T));
    writer.raw(values, static_cast<size_t>(count) * sizeof(T));
}

template <typename T> bool encode_typed(const InputView& input, Writer& writer,
                                        uint64_t& raw_exception_blocks) {
    writer.raw(kFrameMagic, 4);
    writer.integer<uint8_t>(1);
    writer.integer<uint8_t>(sizeof(T));
    writer.integer<uint8_t>(TSCB_SERF_XOR ? 1 : 0);
    writer.integer<uint8_t>(0);
    writer.integer<uint32_t>(input.columns);
    writer.integer<uint32_t>(input.block_size);
    writer.integer<uint64_t>(input.rows);
    writer.raw(&input.error_bound, sizeof(input.error_bound));
    writer.integer<int64_t>(input.adjust_digit);
    const uint64_t blocks_per_column =
        input.rows == 0 ? 0 : (input.rows + input.block_size - 1) / input.block_size;
    writer.integer<uint64_t>(blocks_per_column * input.columns);

    for (uint16_t column = 0; column < input.columns; ++column) {
        std::vector<T> aligned_values(static_cast<size_t>(input.rows));
        if (input.rows)
            std::memcpy(aligned_values.data(),
                        input.payload + static_cast<uint64_t>(column) * input.rows * sizeof(T),
                        static_cast<size_t>(input.rows) * sizeof(T));
        const auto* values = aligned_values.data();
#if TSCB_SERF_XOR
        std::unique_ptr<SerfXORCompressor> compressor64;
        std::unique_ptr<SerfXORCompressor32> compressor32;
        bool reset = true;
#endif
        for (uint64_t row = 0; row < input.rows; row += input.block_size) {
            const uint32_t count = static_cast<uint32_t>(
                std::min<uint64_t>(input.block_size, input.rows - row));
            const T* block = values + row;
            bool raw = !finite_block(block, count);
#if TSCB_SERF_XOR
            if constexpr (std::is_same_v<T, double>) {
                for (uint32_t i = 0; i < count && !raw; ++i) {
                    const long double adjusted = static_cast<long double>(block[i]) + input.adjust_digit;
                    if (!std::isfinite(adjusted) ||
                        adjusted > std::numeric_limits<double>::max() ||
                        adjusted < -std::numeric_limits<double>::max()) raw = true;
                }
            }
#else
            raw = raw || !qt_representable(block, count, input.error_bound);
#endif
            if (raw) {
                write_raw_record(writer, block, count);
                ++raw_exception_blocks;
#if TSCB_SERF_XOR
                compressor64.reset();
                compressor32.reset();
                reset = true;
#endif
                continue;
            }
            Array<uint8_t> encoded;
            uint64_t valid_bits{};
#if TSCB_SERF_XOR
            if constexpr (std::is_same_v<T, double>) {
                if (!compressor64)
                    compressor64 = std::make_unique<SerfXORCompressor>(
                        input.block_size, input.error_bound, input.adjust_digit);
                for (uint32_t i = 0; i < count; ++i) compressor64->AddValue(block[i]);
                compressor64->Close();
                valid_bits = compressor64->compressed_size_last_block();
                encoded = compressor64->compressed_bytes_last_block();
            } else {
                if (!compressor32)
                    compressor32 = std::make_unique<SerfXORCompressor32>(
                        input.block_size, static_cast<float>(input.error_bound));
                for (uint32_t i = 0; i < count; ++i) compressor32->AddValue(block[i]);
                compressor32->Close();
                valid_bits = compressor32->compressed_size_last_block();
                encoded = compressor32->compressed_bytes_last_block();
            }
#else
            if constexpr (std::is_same_v<T, double>) {
                SerfQtCompressor compressor(count, input.error_bound);
                for (uint32_t i = 0; i < count; ++i) compressor.AddValue(block[i]);
                compressor.Close();
                valid_bits = compressor.get_compressed_size_in_bits();
                encoded = compressor.compressed_bytes();
            } else {
                SerfQtCompressor32 compressor(count, static_cast<float>(input.error_bound));
                for (uint32_t i = 0; i < count; ++i) compressor.AddValue(block[i]);
                compressor.Close();
                valid_bits = compressor.stored_compressed_size_in_bits();
                encoded = compressor.compressed_bytes();
            }
#endif
            if (valid_bits == 0 || encoded.length() != static_cast<int>((valid_bits + 7) / 8))
                return false;
            writer.integer<uint8_t>(0);
#if TSCB_SERF_XOR
            writer.integer<uint8_t>(reset ? 1 : 0);
            reset = false;
#else
            writer.integer<uint8_t>(1);
#endif
            writer.integer<uint16_t>(0);
            writer.integer<uint32_t>(count);
            writer.integer<uint64_t>(valid_bits);
            writer.integer<uint64_t>(encoded.length());
            writer.raw(encoded.begin(), encoded.length());
        }
    }
    writer.integer<uint64_t>(checksum(writer.bytes.data(), writer.bytes.size()));
    return true;
}

struct FrameInfo {
    uint8_t width{};
    uint32_t columns{};
    uint32_t block_size{};
    uint64_t rows{};
    double error_bound{};
    int64_t adjust_digit{};
    uint64_t record_count{};
};

bool parse_frame_header(Reader& reader, FrameInfo& frame) {
    std::array<char, 4> magic{};
    uint8_t version{}, scheme{}, reserved{};
    return reader.raw(magic.data(), magic.size()) && !std::memcmp(magic.data(), kFrameMagic, 4) &&
           reader.integer(version) && reader.integer(frame.width) && reader.integer(scheme) &&
           reader.integer(reserved) && reader.integer(frame.columns) &&
           reader.integer(frame.block_size) && reader.integer(frame.rows) &&
           reader.raw(&frame.error_bound, sizeof(frame.error_bound)) &&
           reader.integer(frame.adjust_digit) && reader.integer(frame.record_count) &&
           version == 1 && scheme == (TSCB_SERF_XOR ? 1 : 0) && reserved == 0 &&
           (frame.width == 4 || frame.width == 8) && frame.columns > 0 &&
           frame.block_size > 0 && frame.block_size <= kMaxBlockSize &&
           frame.rows <= kMaxElements && frame.rows <= kMaxElements / frame.columns &&
           std::isfinite(frame.error_bound) && frame.error_bound > 0 &&
           (frame.width != 4 || frame.adjust_digit == 0) &&
           frame.record_count == (frame.rows == 0 ? 0 :
               (frame.rows + frame.block_size - 1) / frame.block_size) * frame.columns;
}

template <typename T> bool decode_typed(Reader& reader, const FrameInfo& frame,
                                        uint8_t* output, uint64_t output_size) {
    if (output_size != frame.rows * frame.columns * sizeof(T)) return false;
    for (uint32_t column = 0; column < frame.columns; ++column) {
        uint64_t row = 0;
#if TSCB_SERF_XOR
        std::unique_ptr<SerfXORDecompressor> decompressor64;
        std::unique_ptr<SerfXORDecompressor32> decompressor32;
#endif
        while (row < frame.rows) {
            uint8_t kind{}, reset{};
            uint16_t reserved{};
            uint32_t count{};
            uint64_t valid_bits{}, payload_size{};
            const uint8_t* payload{};
            if (!reader.integer(kind) || !reader.integer(reset) || !reader.integer(reserved) ||
                !reader.integer(count) || !reader.integer(valid_bits) ||
                !reader.integer(payload_size) || reserved || count == 0 ||
                count > frame.block_size || count != std::min<uint64_t>(frame.block_size, frame.rows - row) ||
                payload_size > std::numeric_limits<int>::max() || !reader.skip(payload_size, payload))
                return false;
            uint8_t* destination = output +
                (static_cast<uint64_t>(column) * frame.rows + row) * sizeof(T);
            if (kind == 1) {
                if (reset || valid_bits != static_cast<uint64_t>(count) * sizeof(T) * 8 ||
                    payload_size != static_cast<uint64_t>(count) * sizeof(T)) return false;
                std::memcpy(destination, payload, payload_size);
#if TSCB_SERF_XOR
                decompressor64.reset();
                decompressor32.reset();
#endif
            } else if (kind == 0) {
                if (reset > 1 || valid_bits == 0 || payload_size != (valid_bits + 7) / 8)
                    return false;
                Array<uint8_t> encoded(static_cast<int>(payload_size));
                std::memcpy(encoded.begin(), payload, payload_size);
#if TSCB_SERF_XOR
                if (reset) {
                    decompressor64.reset();
                    decompressor32.reset();
                }
                if constexpr (std::is_same_v<T, double>) {
                    if (!decompressor64)
                        decompressor64 = std::make_unique<SerfXORDecompressor>(frame.adjust_digit);
                    const auto values = decompressor64->Decompress(encoded);
                    if (values.size() != count) return false;
                    std::memcpy(destination, values.data(), static_cast<size_t>(count) * sizeof(T));
                } else {
                    if (!decompressor32)
                        decompressor32 = std::make_unique<SerfXORDecompressor32>();
                    const auto values = decompressor32->Decompress(encoded);
                    if (values.size() != count) return false;
                    std::memcpy(destination, values.data(), static_cast<size_t>(count) * sizeof(T));
                }
#else
                if (reset != 1) return false;
                if constexpr (std::is_same_v<T, double>) {
                    SerfQtDecompressor decompressor;
                    const auto values = decompressor.Decompress(encoded);
                    if (values.size() != count) return false;
                    std::memcpy(destination, values.data(), static_cast<size_t>(count) * sizeof(T));
                } else {
                    SerfQtDecompressor32 decompressor;
                    const auto values = decompressor.Decompress(encoded);
                    if (values.size() != count) return false;
                    std::memcpy(destination, values.data(), static_cast<size_t>(count) * sizeof(T));
                }
#endif
            } else {
                return false;
            }
            row += count;
        }
    }
    return true;
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
    const uint64_t records = view.rows == 0 ? 0 :
        ((view.rows + view.block_size - 1) / view.block_size) * view.columns;
    const uint64_t raw = view.rows * view.columns * view.width;
    if (records > (std::numeric_limits<uint64_t>::max() - 128) / 24 ||
        raw > (std::numeric_limits<uint64_t>::max() - 128 - records * 24) / 4)
        return TSCB_STATUS_UNSUPPORTED_V1;
    *bound = 128 + records * 24 + raw * 4;
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
    uint64_t raw_exception_blocks = 0;
    try {
        TSCB_TIME_CODEC(handle->native_timer, encode_ns,
            ok = view.width == 4 ? encode_typed<float>(view, writer, raw_exception_blocks)
                                 : encode_typed<double>(view, writer, raw_exception_blocks));
    } catch (const std::bad_alloc&) {
        set_error(handle, "Serf allocation failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    } catch (...) {
        set_error(handle, "Serf encoder raised an unexpected exception");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (!ok) {
        set_error(handle, "Serf encoder produced an invalid block");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (writer.bytes.size() > output->capacity_bytes) return TSCB_STATUS_DST_TOO_SMALL_V1;
    if (!writer.bytes.empty()) std::memcpy(output->data, writer.bytes.data(), writer.bytes.size());
    output->used_bytes = writer.bytes.size();
    handle->input_bytes = input->used_bytes - 36;
    handle->stream_bytes = writer.bytes.size();
    handle->raw_exception_blocks = raw_exception_blocks;
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
                  "{\"input_bytes\":%" PRIu64 ",\"serf_frame_bytes\":%" PRIu64
                  ",\"native_input_descriptor_bytes\":36,\"raw_exception_blocks\":%" PRIu64
                  ",\"finalize_calls\":1}", handle->input_bytes, handle->stream_bytes,
                  handle->raw_exception_blocks);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* handle, const tscb_buffer_v1* input,
                               tscb_buffer_v1* output) {
    if (!handle || !valid_buffer(input) || !valid_buffer(output) || overlaps(input, output) ||
        input->used_bytes < 56) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    const auto* bytes = static_cast<const uint8_t*>(input->data);
    Reader checksum_reader{bytes + input->used_bytes - 8, 8};
    uint64_t stored_checksum{};
    if (!checksum_reader.integer(stored_checksum) ||
        checksum(bytes, static_cast<size_t>(input->used_bytes - 8)) != stored_checksum) {
        set_error(handle, "Serf frame checksum mismatch");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    Reader reader{bytes, static_cast<size_t>(input->used_bytes - 8)};
    FrameInfo frame;
    if (!parse_frame_header(reader, frame)) {
        set_error(handle, "malformed Serf frame header");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    const uint64_t expected = frame.rows * frame.columns * frame.width;
    if (expected > output->capacity_bytes) return TSCB_STATUS_DST_TOO_SMALL_V1;
    bool ok = false;
    try {
        TSCB_TIME_CODEC(handle->native_timer, decode_ns,
            ok = frame.width == 4 ? decode_typed<float>(reader, frame,
                    static_cast<uint8_t*>(output->data), expected)
                : decode_typed<double>(reader, frame,
                    static_cast<uint8_t*>(output->data), expected));
    } catch (...) {
        set_error(handle, "Serf decoder rejected the frame");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (!ok || reader.offset != reader.size) {
        set_error(handle, "malformed Serf block records");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = expected;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1* handle, const char*, uint64_t,
                          char*, uint64_t, uint64_t* used) {
    if (used) *used = 0;
    set_error(handle, "Serf adapter does not support random access");
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
