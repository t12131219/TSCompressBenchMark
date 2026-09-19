#include "tscb_native_timing.h"

#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <new>

extern "C" {
int tscb_sprintz8_bound(size_t elements, size_t* bytes);
int tscb_sprintz8_compress(unsigned variant, const uint8_t* src, size_t elements,
                           uint8_t* dest, size_t capacity, size_t* used);
int tscb_sprintz8_decompress(unsigned variant, const uint8_t* src, size_t size,
                             uint8_t* dest, size_t capacity, size_t expected, size_t* used);
}

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer;
    unsigned variant;
    uint64_t input_bytes;
    uint64_t stream_bytes;
    bool updated;
    bool finalized;
    char last_error[192];
    char accounting_json[192];
};

#if TSCB_SPRINTZ_FIRE
static constexpr unsigned kVariant = 1;
static constexpr char kConfig[] = "{\"algorithm\":\"sprintz-fire-u8\"}";
static constexpr char kManifest[] =
    "{\"abi_version\":1,\"algorithm\":\"sprintz-fire-u8\","
    "\"isa\":\"AVX2_BMI2_LZCNT\",\"threading\":\"SINGLE_THREAD\","
    "\"format\":\"SPRINTZ_XFF_RLE_8B_NDIMS1\"}";
#else
static constexpr unsigned kVariant = 0;
static constexpr char kConfig[] = "{\"algorithm\":\"sprintz-delta-u8\"}";
static constexpr char kManifest[] =
    "{\"abi_version\":1,\"algorithm\":\"sprintz-delta-u8\","
    "\"isa\":\"AVX2_BMI2_LZCNT\",\"threading\":\"SINGLE_THREAD\","
    "\"format\":\"SPRINTZ_DELTA_RLE_8B_NDIMS1\"}";
#endif

static void error(tscb_codec_handle_v1* handle, const char* message) {
    if (handle) std::snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
}

static bool valid_buffer(const tscb_buffer_v1* buffer) {
    return buffer && buffer->dtype == TSCB_DTYPE_BYTES_V1 && buffer->rank == 1 &&
        buffer->used_bytes <= buffer->capacity_bytes &&
        (buffer->capacity_bytes == 0 || buffer->data);
}

static bool overlaps(const tscb_buffer_v1* input, const tscb_buffer_v1* output) {
    uintptr_t a = reinterpret_cast<uintptr_t>(input->data);
    uintptr_t b = reinterpret_cast<uintptr_t>(output->data);
    return input->used_bytes && output->capacity_bytes &&
        (a <= b ? b - a < input->used_bytes : a - b < output->capacity_bytes);
}

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
    *handle = nullptr;
#if defined(__x86_64__)
    __builtin_cpu_init();
    if (!__builtin_cpu_supports("avx2") || !__builtin_cpu_supports("bmi2") ||
        !__builtin_cpu_supports("lzcnt")) return TSCB_STATUS_UNSUPPORTED_V1;
#else
    return TSCB_STATUS_UNSUPPORTED_V1;
#endif
    try {
        *handle = new tscb_codec_handle_v1{};
        (*handle)->variant = kVariant;
        return TSCB_STATUS_OK_V1;
    } catch (const std::bad_alloc&) { return TSCB_STATUS_CODEC_ERROR_V1; }
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* handle) {
    delete handle;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1* handle, uint32_t reset_mode) {
    if (!handle || reset_mode != 0) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    const int enabled = handle->native_timer.enabled;
    *handle = tscb_codec_handle_v1{};
    handle->variant = kVariant;
    return tscb_set_native_timing(handle, enabled ? 1u : 0u);
}

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* handle,
                                  const tscb_buffer_v1* input, uint64_t* bound_bytes) {
    if (!handle || !valid_buffer(input) || !bound_bytes)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    size_t bound = 0;
    if (tscb_sprintz8_bound(input->used_bytes, &bound)) {
        error(handle, "Sprintz 8-bit input exceeds the registered element limit");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    *bound_bytes = bound;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1* handle, const tscb_buffer_v1* input,
                             tscb_buffer_v1* output) {
    if (!handle || !valid_buffer(input) || !valid_buffer(output))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (handle->updated || handle->finalized || overlaps(input, output))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    uint64_t bound = 0;
    auto status = tscb_compress_bound(handle, input, &bound);
    if (status != TSCB_STATUS_OK_V1) return status;
    if (output->capacity_bytes < bound) return TSCB_STATUS_DST_TOO_SMALL_V1;
    size_t used = 0;
    int result = 0;
    TSCB_TIME_CODEC(handle->native_timer, encode_ns,
        result = tscb_sprintz8_compress(handle->variant,
            static_cast<const uint8_t*>(input->data), input->used_bytes,
            static_cast<uint8_t*>(output->data), output->capacity_bytes, &used));
    if (result) {
        error(handle, "bounded Sprintz encoder failed or generated invalid stream");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = used;
    handle->input_bytes = input->used_bytes;
    handle->stream_bytes = used;
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
                  "{\"input_bytes\":%" PRIu64 ",\"sprintz_stream_bytes\":%" PRIu64 ","
                  "\"native_header_bytes\":8,\"finalize_calls\":1}",
                  handle->input_bytes, handle->stream_bytes);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* handle, const tscb_buffer_v1* input,
                               tscb_buffer_v1* output) {
    if (!handle || !valid_buffer(input) || !valid_buffer(output) ||
        overlaps(input, output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    size_t used = 0;
    int result = 0;
    TSCB_TIME_CODEC(handle->native_timer, decode_ns,
        result = tscb_sprintz8_decompress(handle->variant,
            static_cast<const uint8_t*>(input->data), input->used_bytes,
            static_cast<uint8_t*>(output->data), output->capacity_bytes,
            output->capacity_bytes, &used));
    if (result) {
        error(handle, "invalid Sprintz stream or decoded length");
        return result == 2 ? TSCB_STATUS_DST_TOO_SMALL_V1 : TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = used;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1* handle, const char*, uint64_t,
                          char*, uint64_t, uint64_t* used) {
    if (used) *used = 0;
    error(handle, "Sprintz 8-bit does not support random access");
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
}
