#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include "tscb_adapter_v1.h"
#include "tscb_native_timing.h"
#include "zfp.h"

#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if !defined(__BYTE_ORDER__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "zfp-accuracy-1d currently requires a little-endian host"
#endif

#define TSCB_ZFP_MAX_ELEMENTS UINT64_C(16777216)
#define TSCB_ZFP_INPUT_HEADER UINT64_C(24)
#define TSCB_ZFP_FRAME_HEADER UINT64_C(38)
#define TSCB_ZFP_RECORD_HEADER UINT64_C(16)
#define TSCB_ZFP_CHECKSUM_BYTES UINT64_C(8)

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer;
    int updated;
    int finalized;
    uint64_t input_bytes;
    uint64_t stream_bytes;
    uint64_t raw_exception_columns;
    char accounting_json[256];
    char last_error[192];
};

typedef struct {
    uint8_t width;
    uint16_t columns;
    uint64_t rows;
    double requested;
    const uint8_t *payload;
} input_view;

typedef struct {
    uint8_t *data;
    uint64_t capacity;
    uint64_t offset;
} writer;

typedef struct {
    const uint8_t *data;
    uint64_t size;
    uint64_t offset;
} reader;

static const char k_manifest[] =
    "{\"algorithm\":\"zfp-accuracy-1d\",\"backend\":\"C_ABI_V1\","
    "\"dtypes\":[\"float32\",\"float64\"],\"header\":\"ZFP_HEADER_FULL_PER_COLUMN\","
    "\"mode\":\"FIXED_ACCURACY\",\"topology\":\"1D_PER_COLUMN\","
    "\"upstream_commit\":\"c0c2c40b30d99f1787664b51c593fb6e0d729253\"}";
static const char k_config[] = "{\"algorithm\":\"zfp-accuracy-1d\"}";

static void set_error(tscb_codec_handle_v1 *handle, const char *message) {
    if (handle != NULL)
        snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
}

static int valid_buffer(const tscb_buffer_v1 *buffer) {
    return buffer != NULL && buffer->used_bytes <= buffer->capacity_bytes &&
           (buffer->capacity_bytes == 0 || buffer->data != NULL) &&
           buffer->reserved == 0;
}

static int overlaps(const tscb_buffer_v1 *left, const tscb_buffer_v1 *right) {
    uintptr_t a, b;
    if (left->used_bytes == 0 || right->capacity_bytes == 0)
        return 0;
    a = (uintptr_t)left->data;
    b = (uintptr_t)right->data;
    return a < b + right->capacity_bytes && b < a + left->used_bytes;
}

static uint16_t load_u16(const uint8_t *p) {
    return (uint16_t)p[0] | (uint16_t)((uint16_t)p[1] << 8);
}

static uint32_t load_u32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
           (uint32_t)p[3] << 24;
}

static uint64_t load_u64(const uint8_t *p) {
    uint64_t value = 0;
    unsigned i;
    for (i = 0; i < 8; ++i)
        value |= (uint64_t)p[i] << (8 * i);
    return value;
}

static double load_f64(const uint8_t *p) {
    uint64_t bits = load_u64(p);
    double value;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

static int write_bytes(writer *out, const void *data, uint64_t size) {
    if (size > out->capacity - out->offset)
        return 0;
    if (size != 0)
        memcpy(out->data + out->offset, data, (size_t)size);
    out->offset += size;
    return 1;
}

static int write_u8(writer *out, uint8_t value) {
    return write_bytes(out, &value, 1);
}

static int write_u16(writer *out, uint16_t value) {
    uint8_t bytes[2] = {(uint8_t)value, (uint8_t)(value >> 8)};
    return write_bytes(out, bytes, sizeof(bytes));
}

static int write_u32(writer *out, uint32_t value) {
    uint8_t bytes[4];
    unsigned i;
    for (i = 0; i < 4; ++i)
        bytes[i] = (uint8_t)(value >> (8 * i));
    return write_bytes(out, bytes, sizeof(bytes));
}

static int write_u64(writer *out, uint64_t value) {
    uint8_t bytes[8];
    unsigned i;
    for (i = 0; i < 8; ++i)
        bytes[i] = (uint8_t)(value >> (8 * i));
    return write_bytes(out, bytes, sizeof(bytes));
}

static int write_f64(writer *out, double value) {
    uint64_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return write_u64(out, bits);
}

static int read_bytes(reader *in, const uint8_t **data, uint64_t size) {
    if (size > in->size - in->offset)
        return 0;
    *data = in->data + in->offset;
    in->offset += size;
    return 1;
}

static int read_u8(reader *in, uint8_t *value) {
    const uint8_t *p;
    if (!read_bytes(in, &p, 1))
        return 0;
    *value = p[0];
    return 1;
}

static int read_u16(reader *in, uint16_t *value) {
    const uint8_t *p;
    if (!read_bytes(in, &p, 2))
        return 0;
    *value = load_u16(p);
    return 1;
}

static int read_u32(reader *in, uint32_t *value) {
    const uint8_t *p;
    if (!read_bytes(in, &p, 4))
        return 0;
    *value = load_u32(p);
    return 1;
}

static int read_u64(reader *in, uint64_t *value) {
    const uint8_t *p;
    if (!read_bytes(in, &p, 8))
        return 0;
    *value = load_u64(p);
    return 1;
}

static int read_f64(reader *in, double *value) {
    const uint8_t *p;
    if (!read_bytes(in, &p, 8))
        return 0;
    *value = load_f64(p);
    return 1;
}

static uint64_t checksum64(const uint8_t *data, uint64_t size) {
    uint64_t hash = UINT64_C(1469598103934665603);
    uint64_t i;
    for (i = 0; i < size; ++i) {
        hash ^= data[i];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static int parse_input(const tscb_buffer_v1 *input, input_view *view) {
    const uint8_t *p;
    uint64_t raw_bytes;
    if (!valid_buffer(input) || input->dtype != TSCB_DTYPE_BYTES_V1 || input->rank != 1 ||
        input->used_bytes < TSCB_ZFP_INPUT_HEADER)
        return 0;
    p = (const uint8_t *)input->data;
    if (memcmp(p, "ZFI1", 4) != 0 || (p[4] != 4 && p[4] != 8) || p[5] != 0)
        return 0;
    view->width = p[4];
    view->columns = load_u16(p + 6);
    view->rows = load_u64(p + 8);
    view->requested = load_f64(p + 16);
    if (view->columns == 0 || view->rows > TSCB_ZFP_MAX_ELEMENTS ||
        view->rows > TSCB_ZFP_MAX_ELEMENTS / view->columns ||
        !isfinite(view->requested) || view->requested <= 0)
        return 0;
    raw_bytes = view->rows * view->columns * view->width;
    if (input->used_bytes != TSCB_ZFP_INPUT_HEADER + raw_bytes)
        return 0;
    view->payload = p + TSCB_ZFP_INPUT_HEADER;
    return 1;
}

static zfp_type scalar_type(uint8_t width) {
    return width == 4 ? zfp_type_float : zfp_type_double;
}

static int exceptional_column(const uint8_t *data, uint64_t rows, uint8_t width) {
    uint64_t i;
    for (i = 0; i < rows; ++i) {
        if (width == 4) {
            uint32_t bits;
            float value;
            memcpy(&bits, data + i * 4, 4);
            memcpy(&value, &bits, 4);
            if (!isfinite(value) || fpclassify(value) == FP_SUBNORMAL ||
                (value == 0 && (bits >> 31) != 0))
                return 1;
        } else {
            uint64_t bits;
            double value;
            memcpy(&bits, data + i * 8, 8);
            memcpy(&value, &bits, 8);
            if (!isfinite(value) || fpclassify(value) == FP_SUBNORMAL ||
                (value == 0 && (bits >> 63) != 0))
                return 1;
        }
    }
    return 0;
}

static int zfp_bound(uint64_t rows, uint8_t width, double requested,
                     uint64_t *bound, double *actual) {
    zfp_stream *stream = NULL;
    zfp_field *field = NULL;
    size_t maximum;
    if (rows == 0) {
        int exponent;
        frexp(requested, &exponent);
        *actual = ldexp(1.0, exponent - 1);
        *bound = 0;
        return isfinite(*actual) && *actual > 0;
    }
    field = zfp_field_1d(NULL, scalar_type(width), (size_t)rows);
    stream = zfp_stream_open(NULL);
    if (field == NULL || stream == NULL)
        goto fail;
    if (!zfp_stream_set_execution(stream, zfp_exec_serial))
        goto fail;
    *actual = zfp_stream_set_accuracy(stream, requested);
    maximum = zfp_stream_maximum_size(stream, field);
    if (!isfinite(*actual) || *actual <= 0 || *actual > requested || maximum == 0)
        goto fail;
    *bound = (uint64_t)maximum;
    zfp_field_free(field);
    zfp_stream_close(stream);
    return 1;
fail:
    if (field != NULL)
        zfp_field_free(field);
    if (stream != NULL)
        zfp_stream_close(stream);
    return 0;
}

static int calculate_bound(const input_view *view, uint64_t *bound, double *actual) {
    uint64_t per_column, raw_column, payload, records;
    if (!zfp_bound(view->rows, view->width, view->requested, &per_column, actual))
        return 0;
    raw_column = view->rows * view->width;
    if (per_column < raw_column)
        per_column = raw_column;
    records = (uint64_t)view->columns * TSCB_ZFP_RECORD_HEADER;
    if (per_column > (UINT64_MAX - TSCB_ZFP_FRAME_HEADER -
                      TSCB_ZFP_CHECKSUM_BYTES - records) / view->columns)
        return 0;
    payload = per_column * view->columns;
    *bound = TSCB_ZFP_FRAME_HEADER + records + payload + TSCB_ZFP_CHECKSUM_BYTES;
    return 1;
}

static int compress_column(const uint8_t *data, uint64_t rows, uint8_t width,
                           double requested, uint8_t **encoded, uint64_t *encoded_size,
                           uint16_t *header_bits, double expected_actual) {
    zfp_field *field = NULL;
    zfp_stream *stream = NULL;
    bitstream *bits = NULL;
    size_t maximum, size, header;
    double actual;
    int ok = 0;
    field = zfp_field_1d((void *)data, scalar_type(width), (size_t)rows);
    stream = zfp_stream_open(NULL);
    if (field == NULL || stream == NULL ||
        !zfp_stream_set_execution(stream, zfp_exec_serial))
        goto done;
    actual = zfp_stream_set_accuracy(stream, requested);
    if (memcmp(&actual, &expected_actual, sizeof(actual)) != 0)
        goto done;
    maximum = zfp_stream_maximum_size(stream, field);
    if (maximum == 0)
        goto done;
    *encoded = (uint8_t *)malloc(maximum);
    if (*encoded == NULL)
        goto done;
    bits = stream_open(*encoded, maximum);
    if (bits == NULL)
        goto done;
    zfp_stream_set_bit_stream(stream, bits);
    zfp_stream_rewind(stream);
    header = zfp_write_header(stream, field, ZFP_HEADER_FULL);
    if (header == 0 || header > UINT16_MAX)
        goto done;
    zfp_stream_flush(stream);
    size = zfp_compress(stream, field);
    if (size == 0 || size > maximum)
        goto done;
    *encoded_size = (uint64_t)size;
    *header_bits = (uint16_t)header;
    ok = 1;
done:
    if (bits != NULL)
        stream_close(bits);
    if (field != NULL)
        zfp_field_free(field);
    if (stream != NULL)
        zfp_stream_close(stream);
    if (!ok) {
        free(*encoded);
        *encoded = NULL;
    }
    return ok;
}

static int encode_frame(const input_view *view, writer *out, uint64_t *raw_columns) {
    uint64_t ignored_bound, column;
    double actual;
    if (!calculate_bound(view, &ignored_bound, &actual) ||
        !write_bytes(out, "ZFA1", 4) || !write_u8(out, 1) ||
        !write_u8(out, view->width) || !write_u8(out, 4) || !write_u8(out, 7) ||
        !write_u16(out, view->columns) || !write_u64(out, view->rows) ||
        !write_f64(out, view->requested) || !write_f64(out, actual) ||
        !write_u32(out, view->columns))
        return 0;
    for (column = 0; column < view->columns; ++column) {
        const uint8_t *data = view->payload + column * view->rows * view->width;
        uint64_t raw_size = view->rows * view->width;
        if (view->rows == 0 || exceptional_column(data, view->rows, view->width)) {
            if (!write_u8(out, 1) || !write_u8(out, 0) || !write_u16(out, 0) ||
                !write_u32(out, (uint32_t)view->rows) || !write_u64(out, raw_size) ||
                !write_bytes(out, data, raw_size))
                return 0;
            ++*raw_columns;
        } else {
            uint8_t *encoded = NULL;
            uint64_t encoded_size = 0;
            uint16_t header_bits = 0;
            int ok = compress_column(data, view->rows, view->width, view->requested,
                                     &encoded, &encoded_size, &header_bits, actual);
            if (!ok || !write_u8(out, 0) || !write_u8(out, 0) ||
                !write_u16(out, header_bits) || !write_u32(out, (uint32_t)view->rows) ||
                !write_u64(out, encoded_size) || !write_bytes(out, encoded, encoded_size)) {
                free(encoded);
                return 0;
            }
            free(encoded);
        }
    }
    return write_u64(out, checksum64(out->data, out->offset));
}

static int decompress_column(const uint8_t *encoded, uint64_t encoded_size,
                             uint16_t expected_header_bits, uint8_t *output,
                             uint64_t rows, uint8_t width, double expected_actual) {
    zfp_field *field = NULL;
    zfp_stream *stream = NULL;
    bitstream *bits = NULL;
    uint8_t *padded = NULL;
    size_t header, consumed;
    int ok = 0;
    if (encoded_size > SIZE_MAX - 8)
        return 0;
    padded = (uint8_t *)calloc(1, (size_t)encoded_size + 8);
    if (padded == NULL)
        return 0;
    memcpy(padded, encoded, (size_t)encoded_size);
    field = zfp_field_1d(output, scalar_type(width), (size_t)rows);
    stream = zfp_stream_open(NULL);
    bits = stream_open(padded, (size_t)encoded_size + 8);
    if (field == NULL || stream == NULL || bits == NULL ||
        !zfp_stream_set_execution(stream, zfp_exec_serial))
        goto done;
    zfp_stream_set_bit_stream(stream, bits);
    zfp_stream_rewind(stream);
    header = zfp_read_header(stream, field, ZFP_HEADER_FULL);
    if (header != expected_header_bits || field->type != scalar_type(width) ||
        field->nx != rows || field->ny != 0 || field->nz != 0 || field->nw != 0 ||
        zfp_stream_compression_mode(stream) != zfp_mode_fixed_accuracy ||
        memcmp(&expected_actual, &(double){zfp_stream_accuracy(stream)}, sizeof(double)) != 0)
        goto done;
    zfp_stream_align(stream);
    consumed = zfp_decompress(stream, field);
    if (consumed != encoded_size)
        goto done;
    ok = 1;
done:
    if (bits != NULL)
        stream_close(bits);
    if (field != NULL)
        zfp_field_free(field);
    if (stream != NULL)
        zfp_stream_close(stream);
    free(padded);
    return ok;
}

static int decode_records(reader *in, uint8_t *output, uint8_t width, uint16_t columns,
                          uint64_t rows, double actual) {
    uint64_t column;
    for (column = 0; column < columns; ++column) {
        uint8_t kind, reserved;
        uint16_t header_bits;
        uint32_t logical_count;
        uint64_t payload_size;
        const uint8_t *payload;
        uint8_t *destination = output + column * rows * width;
        if (!read_u8(in, &kind) || !read_u8(in, &reserved) ||
            !read_u16(in, &header_bits) || !read_u32(in, &logical_count) ||
            !read_u64(in, &payload_size) || reserved != 0 || logical_count != rows ||
            !read_bytes(in, &payload, payload_size))
            return 0;
        if (kind == 1) {
            if (header_bits != 0 || payload_size != rows * width)
                return 0;
            if (payload_size != 0)
                memcpy(destination, payload, (size_t)payload_size);
        } else if (kind == 0) {
            if (rows == 0 || header_bits == 0 ||
                !decompress_column(payload, payload_size, header_bits, destination,
                                   rows, width, actual))
                return 0;
        } else {
            return 0;
        }
    }
    return 1;
}

TSCB_NATIVE_TIMING_API

uint32_t tscb_get_abi_version(void) {
    return TSCB_ADAPTER_ABI_V1;
}

tscb_status_v1 tscb_get_manifest_json(const char **json, uint64_t *length) {
    if (json == NULL || length == NULL)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = k_manifest;
    *length = sizeof(k_manifest) - 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(const char *config_json, uint64_t config_length,
                           tscb_codec_handle_v1 **handle) {
    if (config_json == NULL || handle == NULL || config_length != sizeof(k_config) - 1 ||
        memcmp(config_json, k_config, sizeof(k_config) - 1) != 0)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *handle = (tscb_codec_handle_v1 *)calloc(1, sizeof(**handle));
    return *handle != NULL ? TSCB_STATUS_OK_V1 : TSCB_STATUS_CODEC_ERROR_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *handle) {
    free(handle);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *handle, uint32_t reset_mode) {
    int timing;
    if (handle == NULL || reset_mode != 0)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    timing = handle->native_timer.enabled;
    memset(handle, 0, sizeof(*handle));
    return tscb_set_native_timing(handle, timing ? 1u : 0u);
}

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *handle,
                                   const tscb_buffer_v1 *input, uint64_t *bound) {
    input_view view;
    double actual;
    if (handle == NULL || bound == NULL || !parse_input(input, &view))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!calculate_bound(&view, bound, &actual)) {
        set_error(handle, "zfp cannot represent this field or accuracy bound");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *handle, const tscb_buffer_v1 *input,
                             tscb_buffer_v1 *output) {
    input_view view;
    writer out;
    uint64_t bound, raw_columns = 0;
    double actual;
    int ok = 0;
    if (handle == NULL || !parse_input(input, &view) || !valid_buffer(output) ||
        handle->updated || handle->finalized || overlaps(input, output))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!calculate_bound(&view, &bound, &actual))
        return TSCB_STATUS_UNSUPPORTED_V1;
    if (output->capacity_bytes < bound)
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    out.data = (uint8_t *)output->data;
    out.capacity = output->capacity_bytes;
    out.offset = 0;
    TSCB_TIME_CODEC(handle->native_timer, encode_ns,
                    ok = encode_frame(&view, &out, &raw_columns));
    if (!ok) {
        set_error(handle, "zfp frame compression failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = out.offset;
    handle->input_bytes = view.rows * view.columns * view.width;
    handle->stream_bytes = out.offset;
    handle->raw_exception_columns = raw_columns;
    handle->updated = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *handle, tscb_buffer_v1 *output) {
    if (handle == NULL || !valid_buffer(output))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!handle->updated)
        return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (handle->finalized)
        return TSCB_STATUS_CODEC_ERROR_V1;
    output->used_bytes = 0;
    handle->finalized = 1;
    snprintf(handle->accounting_json, sizeof(handle->accounting_json),
             "{\"input_bytes\":%" PRIu64 ",\"zfp_frame_bytes\":%" PRIu64
             ",\"native_input_descriptor_bytes\":24,\"raw_exception_columns\":%" PRIu64
             ",\"finalize_calls\":1}", handle->input_bytes, handle->stream_bytes,
             handle->raw_exception_columns);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *handle, const tscb_buffer_v1 *input,
                               tscb_buffer_v1 *output) {
    reader in;
    const uint8_t *magic;
    uint8_t version, width, mode, header_policy;
    uint16_t columns;
    uint32_t record_count;
    uint64_t rows, expected, stored_checksum;
    double requested, actual;
    int ok = 0;
    if (handle == NULL || !valid_buffer(input) || !valid_buffer(output) ||
        input->used_bytes < TSCB_ZFP_FRAME_HEADER + TSCB_ZFP_CHECKSUM_BYTES ||
        overlaps(input, output))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    stored_checksum = load_u64((const uint8_t *)input->data + input->used_bytes - 8);
    if (checksum64((const uint8_t *)input->data, input->used_bytes - 8) != stored_checksum) {
        set_error(handle, "zfp frame checksum mismatch");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    in.data = (const uint8_t *)input->data;
    in.size = input->used_bytes - 8;
    in.offset = 0;
    if (!read_bytes(&in, &magic, 4) || memcmp(magic, "ZFA1", 4) != 0 ||
        !read_u8(&in, &version) || !read_u8(&in, &width) || !read_u8(&in, &mode) ||
        !read_u8(&in, &header_policy) || !read_u16(&in, &columns) ||
        !read_u64(&in, &rows) || !read_f64(&in, &requested) || !read_f64(&in, &actual) ||
        !read_u32(&in, &record_count) || version != 1 || (width != 4 && width != 8) ||
        mode != 4 || header_policy != 7 || columns == 0 || record_count != columns ||
        rows > TSCB_ZFP_MAX_ELEMENTS || rows > TSCB_ZFP_MAX_ELEMENTS / columns ||
        !isfinite(requested) || requested <= 0 || !isfinite(actual) ||
        actual <= 0 || actual > requested) {
        set_error(handle, "malformed zfp frame header");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    expected = rows * columns * width;
    if (expected > output->capacity_bytes)
        return TSCB_STATUS_DST_TOO_SMALL_V1;
    TSCB_TIME_CODEC(handle->native_timer, decode_ns,
                    ok = decode_records(&in, (uint8_t *)output->data, width,
                                        columns, rows, actual));
    if (!ok || in.offset != in.size) {
        set_error(handle, "malformed zfp column records");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    output->used_bytes = expected;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1 *handle, const char *request_json,
                          uint64_t request_length, char *response_json,
                          uint64_t response_capacity, uint64_t *response_used) {
    (void)request_json;
    (void)request_length;
    (void)response_json;
    (void)response_capacity;
    if (response_used != NULL)
        *response_used = 0;
    set_error(handle, "zfp-accuracy-1d does not support random access");
    return TSCB_STATUS_UNSUPPORTED_V1;
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *handle,
                                        const char **json, uint64_t *length) {
    if (handle == NULL || json == NULL || length == NULL || !handle->finalized)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = handle->accounting_json;
    *length = strlen(*json);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1 *handle,
                                   const char **message, uint64_t *length) {
    if (handle == NULL || message == NULL || length == NULL)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message = handle->last_error;
    *length = strlen(*message);
    return TSCB_STATUS_OK_V1;
}
