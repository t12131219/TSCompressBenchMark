#include "tscb_native_timing.h"
#include "lzss_raw_codec.h"
#include <cstddef>

#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <new>

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer;
    uint64_t input_bytes;
    uint64_t stream_bytes;
    uint64_t finalize_calls;
    bool update_called;
    bool finalized;
    char last_error[256];
    char accounting_json[256];
};

static const char TSCB_MANIFEST_JSON[] =
    "{\"abi_version\":1,\"algorithm\":\"lzss-raw\","
    "\"checksum\":\"NONE\",\"framing\":\"NONE\","
    "\"dictionary\":\"NONE\","
    "\"library\":\"tscb-alexkazik-lzss-0.9.1-cpp\","
    "\"stream\":\"LZSS_EI10_EJ4_C32\",\"threading\":\"SINGLE_THREAD\"}";

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

static bool valid_output(const tscb_buffer_v1* buffer) {
    return valid_buffer(buffer) && buffer->capacity_bytes <= PTRDIFF_MAX
        && (buffer->capacity_bytes == 0 || buffer->data != nullptr);
}

static bool disjoint(const tscb_buffer_v1* input, const tscb_buffer_v1* output) {
    uintptr_t a = reinterpret_cast<uintptr_t>(input->data);
    uintptr_t b = reinterpret_cast<uintptr_t>(output->data);
    if (input->used_bytes > UINTPTR_MAX - a || output->capacity_bytes > UINTPTR_MAX - b)
        return false;
    return input->used_bytes == 0 || output->capacity_bytes == 0
        || a + input->used_bytes <= b || b + output->capacity_bytes <= a;
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
        "{\"ei\":10,\"ej\":4,\"initial_byte\":32}";
    if (config_length != sizeof(expected_config) - 1U
        || std::memcmp(config_json, expected_config, sizeof(expected_config) - 1U) != 0) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    try {
        *handle = new tscb_codec_handle_v1{};
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
    *handle = tscb_codec_handle_v1{};
    (void)tscb_set_native_timing(handle, (uint32_t)enabled);
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
    if (input->used_bytes > std::numeric_limits<uint32_t>::max()) {
        set_error(handle, "LZSS input exceeds registered uint32 work limit");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    try {
        *bound_bytes = input->used_bytes + (input->used_bytes + 7U) / 8U;
        return TSCB_STATUS_OK_V1;
    } catch (...) {
        set_error(handle, "LZSS bound raised an exception");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
}

tscb_status_v1 tscb_compress(
    tscb_codec_handle_v1* handle,
    const tscb_buffer_v1* input,
    tscb_buffer_v1* output
) {
    uint64_t bound = 0;
    if (handle == nullptr || !valid_buffer(input) || !valid_output(output)
        || output->data == nullptr || !disjoint(input, output)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (handle->update_called || handle->finalized) {
        set_error(handle, "compress update may be called exactly once per LZSS raw stream");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    tscb_status_v1 status = tscb_compress_bound(handle, input, &bound);
    if (status != TSCB_STATUS_OK_V1) {
        return status;
    }
    if (output->capacity_bytes < bound) {
        set_error(handle, "LZSS compression requires literal worst-case capacity");
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    }
    static const uint8_t empty = 0;
    const uint8_t* source = input->data == nullptr
        ? &empty
        : static_cast<const uint8_t*>(input->data);
    size_t written = 0;
    // Validation and capacity rejection precede the first output write. The
    // actual codec uses only fixed stack buffers and has a noexcept API.
    TSCB_TIME_CODEC(handle->native_timer, encode_ns,
        written = tscb_lzss_raw::encode(source, static_cast<size_t>(input->used_bytes),
                                      static_cast<uint8_t*>(output->data)));
    if (written > output->capacity_bytes) {
        set_error(handle, "LZSS RawCompress exceeded the declared output capacity");
        return TSCB_STATUS_CODEC_ERROR_V1;
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
        ",\"lzss_raw_stream_bytes\":%" PRIu64 "}",
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
    if (handle == nullptr || !valid_buffer(input) || !valid_output(output)
        || !disjoint(input, output)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes > UINT32_MAX || output->capacity_bytes > UINT32_MAX
        || !tscb_lzss_raw::strict_stream(static_cast<const uint8_t*>(input->data),
                                        static_cast<size_t>(input->used_bytes),
                                        static_cast<size_t>(output->capacity_bytes))) {
        set_error(handle, "invalid LZSS token coverage, decoded length or padding");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    static uint8_t empty = 0;
    size_t expected = static_cast<size_t>(output->capacity_bytes);
    TSCB_TIME_CODEC(handle->native_timer, decode_ns,
        tscb_lzss_raw::decode(
            input->data == nullptr ? &empty : static_cast<const uint8_t*>(input->data),
            static_cast<size_t>(input->used_bytes),
            output->data == nullptr ? &empty : static_cast<uint8_t*>(output->data),
            expected));

    output->used_bytes = expected;
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
    set_error(handle, "LZSS raw adapter does not provide random access queries");
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
