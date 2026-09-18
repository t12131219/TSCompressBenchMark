#include "brotli/decode.h"
#include "brotli/encode.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint64_t next_random(uint64_t *state) {
    uint64_t value = *state;
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    *state = value;
    return value;
}

int main(void) {
    uint64_t state = UINT64_C(20260917);
    size_t case_index;
    for (case_index = 0U; case_index < 100U; ++case_index) {
        size_t size = case_index == 0U ? 0U : (size_t)(next_random(&state) % 131074U);
        uint8_t *source = (uint8_t *)malloc(size == 0U ? 1U : size);
        uint8_t *decoded = (uint8_t *)malloc(size == 0U ? 1U : size);
        size_t bound = BrotliEncoderMaxCompressedSize(size);
        uint8_t *compressed = (uint8_t *)malloc(bound == 0U ? 1U : bound);
        size_t encoded_size = bound;
        size_t decoded_size = size;
        size_t index;
        if (source == NULL || decoded == NULL || compressed == NULL || bound == 0U) return 1;
        for (index = 0U; index < size; ++index) {
            source[index] = (uint8_t)next_random(&state);
        }
        if (!BrotliEncoderCompress((int)(case_index % 12U),
                                   (int)(10U + case_index % 15U),
                                   BROTLI_MODE_GENERIC, size, source,
                                   &encoded_size, compressed)
            || BrotliDecoderDecompress(encoded_size, compressed, &decoded_size, decoded)
                != BROTLI_DECODER_RESULT_SUCCESS
            || decoded_size != size || memcmp(source, decoded, size) != 0) {
            fprintf(stderr, "Brotli vendor roundtrip failed at case %zu\n", case_index);
            return 1;
        }
        free(source);
        free(decoded);
        free(compressed);
    }
    puts("Brotli vendor API roundtrip passed 100 deterministic cases (seed 20260917)");
    return 0;
}
