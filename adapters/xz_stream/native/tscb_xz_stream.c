#include "tscb_native_timing.h"
#include "lzma.h"

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct tscb_codec_handle_v1 {
    uint32_t preset;
    int updated;
    int finalized;
    tscb_native_timer native_timer;
    char last_error[256];
};

static const char manifest[] =
    "{\"abi_version\":1,\"algorithm\":\"xz-stream\","
    "\"library\":\"xz-5.8.3-from-lzbench\",\"stream\":\"XZ_LZMA2\","
    "\"data_check\":\"NONE\",\"structural_check\":\"CRC32\","
    "\"dictionary\":\"NO_EXTERNAL_DICTIONARY\",\"threading\":\"SINGLE_THREAD\"}";

static int valid_buffer(const tscb_buffer_v1 *buffer) {
    return buffer != NULL && buffer->rank == 1 && buffer->dtype == TSCB_DTYPE_BYTES_V1
        && buffer->used_bytes <= buffer->capacity_bytes
        && buffer->capacity_bytes <= SIZE_MAX
        && (buffer->used_bytes == 0U || buffer->data != NULL);
}

static void set_error(tscb_codec_handle_v1 *handle, const char *message) {
    if (handle != NULL) snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
}

uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }

tscb_status_v1 tscb_get_manifest_json(const char **json, uint64_t *length) {
    if (json == NULL || length == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = manifest;
    *length = sizeof(manifest) - 1U;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(const char *config_json, uint64_t config_length,
                         tscb_codec_handle_v1 **handle) {
    char config[4097];
    const char *found;
    char *end;
    long preset;
    if (config_json == NULL || handle == NULL || config_length > 4096U) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *handle = NULL;
    memcpy(config, config_json, (size_t)config_length);
    config[config_length] = '\0';
    found = strstr(config, "\"compression_level\":");
    if (found == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    found += strlen("\"compression_level\":");
    errno = 0;
    preset = strtol(found, &end, 10);
    if (errno != 0 || end == found || preset < 0 || preset > 9
        || (*end != ',' && *end != '}')) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *handle = (tscb_codec_handle_v1 *)calloc(1U, sizeof(**handle));
    if (*handle == NULL) return TSCB_STATUS_CODEC_ERROR_V1;
    (*handle)->preset = (uint32_t)preset;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *handle) {
    free(handle);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *handle, uint32_t mode) {
    (void)mode;
    if (handle == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    handle->updated = handle->finalized = 0;
    handle->last_error[0] = '\0';
    handle->native_timer.available = 1;
    handle->native_timer.encode_ns = handle->native_timer.decode_ns = 0U;
    return TSCB_STATUS_OK_V1;
}

TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, uint64_t *bound_bytes) {
    size_t bound;
    if (handle == NULL || bound_bytes == NULL || !valid_buffer(input)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    bound = lzma_stream_buffer_bound((size_t)input->used_bytes);
    if (bound == 0U) {
        set_error(handle, "liblzma stream bound overflow");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    *bound_bytes = bound;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    size_t used = 0U;
    lzma_ret result = LZMA_PROG_ERROR;
    if (handle == NULL || !valid_buffer(input) || !valid_buffer(output)
        || output->data == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (handle->updated || handle->finalized) {
        set_error(handle, "one-shot update may be called once per object");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    TSCB_TIME_CODEC(handle->native_timer, encode_ns,
        result = lzma_easy_buffer_encode(handle->preset, LZMA_CHECK_NONE, NULL,
            (const uint8_t *)input->data, (size_t)input->used_bytes,
            (uint8_t *)output->data, &used, (size_t)output->capacity_bytes));
    if (result != LZMA_OK) {
        set_error(handle, "liblzma one-shot encode failed");
        return result == LZMA_BUF_ERROR ? TSCB_STATUS_DST_TOO_SMALL_V1
                                       : TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = used;
    handle->updated = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    if (handle == NULL || !valid_buffer(output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!handle->updated) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (handle->finalized) {
        set_error(handle, "repeated finalize is forbidden");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    /* The single-call encoder already wrote the block, index and stream footer. */
    output->used_bytes = 0U;
    handle->finalized = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    lzma_stream decoder = LZMA_STREAM_INIT;
    lzma_ret result;
    uint8_t dummy = 0U;
    if (handle == NULL || !valid_buffer(input) || !valid_buffer(output)
        || (output->capacity_bytes != 0U && output->data == NULL)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes < 12U || ((const uint8_t *)input->data)[6] != 0U
        || ((const uint8_t *)input->data)[7] != LZMA_CHECK_NONE) {
        set_error(handle, "xz check/version variant is not registered");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    result = lzma_stream_decoder(&decoder, UINT64_C(1073741824), 0U);
    if (result != LZMA_OK) {
        lzma_end(&decoder);
        set_error(handle, "liblzma independent decoder initialization failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    decoder.next_in = (const uint8_t *)input->data;
    decoder.avail_in = (size_t)input->used_bytes;
    decoder.next_out = output->capacity_bytes == 0U ? &dummy : (uint8_t *)output->data;
    decoder.avail_out = output->capacity_bytes == 0U ? 1U : (size_t)output->capacity_bytes;
    do {
        uint64_t prior_in = decoder.total_in;
        uint64_t prior_out = decoder.total_out;
        TSCB_TIME_CODEC(handle->native_timer, decode_ns,
            result = lzma_code(&decoder, LZMA_FINISH));
        if (result == LZMA_STREAM_END) break;
        if (decoder.avail_out == 0U) {
            lzma_end(&decoder);
            set_error(handle, "liblzma decoded output exceeds descriptor capacity");
            return TSCB_STATUS_DST_TOO_SMALL_V1;
        }
        if (result != LZMA_OK || (prior_in == decoder.total_in && prior_out == decoder.total_out)) {
            lzma_end(&decoder);
            set_error(handle, "liblzma decoder rejected corrupt/truncated stream");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    } while (result != LZMA_STREAM_END);
    if (decoder.avail_in != 0U || decoder.total_out != output->capacity_bytes) {
        lzma_end(&decoder);
        set_error(handle, "liblzma stream consumption or decoded length is not exact");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = decoder.total_out;
    lzma_end(&decoder);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1 *handle, const char *request,
    uint64_t length, char *response, uint64_t capacity, uint64_t *used) {
    (void)request; (void)length; (void)response; (void)capacity;
    if (used != NULL) *used = 0U;
    set_error(handle, "xz random access protocol is not registered");
    return TSCB_STATUS_UNSUPPORTED_V1;
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *handle,
    const char **json, uint64_t *length) {
    static const char accounting[] = "{\"finalize_bytes\":0,\"one_shot\":true}";
    if (handle == NULL || json == NULL || length == NULL || !handle->finalized) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *json = accounting;
    *length = sizeof(accounting) - 1U;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1 *handle,
    const char **message, uint64_t *length) {
    if (handle == NULL || message == NULL || length == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message = handle->last_error;
    *length = strlen(handle->last_error);
    return TSCB_STATUS_OK_V1;
}
