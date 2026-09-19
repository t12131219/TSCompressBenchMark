#define _GNU_SOURCE

#include <stdio.h>

#include "tscb_native_timing.h"

#include "lzss.h"

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer;
    uint64_t input_bytes;
    uint64_t stream_bytes;
    uint64_t finalize_calls;
    int update_called;
    int finalized;
    char last_error[256];
    char accounting_json[256];
};

static const char TSCB_MANIFEST_JSON[] =
    "{\"abi_version\":1,\"algorithm\":\"lzss-dipperstein-c\","
    "\"checksum\":\"NONE\",\"dictionary\":\"FIXED_SPACE_FILLED_4096B\","
    "\"library\":\"MichaelDipperstein-lzss-65b6882\","
    "\"match_finder\":\"BINARY_TREE\","
    "\"stream\":\"LZSS_OFFSET12_LE_NUMERIC_LENGTH4_MSB_BIT_IO\","
    "\"threading\":\"SINGLE_THREAD\"}";

static const char TSCB_CONFIG_JSON[] =
    "{\"initial_byte\":32,\"length_bits\":4,"
    "\"match_finder\":\"BINARY_TREE\",\"offset_bits\":12}";

static void set_error(tscb_codec_handle_v1 *handle, const char *message) {
    if (handle != NULL) {
        (void)snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
    }
}

static int valid_buffer(const tscb_buffer_v1 *buffer) {
    return buffer != NULL && buffer->rank == 1U && buffer->dtype == TSCB_DTYPE_BYTES_V1
        && buffer->used_bytes <= buffer->capacity_bytes
        && (buffer->used_bytes == 0U || buffer->data != NULL);
}

static int valid_output(const tscb_buffer_v1 *buffer) {
    return valid_buffer(buffer) && (buffer->capacity_bytes == 0U || buffer->data != NULL);
}

static int disjoint(const tscb_buffer_v1 *input, const tscb_buffer_v1 *output) {
    uintptr_t first = (uintptr_t)input->data;
    uintptr_t second = (uintptr_t)output->data;
    if (input->used_bytes > UINTPTR_MAX - first
        || output->capacity_bytes > UINTPTR_MAX - second) {
        return 0;
    }
    return input->used_bytes == 0U || output->capacity_bytes == 0U
        || first + input->used_bytes <= second
        || second + output->capacity_bytes <= first;
}

static int read_bits(const uint8_t *data, uint64_t length, uint64_t *bit,
                     unsigned count, uint32_t *value) {
    unsigned index;
    if (*bit > length * 8U || count > length * 8U - *bit) return 0;
    *value = 0U;
    for (index = 0U; index < count; ++index, ++*bit) {
        *value = (*value << 1U)
            | ((uint32_t)(data[*bit / 8U] >> (7U - (*bit % 8U))) & 1U);
    }
    return 1;
}

/* The upstream decoder treats EOF as success. Validate the complete grammar first. */
static int strict_stream(const uint8_t *data, uint64_t length, uint64_t expected) {
    uint64_t bit = 0U;
    uint64_t produced = 0U;
    uint32_t flag;
    uint32_t token;
    uint32_t padding_value;
    unsigned padding;
    while (produced < expected) {
        if (!read_bits(data, length, &bit, 1U, &flag)
            || !read_bits(data, length, &bit, flag != 0U ? 8U : 16U, &token)) {
            return 0;
        }
        produced += flag != 0U ? 1U : (uint64_t)(token & 15U) + 3U;
        if (produced > expected) return 0;
    }
    if (length * 8U - bit > 7U) return 0;
    padding = (unsigned)(length * 8U - bit);
    return read_bits(data, length, &bit, padding, &padding_value)
        && padding_value == 0U;
}

static FILE *open_input_stream(const void *data, size_t length) {
    static unsigned char empty = 0U;
    return fmemopen((void *)(length == 0U ? &empty : data), length, "rb");
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
    if (config_json == NULL || handle == NULL
        || config_length != sizeof(TSCB_CONFIG_JSON) - 1U
        || memcmp(config_json, TSCB_CONFIG_JSON, sizeof(TSCB_CONFIG_JSON) - 1U) != 0) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    *handle = NULL;
    created = (tscb_codec_handle_v1 *)calloc(1U, sizeof(*created));
    if (created == NULL) return TSCB_STATUS_CODEC_ERROR_V1;
    *handle = created;
    return TSCB_STATUS_OK_V1;
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
    return tscb_set_native_timing(handle, (uint32_t)enabled);
}

TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, uint64_t *bound_bytes) {
    if (handle == NULL || bound_bytes == NULL || !valid_buffer(input)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes > UINT32_MAX) {
        set_error(handle, "Dipperstein LZSS input exceeds registered UINT32 work limit");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    *bound_bytes = input->used_bytes + (input->used_bytes + 7U) / 8U;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    FILE *source = NULL;
    FILE *destination = NULL;
    char *encoded = NULL;
    size_t encoded_size = 0U;
    uint64_t bound = 0U;
    int codec_result = -1;
    int source_close_result;
    int destination_close_result;
    if (handle == NULL || !valid_buffer(input) || !valid_output(output)
        || !disjoint(input, output)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (handle->update_called || handle->finalized) {
        set_error(handle, "compress update may be called exactly once per Dipperstein stream");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (tscb_compress_bound(handle, input, &bound) != TSCB_STATUS_OK_V1) {
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    if (output->capacity_bytes < bound) {
        set_error(handle, "Dipperstein LZSS compression requires literal worst-case capacity");
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    }
    if (input->used_bytes == 0U) {
        TSCB_TIME_CODEC(handle->native_timer, encode_ns, codec_result = 0);
        output->used_bytes = 0U;
        handle->input_bytes = 0U;
        handle->stream_bytes = 0U;
        handle->update_called = 1;
        return TSCB_STATUS_OK_V1;
    }
    source = open_input_stream(input->data, (size_t)input->used_bytes);
    destination = open_memstream(&encoded, &encoded_size);
    if (source == NULL || destination == NULL) {
        if (source != NULL) (void)fclose(source);
        if (destination != NULL) (void)fclose(destination);
        free(encoded);
        set_error(handle, "failed to create memory streams for Dipperstein LZSS");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    TSCB_TIME_CODEC(handle->native_timer, encode_ns,
                    codec_result = EncodeLZSS(source, destination));
    source_close_result = fclose(source);
    destination_close_result = fclose(destination);
    if (source_close_result != 0 || destination_close_result != 0 || codec_result != 0) {
        free(encoded);
        set_error(handle, "Dipperstein EncodeLZSS failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (encoded_size > output->capacity_bytes) {
        free(encoded);
        set_error(handle, "Dipperstein EncodeLZSS exceeded the declared output capacity");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (encoded_size != 0U) memcpy(output->data, encoded, encoded_size);
    free(encoded);
    output->used_bytes = encoded_size;
    handle->input_bytes = input->used_bytes;
    handle->stream_bytes = encoded_size;
    handle->update_called = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    if (handle == NULL || output == NULL || output->used_bytes > output->capacity_bytes
        || (output->capacity_bytes != 0U && output->data == NULL)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (!handle->update_called) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (handle->finalized) {
        set_error(handle, "repeated finalize is forbidden");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = 0U;
    handle->finalize_calls = 1U;
    handle->finalized = 1;
    (void)snprintf(handle->accounting_json, sizeof(handle->accounting_json),
        "{\"finalize_calls\":%" PRIu64 ",\"input_bytes\":%" PRIu64
        ",\"lzss_dipperstein_stream_bytes\":%" PRIu64 "}",
        handle->finalize_calls, handle->input_bytes, handle->stream_bytes);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input, tscb_buffer_v1 *output) {
    FILE *source = NULL;
    FILE *destination = NULL;
    char *decoded = NULL;
    size_t decoded_size = 0U;
    int codec_result = -1;
    int source_close_result;
    int destination_close_result;
    if (handle == NULL || !valid_buffer(input) || !valid_output(output)
        || !disjoint(input, output)) {
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    }
    if (input->used_bytes > UINT32_MAX || output->capacity_bytes > UINT32_MAX
        || !strict_stream((const uint8_t *)input->data, input->used_bytes,
                          output->capacity_bytes)) {
        set_error(handle, "invalid Dipperstein token coverage, decoded length or padding");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (input->used_bytes == 0U && output->capacity_bytes == 0U) {
        TSCB_TIME_CODEC(handle->native_timer, decode_ns, codec_result = 0);
        output->used_bytes = 0U;
        return TSCB_STATUS_OK_V1;
    }
    source = open_input_stream(input->data, (size_t)input->used_bytes);
    destination = open_memstream(&decoded, &decoded_size);
    if (source == NULL || destination == NULL) {
        if (source != NULL) (void)fclose(source);
        if (destination != NULL) (void)fclose(destination);
        free(decoded);
        set_error(handle, "failed to create decode memory streams for Dipperstein LZSS");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    TSCB_TIME_CODEC(handle->native_timer, decode_ns,
                    codec_result = DecodeLZSS(source, destination));
    source_close_result = fclose(source);
    destination_close_result = fclose(destination);
    if (source_close_result != 0 || destination_close_result != 0 || codec_result != 0) {
        free(decoded);
        set_error(handle, "Dipperstein DecodeLZSS failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (decoded_size != output->capacity_bytes) {
        free(decoded);
        set_error(handle, "Dipperstein decoded byte count does not match metadata");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    if (decoded_size != 0U) memcpy(output->data, decoded, decoded_size);
    free(decoded);
    output->used_bytes = decoded_size;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1 *handle, const char *request_json,
    uint64_t request_length, char *response_json, uint64_t response_capacity,
    uint64_t *response_used) {
    (void)request_json;
    (void)request_length;
    (void)response_json;
    (void)response_capacity;
    if (response_used != NULL) *response_used = 0U;
    set_error(handle, "Dipperstein LZSS does not provide random access queries");
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
