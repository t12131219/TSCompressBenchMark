#include "tscb_native_timing.h"

#include "brotli/decode.h"
#include "brotli/encode.h"

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct tscb_codec_handle_v1 {
    BrotliEncoderState *encoder;
    int quality;
    int lgwin;
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
    "{\"abi_version\":1,\"algorithm\":\"brotli-stream\","
    "\"checksum\":\"NONE\",\"dictionary\":\"BUILTIN_STATIC_ONLY\","
    "\"library\":\"brotli-1.2.0-from-lzbench\","
    "\"stream\":\"RFC7932_BROTLI\",\"threading\":\"SINGLE_THREAD\"}";

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
    if (handle->encoder != NULL) BrotliEncoderDestroyInstance(handle->encoder);
    handle->encoder = BrotliEncoderCreateInstance(NULL, NULL, NULL);
    if (handle->encoder == NULL) return 0;
    return BrotliEncoderSetParameter(handle->encoder, BROTLI_PARAM_QUALITY,
                                     (uint32_t)handle->quality)
        && BrotliEncoderSetParameter(handle->encoder, BROTLI_PARAM_LGWIN,
                                     (uint32_t)handle->lgwin)
        && BrotliEncoderSetParameter(handle->encoder, BROTLI_PARAM_MODE,
                                     (uint32_t)BROTLI_MODE_GENERIC);
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
    long quality;
    long lgwin;
    if (config_json == NULL || handle == NULL || config_length > 4096U) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *handle = NULL;
    config = (char *)malloc((size_t)config_length + 1U);
    if (config == NULL) return TSCB_STATUS_CODEC_ERROR_V1;
    memcpy(config, config_json, (size_t)config_length);
    config[config_length] = '\0';
    if (!json_int(config, "\"compression_level\":", 0, 11, &quality)
        || !json_int(config, "\"window_bits\":", 10, 24, &lgwin)) {
        free(config);
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    free(config);
    created = (tscb_codec_handle_v1 *)calloc(1U, sizeof(*created));
    if (created == NULL) return TSCB_STATUS_CODEC_ERROR_V1;
    created->quality = (int)quality;
    created->lgwin = (int)lgwin;
    if (!initialize_encoder(created)) {
        BrotliEncoderDestroyInstance(created->encoder);
        free(created);
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    *handle = created;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *handle) {
    if (handle != NULL) {
        BrotliEncoderDestroyInstance(handle->encoder);
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
    if (!initialize_encoder(handle)) {
        set_error(handle, "Brotli encoder reinitialization failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    return TSCB_STATUS_OK_V1;
}

TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, uint64_t *bound_bytes) {
    size_t bound;
    if (handle == NULL || bound_bytes == NULL || !valid_buffer(input)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes > (uint64_t)SIZE_MAX) return TSCB_STATUS_UNSUPPORTED_V1;
    bound = BrotliEncoderMaxCompressedSize((size_t)input->used_bytes);
    if (bound == 0U) {
        set_error(handle, "BrotliEncoderMaxCompressedSize cannot represent input");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    *bound_bytes = (uint64_t)bound;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    size_t available_in;
    size_t available_out;
    const uint8_t *next_in;
    uint8_t *next_out;
    BROTLI_BOOL ok = BROTLI_FALSE;
    if (handle == NULL || !valid_buffer(input) || output == NULL || output->data == NULL
        || output->used_bytes > output->capacity_bytes
        || input->used_bytes > (uint64_t)SIZE_MAX || output->capacity_bytes > (uint64_t)SIZE_MAX) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (handle->update_called || handle->finalized) {
        set_error(handle, "compress update may be called once per Brotli stream");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    available_in = (size_t)input->used_bytes;
    available_out = (size_t)output->capacity_bytes;
    next_in = (const uint8_t *)input->data;
    next_out = (uint8_t *)output->data;
    TSCB_TIME_CODEC(handle->native_timer, encode_ns,
        ok = BrotliEncoderCompressStream(handle->encoder, BROTLI_OPERATION_PROCESS,
            &available_in, &next_in, &available_out, &next_out, NULL));
    if (!ok) {
        set_error(handle, "Brotli PROCESS failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (available_in != 0U) {
        set_error(handle, "Brotli PROCESS destination is too small");
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    }
    output->used_bytes = output->capacity_bytes - (uint64_t)available_out;
    handle->input_bytes = input->used_bytes;
    handle->stream_bytes = output->used_bytes;
    handle->update_called = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    size_t available_in = 0U;
    size_t available_out;
    const uint8_t *next_in = NULL;
    uint8_t *next_out;
    BROTLI_BOOL ok = BROTLI_FALSE;
    if (handle == NULL || output == NULL || output->data == NULL
        || output->used_bytes > output->capacity_bytes
        || output->capacity_bytes > (uint64_t)SIZE_MAX) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!handle->update_called) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (handle->finalized) {
        set_error(handle, "repeated finalize is forbidden");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    available_out = (size_t)output->capacity_bytes;
    next_out = (uint8_t *)output->data;
    while (!BrotliEncoderIsFinished(handle->encoder)) {
        size_t before = available_out;
        TSCB_TIME_CODEC(handle->native_timer, encode_ns,
            ok = BrotliEncoderCompressStream(handle->encoder, BROTLI_OPERATION_FINISH,
                &available_in, &next_in, &available_out, &next_out, NULL));
        handle->finalize_calls += 1U;
        if (!ok) {
            set_error(handle, "Brotli FINISH failed");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
        if (!BrotliEncoderIsFinished(handle->encoder) && available_out == 0U) {
            set_error(handle, "Brotli FINISH destination is too small");
            return TSCB_STATUS_DST_TOO_SMALL_V1;
        }
        if (!BrotliEncoderIsFinished(handle->encoder) && before == available_out) {
            set_error(handle, "Brotli FINISH made no progress");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
    }
    output->used_bytes = output->capacity_bytes - (uint64_t)available_out;
    handle->stream_bytes += output->used_bytes;
    handle->finalized = 1;
    snprintf(handle->accounting_json, sizeof(handle->accounting_json),
        "{\"brotli_stream_bytes\":%" PRIu64 ",\"finalize_calls\":%" PRIu64
        ",\"input_bytes\":%" PRIu64 "}", handle->stream_bytes,
        handle->finalize_calls, handle->input_bytes);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    size_t decoded_size;
    BrotliDecoderResult result = BROTLI_DECODER_RESULT_ERROR;
    if (handle == NULL || !valid_buffer(input) || output == NULL
        || (output->capacity_bytes != 0U && output->data == NULL)
        || input->used_bytes > (uint64_t)SIZE_MAX || output->capacity_bytes > (uint64_t)SIZE_MAX) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    decoded_size = (size_t)output->capacity_bytes;
    TSCB_TIME_CODEC(handle->native_timer, decode_ns,
        result = BrotliDecoderDecompress((size_t)input->used_bytes,
            (const uint8_t *)input->data, &decoded_size, (uint8_t *)output->data));
    if (result != BROTLI_DECODER_RESULT_SUCCESS) {
        set_error(handle, "Brotli decode failed or destination is too small");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (decoded_size != output->capacity_bytes) {
        set_error(handle, "Brotli decoded length does not exactly match descriptor");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = (uint64_t)decoded_size;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1 *handle, const char *request_json,
    uint64_t request_length, char *response_json, uint64_t response_capacity,
    uint64_t *response_used) {
    (void)request_json; (void)request_length; (void)response_json; (void)response_capacity;
    if (response_used != NULL) *response_used = 0U;
    set_error(handle, "Brotli stream adapter does not provide random access queries");
    return TSCB_STATUS_UNSUPPORTED_V1;
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *handle,
    const char **json, uint64_t *length) {
    if (handle == NULL || json == NULL || length == NULL || !handle->finalized) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *json = handle->accounting_json;
    *length = strlen(handle->accounting_json);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1 *handle,
    const char **message, uint64_t *length) {
    if (handle == NULL || message == NULL || length == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message = handle->last_error;
    *length = strlen(handle->last_error);
    return TSCB_STATUS_OK_V1;
}
