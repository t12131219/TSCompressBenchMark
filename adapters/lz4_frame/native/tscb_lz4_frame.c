#include "tscb_adapter_v1.h"

#include "lz4frame.h"

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct tscb_codec_handle_v1 {
    LZ4F_cctx *compression_context;
    LZ4F_preferences_t preferences;
    uint64_t input_bytes;
    uint64_t stream_bytes;
    int update_called;
    int finalized;
    char last_error[256];
    char accounting_json[256];
};

static const char TSCB_MANIFEST_JSON[] =
    "{\"abi_version\":1,\"algorithm\":\"lz4-frame\","
    "\"library\":\"lz4-1.10.0-from-lzbench\",\"stream\":\"LZ4_FRAME\"}";

static void tscb_set_error(tscb_codec_handle_v1 *handle, const char *message) {
    if (handle == NULL) {
        return;
    }
    (void)snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
}

static tscb_status_v1 tscb_lz4_error(
    tscb_codec_handle_v1 *handle,
    const char *operation,
    size_t code
) {
    if (LZ4F_isError(code)) {
        (void)snprintf(
            handle->last_error,
            sizeof(handle->last_error),
            "%s: %s",
            operation,
            LZ4F_getErrorName(code)
        );
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    return TSCB_STATUS_OK_V1;
}

static int tscb_lz4_dst_too_small(size_t code) {
    return LZ4F_isError(code)
        && strcmp(LZ4F_getErrorName(code), "ERROR_dstMaxSize_tooSmall") == 0;
}

static int tscb_json_int(
    const char *json,
    const char *key,
    long default_value,
    long minimum,
    long maximum,
    long *result
) {
    const char *found = strstr(json, key);
    char *end = NULL;
    long value;
    if (found == NULL) {
        *result = default_value;
        return 1;
    }
    found += strlen(key);
    errno = 0;
    value = strtol(found, &end, 10);
    if (errno != 0 || end == found || value < minimum || value > maximum) {
        return 0;
    }
    *result = value;
    return 1;
}

static int tscb_json_bool(
    const char *json,
    const char *key,
    int default_value,
    int *result
) {
    const char *found = strstr(json, key);
    if (found == NULL) {
        *result = default_value;
        return 1;
    }
    found += strlen(key);
    if (strncmp(found, "true", 4) == 0) {
        *result = 1;
        return 1;
    }
    if (strncmp(found, "false", 5) == 0) {
        *result = 0;
        return 1;
    }
    return 0;
}

static int tscb_buffer_shape_is_valid(const tscb_buffer_v1 *buffer) {
    if (buffer == NULL || buffer->rank != 1 || buffer->dtype != TSCB_DTYPE_BYTES_V1) {
        return 0;
    }
    if (buffer->used_bytes > buffer->capacity_bytes) {
        return 0;
    }
    if (buffer->used_bytes != 0 && buffer->data == NULL) {
        return 0;
    }
    return 1;
}

static tscb_status_v1 tscb_new_compression_context(tscb_codec_handle_v1 *handle) {
    size_t code;
    if (handle->compression_context != NULL) {
        (void)LZ4F_freeCompressionContext(handle->compression_context);
        handle->compression_context = NULL;
    }
    code = LZ4F_createCompressionContext(&handle->compression_context, LZ4F_VERSION);
    return tscb_lz4_error(handle, "LZ4F_createCompressionContext", code);
}

uint32_t tscb_get_abi_version(void) {
    return TSCB_ADAPTER_ABI_V1;
}

tscb_status_v1 tscb_get_manifest_json(const char **json, uint64_t *length) {
    if (json == NULL || length == NULL) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *json = TSCB_MANIFEST_JSON;
    *length = (uint64_t)(sizeof(TSCB_MANIFEST_JSON) - 1U);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(
    const char *config_json,
    uint64_t config_length,
    tscb_codec_handle_v1 **handle
) {
    tscb_codec_handle_v1 *created;
    char *config;
    long compression_level;
    long block_size_id;
    long block_mode;
    int content_checksum;
    int block_checksum;
    tscb_status_v1 status;
    if (handle == NULL || config_json == NULL || config_length > 4096U) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *handle = NULL;
    config = (char *)malloc((size_t)config_length + 1U);
    if (config == NULL) {
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    memcpy(config, config_json, (size_t)config_length);
    config[config_length] = '\0';
    if (!tscb_json_int(config, "\"compression_level\":", 0, 0, 12, &compression_level)
        || !tscb_json_int(config, "\"block_size_id\":", 4, 4, 7, &block_size_id)
        || !tscb_json_int(config, "\"block_mode\":", 0, 0, 1, &block_mode)
        || !tscb_json_bool(config, "\"content_checksum\":", 1, &content_checksum)
        || !tscb_json_bool(config, "\"block_checksum\":", 0, &block_checksum)) {
        free(config);
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    free(config);
    created = (tscb_codec_handle_v1 *)calloc(1U, sizeof(*created));
    if (created == NULL) {
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    created->preferences.frameInfo.blockSizeID = (LZ4F_blockSizeID_t)block_size_id;
    created->preferences.frameInfo.blockMode =
        block_mode == 0 ? LZ4F_blockIndependent : LZ4F_blockLinked;
    created->preferences.frameInfo.contentChecksumFlag =
        content_checksum ? LZ4F_contentChecksumEnabled : LZ4F_noContentChecksum;
    created->preferences.frameInfo.blockChecksumFlag =
        block_checksum ? LZ4F_blockChecksumEnabled : LZ4F_noBlockChecksum;
    created->preferences.compressionLevel = (int)compression_level;
    created->preferences.autoFlush = 0U;
    status = tscb_new_compression_context(created);
    if (status != TSCB_STATUS_OK_V1) {
        free(created);
        return status;
    }
    *handle = created;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *handle) {
    if (handle == NULL) {
        return TSCB_STATUS_OK_V1;
    }
    if (handle->compression_context != NULL) {
        (void)LZ4F_freeCompressionContext(handle->compression_context);
    }
    free(handle);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *handle, uint32_t reset_mode) {
    (void)reset_mode;
    if (handle == NULL) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    handle->input_bytes = 0U;
    handle->stream_bytes = 0U;
    handle->update_called = 0;
    handle->finalized = 0;
    handle->last_error[0] = '\0';
    return tscb_new_compression_context(handle);
}

tscb_status_v1 tscb_compress_bound(
    tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input,
    uint64_t *bound_bytes
) {
    size_t update_bound;
    size_t finalize_bound;
    uint64_t total;
    if (handle == NULL || bound_bytes == NULL || !tscb_buffer_shape_is_valid(input)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes > (uint64_t)SIZE_MAX) {
        tscb_set_error(handle, "input exceeds native size_t");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    update_bound = LZ4F_compressBound((size_t)input->used_bytes, &handle->preferences);
    finalize_bound = LZ4F_compressBound(0U, &handle->preferences);
    if (LZ4F_isError(update_bound) || LZ4F_isError(finalize_bound)) {
        tscb_set_error(handle, "LZ4F_compressBound failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    total = (uint64_t)LZ4F_HEADER_SIZE_MAX + (uint64_t)update_bound
        + (uint64_t)finalize_bound;
    if (total < (uint64_t)update_bound || total < (uint64_t)finalize_bound) {
        tscb_set_error(handle, "compression bound overflow");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    *bound_bytes = total;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(
    tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input,
    tscb_buffer_v1 *output
) {
    unsigned char *destination;
    size_t header_size;
    size_t update_size;
    tscb_status_v1 status;
    if (handle == NULL || output == NULL || !tscb_buffer_shape_is_valid(input)
        || output->data == NULL || output->used_bytes > output->capacity_bytes) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (handle->update_called || handle->finalized) {
        tscb_set_error(handle, "compress update may be called exactly once per frame");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (input->used_bytes > (uint64_t)SIZE_MAX || output->capacity_bytes > (uint64_t)SIZE_MAX) {
        tscb_set_error(handle, "buffer exceeds native size_t");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    destination = (unsigned char *)output->data;
    handle->preferences.frameInfo.contentSize = input->used_bytes;
    header_size = LZ4F_compressBegin(
        handle->compression_context,
        destination,
        (size_t)output->capacity_bytes,
        &handle->preferences
    );
    status = tscb_lz4_error(handle, "LZ4F_compressBegin", header_size);
    if (status != TSCB_STATUS_OK_V1) {
        return tscb_lz4_dst_too_small(header_size)
            ? TSCB_STATUS_DST_TOO_SMALL_V1
            : status;
    }
    update_size = LZ4F_compressUpdate(
        handle->compression_context,
        destination + header_size,
        (size_t)output->capacity_bytes - header_size,
        input->data,
        (size_t)input->used_bytes,
        NULL
    );
    status = tscb_lz4_error(handle, "LZ4F_compressUpdate", update_size);
    if (status != TSCB_STATUS_OK_V1) {
        return tscb_lz4_dst_too_small(update_size)
            ? TSCB_STATUS_DST_TOO_SMALL_V1
            : status;
    }
    output->used_bytes = (uint64_t)header_size + (uint64_t)update_size;
    handle->input_bytes = input->used_bytes;
    handle->stream_bytes = output->used_bytes;
    handle->update_called = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    size_t written;
    tscb_status_v1 status;
    if (handle == NULL || output == NULL || output->data == NULL
        || output->used_bytes > output->capacity_bytes) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (!handle->update_called) {
        tscb_set_error(handle, "finalize requires a preceding compress update");
        return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    }
    if (handle->finalized) {
        tscb_set_error(handle, "repeated finalize is forbidden");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (output->capacity_bytes > (uint64_t)SIZE_MAX) {
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    written = LZ4F_compressEnd(
        handle->compression_context,
        output->data,
        (size_t)output->capacity_bytes,
        NULL
    );
    status = tscb_lz4_error(handle, "LZ4F_compressEnd", written);
    if (status != TSCB_STATUS_OK_V1) {
        return tscb_lz4_dst_too_small(written)
            ? TSCB_STATUS_DST_TOO_SMALL_V1
            : status;
    }
    output->used_bytes = (uint64_t)written;
    handle->stream_bytes += (uint64_t)written;
    handle->finalized = 1;
    (void)snprintf(
        handle->accounting_json,
        sizeof(handle->accounting_json),
        "{\"input_bytes\":%" PRIu64 ",\"lz4_frame_bytes\":%" PRIu64 "}",
        handle->input_bytes,
        handle->stream_bytes
    );
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(
    tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input,
    tscb_buffer_v1 *output
) {
    LZ4F_dctx *context = NULL;
    size_t code;
    size_t source_position = 0U;
    size_t destination_position = 0U;
    if (handle == NULL || !tscb_buffer_shape_is_valid(input) || output == NULL
        || output->data == NULL || output->capacity_bytes > (uint64_t)SIZE_MAX
        || input->used_bytes > (uint64_t)SIZE_MAX) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    code = LZ4F_createDecompressionContext(&context, LZ4F_VERSION);
    if (LZ4F_isError(code)) {
        return tscb_lz4_error(handle, "LZ4F_createDecompressionContext", code);
    }
    for (;;) {
        size_t source_size = (size_t)input->used_bytes - source_position;
        size_t destination_size = (size_t)output->capacity_bytes - destination_position;
        code = LZ4F_decompress(
            context,
            (unsigned char *)output->data + destination_position,
            &destination_size,
            (const unsigned char *)input->data + source_position,
            &source_size,
            NULL
        );
        source_position += source_size;
        destination_position += destination_size;
        if (LZ4F_isError(code)) {
            tscb_status_v1 status = tscb_lz4_error(handle, "LZ4F_decompress", code);
            (void)LZ4F_freeDecompressionContext(context);
            return tscb_lz4_dst_too_small(code)
                ? TSCB_STATUS_DST_TOO_SMALL_V1
                : status;
        }
        if (code == 0U) {
            break;
        }
        if (source_size == 0U && destination_size == 0U) {
            tscb_set_error(handle, "LZ4F_decompress made no progress");
            (void)LZ4F_freeDecompressionContext(context);
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    }
    (void)LZ4F_freeDecompressionContext(context);
    if (source_position != (size_t)input->used_bytes) {
        tscb_set_error(handle, "trailing bytes after LZ4 frame");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = (uint64_t)destination_position;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(
    tscb_codec_handle_v1 *handle,
    const char *request_json,
    uint64_t request_length,
    char *response_json,
    uint64_t response_capacity,
    uint64_t *response_used
) {
    (void)request_json;
    (void)request_length;
    (void)response_json;
    (void)response_capacity;
    if (response_used != NULL) {
        *response_used = 0U;
    }
    tscb_set_error(handle, "LZ4 frame adapter does not provide random access queries");
    return TSCB_STATUS_UNSUPPORTED_V1;
}

tscb_status_v1 tscb_get_accounting_json(
    tscb_codec_handle_v1 *handle,
    const char **json,
    uint64_t *length
) {
    if (handle == NULL || json == NULL || length == NULL || !handle->finalized) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *json = handle->accounting_json;
    *length = (uint64_t)strlen(handle->accounting_json);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(
    tscb_codec_handle_v1 *handle,
    const char **message,
    uint64_t *length
) {
    if (handle == NULL || message == NULL || length == NULL) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *message = handle->last_error;
    *length = (uint64_t)strlen(handle->last_error);
    return TSCB_STATUS_OK_V1;
}
