#include "tscb_native_timing.h"

#include "lzsse8.h"

#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <new>

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer;
    unsigned int compression_level;
    uint64_t input_bytes;
    uint64_t stream_bytes;
    uint64_t finalize_calls;
    bool update_called;
    bool finalized;
    char last_error[256];
    char accounting_json[256];
};

static const char TSCB_MANIFEST_JSON[] =
    "{\"abi_version\":1,\"algorithm\":\"lzsse8-raw\","
    "\"checksum\":\"NONE\",\"framing\":\"NONE\","
    "\"dictionary\":\"NONE\",\"isa\":\"SSE4_1\","
    "\"library\":\"lzsse8-2019-04-18-from-lzbench\","
    "\"stream\":\"LZSSE8_RAW\",\"threading\":\"SINGLE_THREAD\"}";

static void set_error(tscb_codec_handle_v1* handle, const char* message) {
    if (handle != nullptr) {
        std::snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
    }
}

static bool valid_buffer(const tscb_buffer_v1* buffer) {
    return buffer != nullptr && buffer->rank == 1 && buffer->dtype == TSCB_DTYPE_BYTES_V1
        && buffer->used_bytes <= buffer->capacity_bytes
        && (buffer->used_bytes == 0 || buffer->data != nullptr);
}


// Walk lengths and offsets before any vendor SIMD loads. No payload decoding here.
static bool valid_stream(const uint8_t* data, size_t size, size_t decoded) {
    if (size == decoded) return true; // The format's intrinsic raw representation.
    if (size >= decoded || size < 40 || decoded < 32) return false;
    size_t in = 8, out = 8, offset = 8;
    bool carry = false;
    while (out < decoded - 16 && in < size - 16) {
        if (size - 16 - in < 16) return false;
        const uint8_t* control = data + in;
        in += 16;
        for (unsigned k = 0; k < 32; ++k) {
            unsigned c = (control[k / 2] >> (4 * (k % 2))) & 15;
            size_t count = carry ? c : (c < 8 ? c + 1 : c - 4);
            size_t read = carry ? 0 : (c < 8 ? count : 2);
            if (size - in < 16 || decoded - out < 16) return false;
            if (!carry && c >= 8) {
                offset ^= static_cast<size_t>(data[in]) | (static_cast<size_t>(data[in + 1]) << 8);
            }
            if (offset < 8 || offset > out || count > decoded - 16 - out
                || read > size - 16 - in) return false;
            // Short overlapping vector matches do not reproduce scalar LZ semantics.
            if ((carry || c >= 8) && offset < 16 && count > offset) return false;
            out += count;
            in += read;
            carry = c == 15;
            if (out == decoded - 16) return in == size - 16;
        }
    }
    return false;
}

static bool overlaps(const tscb_buffer_v1* a, const tscb_buffer_v1* b) {
    uintptr_t x = reinterpret_cast<uintptr_t>(a->data);
    uintptr_t y = reinterpret_cast<uintptr_t>(b->data);
    return a->used_bytes && b->capacity_bytes
        && (x <= y ? y - x < a->used_bytes : x - y < b->capacity_bytes);
}

extern "C" {

TSCB_NATIVE_TIMING_API

uint32_t tscb_get_abi_version(void) {
    return TSCB_ADAPTER_ABI_V1;
}

tscb_status_v1 tscb_get_manifest_json(const char** json, uint64_t* length) {
    if (json == nullptr || length == nullptr) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *json = TSCB_MANIFEST_JSON;
    *length = sizeof(TSCB_MANIFEST_JSON) - 1U;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(
    const char* config_json,
    uint64_t config_length,
    tscb_codec_handle_v1** handle
) {
    if (config_json == nullptr || handle == nullptr || config_length > 4096U) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *handle = nullptr;
    static const char expected_config[] =
        "{\"compression_level\":12,\"content_checksum\":false}";
    if (config_length != sizeof(expected_config) - 1U
        || std::memcmp(config_json, expected_config, sizeof(expected_config) - 1U) != 0) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (!__builtin_cpu_supports("sse4.1")) return TSCB_STATUS_UNSUPPORTED_V1;
    try {
        *handle = new tscb_codec_handle_v1{};
        (*handle)->compression_level = 12U;
        return TSCB_STATUS_OK_V1;
    } catch (...) {
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* handle) {
    delete handle;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1* handle, uint32_t reset_mode) {
    (void)reset_mode;
    if (handle == nullptr) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    int enabled = handle->native_timer.enabled;
    unsigned int level = handle->compression_level;
    *handle = tscb_codec_handle_v1{};
    handle->compression_level = level;
    (void)tscb_set_native_timing(handle, static_cast<uint32_t>(enabled));
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress_bound(
    tscb_codec_handle_v1* handle,
    const tscb_buffer_v1* input,
    uint64_t* bound_bytes
) {
    if (handle == nullptr || bound_bytes == nullptr || !valid_buffer(input)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes > static_cast<uint64_t>(std::numeric_limits<int32_t>::max())) {
        set_error(handle, "LZSSE8 input exceeds its signed 32-bit position limit");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    // The vendor contract is inputLength. One byte keeps the ABI destination non-null for N=0.
    *bound_bytes = input->used_bytes == 0 ? 1U : input->used_bytes;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(
    tscb_codec_handle_v1* handle,
    const tscb_buffer_v1* input,
    tscb_buffer_v1* output
) {
    uint64_t bound = 0;
    if (handle == nullptr || !valid_buffer(input) || output == nullptr
        || output->used_bytes > output->capacity_bytes || output->data == nullptr) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (handle->update_called || handle->finalized) {
        set_error(handle, "compress update may be called exactly once per LZSSE8 raw stream");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    tscb_status_v1 status = tscb_compress_bound(handle, input, &bound);
    if (status != TSCB_STATUS_OK_V1) {
        return status;
    }
    if (output->capacity_bytes < bound) {
        set_error(handle, "LZSSE8 raw compression requires input-length capacity");
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    }

    if (overlaps(input, output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    size_t written = 0;
    {
        LZSSE8_OptimalParseState* state = LZSSE8_MakeOptimalParseState(
            static_cast<size_t>(input->used_bytes == 0 ? 1 : input->used_bytes));
        if (state == nullptr) {
            set_error(handle, "LZSSE8 optimal parse state allocation failed");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
        TSCB_TIME_CODEC(handle->native_timer, encode_ns,
            written = LZSSE8_CompressOptimalParse(
                state,
                input->data == nullptr ? static_cast<const void*>("") : input->data,
                static_cast<size_t>(input->used_bytes),
                output->data,
                static_cast<size_t>(output->capacity_bytes),
                handle->compression_level));
        LZSSE8_FreeOptimalParseState(state);
        if ((written == 0 && input->used_bytes != 0) || written > input->used_bytes) {
            set_error(handle, "LZSSE8 compression failed or exceeded its raw-stream bound");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    }

    output->used_bytes = written;
    handle->input_bytes = input->used_bytes;
    handle->stream_bytes = written;
    handle->update_called = true;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* handle, tscb_buffer_v1* output) {
    if (handle == nullptr || output == nullptr || output->used_bytes > output->capacity_bytes
        || (output->capacity_bytes != 0 && output->data == nullptr)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (!handle->update_called) {
        set_error(handle, "finalize requires a preceding compress update");
        return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    }
    if (handle->finalized) {
        set_error(handle, "repeated finalize is forbidden");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = 0;
    handle->finalize_calls = 1;
    handle->finalized = true;
    std::snprintf(
        handle->accounting_json,
        sizeof(handle->accounting_json),
        "{\"finalize_calls\":%" PRIu64 ",\"input_bytes\":%" PRIu64
        ",\"lzsse8_raw_stream_bytes\":%" PRIu64 "}",
        handle->finalize_calls,
        handle->input_bytes,
        handle->stream_bytes
    );
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(
    tscb_codec_handle_v1* handle,
    const tscb_buffer_v1* input,
    tscb_buffer_v1* output
) {
    if (handle == nullptr || !valid_buffer(input) || output == nullptr
        || output->used_bytes > output->capacity_bytes
        || (output->capacity_bytes != 0 && output->data == nullptr)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (output->capacity_bytes > static_cast<uint64_t>(std::numeric_limits<int32_t>::max())) {
        set_error(handle, "LZSSE8 decoded length exceeds its signed 32-bit limit");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    if (overlaps(input, output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!valid_stream(static_cast<const uint8_t*>(input->data),
            static_cast<size_t>(input->used_bytes), static_cast<size_t>(output->capacity_bytes))) {
        set_error(handle, "invalid LZSSE8 control, offset, length or tail");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    size_t decoded = 0;
    uint8_t dummy = 0;
    TSCB_TIME_CODEC(handle->native_timer, decode_ns,
        decoded = LZSSE8_Decompress(
            input->data == nullptr ? &dummy : input->data,
            static_cast<size_t>(input->used_bytes),
            output->data == nullptr ? &dummy : output->data,
            static_cast<size_t>(output->capacity_bytes)));
    if (decoded != output->capacity_bytes) {
        set_error(handle, "LZSSE8 decoded length differs from descriptor");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = decoded;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(
    tscb_codec_handle_v1* handle,
    const char* request_json,
    uint64_t request_length,
    char* response_json,
    uint64_t response_capacity,
    uint64_t* response_used
) {
    (void)request_json;
    (void)request_length;
    (void)response_json;
    (void)response_capacity;
    if (response_used != nullptr) {
        *response_used = 0;
    }
    set_error(handle, "LZSSE8 raw adapter does not provide random access queries");
    return TSCB_STATUS_UNSUPPORTED_V1;
}

tscb_status_v1 tscb_get_accounting_json(
    tscb_codec_handle_v1* handle,
    const char** json,
    uint64_t* length
) {
    if (handle == nullptr || json == nullptr || length == nullptr || !handle->finalized) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *json = handle->accounting_json;
    *length = std::strlen(handle->accounting_json);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(
    tscb_codec_handle_v1* handle,
    const char** message,
    uint64_t* length
) {
    if (handle == nullptr || message == nullptr || length == nullptr) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *message = handle->last_error;
    *length = std::strlen(handle->last_error);
    return TSCB_STATUS_OK_V1;
}

}  // extern "C"
