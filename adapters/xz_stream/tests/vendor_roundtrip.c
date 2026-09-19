#include "lzma.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t state = 20260918U;
static uint32_t next_random(void) {
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

int main(void) {
    unsigned int iteration;
    for (iteration = 0U; iteration < 100U; ++iteration) {
        size_t size = iteration < 3U ? iteration : next_random() % 131074U;
        size_t bound = lzma_stream_buffer_bound(size);
        uint8_t *input = (uint8_t *)malloc(size == 0U ? 1U : size);
        uint8_t *decoded = (uint8_t *)malloc(size == 0U ? 1U : size);
        uint8_t *compressed = (uint8_t *)malloc(bound);
        size_t index, encoded_size = 0U, input_pos = 0U, output_pos = 0U;
        uint64_t memory_limit = UINT64_C(1073741824);
        int failed = input == NULL || decoded == NULL || compressed == NULL || bound == 0U;
        if (!failed) {
            for (index = 0U; index < size; ++index) input[index] = (uint8_t)next_random();
            failed = lzma_easy_buffer_encode(iteration % 10U, LZMA_CHECK_NONE, NULL,
                input, size, compressed, &encoded_size, bound) != LZMA_OK;
        }
        if (!failed) {
            failed = lzma_stream_buffer_decode(&memory_limit, 0U, NULL,
                compressed, &input_pos, encoded_size, decoded, &output_pos, size) != LZMA_OK
                || input_pos != encoded_size || output_pos != size
                || memcmp(input, decoded, size) != 0;
        }
        free(input); free(decoded); free(compressed);
        if (failed) {
            fprintf(stderr, "XZ vendored API failed case %u\n", iteration);
            return 1;
        }
    }
    puts("XZ vendored API passed 100 deterministic cases (seed 20260918)");
    return 0;
}
