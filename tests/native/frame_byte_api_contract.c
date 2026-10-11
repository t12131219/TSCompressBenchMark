#include "tscb_adapter_v1.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern tscb_status_v1 tscb_stream_decoder_reset(tscb_codec_handle_v1 *);
extern tscb_status_v1 tscb_stream_decompress_update(tscb_codec_handle_v1 *,
    const tscb_buffer_v1 *, tscb_buffer_v1 *, uint32_t *);
extern tscb_status_v1 tscb_stream_decoder_finish(tscb_codec_handle_v1 *);
extern tscb_status_v1 tscb_stream_update(tscb_codec_handle_v1 *,
    const tscb_buffer_v1 *, tscb_buffer_v1 *);
extern tscb_status_v1 tscb_stream_finalize(tscb_codec_handle_v1 *, tscb_buffer_v1 *);

static tscb_buffer_v1 buffer(void *data, uint64_t capacity, uint64_t used) {
    tscb_buffer_v1 result = {0};
    result.data = data;
    result.capacity_bytes = capacity;
    result.used_bytes = used;
    result.dtype = TSCB_DTYPE_BYTES_V1;
    result.rank = 1;
    result.shape[0] = used;
    result.strides_bytes[0] = 1;
    result.alignment_bytes = 1;
    return result;
}

int main(void) {
    uint8_t source[128], decoded[128], canary[128];
    tscb_codec_handle_v1 *encoder = NULL, *decoder = NULL;
    tscb_buffer_v1 input, output, tail, wire, target;
    uint64_t bound = 0;
    uint32_t stream_end = 77;
    unsigned mutation, index;
    for (index = 0; index < sizeof(source); ++index) source[index] = (uint8_t)index;
    memset(canary, 0xA5, sizeof(canary));
    assert(tscb_create("{}", 2, &encoder) == TSCB_STATUS_OK_V1);
    assert(tscb_create("{}", 2, &decoder) == TSCB_STATUS_OK_V1);
    input = buffer(source, sizeof(source), sizeof(source));
    assert(tscb_compress_bound(encoder, &input, &bound) == TSCB_STATUS_OK_V1);
    output = buffer(malloc((size_t)bound), bound, 0);
    assert(output.data != NULL);
    assert(tscb_compress(encoder, &input, &output) == TSCB_STATUS_OK_V1);
    tail = buffer((uint8_t *)output.data + output.used_bytes, bound - output.used_bytes, 0);
    assert(tscb_finalize(encoder, &tail) == TSCB_STATUS_OK_V1);
    wire = buffer(output.data, output.used_bytes + tail.used_bytes,
        output.used_bytes + tail.used_bytes);

    for (mutation = 0; mutation < 5; ++mutation) {
        uint64_t original_used;
        memcpy(decoded, canary, sizeof(decoded));
        target = buffer(decoded, sizeof(decoded), 0);
        if (mutation == 0) target.used_bytes = sizeof(decoded) + 1;
        if (mutation == 1) target.dtype = TSCB_DTYPE_INVALID_V1;
        if (mutation == 2) target.rank = 0;
        if (mutation == 3) target.capacity_bytes = UINT64_MAX;
        if (mutation == 4) target.data = NULL;
        original_used = target.used_bytes;
        assert(tscb_compress(encoder, &input, &target) == TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(tscb_finalize(encoder, &target) == TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(tscb_stream_update(encoder, &input, &target) == TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(tscb_stream_finalize(encoder, &target) == TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(target.used_bytes == original_used);
        assert(memcmp(decoded, canary, sizeof(decoded)) == 0);
        assert(tscb_decompress(decoder, &wire, &target) == TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(target.used_bytes == original_used);
        assert(memcmp(decoded, canary, sizeof(decoded)) == 0);
        assert(tscb_stream_decoder_reset(decoder) == TSCB_STATUS_OK_V1);
        assert(tscb_stream_decompress_update(decoder, &wire, &target, &stream_end)
            == TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(target.used_bytes == original_used && stream_end == 77);
        assert(memcmp(decoded, canary, sizeof(decoded)) == 0);
    }

    target = buffer(decoded, sizeof(decoded), 0);
    assert(tscb_decompress(decoder, &wire, &target) == TSCB_STATUS_OK_V1);
    assert(target.used_bytes == sizeof(source) && memcmp(decoded, source, sizeof(source)) == 0);
    assert(tscb_stream_decoder_reset(decoder) == TSCB_STATUS_OK_V1);
    target.used_bytes = 0;
    assert(tscb_stream_decompress_update(decoder, &wire, &target, &stream_end)
        == TSCB_STATUS_OK_V1);
    assert(stream_end == 1 && target.used_bytes == sizeof(source));
    stream_end = 77;
    assert(tscb_stream_decompress_update(decoder, &wire, &target, &stream_end)
        == TSCB_STATUS_CODEC_ERROR_V1);
    assert(stream_end == 77 && target.used_bytes == sizeof(source));
    assert(tscb_stream_decoder_finish(decoder) == TSCB_STATUS_OK_V1);
    memcpy(decoded, canary, sizeof(decoded));
    target.used_bytes = 0;
    stream_end = 77;
    assert(tscb_stream_decompress_update(decoder, &wire, &target, &stream_end)
        == TSCB_STATUS_CODEC_ERROR_V1);
    assert(target.used_bytes == 0 && stream_end == 77);
    assert(memcmp(decoded, canary, sizeof(decoded)) == 0);
    assert(tscb_stream_decoder_reset(decoder) == TSCB_STATUS_OK_V1);
    assert(tscb_stream_decoder_finish(decoder) == TSCB_STATUS_CODEC_ERROR_V1);
    assert(tscb_stream_decompress_update(decoder, &wire, &target, &stream_end)
        == TSCB_STATUS_OK_V1);
    assert(memcmp(decoded, source, sizeof(source)) == 0);
    assert(tscb_stream_decoder_finish(decoder) == TSCB_STATUS_OK_V1);
    assert(tscb_destroy(encoder) == TSCB_STATUS_OK_V1);
    assert(tscb_destroy(decoder) == TSCB_STATUS_OK_V1);
    free(output.data);
    puts("frame byte API contract: 30 descriptor rejects, EOF/reset recovery PASS");
    return 0;
}
