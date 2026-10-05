#include "tscb_adapter_v1.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

tscb_status_v1 tscb_zlib_stream_update(tscb_codec_handle_v1 *,
    const tscb_buffer_v1 *, tscb_buffer_v1 *);
tscb_status_v1 tscb_zlib_stream_finalize(tscb_codec_handle_v1 *, tscb_buffer_v1 *);
tscb_status_v1 tscb_zlib_stream_decoder_reset(tscb_codec_handle_v1 *);
tscb_status_v1 tscb_zlib_stream_decompress_update(tscb_codec_handle_v1 *,
    const tscb_buffer_v1 *, tscb_buffer_v1 *, uint32_t *);
tscb_status_v1 tscb_zlib_stream_decoder_finish(tscb_codec_handle_v1 *);
tscb_status_v1 tscb_zlib_stream_state_bytes(tscb_codec_handle_v1 *, uint64_t *);

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

static int round_trip(size_t size) {
    static const char config[] = "{\"compression_level\":6,\"window_bits\":15}";
    tscb_codec_handle_v1 *encode = NULL;
    tscb_codec_handle_v1 *decode = NULL;
    unsigned char *source = (unsigned char *)malloc(size == 0U ? 1U : size);
    unsigned char *decoded = (unsigned char *)malloc(size == 0U ? 1U : size);
    unsigned char *compressed = NULL;
    uint64_t bound = 0U;
    int status = 1;
    size_t index;
    if (source == NULL || decoded == NULL) goto cleanup;
    for (index = 0U; index < size; ++index) {
        source[index] = (unsigned char)((index * 131U + size) & 0xFFU);
    }
    if (tscb_create(config, sizeof(config) - 1U, &encode) != TSCB_STATUS_OK_V1
        || tscb_create(config, sizeof(config) - 1U, &decode) != TSCB_STATUS_OK_V1) goto cleanup;
    {
        tscb_buffer_v1 input = buffer(source, size, size);
        tscb_buffer_v1 output;
        tscb_buffer_v1 final_output;
        tscb_buffer_v1 compressed_input;
        tscb_buffer_v1 decoded_output;
        tscb_native_timing_v1 timing = {sizeof(timing), 1U, 0U, 0U};
        uint64_t update_bytes;
        if (tscb_set_native_timing(encode, 1U) != TSCB_STATUS_OK_V1
            || tscb_set_native_timing(decode, 1U) != TSCB_STATUS_OK_V1
            || tscb_compress_bound(encode, &input, &bound) != TSCB_STATUS_OK_V1
            || bound < 6U) goto cleanup;
        compressed = (unsigned char *)malloc((size_t)bound);
        if (compressed == NULL) goto cleanup;
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
        compressed_input = buffer(compressed, update_bytes + final_output.used_bytes,
                                  update_bytes + final_output.used_bytes);
        decoded_output = buffer(decoded, size, 0U);
        if (tscb_decompress(decode, &compressed_input, &decoded_output) != TSCB_STATUS_OK_V1
            || decoded_output.used_bytes != size || memcmp(source, decoded, size) != 0
            || tscb_get_native_timing(decode, &timing) != TSCB_STATUS_OK_V1
            || timing.native_decode_wall_ns == 0U) goto cleanup;
        compressed[update_bytes + final_output.used_bytes - 1U] ^= 1U;
        if (tscb_decompress(decode, &compressed_input, &decoded_output)
            == TSCB_STATUS_OK_V1) goto cleanup;
        if (tscb_reset(encode, 0U) != TSCB_STATUS_OK_V1
            || tscb_get_native_timing(encode, &timing) != TSCB_STATUS_OK_V1
            || timing.native_encode_wall_ns != 0U
            || timing.native_decode_wall_ns != 0U) goto cleanup;
        output = buffer(compressed, bound, 0U);
        if (tscb_compress(encode, &input, &output) != TSCB_STATUS_OK_V1) goto cleanup;
        final_output = buffer(compressed + output.used_bytes, 0U, 0U);
        if (tscb_finalize(encode, &final_output) != TSCB_STATUS_DST_TOO_SMALL_V1) goto cleanup;
        if (tscb_reset(encode, 0U) != TSCB_STATUS_OK_V1) goto cleanup;
        output = buffer(compressed, bound, 0U);
        if (tscb_compress(encode, &input, &output) != TSCB_STATUS_OK_V1) goto cleanup;
        final_output = buffer(compressed + output.used_bytes, bound - output.used_bytes, 0U);
        if (tscb_finalize(encode, &final_output) != TSCB_STATUS_OK_V1) goto cleanup;
        compressed_input = buffer(compressed, output.used_bytes + final_output.used_bytes,
                                  output.used_bytes + final_output.used_bytes);
        decoded_output = buffer(decoded, size, 0U);
        if (tscb_decompress(decode, &compressed_input, &decoded_output) != TSCB_STATUS_OK_V1
            || memcmp(source, decoded, size) != 0) goto cleanup;
    }
    status = 0;
cleanup:
    tscb_destroy(encode);
    tscb_destroy(decode);
    free(source);
    free(decoded);
    free(compressed);
    return status;
}

static int streaming_round_trip(size_t size, size_t block_size) {
    static const char config[] = "{\"compression_level\":6,\"window_bits\":15}";
    tscb_codec_handle_v1 *handle = NULL;
    unsigned char *source = (unsigned char *)malloc(size == 0U ? 1U : size);
    unsigned char *decoded = (unsigned char *)malloc(size == 0U ? 1U : size);
    unsigned char *compressed = NULL;
    uint64_t bound = 0U;
    uint64_t state_bytes = 0U;
    size_t source_offset = 0U;
    size_t compressed_size = 0U;
    size_t decoded_size = 0U;
    int status = 1;
    size_t index;
    if (source == NULL || decoded == NULL || block_size == 0U) goto cleanup;
    for (index = 0U; index < size; ++index) source[index] = (unsigned char)(index * 29U + 7U);
    if (tscb_create(config, sizeof(config) - 1U, &handle) != TSCB_STATUS_OK_V1) goto cleanup;
    {
        tscb_buffer_v1 whole = buffer(source, size, size);
        if (tscb_compress_bound(handle, &whole, &bound) != TSCB_STATUS_OK_V1) goto cleanup;
    }
    compressed = (unsigned char *)malloc((size_t)bound);
    if (compressed == NULL) goto cleanup;
    if (size != 0U) {
        tscb_buffer_v1 first = buffer(source, 1U, 1U);
        tscb_buffer_v1 no_space = buffer(compressed, 0U, 0U);
        if (tscb_zlib_stream_update(handle, &first, &no_space)
            != TSCB_STATUS_DST_TOO_SMALL_V1
            || tscb_reset(handle, 0U) != TSCB_STATUS_OK_V1) goto cleanup;
    }
    while (source_offset < size) {
        size_t amount = size - source_offset < block_size ? size - source_offset : block_size;
        tscb_buffer_v1 input = buffer(source + source_offset, amount, amount);
        tscb_buffer_v1 output = buffer(compressed + compressed_size,
                                      bound - compressed_size, 0U);
        if (tscb_zlib_stream_update(handle, &input, &output) != TSCB_STATUS_OK_V1)
            goto cleanup;
        source_offset += amount;
        compressed_size += (size_t)output.used_bytes;
    }
    {
        tscb_buffer_v1 output = buffer(compressed + compressed_size,
                                      bound - compressed_size, 0U);
        if (tscb_zlib_stream_finalize(handle, &output) != TSCB_STATUS_OK_V1
            || tscb_zlib_stream_finalize(handle, &output) == TSCB_STATUS_OK_V1
            || tscb_zlib_stream_state_bytes(handle, &state_bytes) != TSCB_STATUS_OK_V1
            || state_bytes == 0U) goto cleanup;
        compressed_size += (size_t)output.used_bytes;
    }
    if (tscb_zlib_stream_decoder_reset(handle) != TSCB_STATUS_OK_V1) goto cleanup;
    for (index = 0U; index < compressed_size; ++index) {
        tscb_buffer_v1 input = buffer(compressed + index, 1U, 1U);
        tscb_buffer_v1 output = buffer(decoded + decoded_size, size - decoded_size, 0U);
        uint32_t ended = 0U;
        if (tscb_zlib_stream_decompress_update(handle, &input, &output, &ended)
            != TSCB_STATUS_OK_V1) goto cleanup;
        decoded_size += (size_t)output.used_bytes;
        if ((ended != 0U) != (index + 1U == compressed_size)) goto cleanup;
    }
    if (tscb_zlib_stream_decoder_finish(handle) != TSCB_STATUS_OK_V1
        || decoded_size != size || memcmp(source, decoded, size) != 0) goto cleanup;
    if (compressed_size > 1U) {
        tscb_buffer_v1 truncated = buffer(compressed, compressed_size - 1U,
                                          compressed_size - 1U);
        tscb_buffer_v1 output = buffer(decoded, size, 0U);
        uint32_t ended = 0U;
        if (tscb_zlib_stream_decoder_reset(handle) != TSCB_STATUS_OK_V1
            || tscb_zlib_stream_decompress_update(handle, &truncated, &output, &ended)
                != TSCB_STATUS_OK_V1
            || ended != 0U
            || tscb_zlib_stream_decoder_finish(handle) == TSCB_STATUS_OK_V1) goto cleanup;
    }
    status = 0;
cleanup:
    tscb_destroy(handle);
    free(source);
    free(decoded);
    free(compressed);
    return status;
}

int main(void) {
    if (tscb_get_abi_version() != TSCB_ADAPTER_ABI_V1 || round_trip(0U)
        || round_trip(1U) || round_trip(2U) || round_trip(65535U)
        || round_trip(65536U) || round_trip(65537U) || round_trip(131073U)
        || streaming_round_trip(0U, 8U) || streaming_round_trip(1U, 8U)
        || streaming_round_trip(2U, 1U) || streaming_round_trip(65535U, 8192U)
        || streaming_round_trip(65536U, 8192U)
        || streaming_round_trip(65537U, 8192U)) {
        fputs("DEFLATE zlib C ABI smoke failed\n", stderr);
        return 1;
    }
    puts("DEFLATE zlib C ABI smoke passed");
    return 0;
}
