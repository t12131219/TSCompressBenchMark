#include "zlib.h"

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
    uint64_t state = UINT64_C(20260918);
    size_t case_index;
    for (case_index = 0U; case_index < 100U; ++case_index) {
        uLong size = case_index == 0U ? 0U : (uLong)(next_random(&state) % 131074U);
        Bytef *source = (Bytef *)malloc(size == 0U ? 1U : (size_t)size);
        Bytef *decoded = (Bytef *)malloc(size == 0U ? 1U : (size_t)size);
        uLongf encoded_size = compressBound(size);
        Bytef *compressed = (Bytef *)malloc((size_t)encoded_size);
        uLongf decoded_size = size;
        uLong index;
        if (source == NULL || decoded == NULL || compressed == NULL) return 1;
        for (index = 0U; index < size; ++index) source[index] = (Bytef)next_random(&state);
        if (compress2(compressed, &encoded_size, source, size, (int)(case_index % 10U)) != Z_OK
            || uncompress(decoded, &decoded_size, compressed, encoded_size) != Z_OK
            || decoded_size != size || memcmp(source, decoded, (size_t)size) != 0) {
            fprintf(stderr, "zlib benchmark API roundtrip failed at case %zu\n", case_index);
            return 1;
        }
        free(source);
        free(decoded);
        free(compressed);
    }
    puts("zlib benchmark API roundtrip passed 100 deterministic cases (seed 20260918)");
    return 0;
}
