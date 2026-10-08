#define _GNU_SOURCE
#include "fastdelta.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

typedef struct { void *base; size_t size; uint32_t *data; } guarded;
static guarded allocate(size_t n) {
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    size_t bytes = n * sizeof(uint32_t);
    guarded out = {0};
    out.size = ((bytes + page - 1) / page + 1) * page;
    out.base = mmap(NULL, out.size, PROT_READ | PROT_WRITE,
                    MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(out.base != MAP_FAILED);
    uint8_t *end = (uint8_t *)out.base + out.size - page;
    assert(mprotect(end, page, PROT_NONE) == 0);
    out.data = (uint32_t *)(end - bytes);
    return out;
}
static void release(guarded x) { assert(munmap(x.base, x.size) == 0); }
int main(void) {
#if defined(__x86_64__) && defined(__GNUC__)
    if (!__builtin_cpu_supports("sse4.1")) return 2;
#else
    return 2;
#endif
    const size_t lengths[] = {0,1,2,3,4,5,7,8,9,15,16,17,31,32,33,
                              63,64,65,127,128,129,255,256,257,1000,8193};
    const uint32_t seeds[] = {0,1,0x80000000U,UINT32_MAX};
    unsigned cases = 0;
    for (size_t l = 0; l < sizeof(lengths)/sizeof(lengths[0]); ++l)
        for (size_t s = 0; s < sizeof(seeds)/sizeof(seeds[0]); ++s)
            for (unsigned pattern = 0; pattern < 5; ++pattern) {
                size_t n = lengths[l], bytes = n * sizeof(uint32_t);
                guarded source = allocate(n), deltas = allocate(n), decoded = allocate(n);
                uint32_t *expected = malloc(bytes + 1), *saved = malloc(bytes + 1);
                assert(expected && saved);
                uint32_t previous = seeds[s], random = 123456789U;
                for (size_t i = 0; i < n; ++i) {
                    random = random * 1664525U + 1013904223U;
                    uint32_t value = pattern == 0 ? 0 : pattern == 1 ? UINT32_MAX
                        : pattern == 2 ? (uint32_t)i * 257U
                        : pattern == 3 ? (i % 2 ? 1U : UINT32_MAX) : random;
                    source.data[i] = saved[i] = value;
                    expected[i] = value - previous; previous = value;
                }
                size_t readable = source.size - (size_t)sysconf(_SC_PAGESIZE);
                if (readable) assert(mprotect(source.base, readable, PROT_READ) == 0);
                compute_deltas(source.data, n, deltas.data, seeds[s]);
                if (n) assert(memcmp(deltas.data, expected, bytes) == 0);
                compute_prefix_sum(deltas.data, n, decoded.data, seeds[s]);
                if (n) {
                    assert(memcmp(decoded.data, saved, bytes) == 0);
                    assert(memcmp(source.data, saved, bytes) == 0);
                }
                compute_deltas_inplace(decoded.data, n, seeds[s]);
                if (n) assert(memcmp(decoded.data, expected, bytes) == 0);
                compute_prefix_sum_inplace(decoded.data, n, seeds[s]);
                if (n) assert(memcmp(decoded.data, saved, bytes) == 0);
                release(source); release(deltas); release(decoded); free(expected); free(saved);
                ++cases;
            }
    printf("FastDifferentialCoding original four-API modular32/seed/tail/guard cases PASS: %u\n", cases);
    return 0;
}
