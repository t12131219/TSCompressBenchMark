#include "tscb_native_timing.h"

#include "zlib.h"

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct tscb_codec_handle_v1 {
    z_stream encoder;
    int encoder_initialized;
    int level;
    int window_bits;
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
    "{\"abi_version\":1,\"algorithm\":\"deflate-zlib\","
    "\"checksum\":\"ADLER32\",\"dictionary\":\"NONE\","
    "\"library\":\"zlib-1.3.2-from-lzbench\","
    "\"stream\":\"RFC1950_ZLIB_WITH_RFC1951_DEFLATE\","
    "\"threading\":\"SINGLE_THREAD\"}";

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
        (void)deflateEnd(&handle->encoder);
        handle->encoder_initialized = 0;
    }
    memset(&handle->encoder, 0, sizeof(handle->encoder));
    result = deflateInit2(&handle->encoder, handle->level, Z_DEFLATED,
                          handle->window_bits, 8, Z_DEFAULT_STRATEGY);
    if (result == Z_OK) handle->encoder_initialized = 1;
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
    long level;
    long window_bits;
    if (config_json == NULL || handle == NULL || config_length > 4096U) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *handle = NULL;
    config = (char *)malloc((size_t)config_length + 1U);
    if (config == NULL) return TSCB_STATUS_CODEC_ERROR_V1;
    memcpy(config, config_json, (size_t)config_length);
    config[config_length] = '\0';
    if (!json_int(config, "\"compression_level\":", 0, 9, &level)
        || !json_int(config, "\"window_bits\":", 9, 15, &window_bits)) {
        free(config);
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    free(config);
    created = (tscb_codec_handle_v1 *)calloc(1U, sizeof(*created));
    if (created == NULL) return TSCB_STATUS_CODEC_ERROR_V1;
    created->level = (int)level;
    created->window_bits = (int)window_bits;
    if (initialize_encoder(created) != Z_OK) {
        free(created);
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    *handle = created;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *handle) {
    if (handle != NULL) {
        if (handle->encoder_initialized) (void)deflateEnd(&handle->encoder);
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
    if (initialize_encoder(handle) != Z_OK) {
        set_error(handle, "zlib deflate context reinitialization failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    return TSCB_STATUS_OK_V1;
}

TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, uint64_t *bound_bytes) {
    uLong bound;
    if (handle == NULL || bound_bytes == NULL || !valid_buffer(input)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes > (uint64_t)UINT_MAX) {
        set_error(handle, "single-update zlib variant is limited to UINT_MAX input bytes");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    bound = deflateBound(&handle->encoder, (uLong)input->used_bytes);
    if (bound == 0U || (uint64_t)bound > (uint64_t)UINT_MAX) {
        set_error(handle, "zlib deflateBound cannot represent this input");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    *bound_bytes = (uint64_t)bound;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    int result = Z_STREAM_ERROR;
    uLong before;
    if (handle == NULL || !valid_buffer(input) || output == NULL || output->data == NULL
        || output->used_bytes > output->capacity_bytes
        || input->used_bytes > (uint64_t)UINT_MAX
        || output->capacity_bytes > (uint64_t)UINT_MAX) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (handle->update_called || handle->finalized) {
        set_error(handle, "compress update may be called once per zlib stream");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    handle->encoder.next_in = (Bytef *)input->data;
    handle->encoder.avail_in = (uInt)input->used_bytes;
    handle->encoder.next_out = (Bytef *)output->data;
    handle->encoder.avail_out = (uInt)output->capacity_bytes;
    before = handle->encoder.total_out;
    TSCB_TIME_CODEC(handle->native_timer, encode_ns,
                    result = deflate(&handle->encoder, Z_NO_FLUSH));
    if (result != Z_OK) {
        set_error(handle, "zlib Z_NO_FLUSH update failed");
        return result == Z_BUF_ERROR ? TSCB_STATUS_DST_TOO_SMALL_V1
                                     : TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (handle->encoder.avail_in != 0U) {
        set_error(handle, "zlib update destination is too small");
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    }
    output->used_bytes = (uint64_t)(handle->encoder.total_out - before);
    handle->input_bytes = input->used_bytes;
    handle->stream_bytes = output->used_bytes;
    handle->update_called = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    int result = Z_STREAM_ERROR;
    uLong before;
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
    handle->encoder.next_in = Z_NULL;
    handle->encoder.avail_in = 0U;
    handle->encoder.next_out = (Bytef *)output->data;
    handle->encoder.avail_out = (uInt)output->capacity_bytes;
    before = handle->encoder.total_out;
    do {
        uLong prior_out = handle->encoder.total_out;
        TSCB_TIME_CODEC(handle->native_timer, encode_ns,
                        result = deflate(&handle->encoder, Z_FINISH));
        handle->finalize_calls += 1U;
        if (result == Z_STREAM_END) break;
        if (result == Z_BUF_ERROR || handle->encoder.avail_out == 0U) {
            set_error(handle, "zlib Z_FINISH destination is too small");
            return TSCB_STATUS_DST_TOO_SMALL_V1;
        }
        if (result != Z_OK || handle->encoder.total_out == prior_out) {
            set_error(handle, "zlib Z_FINISH failed or made no progress");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    } while (result != Z_STREAM_END);
    output->used_bytes = (uint64_t)(handle->encoder.total_out - before);
    handle->stream_bytes += output->used_bytes;
    handle->finalized = 1;
    snprintf(handle->accounting_json, sizeof(handle->accounting_json),
        "{\"finalize_calls\":%" PRIu64 ",\"input_bytes\":%" PRIu64
        ",\"zlib_stream_bytes\":%" PRIu64 "}", handle->finalize_calls,
        handle->input_bytes, handle->stream_bytes);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    z_stream decoder;
    Bytef dummy = 0U;
    int result = Z_STREAM_ERROR;
    int initialized;
    if (handle == NULL || !valid_buffer(input) || output == NULL
        || (output->capacity_bytes != 0U && output->data == NULL)
        || input->used_bytes > (uint64_t)UINT_MAX
        || output->capacity_bytes > (uint64_t)UINT_MAX) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    memset(&decoder, 0, sizeof(decoder));
    initialized = inflateInit2(&decoder, handle->window_bits);
    if (initialized != Z_OK) {
        set_error(handle, "zlib inflate context initialization failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    decoder.next_in = (Bytef *)input->data;
    decoder.avail_in = (uInt)input->used_bytes;
    decoder.next_out = output->capacity_bytes == 0U ? &dummy : (Bytef *)output->data;
    decoder.avail_out = output->capacity_bytes == 0U ? 1U : (uInt)output->capacity_bytes;
    do {
        uLong prior_in = decoder.total_in;
        uLong prior_out = decoder.total_out;
        TSCB_TIME_CODEC(handle->native_timer, decode_ns,
                        result = inflate(&decoder, Z_FINISH));
        if (result == Z_STREAM_END) break;
        if (result == Z_BUF_ERROR && decoder.avail_out == 0U) {
            (void)inflateEnd(&decoder);
            set_error(handle, "zlib inflate destination is too small");
            return TSCB_STATUS_DST_TOO_SMALL_V1;
        }
        if (result != Z_OK || (decoder.total_in == prior_in && decoder.total_out == prior_out)) {
            (void)inflateEnd(&decoder);
            set_error(handle, "zlib inflate rejected the stream");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    } while (result != Z_STREAM_END);
    if (decoder.total_out != (uLong)output->capacity_bytes || decoder.avail_in != 0U) {
        (void)inflateEnd(&decoder);
        set_error(handle, "zlib decoded length or consumed stream length is not exact");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = (uint64_t)decoder.total_out;
    (void)inflateEnd(&decoder);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1 *handle, const char *request_json,
    uint64_t request_length, char *response_json, uint64_t response_capacity,
    uint64_t *response_used) {
    (void)request_json; (void)request_length; (void)response_json; (void)response_capacity;
    if (response_used != NULL) *response_used = 0U;
    set_error(handle, "zlib DEFLATE adapter does not provide random access queries");
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
