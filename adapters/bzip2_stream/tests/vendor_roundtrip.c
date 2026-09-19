#include "bzlib.h"

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
    uint64_t state = UINT64_C(20260919);
    size_t case_index;
    for (case_index = 0U; case_index < 36U; ++case_index) {
        unsigned int size = case_index == 0U ? 0U
            : (unsigned int)(next_random(&state) % 220001U);
        unsigned char *source = (unsigned char *)malloc(size == 0U ? 1U : size);
        unsigned char *decoded = (unsigned char *)malloc(size == 0U ? 1U : size);
        unsigned int encoded_size = size + size / 100U + 600U;
        unsigned char *compressed = (unsigned char *)malloc(encoded_size);
        unsigned int decoded_size = size;
        unsigned int index;
        int level = (int)(case_index % 9U) + 1;
        if (source == NULL || decoded == NULL || compressed == NULL) return 1;
        for (index = 0U; index < size; ++index) {
            source[index] = (unsigned char)next_random(&state);
        }
        if (BZ2_bzBuffToBuffCompress((char *)compressed, &encoded_size,
                                     (char *)source, size, level, 0, 0) != BZ_OK
            || BZ2_bzBuffToBuffDecompress((char *)decoded, &decoded_size,
                                          (char *)compressed, encoded_size, 0, 0) != BZ_OK
            || decoded_size != size || memcmp(source, decoded, size) != 0) {
            fprintf(stderr, "libbz2 benchmark API roundtrip failed at case %zu\n", case_index);
            return 1;
        }
        free(source);
        free(decoded);
        free(compressed);
    }
    puts("libbz2 benchmark API roundtrip passed 36 deterministic cases (seed 20260919)");
    return 0;
}
