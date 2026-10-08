#define _GNU_SOURCE
#include "bitpacking.h"
#include "util.h"
#include <assert.h>
#include <sys/mman.h>
#include <unistd.h>

typedef void (*pack_fn)(const uint32_t *, uint32_t, uint32_t, uint8_t *);
typedef void (*unpack_fn)(const uint8_t *, uint32_t, uint32_t, uint32_t *);
static const pack_fn packs[] = {pack32, turbopack32, scpack32, bmipack32, pack32};
static const unpack_fn unpacks[] = {
    unpack32, turbounpack32, scunpack32, bmiunpack32, horizontalunpack32
};
static const char *names[] = {"PACK32", "TURBO", "SC", "BMI2", "HORIZONTAL"};
static const uint32_t lengths[] = {
    0, 1, 2, 7, 15, 16, 17, 31, 32, 33, 63, 64, 65, 127, 128, 129, 255, 256, 257,
    511, 512, 513, 8193
};

static uint32_t random32(uint64_t *state) {
    *state ^= *state >> 12;
    *state ^= *state << 25;
    *state ^= *state >> 27;
    return (uint32_t)((*state * UINT64_C(2685821657736338717)) >> 32);
}

/* Independent linear little-endian bit grammar; do not call source helpers. */
static void oracle(const uint32_t *input, uint32_t n, uint32_t b, uint8_t *output) {
    const size_t bytes = ((size_t)n * b + 7) / 8;
    memset(output, 0, bytes);
    for (uint32_t i = 0; i < n; ++i) {
        for (uint32_t k = 0; k < b; ++k) {
            const size_t bit = (size_t)i * b + k;
            output[bit / 8] |= (uint8_t)(((input[i] >> k) & 1U) << (bit % 8));
        }
    }
}

static int matrix(void) {
    uint64_t cases = 0, failures = 0, state = UINT64_C(0x4b177af039264201);
    for (uint32_t api = 0; api < 5; ++api) {
        uint64_t api_failures = 0;
        for (uint32_t b = 0; b <= 32; ++b) {
            const uint32_t mask = (uint32_t)((UINT64_C(1) << b) - 1);
            for (size_t li = 0; li < sizeof(lengths) / sizeof(lengths[0]); ++li) {
                const uint32_t n = lengths[li];
                const size_t capacity = ((size_t)n + 256) * 4;
                uint32_t *input = calloc((size_t)n + 256, 4);
                uint32_t *decoded = calloc((size_t)n + 256, 4);
                uint8_t *packed = calloc(capacity, 1), *reference = calloc(capacity, 1);
                assert(input && decoded && packed && reference);
                for (uint32_t pattern = 0; pattern < 5; ++pattern) {
                    for (uint32_t i = 0; i < n; ++i) {
                        input[i] = pattern == 0 ? 0 : pattern == 1 ? mask :
                            pattern == 2 ? (i & mask) :
                            pattern == 3 ? ((i & 1U) ? mask : 0) : (random32(&state) & mask);
                    }
                    memset(packed, 0, capacity);
                    memset(decoded, 0xa5, capacity);
                    oracle(input, n, b, reference);
                    packs[api](input, n, b, packed);
                    const size_t bytes = ((size_t)n * b + 7) / 8;
                    if (memcmp(packed, reference, bytes)) {
                        if (api_failures < 6)
                            fprintf(stderr, "WIRE_FAIL %s %u %u %u\n", names[api], b, n, pattern);
                        ++api_failures;
                    }
                    /* Keep exactly the serialized bytes; all internal readable padding is zero. */
                    memset(packed + bytes, 0, capacity - bytes);
                    unpacks[api](packed, n, b, decoded);
                    if (memcmp(input, decoded, (size_t)n * 4)) {
                        if (api_failures < 6)
                            fprintf(stderr, "INVERSE_FAIL %s %u %u %u\n", names[api], b, n, pattern);
                        ++api_failures;
                    }
                    ++cases;
                }
                free(reference); free(packed); free(decoded); free(input);
            }
        }
        failures += api_failures;
        printf("API_DONE %s widths=33 lengths=23 patterns=5 cases=3795 failures=%" PRIu64 "\n",
               names[api], api_failures);
        fflush(stdout);
    }
    printf("MATRIX_DONE cases=%" PRIu64 " failures=%" PRIu64
           " widths=33 lengths=23 patterns=5 apis=5\n", cases, failures);
    return failures ? 12 : 0;
}

static void *guarded_tail(size_t size) {
    const size_t page = (size_t)sysconf(_SC_PAGESIZE);
    assert(size <= page);
    uint8_t *mapping = mmap(NULL, page * 2, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(mapping != MAP_FAILED);
    assert(mprotect(mapping + page, page, PROT_NONE) == 0);
    return mapping + page - size;
}

static int unsafe_probe(uint32_t api, const char *mode) {
    uint32_t *input = calloc(256, 4), *decoded = calloc(256, 4);
    uint8_t *packed = calloc(2048, 1);
    assert(input && decoded && packed && api < 5);
    input[0] = 1;
    fprintf(stderr, "RAW_UNSAFE_PROBE api=%s mode=%s\n", names[api], mode);
    fflush(stderr);
    if (!strcmp(mode, "exact-input")) {
        uint32_t *short_input = guarded_tail(4);
        short_input[0] = 1;
        packs[api](short_input, 1, 1, packed);
    } else if (!strcmp(mode, "exact-packed-output")) {
        packs[api](input, 1, 1, guarded_tail(1));
    } else if (!strcmp(mode, "exact-decoded-output")) {
        packs[api](input, 1, 1, packed);
        unpacks[api](packed, 1, 1, guarded_tail(4));
    } else if (!strcmp(mode, "exact-packed-input")) {
        uint8_t *short_input = guarded_tail(1);
        short_input[0] = 1;
        unpacks[api](short_input, 1, 1, decoded);
    } else if (!strcmp(mode, "invalid-width")) {
        packs[api](input, 1, 33, packed);
    } else if (!strcmp(mode, "odd-width-multiple-blocks")) {
        packs[api](input, 65, 1, packed);
        unpacks[api](packed, 65, 1, decoded);
    } else {
        return 2;
    }
    puts("RAW_PROBE_RETURNED_WITHOUT_DETECTED_FAILURE");
    free(packed); free(decoded); free(input);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 1) return matrix();
    if (argc == 3) return unsafe_probe((uint32_t)strtoul(argv[1], NULL, 10), argv[2]);
    return 2;
}
