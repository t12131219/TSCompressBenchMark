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

static int round_trip(size_t size) {
    static const char config[] =
        "{\"block_checksum\":false,\"block_mode\":0,\"block_size_id\":4,"
        "\"compression_level\":0,\"content_checksum\":true}";
    tscb_codec_handle_v1 *encode = NULL;
    tscb_codec_handle_v1 *decode = NULL;
    unsigned char *source = (unsigned char *)malloc(size == 0 ? 1 : size);
    unsigned char *compressed = NULL;
    unsigned char *reconstructed = (unsigned char *)malloc(size == 0 ? 1 : size);
    tscb_buffer_v1 input;
    tscb_buffer_v1 output;
    tscb_buffer_v1 final_output;
    tscb_buffer_v1 compressed_input;
    tscb_buffer_v1 decoded_output;
    uint64_t bound = 0;
    size_t index;
    int result = 1;

    if (source == NULL || reconstructed == NULL) {
        goto cleanup;
    }
    for (index = 0; index < size; ++index) {
        source[index] = (unsigned char)((index * 131U + size) & 0xFFU);
    }
    if (tscb_create(config, sizeof(config) - 1U, &encode) != TSCB_STATUS_OK_V1
        || tscb_create(config, sizeof(config) - 1U, &decode) != TSCB_STATUS_OK_V1) {
        goto cleanup;
    }
    input = buffer(source, (uint64_t)size, (uint64_t)size);
    if (tscb_compress_bound(encode, &input, &bound) != TSCB_STATUS_OK_V1 || bound == 0) {
        goto cleanup;
    }
    compressed = (unsigned char *)malloc((size_t)bound);
    if (compressed == NULL) {
        goto cleanup;
    }
    output = buffer(compressed, bound, 0);
    if (tscb_compress(encode, &input, &output) != TSCB_STATUS_OK_V1) {
        goto cleanup;
    }
    final_output = buffer(
        compressed + output.used_bytes,
        bound - output.used_bytes,
        0
    );
    if (tscb_finalize(encode, &final_output) != TSCB_STATUS_OK_V1) {
        goto cleanup;
    }
    if (tscb_finalize(encode, &final_output) == TSCB_STATUS_OK_V1) {
        goto cleanup;
    }
    compressed_input = buffer(
        compressed,
        output.used_bytes + final_output.used_bytes,
        output.used_bytes + final_output.used_bytes
    );
    decoded_output = buffer(reconstructed, (uint64_t)size, 0);
    if (tscb_decompress(decode, &compressed_input, &decoded_output) != TSCB_STATUS_OK_V1
        || decoded_output.used_bytes != (uint64_t)size
        || memcmp(source, reconstructed, size) != 0) {
        goto cleanup;
    }
    result = 0;

cleanup:
    (void)tscb_destroy(encode);
    (void)tscb_destroy(decode);
    free(source);
    free(compressed);
    free(reconstructed);
    return result;
}

int main(void) {
    if (tscb_get_abi_version() != TSCB_ADAPTER_ABI_V1) {
        return 1;
    }
    if (round_trip(0) || round_trip(1) || round_trip(2) || round_trip(65535)
        || round_trip(65536) || round_trip(65537) || round_trip(131073)) {
        fputs("LZ4 C ABI smoke failed\n", stderr);
        return 1;
    }
    puts("LZ4 C ABI smoke passed");
    return 0;
}
