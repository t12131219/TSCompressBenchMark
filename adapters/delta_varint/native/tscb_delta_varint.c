#include "tscb_native_timing.h"

#include "varintDelta.h"

#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct tscb_codec_handle_v1 {
    uint64_t input_count;
    uint64_t encoded_bytes;
    int updated;
    int finalized;
    tscb_native_timer native_timer;
    char last_error[256];
    char accounting_json[256];
};

static const char TSCB_MANIFEST_JSON[] =
    "{\"abi_version\":1,\"algorithm\":\"delta-varint\","
    "\"library\":\"mattsta-varint-delta\","
    "\"format\":\"BASE_ZIGZAG_PLUS_EXTERNAL_WIDTH_DELTAS\","
    "\"endianness\":\"LITTLE\",\"threading\":\"SINGLE_THREAD\"}";

static void set_error(tscb_codec_handle_v1 *handle, const char *message) {
    if (handle != NULL) snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
}

static int valid_input(const tscb_buffer_v1 *buffer) {
    return buffer != NULL && buffer->rank == 1 && buffer->dtype == TSCB_DTYPE_I64_LE_V1
        && buffer->used_bytes <= buffer->capacity_bytes
        && (buffer->used_bytes % sizeof(int64_t)) == 0U
        && buffer->shape[0] == buffer->used_bytes / sizeof(int64_t)
        && buffer->strides_bytes[0] == (int64_t)sizeof(int64_t)
        && (buffer->used_bytes == 0U || buffer->data != NULL);
}

static int valid_bytes(const tscb_buffer_v1 *buffer) {
    return buffer != NULL && buffer->rank == 1 && buffer->dtype == TSCB_DTYPE_BYTES_V1
        && buffer->used_bytes <= buffer->capacity_bytes
        && buffer->shape[0] == buffer->capacity_bytes
        && buffer->strides_bytes[0] == 1
        && (buffer->used_bytes == 0U || buffer->data != NULL);
}

static int valid_encoded(const uint8_t *input, size_t length, size_t count) {
    size_t offset;
    size_t index;
    if (count == 0U) return length == 0U;
    if (input == NULL || length < 2U) return 0;
    offset = 0U;
    for (index = 0U; index < count; ++index) {
        uint8_t width;
        if (offset >= length) return 0;
        width = input[offset++];
        if (width < 1U || width > 8U || width > length - offset) return 0;
        offset += width;
    }
    return offset == length;
}

uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }

tscb_status_v1 tscb_get_manifest_json(const char **json, uint64_t *length) {
    if (json == NULL || length == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = TSCB_MANIFEST_JSON;
    *length = sizeof(TSCB_MANIFEST_JSON) - 1U;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(const char *config_json, uint64_t config_length,
                           tscb_codec_handle_v1 **handle) {
    static const char expected[] = "{\"isa\":\"SCALAR\"}";
    if (handle == NULL || config_json == NULL
        || config_length != sizeof(expected) - 1U
        || memcmp(config_json, expected, sizeof(expected) - 1U) != 0) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *handle = (tscb_codec_handle_v1 *)calloc(1U, sizeof(tscb_codec_handle_v1));
    return *handle == NULL ? TSCB_STATUS_CODEC_ERROR_V1 : TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *handle) {
    free(handle);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *handle, uint32_t reset_mode) {
    int enabled;
    (void)reset_mode;
    if (handle == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    enabled = handle->native_timer.enabled;
    memset(handle, 0, sizeof(*handle));
    handle->native_timer.enabled = enabled;
    handle->native_timer.available = 1;
    return TSCB_STATUS_OK_V1;
}

TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, uint64_t *bound_bytes) {
    uint64_t count;
    if (handle == NULL || bound_bytes == NULL || !valid_input(input)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    count = input->used_bytes / sizeof(int64_t);
    if (count > (UINT64_MAX - 9U) / 9U) {
        set_error(handle, "delta-varint bound overflows uint64");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    *bound_bytes = count == 0U ? 0U : 1U + 8U + (count - 1U) * 9U;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    size_t count;
    size_t bound;
    size_t written;
    if (handle == NULL || !valid_input(input) || !valid_bytes(output)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (handle->updated || handle->finalized) {
        set_error(handle, "delta-varint update may be called once");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    count = (size_t)(input->used_bytes / sizeof(int64_t));
    bound = count == 0U ? 0U : 1U + 8U + (count - 1U) * 9U;
    if (output->capacity_bytes < bound || (bound != 0U && output->data == NULL)) {
        set_error(handle, "delta-varint destination is too small");
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    }
    TSCB_TIME_CODEC(handle->native_timer, encode_ns,
        written = varintDeltaEncode((uint8_t *)output->data,
                                     (const int64_t *)input->data, count));
    output->used_bytes = written;
    handle->input_count = count;
    handle->encoded_bytes = written;
    handle->updated = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    if (handle == NULL || !valid_bytes(output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!handle->updated) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (handle->finalized) return TSCB_STATUS_CODEC_ERROR_V1;
    output->used_bytes = 0U;
    handle->finalized = 1;
    snprintf(handle->accounting_json, sizeof(handle->accounting_json),
             "{\"input_count\":%" PRIu64 ",\"encoded_bytes\":%" PRIu64 "}",
             handle->input_count, handle->encoded_bytes);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    size_t count;
    if (handle == NULL || !valid_bytes(input) || output == NULL
        || output->rank != 1 || output->dtype != TSCB_DTYPE_I64_LE_V1
        || output->used_bytes > output->capacity_bytes
        || output->used_bytes != 0U || output->capacity_bytes % sizeof(int64_t) != 0U
        || output->shape[0] != output->capacity_bytes / sizeof(int64_t)
        || output->strides_bytes[0] != (int64_t)sizeof(int64_t)
        || (output->capacity_bytes != 0U && output->data == NULL)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    count = (size_t)(output->capacity_bytes / sizeof(int64_t));
    if (!valid_encoded((const uint8_t *)input->data, (size_t)input->used_bytes, count)) {
        set_error(handle, "malformed delta-varint stream");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    TSCB_TIME_CODEC(handle->native_timer, decode_ns,
        (void)varintDeltaDecode((const uint8_t *)input->data, count,
                                 (int64_t *)output->data));
    output->used_bytes = output->capacity_bytes;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *handle,
    const char **json, uint64_t *length) {
    if (handle == NULL || json == NULL || length == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = handle->accounting_json;
    *length = (uint64_t)strlen(handle->accounting_json);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1 *handle,
    const char **message, uint64_t *length) {
    if (handle == NULL || message == NULL || length == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message = handle->last_error;
    *length = (uint64_t)strlen(handle->last_error);
    return TSCB_STATUS_OK_V1;
}
