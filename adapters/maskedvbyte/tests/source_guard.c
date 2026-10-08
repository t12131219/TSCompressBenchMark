#define _GNU_SOURCE
#include "varintencode.h"
#include "varintdecode.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

typedef struct { void *base; size_t mapped; unsigned char *data; } guarded;
static guarded allocate(size_t bytes) {
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    guarded out = {0};
    /* Give empty inputs a valid address; they still have zero readable bytes. */
    out.mapped = ((bytes + page - 1) / page + 2) * page;
    out.base = mmap(NULL, out.mapped, PROT_READ | PROT_WRITE,
                    MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(out.base != MAP_FAILED);
    unsigned char *end = (unsigned char *)out.base + out.mapped - page;
    assert(mprotect(end, page, PROT_NONE) == 0);
    out.data = end - bytes;
    return out;
}
static void readonly(guarded x) {
    assert(mprotect(x.base, x.mapped - (size_t)sysconf(_SC_PAGESIZE), PROT_READ) == 0);
}
static void release(guarded x) { assert(munmap(x.base, x.mapped) == 0); }

/* Independent unsigned scalar LEB128, rather than the source's branch table. */
static size_t scalar_encode(const uint32_t *in, size_t count, unsigned char *out,
                            unsigned delta, uint32_t prev) {
    size_t bytes = 0;
    for (size_t i = 0; i < count; ++i) {
        uint32_t value = delta ? in[i] - prev : in[i];
        prev = in[i];
        do {
            unsigned char byte = (unsigned char)(value & 127U);
            value >>= 7;
            out[bytes++] = (unsigned char)(byte | (value ? 128U : 0U));
        } while (value);
    }
    return bytes;
}

static uint32_t pattern_value(unsigned pattern, size_t index, uint32_t *random) {
    *random = *random * 1664525U + 1013904223U;
    const uint32_t edges[] = {0, 1, 127, 128, 16383, 16384, 2097151, 2097152,
                             268435455, 268435456, 0x7fffffffU, 0x80000000U, UINT32_MAX};
    return pattern == 0 ? 0 : pattern == 1 ? UINT32_MAX
        : pattern == 2 ? (uint32_t)index * 257U
        : pattern == 3 ? (index % 2 ? 1U : UINT32_MAX)
        : pattern == 4 ? edges[index % (sizeof(edges) / sizeof(edges[0]))] : *random;
}

static void decode_case(size_t count, unsigned pattern, unsigned delta, uint32_t seed) {
    guarded input = allocate(count * 4), decoded = allocate(count * 4);
    uint32_t *values = (uint32_t *)input.data, random = 123456789U;
    unsigned char *expected = malloc(5 * count + 1);
    assert(expected);
    for (size_t i = 0; i < count; ++i) values[i] = pattern_value(pattern, i, &random);
    size_t length = scalar_encode(values, count, expected, delta, seed);
    guarded encoded = allocate(length);
    readonly(input);
    size_t written = delta ? vbyte_encode_delta(values, count, encoded.data, seed)
                           : vbyte_encode(values, count, encoded.data);
    assert(written == length);
    if (length) assert(memcmp(encoded.data, expected, length) == 0);
    readonly(encoded);
    size_t consumed = delta ? masked_vbyte_decode_delta(encoded.data, (uint32_t *)decoded.data, count, seed)
                            : masked_vbyte_decode(encoded.data, (uint32_t *)decoded.data, count);
    assert(consumed == length);
    if (count) assert(memcmp(decoded.data, input.data, count * 4) == 0);
    if (count) memset(decoded.data, 0xA5, count * 4);
    size_t recovered = delta ? masked_vbyte_decode_fromcompressedsize_delta(encoded.data, (uint32_t *)decoded.data, length, seed)
                             : masked_vbyte_decode_fromcompressedsize(encoded.data, (uint32_t *)decoded.data, length);
    assert(recovered == count);
    if (count) assert(memcmp(decoded.data, input.data, count * 4) == 0);
    free(expected); release(input); release(encoded); release(decoded);
}

static unsigned query_case(size_t count, unsigned pattern, uint32_t seed) {
    guarded input = allocate(count * 4);
    uint32_t *values = (uint32_t *)input.data;
    unsigned char *bytes = malloc(5 * count + 1);
    assert(bytes);
    for (size_t i = 0; i < count; ++i)
        values[i] = pattern == 0 ? (uint32_t)(i / 3)
            : pattern == 1 ? 0x80000000U + (uint32_t)(i / 3)
            : pattern == 2 ? UINT32_MAX - (uint32_t)count + (uint32_t)i
            : pattern == 3 ? (uint32_t)i * 257U
            : pattern == 4 ? (uint32_t)i * 16384U
            : (uint32_t)i * (UINT32_MAX / (uint32_t)(count + 1));
    size_t length = scalar_encode(values, count, bytes, 1, seed);
    guarded encoded = allocate(length);
    if (length) memcpy(encoded.data, bytes, length);
    readonly(encoded);
    unsigned calls = 0;
    for (size_t i = 0; i < count; ++i) {
        if (count > 513 && i >= 32 && i + 32 < count &&
            i != 95 && i != 96 && i != 97 && i != 111 && i != 112 && i != 113 &&
            i != 255 && i != 256 && i != 257 && i != 511 && i != 512 && i != 513) continue;
        assert(masked_vbyte_select_delta(encoded.data, count, seed, i) == values[i]);
        ++calls;
    }
    const uint32_t special[] = {0,1,127,0x7fffffffU,0x80000000U,UINT32_MAX};
    for (size_t i = 0; i < count + sizeof(special) / sizeof(special[0]); ++i) {
        if (count > 513 && i >= 32 && i + 32 < count &&
            i != 95 && i != 96 && i != 97 && i != 111 && i != 112 && i != 113 &&
            i != 255 && i != 256 && i != 257 && i != 511 && i != 512 && i != 513) continue;
        uint32_t key = i < count ? values[i] : special[i - count];
        size_t slot = 0;
        while (slot < count && values[slot] < key) ++slot;
        uint32_t value = 0xdeadbeefU;
        int got = masked_vbyte_search_delta(encoded.data, count, seed, key, &value);
        assert(got >= 0 && (size_t)got == slot);
        assert(value == (slot < count ? values[slot] : key + 1U));
        ++calls;
    }
    release(input); release(encoded); free(bytes);
    return calls;
}

int main(int argc, char **argv) {
    (void)argc;
    int query = argv[1] && strcmp(argv[1], "query") == 0;
    const size_t lengths[] = {0,1,2,3,4,5,7,8,9,15,16,17,31,32,33,47,48,49,
        63,64,65,95,96,97,111,112,113,127,128,129,191,192,193,255,256,257,513,1000,8193};
    const uint32_t seeds[] = {0,1,0x80000000U,UINT32_MAX};
    unsigned cases = 0, calls = 0;
    for (size_t l = 0; l < sizeof(lengths) / sizeof(lengths[0]); ++l)
        for (size_t s = 0; s < sizeof(seeds) / sizeof(seeds[0]); ++s)
            for (unsigned pattern = 0; pattern < 6U; ++pattern) {
                if (query) calls += query_case(lengths[l], pattern, seeds[s]);
                else for (unsigned delta = 0; delta < 2; ++delta) {
                    decode_case(lengths[l], pattern, delta, seeds[s]);
                    ++cases;
                }
                if (query) ++cases;
            }
    printf("MaskedVByte original API %s scalar/seed/guard cases PASS: %u; query calls: %u\n",
           query ? "query" : "decode", cases, calls);
    return 0;
}
