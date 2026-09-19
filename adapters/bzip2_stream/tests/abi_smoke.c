#include "tscb_adapter_v1.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static tscb_buffer_v1 buffer(void *data, uint64_t capacity, uint64_t used) {
    tscb_buffer_v1 result;
    memset(&result, 0, sizeof(result));
    result.data = data;
    result.capacity_bytes = capacity;
    result.used_bytes = used;
    result.dtype = TSCB_DTYPE_BYTES_V1;
    result.rank = 1;
    result.shape[0] = used;
    result.strides_bytes[0] = 1;
    result.alignment_bytes = 1;
    result.ownership = TSCB_OWNERSHIP_CALLER_V1;
    return result;
}

static int round_trip(size_t size, int level) {
    char config[64];
    tscb_codec_handle_v1 *encode = NULL;
    tscb_codec_handle_v1 *decode = NULL;
    unsigned char *source = (unsigned char *)malloc(size == 0U ? 1U : size);
    unsigned char *source_copy = (unsigned char *)malloc(size == 0U ? 1U : size);
    unsigned char *decoded = (unsigned char *)malloc(size == 0U ? 1U : size);
    unsigned char *compressed = NULL;
    uint64_t bound = 0U;
    int status = 1;
    size_t index;
    int config_length = snprintf(config, sizeof(config),
                                 "{\"compression_level\":%d}", level);
    if (source == NULL || source_copy == NULL || decoded == NULL || config_length < 0) {
        goto cleanup;
    }
    for (index = 0U; index < size; ++index) {
        source[index] = (unsigned char)((index * 131U + size * 17U) & 0xFFU);
    }
    memcpy(source_copy, source, size);
    if (tscb_create(config, (uint64_t)config_length, &encode) != TSCB_STATUS_OK_V1
        || tscb_create(config, (uint64_t)config_length, &decode) != TSCB_STATUS_OK_V1) {
        goto cleanup;
    }
    {
        tscb_buffer_v1 input = buffer(source, size, size);
        tscb_buffer_v1 output;
        tscb_buffer_v1 final_output;
        tscb_buffer_v1 compressed_input;
        tscb_buffer_v1 decoded_output;
        tscb_native_timing_v1 timing = {sizeof(timing), 1U, 0U, 0U};
        uint64_t update_bytes;
        uint64_t stream_bytes;
        if (tscb_set_native_timing(encode, 1U) != TSCB_STATUS_OK_V1
            || tscb_set_native_timing(decode, 1U) != TSCB_STATUS_OK_V1
            || tscb_compress_bound(encode, &input, &bound) != TSCB_STATUS_OK_V1
            || bound != size + size / 100U + 600U) goto cleanup;
        compressed = (unsigned char *)malloc((size_t)bound + 32U);
        if (compressed == NULL) goto cleanup;
        memset(compressed, 0xA5, (size_t)bound + 32U);
        output = buffer(compressed, bound, 0U);
        if (tscb_finalize(encode, &output) != TSCB_STATUS_FINALIZE_REQUIRED_V1) goto cleanup;
        if (tscb_compress(encode, &input, &output) != TSCB_STATUS_OK_V1) goto cleanup;
        if (tscb_compress(encode, &input, &output) == TSCB_STATUS_OK_V1) goto cleanup;
        update_bytes = output.used_bytes;
        final_output = buffer(compressed + update_bytes, bound - update_bytes, 0U);
        if (tscb_finalize(encode, &final_output) != TSCB_STATUS_OK_V1
            || tscb_finalize(encode, &final_output) == TSCB_STATUS_OK_V1
            || tscb_get_native_timing(encode, &timing) != TSCB_STATUS_OK_V1
            || timing.native_encode_wall_ns == 0U) goto cleanup;
        stream_bytes = update_bytes + final_output.used_bytes;
        if (stream_bytes < 14U || compressed[0] != 'B' || compressed[1] != 'Z'
            || compressed[2] != 'h' || compressed[3] != (unsigned char)('0' + level)
            || memcmp(source, source_copy, size) != 0) goto cleanup;
        for (index = (size_t)bound; index < (size_t)bound + 32U; ++index) {
            if (compressed[index] != 0xA5U) goto cleanup;
        }
        compressed_input = buffer(compressed, stream_bytes, stream_bytes);
        decoded_output = buffer(decoded, size, 0U);
        if (tscb_decompress(decode, &compressed_input, &decoded_output) != TSCB_STATUS_OK_V1
            || decoded_output.used_bytes != size || memcmp(source, decoded, size) != 0
            || tscb_get_native_timing(decode, &timing) != TSCB_STATUS_OK_V1
            || timing.native_decode_wall_ns == 0U) goto cleanup;
        compressed_input.capacity_bytes = stream_bytes + 1U;
        compressed_input.used_bytes = stream_bytes + 1U;
        compressed[stream_bytes] = 0U;
        if (tscb_decompress(decode, &compressed_input, &decoded_output)
            == TSCB_STATUS_OK_V1) goto cleanup;
        compressed_input.capacity_bytes = stream_bytes;
        compressed_input.used_bytes = stream_bytes;
        compressed[stream_bytes - 5U] ^= 1U;
        if (tscb_decompress(decode, &compressed_input, &decoded_output)
            == TSCB_STATUS_OK_V1) goto cleanup;
        compressed[stream_bytes - 5U] ^= 1U;
        if (tscb_reset(encode, 0U) != TSCB_STATUS_OK_V1
            || tscb_get_native_timing(encode, &timing) != TSCB_STATUS_OK_V1
            || timing.native_encode_wall_ns != 0U || timing.native_decode_wall_ns != 0U) {
            goto cleanup;
        }
        output = buffer(compressed, stream_bytes - 1U, 0U);
        if (tscb_compress(encode, &input, &output) != TSCB_STATUS_OK_V1) goto cleanup;
        final_output = buffer(compressed + output.used_bytes,
                              stream_bytes - 1U - output.used_bytes, 0U);
        if (tscb_finalize(encode, &final_output) == TSCB_STATUS_OK_V1) goto cleanup;
        if (tscb_reset(encode, 0U) != TSCB_STATUS_OK_V1) goto cleanup;
        output = buffer(compressed, bound, 0U);
        if (tscb_compress(encode, &input, &output) != TSCB_STATUS_OK_V1) goto cleanup;
        final_output = buffer(compressed + output.used_bytes, bound - output.used_bytes, 0U);
        if (tscb_finalize(encode, &final_output) != TSCB_STATUS_OK_V1) goto cleanup;
    }
    status = 0;
cleanup:
    tscb_destroy(encode);
    tscb_destroy(decode);
    free(source);
    free(source_copy);
    free(decoded);
    free(compressed);
    return status;
}

int main(void) {
    static const size_t sizes[] = {
        0U, 1U, 2U, 99980U, 99981U, 99999U, 100000U, 100001U,
        899980U, 899981U, 900000U, 900001U
    };
    size_t index;
    if (tscb_get_abi_version() != TSCB_ADAPTER_ABI_V1) return 1;
    for (index = 0U; index < sizeof(sizes) / sizeof(sizes[0]); ++index) {
        int level = sizes[index] >= 899980U ? 9 : 1;
        if (round_trip(sizes[index], level)) {
            fprintf(stderr, "bzip2 C ABI smoke failed for size %zu level %d\n",
                    sizes[index], level);
            return 1;
        }
    }
    puts("bzip2 C ABI smoke passed empty/small/100k/900k boundaries");
    return 0;
}
