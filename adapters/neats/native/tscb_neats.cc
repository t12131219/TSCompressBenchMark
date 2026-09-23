#include "tscb_native_timing.h"

#include "NeaTS.hpp"
#include "LeaTS.hpp"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <new>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer{};
    uint8_t max_bpc{16};
    uint64_t input_bytes{};
    uint64_t stream_bytes{};
    bool updated{};
    bool finalized{};
    char last_error[256]{};
    char accounting_json[320]{};
};

namespace {

constexpr uint64_t kMaxElements = 262144;
constexpr uint32_t kMaxRows = 65536;
constexpr uint16_t kMaxColumns = 64;
constexpr size_t kInputHeader = 12;
constexpr size_t kFrameHeader = 16;
constexpr size_t kRecordHeader = 24;

#if TSCB_NEATS
using Codec = pfa::neats::compressor<uint32_t, int64_t, double, float, double>;
constexpr char kAlgorithm[] = "neats-lossless-i64";
constexpr char kMagic[] = "NTS1";
constexpr char kConfig16[] = "{\"algorithm\":\"neats-lossless-i64\",\"max_bpc\":16}";
constexpr char kConfig32[] = "{\"algorithm\":\"neats-lossless-i64\",\"max_bpc\":32}";
constexpr char kManifest[] =
    "{\"abi_version\":1,\"algorithm\":\"neats-lossless-i64\","
    "\"library\":\"and-gue/NeaTS@2d804ff492e4\",\"mode\":\"LOSSLESS\","
    "\"model\":\"PIECEWISE_NONLINEAR\",\"isa\":\"SCALAR\","
    "\"threading\":\"SINGLE_THREAD\",\"serialization\":\"UPSTREAM_SDSL\"}";
#else
using Codec = pfa::leats::compressor<uint32_t, int64_t, double, float, double>;
constexpr char kAlgorithm[] = "leats-lossless-i64";
constexpr char kMagic[] = "LTS1";
constexpr char kConfig16[] = "{\"algorithm\":\"leats-lossless-i64\",\"max_bpc\":16}";
constexpr char kConfig32[] = "{\"algorithm\":\"leats-lossless-i64\",\"max_bpc\":32}";
constexpr char kManifest[] =
    "{\"abi_version\":1,\"algorithm\":\"leats-lossless-i64\","
    "\"library\":\"and-gue/NeaTS@2d804ff492e4\",\"mode\":\"LOSSLESS\","
    "\"model\":\"PIECEWISE_LINEAR\",\"isa\":\"SCALAR\","
    "\"threading\":\"SINGLE_THREAD\",\"serialization\":\"REVIEWED_SDSL_PATCH\"}";
#endif

void set_error(tscb_codec_handle_v1* handle, const char* text) {
    if (handle) std::snprintf(handle->last_error, sizeof(handle->last_error), "%s", text);
}

bool valid_bytes(const tscb_buffer_v1* buffer) {
    return buffer && buffer->dtype == TSCB_DTYPE_BYTES_V1 && buffer->rank == 1 &&
           buffer->used_bytes <= buffer->capacity_bytes &&
           (buffer->used_bytes == 0 || buffer->data);
}

bool overlaps(const tscb_buffer_v1* input, const tscb_buffer_v1* output) {
    auto a = reinterpret_cast<uintptr_t>(input->data);
    auto b = reinterpret_cast<uintptr_t>(output->data);
    return input->used_bytes && output->capacity_bytes &&
           (a <= b ? b - a < input->used_bytes : a - b < output->capacity_bytes);
}

uint16_t read_u16(const uint8_t* p) {
    return static_cast<uint16_t>(p[0]) | static_cast<uint16_t>(p[1]) << 8;
}

uint32_t read_u32(const uint8_t* p) {
    uint32_t value{};
    for (unsigned i = 0; i < 4; ++i) value |= static_cast<uint32_t>(p[i]) << (8 * i);
    return value;
}

uint64_t read_u64(const uint8_t* p) {
    uint64_t value{};
    for (unsigned i = 0; i < 8; ++i) value |= static_cast<uint64_t>(p[i]) << (8 * i);
    return value;
}

void append_u16(std::vector<uint8_t>& out, uint16_t value) {
    out.push_back(static_cast<uint8_t>(value));
    out.push_back(static_cast<uint8_t>(value >> 8));
}

void append_u32(std::vector<uint8_t>& out, uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) out.push_back(static_cast<uint8_t>(value >> (8 * i)));
}

void append_u64(std::vector<uint8_t>& out, uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) out.push_back(static_cast<uint8_t>(value >> (8 * i)));
}

uint64_t checksum(const uint8_t* data, size_t size) {
    uint64_t hash = UINT64_C(1469598103934665603);
    for (size_t i = 0; i < size; ++i) {
        hash ^= data[i];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

struct InputView {
    uint8_t width{};
    uint16_t columns{};
    uint32_t rows{};
    const uint8_t* values{};
};

bool parse_input(const tscb_buffer_v1* input, InputView& view) {
    if (!valid_bytes(input) || input->used_bytes < kInputHeader) return false;
    auto* data = static_cast<const uint8_t*>(input->data);
    if (std::memcmp(data, "NTI1", 4) != 0 || data[5] != 0) return false;
    view.width = data[4];
    view.columns = read_u16(data + 6);
    view.rows = read_u32(data + 8);
    uint64_t count = static_cast<uint64_t>(view.rows) * view.columns;
    if ((view.width != 1 && view.width != 2 && view.width != 4 && view.width != 8) ||
        view.rows < 1 || view.rows > kMaxRows || view.columns < 1 ||
        view.columns > kMaxColumns || count > kMaxElements ||
        count > (UINT64_MAX - kInputHeader) / view.width ||
        input->used_bytes != kInputHeader + count * view.width) return false;
    view.values = data + kInputHeader;
    return true;
}

int64_t read_signed(const uint8_t* p, uint8_t width) {
    uint64_t raw{};
    for (uint8_t i = 0; i < width; ++i) raw |= static_cast<uint64_t>(p[i]) << (8 * i);
    if (width < 8 && (raw & (UINT64_C(1) << (width * 8 - 1))))
        raw |= UINT64_MAX << (width * 8);
    return static_cast<int64_t>(raw);
}

bool write_signed(uint8_t* p, uint8_t width, int64_t value) {
    int64_t minimum = width == 8 ? std::numeric_limits<int64_t>::min()
                                 : -(INT64_C(1) << (width * 8 - 1));
    int64_t maximum = width == 8 ? std::numeric_limits<int64_t>::max()
                                 : (INT64_C(1) << (width * 8 - 1)) - 1;
    if (value < minimum || value > maximum) return false;
    uint64_t raw = static_cast<uint64_t>(value);
    for (uint8_t i = 0; i < width; ++i) p[i] = static_cast<uint8_t>(raw >> (8 * i));
    return true;
}

void add_time(tscb_native_timer& timer, uint64_t start, bool encode) {
    uint64_t end = tscb_native_now(&timer);
    if (!timer.enabled || !timer.available) return;
    if (end < start) { timer.available = 0; return; }
    auto& total = encode ? timer.encode_ns : timer.decode_ns;
    if (UINT64_MAX - total < end - start) { timer.available = 0; return; }
    total += end - start;
}

std::string serialize_codec(Codec& codec) {
    std::ostringstream stream(std::ios::out | std::ios::binary);
    codec.serialize(stream);
    if (!stream) throw std::runtime_error("codec serialization failed");
    return stream.str();
}

Codec load_codec(const uint8_t* data, size_t size) {
    std::string payload(reinterpret_cast<const char*>(data), size);
    std::istringstream stream(payload, std::ios::in | std::ios::binary);
    auto codec = Codec::load(stream);
    if (!stream || stream.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("invalid serialized codec object");
    return codec;
}

std::vector<uint8_t> encode_frame(const InputView& input, uint8_t max_bpc) {
    std::vector<uint8_t> frame;
    frame.reserve(kFrameHeader + 8 + static_cast<size_t>(input.rows) * input.columns * 16);
    frame.insert(frame.end(), kMagic, kMagic + 4);
    frame.push_back(1);
    frame.push_back(input.width);
    frame.push_back(max_bpc);
    frame.push_back(0);
    append_u16(frame, input.columns);
    append_u16(frame, 0);
    append_u32(frame, input.rows);
    for (uint16_t column = 0; column < input.columns; ++column) {
        const uint8_t* source = input.values + static_cast<uint64_t>(column) * input.rows * input.width;
        std::vector<int64_t> normalized(input.rows);
        int64_t bias = read_signed(source, input.width);
        for (uint32_t row = 1; row < input.rows; ++row)
            bias = std::min(bias, read_signed(source + static_cast<uint64_t>(row) * input.width, input.width));
        for (uint32_t row = 0; row < input.rows; ++row) {
            int64_t value = read_signed(source + static_cast<uint64_t>(row) * input.width, input.width);
            uint64_t delta = static_cast<uint64_t>(value) - static_cast<uint64_t>(bias);
            if (delta > static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))
                throw std::runtime_error("column span exceeds signed 64-bit normalization");
            normalized[row] = static_cast<int64_t>(delta);
        }
        Codec codec{max_bpc};
        codec.partitioning(normalized.begin(), normalized.end());
        std::string payload = serialize_codec(codec);
        append_u64(frame, static_cast<uint64_t>(bias));
        append_u64(frame, payload.size());
        append_u64(frame, codec.size_in_bits());
        frame.insert(frame.end(), payload.begin(), payload.end());
    }
    append_u64(frame, checksum(frame.data(), frame.size()));
    return frame;
}

struct RecordView {
    int64_t bias{};
    const uint8_t* payload{};
    size_t payload_size{};
};

struct FrameView {
    uint8_t width{};
    uint8_t max_bpc{};
    uint16_t columns{};
    uint32_t rows{};
    std::vector<RecordView> records;
};

bool parse_frame(const uint8_t* data, size_t size, FrameView& frame) {
    if (!data || size < kFrameHeader + 8 || std::memcmp(data, kMagic, 4) != 0 ||
        data[4] != 1 || data[7] != 0 || read_u16(data + 10) != 0) return false;
    frame.width = data[5];
    frame.max_bpc = data[6];
    frame.columns = read_u16(data + 8);
    frame.rows = read_u32(data + 12);
    uint64_t count = static_cast<uint64_t>(frame.rows) * frame.columns;
    if ((frame.width != 1 && frame.width != 2 && frame.width != 4 && frame.width != 8) ||
        (frame.max_bpc != 16 && frame.max_bpc != 32) || frame.rows < 1 ||
        frame.rows > kMaxRows || frame.columns < 1 || frame.columns > kMaxColumns ||
        count > kMaxElements || read_u64(data + size - 8) != checksum(data, size - 8)) return false;
    size_t offset = kFrameHeader;
    frame.records.clear();
    frame.records.reserve(frame.columns);
    for (uint16_t column = 0; column < frame.columns; ++column) {
        if (offset > size - 8 || size - 8 - offset < kRecordHeader) return false;
        int64_t bias = static_cast<int64_t>(read_u64(data + offset));
        uint64_t payload_size = read_u64(data + offset + 8);
        uint64_t logical_storage_bits = read_u64(data + offset + 16);
        (void)logical_storage_bits;
        offset += kRecordHeader;
        if (payload_size > size - 8 - offset) return false;
        frame.records.push_back({bias, data + offset, static_cast<size_t>(payload_size)});
        offset += static_cast<size_t>(payload_size);
    }
    return offset == size - 8;
}

bool decode_frame(const FrameView& frame, uint8_t* output, size_t output_size) {
    uint64_t expected = static_cast<uint64_t>(frame.rows) * frame.columns * frame.width;
    if (output_size != expected) return false;
    for (uint16_t column = 0; column < frame.columns; ++column) {
        Codec codec = load_codec(frame.records[column].payload, frame.records[column].payload_size);
        if (codec.size() != frame.rows) return false;
        std::vector<int64_t> normalized(frame.rows);
        codec.decompress(normalized.begin(), normalized.end());
        uint8_t* target = output + static_cast<uint64_t>(column) * frame.rows * frame.width;
        for (uint32_t row = 0; row < frame.rows; ++row) {
            __int128 value = static_cast<__int128>(normalized[row]) + frame.records[column].bias;
            if (value < std::numeric_limits<int64_t>::min() || value > std::numeric_limits<int64_t>::max() ||
                !write_signed(target + static_cast<uint64_t>(row) * frame.width, frame.width,
                              static_cast<int64_t>(value))) return false;
        }
    }
    return true;
}

}  // namespace

extern "C" {

uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }

tscb_status_v1 tscb_get_manifest_json(const char** json, uint64_t* length) {
    if (!json || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = kManifest;
    *length = sizeof(kManifest) - 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(const char* config, uint64_t length, tscb_codec_handle_v1** result) {
    if (!config || !result) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    uint8_t max_bpc{};
    if (length == sizeof(kConfig16) - 1 && std::memcmp(config, kConfig16, length) == 0) max_bpc = 16;
    if (length == sizeof(kConfig32) - 1 && std::memcmp(config, kConfig32, length) == 0) max_bpc = 32;
    if (!max_bpc) return TSCB_STATUS_UNSUPPORTED_V1;
    auto* handle = new (std::nothrow) tscb_codec_handle_v1;
    if (!handle) return TSCB_STATUS_CODEC_ERROR_V1;
    handle->max_bpc = max_bpc;
    *result = handle;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* handle) {
    if (!handle) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    delete handle;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1* handle, uint32_t mode) {
    if (!handle || mode != 0) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    handle->input_bytes = handle->stream_bytes = 0;
    handle->updated = handle->finalized = false;
    handle->last_error[0] = handle->accounting_json[0] = 0;
    handle->native_timer.encode_ns = handle->native_timer.decode_ns = 0;
    return TSCB_STATUS_OK_V1;
}

TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* handle,
                                    const tscb_buffer_v1* input, uint64_t* bound) {
    InputView view;
    if (!handle || !bound || !parse_input(input, view)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    uint64_t count = static_cast<uint64_t>(view.rows) * view.columns;
    if (count > (UINT64_MAX - kFrameHeader - 8 - static_cast<uint64_t>(view.columns) * (kRecordHeader + 4096)) / 128)
        return TSCB_STATUS_CODEC_ERROR_V1;
    *bound = kFrameHeader + 8 + static_cast<uint64_t>(view.columns) * (kRecordHeader + 4096) + count * 128;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1* handle, const tscb_buffer_v1* input,
                             tscb_buffer_v1* output) {
    InputView view;
    if (!handle || !valid_bytes(output) || !parse_input(input, view) || handle->updated ||
        overlaps(input, output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    try {
        uint64_t started = tscb_native_now(&handle->native_timer);
        std::vector<uint8_t> frame = encode_frame(view, handle->max_bpc);
        add_time(handle->native_timer, started, true);
        if (frame.size() > output->capacity_bytes) return TSCB_STATUS_DST_TOO_SMALL_V1;
        if (!frame.empty()) std::memcpy(output->data, frame.data(), frame.size());
        output->used_bytes = frame.size();
        handle->input_bytes = input->used_bytes;
        handle->stream_bytes = frame.size();
        handle->updated = true;
        return TSCB_STATUS_OK_V1;
    } catch (const std::exception& error) {
        set_error(handle, error.what());
        return TSCB_STATUS_CODEC_ERROR_V1;
    } catch (...) {
        set_error(handle, "unknown codec exception");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* handle, tscb_buffer_v1* output) {
    if (!handle || !output || output->capacity_bytes != 0 || !handle->updated || handle->finalized)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    output->used_bytes = 0;
    handle->finalized = true;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* handle, const tscb_buffer_v1* input,
                               tscb_buffer_v1* output) {
    if (!handle || !valid_bytes(input) || !valid_bytes(output) || overlaps(input, output))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    FrameView frame;
    if (!parse_frame(static_cast<const uint8_t*>(input->data), input->used_bytes, frame))
        return TSCB_STATUS_CODEC_ERROR_V1;
    uint64_t expected = static_cast<uint64_t>(frame.rows) * frame.columns * frame.width;
    if (expected > output->capacity_bytes) return TSCB_STATUS_DST_TOO_SMALL_V1;
    try {
        uint64_t started = tscb_native_now(&handle->native_timer);
        bool ok = decode_frame(frame, static_cast<uint8_t*>(output->data), expected);
        add_time(handle->native_timer, started, false);
        if (!ok) return TSCB_STATUS_CODEC_ERROR_V1;
        output->used_bytes = expected;
        return TSCB_STATUS_OK_V1;
    } catch (const std::exception& error) {
        set_error(handle, error.what());
        return TSCB_STATUS_CODEC_ERROR_V1;
    } catch (...) {
        set_error(handle, "unknown codec exception");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1*, const char*, uint64_t, char*, uint64_t,
                          uint64_t*) { return TSCB_STATUS_UNSUPPORTED_V1; }

tscb_status_v1 tscb_neats_query_i64(const uint8_t* data, uint64_t size, uint16_t column,
                                    uint32_t start, uint32_t length, int64_t* output,
                                    uint64_t output_count, uint64_t* bytes_touched) {
    FrameView frame;
    if (!parse_frame(data, size, frame) || column >= frame.columns || start > frame.rows ||
        length > frame.rows - start || output_count < length || (length && !output) || !bytes_touched)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    try {
        Codec codec = load_codec(frame.records[column].payload, frame.records[column].payload_size);
        if (codec.size() != frame.rows) return TSCB_STATUS_CODEC_ERROR_V1;
        for (uint32_t i = 0; i < length; ++i) {
            __int128 value = static_cast<__int128>(codec[start + i]) + frame.records[column].bias;
            if (value < std::numeric_limits<int64_t>::min() || value > std::numeric_limits<int64_t>::max())
                return TSCB_STATUS_CODEC_ERROR_V1;
            output[i] = static_cast<int64_t>(value);
        }
        *bytes_touched = size;
        return TSCB_STATUS_OK_V1;
    } catch (...) {
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1* handle,
                                         const char** json, uint64_t* length) {
    if (!handle || !json || !length || !handle->updated) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    int written = std::snprintf(handle->accounting_json, sizeof(handle->accounting_json),
        "{\"schema_version\":\"tscb.neats-native-accounting.v1\",\"algorithm\":\"%s\","
        "\"input_bytes\":%llu,\"stream_bytes\":%llu,\"model_index_bytes\":%llu}",
        kAlgorithm, static_cast<unsigned long long>(handle->input_bytes),
        static_cast<unsigned long long>(handle->stream_bytes),
        static_cast<unsigned long long>(handle->stream_bytes));
    if (written < 0 || static_cast<size_t>(written) >= sizeof(handle->accounting_json))
        return TSCB_STATUS_CODEC_ERROR_V1;
    *json = handle->accounting_json;
    *length = static_cast<uint64_t>(written);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* handle,
                                    const char** message, uint64_t* length) {
    if (!handle || !message || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message = handle->last_error;
    *length = std::strlen(handle->last_error);
    return TSCB_STATUS_OK_V1;
}

}  // extern "C"
