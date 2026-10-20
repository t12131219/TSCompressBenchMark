/* Direct zfp full-header stream. No ZFI1/ZFA1 ABI envelope or raw substitute.
 * Exceptional values and empty fields have no supported fixed-accuracy native
 * representation here and return unsupported rather than changing the method.
 */
#include "tsbench_core.h"
#include <ctype.h>
#include <errno.h>

typedef struct {
    size_t count, bytes;
    uint8_t width;
    int decoder;
    double requested;
    char error[192];
} zfp_core;
static _Thread_local char zfp_core_last_error[192];
static int core_zfp_error(zfp_core* context, int code, const char* error) {
    snprintf(zfp_core_last_error, sizeof(zfp_core_last_error), "%s", error);
    if (context) snprintf(context->error, sizeof(context->error), "%s", error);
    return code;
}
/* Parameters are canonical flat JSON from the experiment's resolved method.
 * Parse the requested bound at create; derive the actual mode again in encode.
 */
static int core_zfp_accuracy(const char* json, double* value) {
    const char* at;
    char* end;
    int quoted;
    *value = 0.001;
    if (!json) return 1;
    at = strstr(json, "\"error_bound\"");
    if (!at) return 1;
    at += sizeof("\"error_bound\"") - 1;
    while (isspace((unsigned char)*at)) ++at;
    if (*at++ != ':') return 0;
    while (isspace((unsigned char)*at)) ++at;
    quoted = *at == '"'; if (quoted) ++at;
    errno = 0; *value = strtod(at, &end);
    if (end == at || errno == ERANGE || !isfinite(*value) || *value <= 0) return 0;
    if (quoted && *end++ != '"') return 0;
    while (isspace((unsigned char)*end)) ++end;
    return *end == ',' || *end == '}';
}
uint32_t tsbench_core_version(void) { return 1; }
uint32_t tsbench_core_storage(void) { return 3; }
int tsbench_core_create(const tsbench_core_config* config, int decoder, void** result) {
    zfp_core* context;
    size_t count = 1;
    uint32_t i;
    if (!config || !result) return core_zfp_error(NULL, 1, "null ZFP core configuration");
    *result = NULL;
    if (config->version != 1 || config->rank < 1 || config->rank > 8 || config->order > 1)
        return core_zfp_error(NULL, 1, "invalid ZFP core geometry");
    if (config->dtype != TSCB_DTYPE_F32_LE_V1 && config->dtype != TSCB_DTYPE_F64_LE_V1)
        return core_zfp_error(NULL, 2, "ZFP accuracy requires float32 or float64");
    for (i = 0; i < config->rank; ++i) {
        if (config->shape[i] > TSCB_ZFP_MAX_ELEMENTS ||
            (config->shape[i] && count > TSCB_ZFP_MAX_ELEMENTS / config->shape[i]))
            return core_zfp_error(NULL, 2, "ZFP element limit exceeded");
        count *= (size_t)config->shape[i];
    }
    if (!count) return core_zfp_error(NULL, 2, "ZFP native full header cannot represent an empty 1D field");
    context = (zfp_core*)calloc(1, sizeof(*context));
    if (!context) return core_zfp_error(NULL, 1, "ZFP context allocation failed");
    context->count = count; context->width = config->dtype == TSCB_DTYPE_F32_LE_V1 ? 4 : 8;
    context->bytes = count * context->width; context->decoder = decoder != 0;
    if (!decoder && !core_zfp_accuracy(config->parameters_json, &context->requested)) {
        free(context); return core_zfp_error(NULL, 2, "ZFP accuracy bound is not representable");
    }
    *result = context; return 0;
}
int tsbench_core_destroy(void* context) { free(context); return 0; }
int tsbench_core_validate_input(void* opaque, const uint8_t* input, size_t length) {
    zfp_core* context = (zfp_core*)opaque;
    if (!context || context->decoder || !input || length != context->bytes)
        return core_zfp_error(context, 1, "ZFP validation input mismatch");
    if (exceptional_column(input, context->count, context->width))
        return core_zfp_error(context, 2, "ZFP fixed accuracy excludes nonfinite, subnormal and negative zero inputs");
    return 0;
}
int tsbench_core_bound(void* opaque, const uint8_t* input, size_t length, size_t* bound) {
    zfp_core* context = (zfp_core*)opaque;
    uint64_t maximum;
    double actual;
    if (!context || !bound || !input || length != context->bytes)
        return core_zfp_error(context, 1, "ZFP direct input size mismatch");
    if (!zfp_bound(context->count, context->width, context->requested, &maximum, &actual))
        return core_zfp_error(context, 2, "ZFP cannot represent the requested accuracy");
    *bound = (size_t)maximum; return 0;
}
int tsbench_core_encode(void* opaque, const uint8_t* input, size_t length,
                        uint8_t* output, size_t capacity, tsbench_core_result* result) {
    zfp_core* context = (zfp_core*)opaque;
    zfp_field* field = NULL;
    zfp_stream* stream = NULL;
    bitstream* bits = NULL;
    size_t maximum, header, used;
    double actual;
    int status = 1;
    if (!context || context->decoder || !input || !result || length != context->bytes)
        return core_zfp_error(context, 1, "ZFP direct input mismatch");
    field = zfp_field_1d((void*)input, scalar_type(context->width), context->count);
    stream = zfp_stream_open(NULL);
    if (!field || !stream || !zfp_stream_set_execution(stream, zfp_exec_serial)) goto done;
    actual = zfp_stream_set_accuracy(stream, context->requested);
    if (!isfinite(actual) || actual <= 0 || actual > context->requested) { status = 2; goto done; }
    maximum = zfp_stream_maximum_size(stream, field);
    if (!maximum) goto done;
    if (!output || capacity < maximum) { status = 3; goto done; }
    bits = stream_open(output, capacity); if (!bits) goto done;
    zfp_stream_set_bit_stream(stream, bits); zfp_stream_rewind(stream);
    header = zfp_write_header(stream, field, ZFP_HEADER_FULL); if (!header) goto done;
    zfp_stream_flush(stream);
    used = zfp_compress(stream, field); if (!used || used > capacity) goto done;
    result->data = output; result->size = used; result->capacity = capacity; result->owner = NULL;
    status = 0;
done:
    if (bits) stream_close(bits);
    if (field) zfp_field_free(field);
    if (stream) zfp_stream_close(stream);
    return status ? core_zfp_error(context, status, "ZFP native compression failed or capacity unavailable") : 0;
}
int tsbench_core_decode(void* opaque, const uint8_t* input, size_t length,
                        uint8_t* output, size_t capacity, tsbench_core_result* result) {
    zfp_core* context = (zfp_core*)opaque;
    zfp_field* field = NULL;
    zfp_stream* stream = NULL;
    bitstream* bits = NULL;
    uint8_t* padded = NULL;
    size_t consumed, header_bits;
    int status = 1;
    if (!context || !context->decoder || !input || length < 12 || !result)
        return core_zfp_error(context, 1, "invalid ZFP native frame");
    if (!output || capacity < context->bytes)
        return core_zfp_error(context, 3, "ZFP decoded buffer too small");
    if (length > SIZE_MAX - 16) return core_zfp_error(context, 1, "ZFP frame size overflow");
    /* ZFP bitstream word reads require safe tail storage; this mandatory copy
     * is decode work and never changes the valid raw byte denominator. */
    padded = (uint8_t*)calloc(length + 16, 1); if (!padded) goto done;
    memcpy(padded, input, length);
    field = zfp_field_alloc(); stream = zfp_stream_open(NULL);
    bits = stream_open(padded, length + 16);
    if (!field || !stream || !bits || !zfp_stream_set_execution(stream, zfp_exec_serial)) goto done;
    zfp_stream_set_bit_stream(stream, bits); zfp_stream_rewind(stream);
    header_bits = zfp_read_header(stream, field, ZFP_HEADER_FULL);
    if (!header_bits || header_bits > length * 8 || field->type != scalar_type(context->width) ||
        field->nx != context->count || field->ny || field->nz || field->nw ||
        zfp_stream_compression_mode(stream) != zfp_mode_fixed_accuracy ||
        !isfinite(zfp_stream_accuracy(stream)) || zfp_stream_accuracy(stream) <= 0) goto done;
    zfp_field_set_pointer(field, output); zfp_stream_align(stream);
    consumed = zfp_decompress(stream, field); if (consumed != length) goto done;
    result->data = output; result->size = context->bytes; result->capacity = capacity; result->owner = NULL;
    status = 0;
done:
    if (bits) stream_close(bits);
    if (field) zfp_field_free(field);
    if (stream) zfp_stream_close(stream);
    free(padded);
    return status ? core_zfp_error(context, status, "malformed ZFP native frame") : 0;
}
void tsbench_core_release(tsbench_core_result* result) {
    if (result) { free(result->owner); memset(result, 0, sizeof(*result)); }
}
const char* tsbench_core_error(void* context) {
    return context ? ((zfp_core*)context)->error : zfp_core_last_error;
}
