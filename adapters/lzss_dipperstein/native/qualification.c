#include "tscb_adapter_v1.h"

#include <assert.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char CONFIG[] =
    "{\"initial_byte\":32,\"length_bits\":4,"
    "\"match_finder\":\"BINARY_TREE\",\"offset_bits\":12}";

static void fill(unsigned char *data, size_t length, unsigned pattern) {
    size_t index;
    for (index = 0U; index < length; ++index) {
        if (pattern == 0U) data[index] = 0U;
        else if (pattern == 1U) data[index] = (unsigned char)(index % 7U);
        else data[index] = (unsigned char)((index * 67U) ^ (index >> 5U));
    }
}

static void qualify_case(size_t length, unsigned pattern) {
    tscb_codec_handle_v1 *handle = NULL;
    tscb_buffer_v1 input = {0};
    tscb_buffer_v1 compressed = {0};
    tscb_buffer_v1 decoded = {0};
    tscb_buffer_v1 final = {0};
    uint64_t bound = 0U;
    unsigned char *source = malloc(length + 1U);
    unsigned char *encoded;
    unsigned char *roundtrip = malloc(length + 1U);
    assert(source != NULL && roundtrip != NULL);
    fill(source, length, pattern);
    source[length] = 0xA5U;
    roundtrip[length] = 0x5AU;

    assert(tscb_create(CONFIG, sizeof(CONFIG) - 1U, &handle) == TSCB_STATUS_OK_V1);
    input.data = source;
    input.capacity_bytes = input.used_bytes = length;
    input.dtype = TSCB_DTYPE_BYTES_V1;
    input.rank = 1U;
    assert(tscb_compress_bound(handle, &input, &bound) == TSCB_STATUS_OK_V1);
    assert(bound == length + (length + 7U) / 8U);
    encoded = malloc((size_t)bound + 2U);
    assert(encoded != NULL);
    memset(encoded, 0xC7, (size_t)bound + 2U);
    compressed.data = encoded;
    compressed.capacity_bytes = bound;
    compressed.dtype = TSCB_DTYPE_BYTES_V1;
    compressed.rank = 1U;

    if (bound != 0U) {
        compressed.capacity_bytes = bound - 1U;
        assert(tscb_compress(handle, &input, &compressed) == TSCB_STATUS_DST_TOO_SMALL_V1);
        assert(compressed.used_bytes == 0U);
        compressed.capacity_bytes = bound;
    }
    assert(tscb_compress(handle, &input, &compressed) == TSCB_STATUS_OK_V1);
    assert(compressed.used_bytes <= bound);
    assert(encoded[bound] == 0xC7U && encoded[bound + 1U] == 0xC7U);
    assert(source[length] == 0xA5U);

    decoded.data = roundtrip;
    decoded.capacity_bytes = length;
    decoded.dtype = TSCB_DTYPE_BYTES_V1;
    decoded.rank = 1U;
    input.data = encoded;
    input.capacity_bytes = input.used_bytes = compressed.used_bytes;
    {
        tscb_status_v1 status = tscb_decompress(handle, &input, &decoded);
        if (status != TSCB_STATUS_OK_V1) {
            fprintf(stderr, "decode failure: length=%zu pattern=%u encoded=%" PRIu64
                " status=%u\n", length, pattern, compressed.used_bytes, (unsigned)status);
        }
        assert(status == TSCB_STATUS_OK_V1);
    }
    assert(decoded.used_bytes == length);
    assert(memcmp(source, roundtrip, length) == 0);
    assert(roundtrip[length] == 0x5AU);

    assert(tscb_finalize(handle, &final) == TSCB_STATUS_OK_V1);
    assert(final.used_bytes == 0U);
    assert(tscb_finalize(handle, &final) == TSCB_STATUS_CODEC_ERROR_V1);
    assert(tscb_reset(handle, 0U) == TSCB_STATUS_OK_V1);
    assert(tscb_finalize(handle, &final) == TSCB_STATUS_FINALIZE_REQUIRED_V1);
    assert(tscb_destroy(handle) == TSCB_STATUS_OK_V1);
    free(encoded);
    free(roundtrip);
    free(source);
}

static void qualify_hostile_streams(void) {
    static unsigned char truncated[] = {0x80U};
    static unsigned char trailing[] = {0x80U, 0x00U, 0x00U};
    static unsigned char nonzero_padding[] = {0x80U, 0x01U};
    unsigned char output_byte = 0U;
    tscb_codec_handle_v1 *handle = NULL;
    tscb_buffer_v1 input = {0};
    tscb_buffer_v1 output = {0};
    assert(tscb_create(CONFIG, sizeof(CONFIG) - 1U, &handle) == TSCB_STATUS_OK_V1);
    input.dtype = TSCB_DTYPE_BYTES_V1;
    input.rank = 1U;
    output.data = &output_byte;
    output.capacity_bytes = 1U;
    output.dtype = TSCB_DTYPE_BYTES_V1;
    output.rank = 1U;
    input.data = truncated;
    input.capacity_bytes = input.used_bytes = sizeof(truncated);
    assert(tscb_decompress(handle, &input, &output) == TSCB_STATUS_CODEC_ERROR_V1);
    input.data = trailing;
    input.capacity_bytes = input.used_bytes = sizeof(trailing);
    assert(tscb_decompress(handle, &input, &output) == TSCB_STATUS_CODEC_ERROR_V1);
    input.data = nonzero_padding;
    input.capacity_bytes = input.used_bytes = sizeof(nonzero_padding);
    assert(tscb_decompress(handle, &input, &output) == TSCB_STATUS_CODEC_ERROR_V1);
    assert(tscb_destroy(handle) == TSCB_STATUS_OK_V1);
}

int main(void) {
    static const size_t sizes[] = {
        0U, 1U, 2U, 17U, 18U, 19U, 63U, 64U, 65U,
        4095U, 4096U, 4097U, 8191U, 8192U, 8193U, 65537U
    };
    size_t index;
    unsigned pattern;
    for (pattern = 0U; pattern < 3U; ++pattern) {
        for (index = 0U; index < sizeof(sizes) / sizeof(sizes[0]); ++index) {
            qualify_case(sizes[index], pattern);
        }
    }
    qualify_hostile_streams();
    puts("lzss-dipperstein-c qualification passed: 48 roundtrips + hostile streams");
    return 0;
}
