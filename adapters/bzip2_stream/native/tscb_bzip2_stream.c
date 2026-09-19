#include "tscb_native_timing.h"

#include "bzlib.h"

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct tscb_codec_handle_v1 {
    bz_stream encoder;
    int encoder_initialized;
    int compression_level;
    uint64_t input_bytes;
    uint64_t stream_bytes;
    uint64_t finalize_calls;
    int update_called;
    int finalized;
    tscb_native_timer native_timer;
    char last_error[256];
    char accounting_json[256];
};

static const char TSCB_MANIFEST_JSON[] =
    "{\"abi_version\":1,\"algorithm\":\"bzip2-stream\","
    "\"library\":\"bzip2-1.0.8-from-lzbench\","
    "\"pipeline\":\"BWT_MTF_RLE_HUFFMAN\","
    "\"stream\":\"BZIP2_STREAM\",\"threading\":\"SINGLE_THREAD\"}";

static void set_error(tscb_codec_handle_v1 *handle, const char *message) {
    if (handle != NULL) snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
}

static int valid_buffer(const tscb_buffer_v1 *buffer) {
    return buffer != NULL && buffer->rank == 1 && buffer->dtype == TSCB_DTYPE_BYTES_V1
        && buffer->used_bytes <= buffer->capacity_bytes
        && (buffer->used_bytes == 0U || buffer->data != NULL);
}

static int json_int(const char *json, const char *key, long min, long max, long *result) {
    const char *found = strstr(json, key);
    char *end = NULL;
    long value;
    if (found == NULL) return 0;
    found += strlen(key);
    errno = 0;
    value = strtol(found, &end, 10);
    if (errno != 0 || end == found || value < min || value > max) return 0;
    *result = value;
    return 1;
}

static int initialize_encoder(tscb_codec_handle_v1 *handle) {
    int result;
    if (handle->encoder_initialized) {
        (void)BZ2_bzCompressEnd(&handle->encoder);
        handle->encoder_initialized = 0;
    }
    memset(&handle->encoder, 0, sizeof(handle->encoder));
    result = BZ2_bzCompressInit(&handle->encoder, handle->compression_level, 0, 0);
    if (result == BZ_OK) handle->encoder_initialized = 1;
    return result;
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
    tscb_codec_handle_v1 *created;
    char *config;
    long compression_level;
    if (config_json == NULL || handle == NULL || config_length > 4096U) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *handle = NULL;
    config = (char *)malloc((size_t)config_length + 1U);
    if (config == NULL) return TSCB_STATUS_CODEC_ERROR_V1;
    memcpy(config, config_json, (size_t)config_length);
    config[config_length] = '\0';
    if (!json_int(config, "\"compression_level\":", 1, 9, &compression_level)) {
        free(config);
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    free(config);
    created = (tscb_codec_handle_v1 *)calloc(1U, sizeof(*created));
    if (created == NULL) return TSCB_STATUS_CODEC_ERROR_V1;
    created->compression_level = (int)compression_level;
    if (initialize_encoder(created) != BZ_OK) {
        free(created);
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    *handle = created;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *handle) {
    if (handle != NULL) {
        if (handle->encoder_initialized) (void)BZ2_bzCompressEnd(&handle->encoder);
        free(handle);
    }
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *handle, uint32_t reset_mode) {
    int enabled;
    (void)reset_mode;
    if (handle == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    enabled = handle->native_timer.enabled;
    handle->input_bytes = handle->stream_bytes = handle->finalize_calls = 0U;
    handle->update_called = handle->finalized = 0;
    handle->last_error[0] = '\0';
    handle->native_timer.enabled = enabled;
    handle->native_timer.available = 1;
    handle->native_timer.encode_ns = handle->native_timer.decode_ns = 0U;
    if (initialize_encoder(handle) != BZ_OK) {
        set_error(handle, "libbz2 encoder reinitialization failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    return TSCB_STATUS_OK_V1;
}

TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, uint64_t *bound_bytes) {
    uint64_t bound;
    if (handle == NULL || bound_bytes == NULL || !valid_buffer(input)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes > (uint64_t)UINT_MAX) {
        set_error(handle, "single-update libbz2 variant is limited to UINT_MAX input bytes");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    bound = input->used_bytes + input->used_bytes / 100U + 600U;
    if (bound > (uint64_t)UINT_MAX) {
        set_error(handle, "libbz2 documented output bound exceeds UINT_MAX");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    *bound_bytes = bound;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    int result = BZ_SEQUENCE_ERROR;
    unsigned int before;
    char dummy = 0;
    if (handle == NULL || !valid_buffer(input) || output == NULL || output->data == NULL
        || output->used_bytes > output->capacity_bytes
        || input->used_bytes > (uint64_t)UINT_MAX
        || output->capacity_bytes > (uint64_t)UINT_MAX) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (handle->update_called || handle->finalized) {
        set_error(handle, "compress update may be called once per bzip2 stream");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    handle->encoder.next_in = input->used_bytes == 0U ? &dummy : (char *)input->data;
    handle->encoder.avail_in = (unsigned int)input->used_bytes;
    handle->encoder.next_out = (char *)output->data;
    handle->encoder.avail_out = (unsigned int)output->capacity_bytes;
    before = handle->encoder.total_out_lo32;
    if (input->used_bytes == 0U) {
        result = BZ_RUN_OK;
    } else {
        TSCB_TIME_CODEC(handle->native_timer, encode_ns,
                        result = BZ2_bzCompress(&handle->encoder, BZ_RUN));
    }
    if (result != BZ_RUN_OK) {
        set_error(handle, "libbz2 BZ_RUN update failed");
        return handle->encoder.avail_out == 0U ? TSCB_STATUS_DST_TOO_SMALL_V1
                                               : TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (handle->encoder.avail_in != 0U) {
        set_error(handle, "libbz2 update destination is too small");
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    }
    output->used_bytes = (uint64_t)(handle->encoder.total_out_lo32 - before);
    handle->input_bytes = input->used_bytes;
    handle->stream_bytes = output->used_bytes;
    handle->update_called = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    int result = BZ_SEQUENCE_ERROR;
    unsigned int before;
    if (handle == NULL || output == NULL || output->data == NULL
        || output->used_bytes > output->capacity_bytes
        || output->capacity_bytes > (uint64_t)UINT_MAX) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (!handle->update_called) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (handle->finalized) {
        set_error(handle, "repeated finalize is forbidden");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    handle->encoder.next_in = NULL;
    handle->encoder.avail_in = 0U;
    handle->encoder.next_out = (char *)output->data;
    handle->encoder.avail_out = (unsigned int)output->capacity_bytes;
    before = handle->encoder.total_out_lo32;
    do {
        unsigned int prior_out = handle->encoder.total_out_lo32;
        TSCB_TIME_CODEC(handle->native_timer, encode_ns,
                        result = BZ2_bzCompress(&handle->encoder, BZ_FINISH));
        handle->finalize_calls += 1U;
        if (result == BZ_STREAM_END) break;
        if (result == BZ_FINISH_OK && handle->encoder.avail_out == 0U) {
            set_error(handle, "libbz2 BZ_FINISH destination is too small");
            return TSCB_STATUS_DST_TOO_SMALL_V1;
        }
        if (result != BZ_FINISH_OK || handle->encoder.total_out_lo32 == prior_out) {
            set_error(handle, "libbz2 BZ_FINISH failed or made no progress");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    } while (result != BZ_STREAM_END);
    output->used_bytes = (uint64_t)(handle->encoder.total_out_lo32 - before);
    handle->stream_bytes += output->used_bytes;
    handle->finalized = 1;
    snprintf(handle->accounting_json, sizeof(handle->accounting_json),
        "{\"bzip2_stream_bytes\":%" PRIu64 ",\"finalize_calls\":%" PRIu64
        ",\"input_bytes\":%" PRIu64 "}", handle->stream_bytes,
        handle->finalize_calls, handle->input_bytes);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    bz_stream decoder;
    char dummy = 0;
    int result = BZ_SEQUENCE_ERROR;
    int initialized;
    if (handle == NULL || !valid_buffer(input) || output == NULL
        || (output->capacity_bytes != 0U && output->data == NULL)
        || input->used_bytes > (uint64_t)UINT_MAX
        || output->capacity_bytes > (uint64_t)UINT_MAX) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    memset(&decoder, 0, sizeof(decoder));
    initialized = BZ2_bzDecompressInit(&decoder, 0, 0);
    if (initialized != BZ_OK) {
        set_error(handle, "libbz2 decoder initialization failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    decoder.next_in = input->used_bytes == 0U ? &dummy : (char *)input->data;
    decoder.avail_in = (unsigned int)input->used_bytes;
    decoder.next_out = output->capacity_bytes == 0U ? &dummy : (char *)output->data;
    decoder.avail_out = output->capacity_bytes == 0U ? 1U : (unsigned int)output->capacity_bytes;
    do {
        unsigned int prior_in = decoder.total_in_lo32;
        unsigned int prior_out = decoder.total_out_lo32;
        TSCB_TIME_CODEC(handle->native_timer, decode_ns,
                        result = BZ2_bzDecompress(&decoder));
        if (decoder.total_out_hi32 != 0U
            || decoder.total_out_lo32 > (unsigned int)output->capacity_bytes) {
            (void)BZ2_bzDecompressEnd(&decoder);
            set_error(handle, "libbz2 stream exceeds the declared decoded length");
            return TSCB_STATUS_DST_TOO_SMALL_V1;
        }
        if (result == BZ_STREAM_END) break;
        if (result != BZ_OK
            || (decoder.total_in_lo32 == prior_in && decoder.total_out_lo32 == prior_out)) {
            (void)BZ2_bzDecompressEnd(&decoder);
            set_error(handle, "libbz2 rejected a truncated or malformed stream");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
        if (decoder.total_out_lo32 == (unsigned int)output->capacity_bytes) {
            decoder.next_out = &dummy;
            decoder.avail_out = 1U;
        }
    } while (result != BZ_STREAM_END);
    if (decoder.total_out_hi32 != 0U
        || decoder.total_out_lo32 != (unsigned int)output->capacity_bytes
        || decoder.avail_in != 0U) {
        (void)BZ2_bzDecompressEnd(&decoder);
        set_error(handle, "libbz2 decoded length or consumed stream length is not exact");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = (uint64_t)decoder.total_out_lo32;
    (void)BZ2_bzDecompressEnd(&decoder);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1 *handle, const char *request_json,
    uint64_t request_length, char *response_json, uint64_t response_capacity,
    uint64_t *response_used) {
    (void)request_json; (void)request_length; (void)response_json; (void)response_capacity;
    if (response_used != NULL) *response_used = 0U;
    set_error(handle, "bzip2 stream adapter does not provide random access queries");
    return TSCB_STATUS_UNSUPPORTED_V1;
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *handle,
    const char **json, uint64_t *length) {
    if (handle == NULL || json == NULL || length == NULL || !handle->finalized) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *json = handle->accounting_json;
    *length = (uint64_t)strlen(handle->accounting_json);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1 *handle,
    const char **message, uint64_t *length) {
    if (handle == NULL || message == NULL || length == NULL) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *message = handle->last_error;
    *length = (uint64_t)strlen(handle->last_error);
    return TSCB_STATUS_OK_V1;
}
