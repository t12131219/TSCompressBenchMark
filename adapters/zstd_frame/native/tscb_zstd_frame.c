#include "tscb_native_timing.h"

#include "zstd.h"
#include "zstd_errors.h"

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer;
    ZSTD_CCtx *compression_context;
    int compression_level;
    int content_checksum;
    uint64_t input_bytes;
    uint64_t stream_bytes;
    uint64_t finalize_calls;
    int update_called;
    int finalized;
    char last_error[256];
    char accounting_json[320];
};

TSCB_NATIVE_TIMING_API

static const char TSCB_MANIFEST_JSON[] =
    "{\"abi_version\":1,\"algorithm\":\"zstd-frame\"," 
    "\"dictionary\":\"NONE\",\"library\":\"zstd-1.5.7-from-lzbench\"," 
    "\"stream\":\"ZSTD_FRAME\",\"threading\":\"SINGLE_THREAD\"}";

static void tscb_set_error(tscb_codec_handle_v1 *handle, const char *message) {
    if (handle != NULL) {
        (void)snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
    }
}

static tscb_status_v1 tscb_zstd_error(
    tscb_codec_handle_v1 *handle,
    const char *operation,
    size_t code
) {
    if (!ZSTD_isError(code)) {
        return TSCB_STATUS_OK_V1;
    }
    (void)snprintf(
        handle->last_error,
        sizeof(handle->last_error),
        "%s: %s",
        operation,
        ZSTD_getErrorName(code)
    );
    return ZSTD_getErrorCode(code) == ZSTD_error_dstSize_tooSmall
        ? TSCB_STATUS_DST_TOO_SMALL_V1
        : TSCB_STATUS_CODEC_ERROR_V1;
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
    if (buffer->used_bytes != 0U && buffer->data == NULL) {
        return 0;
    }
    return 1;
}

static tscb_status_v1 tscb_configure_context(tscb_codec_handle_v1 *handle) {
    size_t code;
    code = ZSTD_CCtx_reset(handle->compression_context, ZSTD_reset_session_and_parameters);
    if (ZSTD_isError(code)) {
        return tscb_zstd_error(handle, "ZSTD_CCtx_reset", code);
    }
    code = ZSTD_CCtx_setParameter(
        handle->compression_context,
        ZSTD_c_compressionLevel,
        handle->compression_level
    );
    if (ZSTD_isError(code)) {
        return tscb_zstd_error(handle, "ZSTD_c_compressionLevel", code);
    }
    code = ZSTD_CCtx_setParameter(handle->compression_context, ZSTD_c_nbWorkers, 0);
    if (ZSTD_isError(code)) {
        return tscb_zstd_error(handle, "ZSTD_c_nbWorkers", code);
    }
    code = ZSTD_CCtx_setParameter(handle->compression_context, ZSTD_c_contentSizeFlag, 1);
    if (ZSTD_isError(code)) {
        return tscb_zstd_error(handle, "ZSTD_c_contentSizeFlag", code);
    }
    code = ZSTD_CCtx_setParameter(
        handle->compression_context,
        ZSTD_c_checksumFlag,
        handle->content_checksum
    );
    if (ZSTD_isError(code)) {
        return tscb_zstd_error(handle, "ZSTD_c_checksumFlag", code);
    }
    code = ZSTD_CCtx_setParameter(handle->compression_context, ZSTD_c_dictIDFlag, 0);
    if (ZSTD_isError(code)) {
        return tscb_zstd_error(handle, "ZSTD_c_dictIDFlag", code);
    }
    return TSCB_STATUS_OK_V1;
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
    int content_checksum;
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
    if (!tscb_json_int(config, "\"compression_level\":", 3, -5, 22, &compression_level)
        || !tscb_json_bool(
            config,
            "\"content_checksum\":",
            1,
            &content_checksum
        )) {
        free(config);
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    free(config);
    created = (tscb_codec_handle_v1 *)calloc(1U, sizeof(*created));
    if (created == NULL) {
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    created->compression_context = ZSTD_createCCtx();
    if (created->compression_context == NULL) {
        free(created);
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    created->compression_level = (int)compression_level;
    created->content_checksum = content_checksum;
    status = tscb_configure_context(created);
    if (status != TSCB_STATUS_OK_V1) {
        (void)ZSTD_freeCCtx(created->compression_context);
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
    (void)ZSTD_freeCCtx(handle->compression_context);
    free(handle);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *handle, uint32_t reset_mode) {
    (void)reset_mode;
    if (handle == NULL) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    handle->input_bytes = 0U;
    (void)tscb_set_native_timing(handle, (uint32_t)handle->native_timer.enabled);
    handle->stream_bytes = 0U;
    handle->finalize_calls = 0U;
    handle->update_called = 0;
    handle->finalized = 0;
    handle->last_error[0] = '\0';
    return tscb_configure_context(handle);
}

tscb_status_v1 tscb_compress_bound(
    tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input,
    uint64_t *bound_bytes
) {
    size_t bound;
    size_t flush_allowance;
    uint64_t total;
    if (handle == NULL || bound_bytes == NULL || !tscb_buffer_shape_is_valid(input)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes > (uint64_t)SIZE_MAX) {
        tscb_set_error(handle, "input exceeds native size_t");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    bound = ZSTD_compressBound((size_t)input->used_bytes);
    if (ZSTD_isError(bound)) {
        return tscb_zstd_error(handle, "ZSTD_compressBound", bound);
    }
    flush_allowance = ZSTD_CStreamOutSize();
    total = (uint64_t)bound + (uint64_t)flush_allowance;
    if (total < (uint64_t)bound) {
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
    ZSTD_inBuffer source;
    ZSTD_outBuffer destination;
    size_t code;
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
    code = ZSTD_CCtx_setPledgedSrcSize(handle->compression_context, input->used_bytes);
    if (ZSTD_isError(code)) {
        return tscb_zstd_error(handle, "ZSTD_CCtx_setPledgedSrcSize", code);
    }
    source.src = input->data;
    source.size = (size_t)input->used_bytes;
    source.pos = 0U;
    destination.dst = output->data;
    destination.size = (size_t)output->capacity_bytes;
    destination.pos = 0U;
    do {
        size_t old_source_position = source.pos;
        size_t old_destination_position = destination.pos;
        TSCB_TIME_CODEC(handle->native_timer, encode_ns, code = ZSTD_compressStream2(
            handle->compression_context,
            &destination,
            &source,
            ZSTD_e_continue
        ));
        if (ZSTD_isError(code)) {
            return tscb_zstd_error(handle, "ZSTD_compressStream2(continue)", code);
        }
        if (source.pos == old_source_position && destination.pos == old_destination_position
            && source.pos < source.size) {
            tscb_set_error(handle, "ZSTD_compressStream2(continue) made no progress");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
        if (source.pos < source.size && destination.pos == destination.size) {
            tscb_set_error(handle, "ZSTD update destination is too small");
            return TSCB_STATUS_DST_TOO_SMALL_V1;
        }
    } while (source.pos < source.size);
    output->used_bytes = (uint64_t)destination.pos;
    handle->input_bytes = input->used_bytes;
    handle->stream_bytes = output->used_bytes;
    handle->update_called = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    ZSTD_inBuffer source = {NULL, 0U, 0U};
    ZSTD_outBuffer destination;
    size_t remaining;
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
    destination.dst = output->data;
    destination.size = (size_t)output->capacity_bytes;
    destination.pos = 0U;
    do {
        size_t old_position = destination.pos;
        TSCB_TIME_CODEC(handle->native_timer, encode_ns, remaining = ZSTD_compressStream2(
            handle->compression_context,
            &destination,
            &source,
            ZSTD_e_end
        ));
        handle->finalize_calls += 1U;
        if (ZSTD_isError(remaining)) {
            return tscb_zstd_error(handle, "ZSTD_compressStream2(end)", remaining);
        }
        if (remaining != 0U && destination.pos == destination.size) {
            tscb_set_error(handle, "ZSTD finalize destination is too small");
            return TSCB_STATUS_DST_TOO_SMALL_V1;
        }
        if (remaining != 0U && destination.pos == old_position) {
            tscb_set_error(handle, "ZSTD_compressStream2(end) made no progress");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    } while (remaining != 0U);
    output->used_bytes = (uint64_t)destination.pos;
    handle->stream_bytes += output->used_bytes;
    handle->finalized = 1;
    (void)snprintf(
        handle->accounting_json,
        sizeof(handle->accounting_json),
        "{\"finalize_calls\":%" PRIu64 ",\"input_bytes\":%" PRIu64
        ",\"zstd_frame_bytes\":%" PRIu64 "}",
        handle->finalize_calls,
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
    ZSTD_DCtx *context;
    ZSTD_inBuffer source;
    ZSTD_outBuffer destination;
    size_t remaining;
    if (handle == NULL || !tscb_buffer_shape_is_valid(input) || output == NULL
        || output->data == NULL || output->capacity_bytes > (uint64_t)SIZE_MAX
        || input->used_bytes > (uint64_t)SIZE_MAX) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    context = ZSTD_createDCtx();
    if (context == NULL) {
        tscb_set_error(handle, "ZSTD_createDCtx failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    source.src = input->data;
    source.size = (size_t)input->used_bytes;
    source.pos = 0U;
    destination.dst = output->data;
    destination.size = (size_t)output->capacity_bytes;
    destination.pos = 0U;
    do {
        size_t old_source_position = source.pos;
        size_t old_destination_position = destination.pos;
        TSCB_TIME_CODEC(handle->native_timer, decode_ns,
            remaining = ZSTD_decompressStream(context, &destination, &source));
        if (ZSTD_isError(remaining)) {
            tscb_status_v1 status = tscb_zstd_error(
                handle,
                "ZSTD_decompressStream",
                remaining
            );
            (void)ZSTD_freeDCtx(context);
            return status;
        }
        if (remaining != 0U && destination.pos == destination.size) {
            tscb_set_error(handle, "ZSTD decode destination is too small");
            (void)ZSTD_freeDCtx(context);
            return TSCB_STATUS_DST_TOO_SMALL_V1;
        }
        if (remaining != 0U && source.pos == old_source_position
            && destination.pos == old_destination_position) {
            tscb_set_error(handle, "ZSTD_decompressStream made no progress");
            (void)ZSTD_freeDCtx(context);
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    } while (remaining != 0U);
    (void)ZSTD_freeDCtx(context);
    if (source.pos != source.size) {
        tscb_set_error(handle, "trailing bytes after Zstd frame");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = (uint64_t)destination.pos;
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
    tscb_set_error(handle, "Zstd frame adapter does not provide random access queries");
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
