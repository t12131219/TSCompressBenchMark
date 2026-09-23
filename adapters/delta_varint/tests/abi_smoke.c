#include "tscb_adapter_v1.h"

#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static tscb_buffer_v1 buffer(void *data, uint64_t capacity, uint64_t used,
                             uint32_t dtype) {
    tscb_buffer_v1 result;
    memset(&result, 0, sizeof(result));
    result.data = data;
    result.capacity_bytes = capacity;
    result.used_bytes = used;
    result.dtype = dtype;
    result.rank = 1U;
    result.shape[0] = dtype == TSCB_DTYPE_I64_LE_V1
        ? capacity / sizeof(int64_t) : capacity;
    result.strides_bytes[0] = dtype == TSCB_DTYPE_I64_LE_V1
        ? (int64_t)sizeof(int64_t) : 1;
    result.alignment_bytes = 1U;
    result.ownership = TSCB_OWNERSHIP_CALLER_V1;
    return result;
}

static int round_trip(const int64_t *values, size_t count) {
    static const char config[] = "{\"isa\":\"SCALAR\"}";
    tscb_codec_handle_v1 *encoder = NULL;
    tscb_codec_handle_v1 *decoder = NULL;
    int64_t *decoded = (int64_t *)calloc(count == 0U ? 1U : count, sizeof(int64_t));
    uint8_t *encoded = NULL;
    uint64_t bound = 0U;
    int status = 1;
    if (decoded == NULL
        || tscb_create(config, sizeof(config) - 1U, &encoder) != TSCB_STATUS_OK_V1
        || tscb_create(config, sizeof(config) - 1U, &decoder) != TSCB_STATUS_OK_V1) {
        goto cleanup;
    }
    {
        tscb_buffer_v1 input = buffer((void *)values, count * sizeof(int64_t),
                                      count * sizeof(int64_t), TSCB_DTYPE_I64_LE_V1);
        tscb_buffer_v1 output;
        tscb_buffer_v1 final_output;
        tscb_buffer_v1 encoded_input;
        tscb_buffer_v1 decoded_output;
        if (tscb_compress_bound(encoder, &input, &bound) != TSCB_STATUS_OK_V1
            || bound != (count == 0U ? 0U : 9U * count)) goto cleanup;
        encoded = (uint8_t *)malloc((size_t)bound + 16U);
        if (encoded == NULL) goto cleanup;
        memset(encoded, 0xA5, (size_t)bound + 16U);
        output = buffer(encoded, bound, 0U, TSCB_DTYPE_BYTES_V1);
        if (tscb_finalize(encoder, &output) != TSCB_STATUS_FINALIZE_REQUIRED_V1
            || tscb_set_native_timing(encoder, 1U) != TSCB_STATUS_OK_V1
            || tscb_set_native_timing(decoder, 1U) != TSCB_STATUS_OK_V1
            || tscb_compress(encoder, &input, &output) != TSCB_STATUS_OK_V1
            || output.used_bytes > bound) goto cleanup;
        final_output = buffer(encoded + output.used_bytes, bound - output.used_bytes,
                              0U, TSCB_DTYPE_BYTES_V1);
        if (tscb_finalize(encoder, &final_output) != TSCB_STATUS_OK_V1
            || final_output.used_bytes != 0U
            || tscb_finalize(encoder, &final_output) == TSCB_STATUS_OK_V1) goto cleanup;
        {
            size_t index;
            for (index = (size_t)bound; index < (size_t)bound + 16U; ++index) {
                if (encoded[index] != 0xA5U) goto cleanup;
            }
        }
        encoded_input = buffer(encoded, output.used_bytes, output.used_bytes,
                               TSCB_DTYPE_BYTES_V1);
        decoded_output = buffer(decoded, count * sizeof(int64_t), 0U,
                                TSCB_DTYPE_I64_LE_V1);
        if (tscb_decompress(decoder, &encoded_input, &decoded_output) != TSCB_STATUS_OK_V1
            || decoded_output.used_bytes != count * sizeof(int64_t)
            || (count != 0U
                && memcmp(values, decoded, count * sizeof(int64_t)) != 0)) goto cleanup;
        if (count != 0U) {
            encoded_input.used_bytes -= 1U;
            if (tscb_decompress(decoder, &encoded_input, &decoded_output)
                == TSCB_STATUS_OK_V1) goto cleanup;
            encoded_input.used_bytes += 1U;
            encoded[0] = 9U;
            if (tscb_decompress(decoder, &encoded_input, &decoded_output)
                == TSCB_STATUS_OK_V1) goto cleanup;
        }
        if (tscb_reset(encoder, 0U) != TSCB_STATUS_OK_V1) goto cleanup;
        if (bound != 0U) {
            output = buffer(encoded, bound - 1U, 0U, TSCB_DTYPE_BYTES_V1);
            if (tscb_compress(encoder, &input, &output)
                != TSCB_STATUS_DST_TOO_SMALL_V1) goto cleanup;
        }
    }
    status = 0;
cleanup:
    tscb_destroy(encoder);
    tscb_destroy(decoder);
    free(decoded);
    free(encoded);
    return status;
}

int main(void) {
    static const int64_t one[] = {INT64_MIN};
    static const int64_t two[] = {INT64_MAX, INT64_MIN};
    static const int64_t mixed[] = {
        0, 1, 1, -1, 1700000000, 1699999999, INT64_MAX, INT64_MIN
    };
    if (tscb_get_abi_version() != TSCB_ADAPTER_ABI_V1
        || round_trip(NULL, 0U)
        || round_trip(one, sizeof(one) / sizeof(one[0]))
        || round_trip(two, sizeof(two) / sizeof(two[0]))
        || round_trip(mixed, sizeof(mixed) / sizeof(mixed[0]))) {
        fputs("delta-varint C ABI smoke failed\n", stderr);
        return 1;
    }
    puts("delta-varint C ABI smoke passed empty/extreme/modular-delta cases");
    return 0;
}
