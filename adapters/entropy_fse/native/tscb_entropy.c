#include "tscb_native_timing.h"
#include "fse.h"
#include "huf.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef TSCB_HUFF0
#define TSCB_HUFF0 0
#endif

struct tscb_codec_handle_v1 {
    int updated;
    int finalized;
    tscb_native_timer native_timer;
    char error[160];
    char accounting[128];
};

#if TSCB_HUFF0
static const char manifest[] = "{\"algorithm\":\"huff0\",\"abi_version\":1,\"threading\":\"SINGLE_THREAD\"}";
#else
static const char manifest[] = "{\"algorithm\":\"fse\",\"abi_version\":1,\"threading\":\"SINGLE_THREAD\"}";
#endif

static int valid(const tscb_buffer_v1 *buffer) {
    return buffer && buffer->dtype == TSCB_DTYPE_BYTES_V1 && buffer->rank == 1
        && buffer->used_bytes <= buffer->capacity_bytes && buffer->data;
}

static void put_size(unsigned char *p, uint64_t size) {
    for (unsigned i = 0; i < 8; ++i) p[i] = (unsigned char)(size >> (8 * i));
}

static uint64_t get_size(const unsigned char *p) {
    uint64_t size = 0;
    for (unsigned i = 0; i < 8; ++i) size |= (uint64_t)p[i] << (8 * i);
    return size;
}

uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }

tscb_status_v1 tscb_get_manifest_json(const char **json, uint64_t *length) {
    if (!json || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = manifest;
    *length = strlen(manifest);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(const char *config, uint64_t length, tscb_codec_handle_v1 **out) {
    if (!config || length > 4096 || !out) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *out = calloc(1, sizeof(**out));
    return *out ? TSCB_STATUS_OK_V1 : TSCB_STATUS_CODEC_ERROR_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *handle) {
    free(handle);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *handle, uint32_t mode) {
    (void)mode;
    if (!handle) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    handle->updated = handle->finalized = 0;
    handle->native_timer.encode_ns = handle->native_timer.decode_ns = 0;
    handle->native_timer.available = 1;
    return TSCB_STATUS_OK_V1;
}

TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, uint64_t *bound) {
    size_t vendor_bound;
    if (!handle || !valid(input) || !bound) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (input->used_bytes > 128 * 1024) return TSCB_STATUS_UNSUPPORTED_V1;
    vendor_bound = TSCB_HUFF0 ? HUF_compressBound((size_t)input->used_bytes)
                              : FSE_compressBound((size_t)input->used_bytes);
    *bound = 9 + (vendor_bound > input->used_bytes ? vendor_bound : input->used_bytes);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    size_t result = 0;
    unsigned char *dst;
    if (!handle || !valid(input) || !valid(output) || handle->updated)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (input->used_bytes > 128 * 1024) return TSCB_STATUS_UNSUPPORTED_V1;
    if (output->capacity_bytes < 9 + input->used_bytes)
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    dst = output->data;
    put_size(dst + 1, input->used_bytes);
    if (input->used_bytes >= 2) {
        TSCB_TIME_CODEC(handle->native_timer, encode_ns,
            result = TSCB_HUFF0
                ? HUF_compress(dst + 9, (size_t)output->capacity_bytes - 9,
                               input->data, (size_t)input->used_bytes)
                : FSE_compress(dst + 9, (size_t)output->capacity_bytes - 9,
                               input->data, (size_t)input->used_bytes));
        if (TSCB_HUFF0 ? HUF_isError(result) : FSE_isError(result)) {
            snprintf(handle->error, sizeof(handle->error), "entropy encoder error");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    }
    if (result > 1 && result < input->used_bytes) {
        dst[0] = 2;
        output->used_bytes = 9 + result;
    } else if (result == 1 && input->used_bytes && !TSCB_HUFF0) {
        dst[0] = 1;
        dst[9] = ((const unsigned char *)input->data)[0];
        output->used_bytes = 10;
    } else {
        dst[0] = 0;
        memcpy(dst + 9, input->data, (size_t)input->used_bytes);
        output->used_bytes = 9 + input->used_bytes;
    }
    handle->updated = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    if (!handle || !valid(output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!handle->updated || handle->finalized) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    handle->finalized = 1;
    output->used_bytes = 0;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    const unsigned char *src;
    uint64_t length;
    size_t result;
    if (!handle || !valid(input) || !valid(output) || input->used_bytes < 9)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    src = input->data;
    length = get_size(src + 1);
    if (length > 128 * 1024 || length != output->capacity_bytes)
        return TSCB_STATUS_CODEC_ERROR_V1;
    if (src[0] == 0 && input->used_bytes == length + 9) {
        memcpy(output->data, src + 9, (size_t)length);
    } else if (!TSCB_HUFF0 && src[0] == 1 && input->used_bytes == 10 && length > 0) {
        memset(output->data, src[9], (size_t)length);
    } else if (src[0] == 2 && input->used_bytes > 10 && length > 0) {
        TSCB_TIME_CODEC(handle->native_timer, decode_ns,
            result = TSCB_HUFF0
                ? HUF_decompress(output->data, (size_t)length, src + 9,
                                 (size_t)input->used_bytes - 9)
                : FSE_decompress(output->data, (size_t)length, src + 9,
                                 (size_t)input->used_bytes - 9));
        if ((TSCB_HUFF0 ? HUF_isError(result) : FSE_isError(result)) || result != length)
            return TSCB_STATUS_CODEC_ERROR_V1;
    } else return TSCB_STATUS_CODEC_ERROR_V1;
    output->used_bytes = length;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1 *handle,
    const char **message, uint64_t *length) {
    if (!handle || !message || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message = handle->error;
    *length = strlen(handle->error);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *handle,
    const char **json, uint64_t *length) {
    if (!handle || !json || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    snprintf(handle->accounting, sizeof(handle->accounting), "{\"finalized\":%s}",
             handle->finalized ? "true" : "false");
    *json = handle->accounting;
    *length = strlen(*json);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1 *handle, const char *request,
    uint64_t length, char *response, uint64_t capacity, uint64_t *used) {
    (void)handle; (void)request; (void)length; (void)response; (void)capacity; (void)used;
    return TSCB_STATUS_UNSUPPORTED_V1;
}
