#define _GNU_SOURCE
#include "tscb_adapter_v1.h"
#include "fastdelta.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#ifdef INSTRUMENTED
static unsigned api_calls[4];
static int malloc_until_failure = -1, calloc_fail, clock_mode;
static uint64_t clock_tick;
void *__real_malloc(size_t);
void *__real_calloc(size_t, size_t);
int __real_clock_gettime(clockid_t, struct timespec *);
void *__wrap_malloc(size_t n) {
    if (malloc_until_failure == 0) { malloc_until_failure = -1; return NULL; }
    if (malloc_until_failure > 0) --malloc_until_failure;
    return __real_malloc(n);
}
void *__wrap_calloc(size_t n, size_t w) {
    if (calloc_fail) { calloc_fail = 0; return NULL; }
    return __real_calloc(n, w);
}
int __wrap_clock_gettime(clockid_t id, struct timespec *p) {
    if (!clock_mode) return __real_clock_gettime(id, p);
    if (clock_mode == 2) return -1;
    uint64_t tick = clock_mode == 3 ? UINT64_C(100000) - clock_tick : clock_tick;
    clock_tick += 10;
    p->tv_sec = (time_t)(tick / UINT64_C(1000000000));
    p->tv_nsec = (long)(tick % UINT64_C(1000000000));
    return 0;
}
void __real_compute_deltas(const uint32_t *, size_t, uint32_t *, uint32_t);
void __real_compute_deltas_inplace(uint32_t *, size_t, uint32_t);
void __real_compute_prefix_sum(const uint32_t *, size_t, uint32_t *, uint32_t);
void __real_compute_prefix_sum_inplace(uint32_t *, size_t, uint32_t);
void __wrap_compute_deltas(const uint32_t *p, size_t n, uint32_t *q, uint32_t seed) {
    ++api_calls[0]; __real_compute_deltas(p, n, q, seed);
}
void __wrap_compute_deltas_inplace(uint32_t *p, size_t n, uint32_t seed) {
    ++api_calls[1]; __real_compute_deltas_inplace(p, n, seed);
}
void __wrap_compute_prefix_sum(const uint32_t *p, size_t n, uint32_t *q, uint32_t seed) {
    ++api_calls[2]; __real_compute_prefix_sum(p, n, q, seed);
}
void __wrap_compute_prefix_sum_inplace(uint32_t *p, size_t n, uint32_t seed) {
    ++api_calls[3]; __real_compute_prefix_sum_inplace(p, n, seed);
}
#endif

typedef struct { uint8_t *base, *data; size_t size, readable, bytes, shift; } guarded;
static guarded allocate(size_t bytes, size_t shift) {
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    guarded g = {0};
    g.readable = ((bytes + shift + 16 + page - 1) / page) * page;
    g.size = g.readable + 2 * page; g.bytes = bytes; g.shift = shift;
    g.base = mmap(NULL, g.size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(g.base != MAP_FAILED);
    assert(mprotect(g.base, page, PROT_NONE) == 0);
    assert(mprotect(g.base + page + g.readable, page, PROT_NONE) == 0);
    memset(g.base + page, 0xa5, g.readable);
    g.data = g.base + page + g.readable - bytes - shift;
    return g;
}
static void protect(guarded g) {
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    assert(mprotect(g.base + page, g.readable, PROT_READ) == 0);
}
static void canary(guarded g, size_t used) {
    for (unsigned i = 1; i <= 16; ++i) assert(g.data[-(int)i] == 0xa5);
    for (size_t i = used; i < g.bytes + g.shift; ++i) assert(g.data[i] == 0xa5);
}
static void release(guarded g) { assert(munmap(g.base, g.size) == 0); }
static tscb_buffer_v1 buffer(void *p, uint64_t cap, uint64_t used, uint32_t dtype,
                              int source) {
    tscb_buffer_v1 b = {0};
    unsigned width = dtype == TSCB_DTYPE_U32_LE_V1 ? 4 : 1;
    b.data = p; b.capacity_bytes = cap; b.used_bytes = used;
    b.dtype = dtype; b.rank = 1; b.shape[0] = (source && width == 4 ? used : cap) / width;
    b.strides_bytes[0] = width; b.alignment_bytes = 1;
    b.ownership = TSCB_OWNERSHIP_CALLER_V1; return b;
}
static tscb_codec_handle_v1 *create(unsigned mode, uint32_t seed) {
    char json[128];
    int length = snprintf(json, sizeof(json),
        "{\"api_mode\":\"%s\",\"isa\":\"SSE4_1\",\"starting_point\":%u}",
        mode ? "INPLACE" : "DISTINCT", seed);
    tscb_codec_handle_v1 *h = NULL;
    assert(tscb_create(json, (uint64_t)length, &h) == TSCB_STATUS_OK_V1 && h);
    return h;
}
static void finish(tscb_codec_handle_v1 *h) {
    tscb_buffer_v1 final = buffer(NULL, 0, 0, TSCB_DTYPE_BYTES_V1, 0);
    assert(tscb_finalize(h, &final) == TSCB_STATUS_OK_V1 && !final.used_bytes);
}
static void atomic_decode(tscb_codec_handle_v1 *h, tscb_buffer_v1 source,
                           tscb_status_v1 expected) {
    uint8_t storage[40], saved[40];
    memset(storage, 0x73, sizeof(storage)); memcpy(saved, storage, sizeof(storage));
    tscb_buffer_v1 out = buffer(storage + 1, 32, 0, TSCB_DTYPE_U32_LE_V1, 0);
    assert(tscb_decompress(h, &source, &out) == expected);
    assert(!out.used_bytes && memcmp(storage, saved, sizeof(storage)) == 0);
}
static uint64_t checksum(const uint8_t *p, size_t n) {
    uint64_t v = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < n; ++i) v = (v ^ p[i]) * UINT64_C(1099511628211);
    return v;
}
static void resign(uint8_t *p, size_t n) {
    uint64_t v = checksum(p, n - 8);
    for (unsigned i = 0; i < 8; ++i) p[n - 8 + i] = (uint8_t)(v >> (8 * i));
}

static void roundtrip(size_t n, unsigned mode, uint32_t seed, unsigned pattern,
                      unsigned shift) {
    size_t raw = 4 * n, encoded = raw + 32;
    guarded src = allocate(raw, shift), dst = allocate(encoded, shift), dec = allocate(raw + 4, shift);
    uint32_t *saved = malloc(raw + 4), *oracle = malloc(raw + 4), *upstream = malloc(raw + 4);
    assert(saved && oracle && upstream);
    uint32_t previous = seed, random = 123456789U;
    for (size_t i = 0; i < n; ++i) {
        random = random * 1664525U + 1013904223U;
        uint32_t value = pattern == 0 ? 0 : pattern == 1 ? UINT32_MAX
            : pattern == 2 ? (uint32_t)i * 257U
            : pattern == 3 ? (i % 2 ? 1U : UINT32_MAX) : random;
        saved[i] = value; oracle[i] = value - previous; previous = value;
        memcpy(src.data + 4 * i, &value, 4);
    }
    protect(src);
    tscb_codec_handle_v1 *h = create(mode, seed);
    tscb_buffer_v1 in = buffer(src.data, raw, raw, TSCB_DTYPE_U32_LE_V1, 1);
    tscb_buffer_v1 out = buffer(dst.data, encoded, 0, TSCB_DTYPE_BYTES_V1, 0);
    uint64_t bound = 0;
    assert(tscb_compress_bound(h, &in, &bound) == TSCB_STATUS_OK_V1 && bound == encoded);
#ifdef INSTRUMENTED
    unsigned before[4]; memcpy(before, api_calls, sizeof(before));
#endif
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1 && out.used_bytes == encoded);
#ifdef INSTRUMENTED
    for (unsigned i = 0; i < 4; ++i) assert(api_calls[i] == before[i] + (i == mode));
#endif
    assert(!memcmp(dst.data, "TSCBFDC1", 8));
    assert(memcmp(dst.data + 24, oracle, raw) == 0);
    assert(memcmp(src.data, saved, raw) == 0);
    if (mode) {
        memcpy(upstream, saved, raw); compute_deltas_inplace(upstream, n, seed);
    } else compute_deltas(saved, n, upstream, seed);
    assert(memcmp(dst.data + 24, upstream, raw) == 0);
    // Independently reverse the emitted original-API words with the other API mode.
    if (mode) compute_prefix_sum(upstream, n, oracle, seed);
    else { memcpy(oracle, upstream, raw); compute_prefix_sum_inplace(oracle, n, seed); }
    assert(memcmp(oracle, saved, raw) == 0);
    finish(h); protect(dst);
    const char *accounting; uint64_t length;
    assert(tscb_get_accounting_json(h, &accounting, &length) == TSCB_STATUS_OK_V1 && length);
    // A different configured mode and seed must still decode from the frame alone.
    tscb_codec_handle_v1 *fresh = create(!mode, ~seed);
    tscb_buffer_v1 wire = buffer(dst.data, encoded, encoded, TSCB_DTYPE_BYTES_V1, 1);
    tscb_buffer_v1 recovered = buffer(dec.data, raw + 4, 0, TSCB_DTYPE_U32_LE_V1, 0);
#ifdef INSTRUMENTED
    memcpy(before, api_calls, sizeof(before));
#endif
    assert(tscb_decompress(fresh, &wire, &recovered) == TSCB_STATUS_OK_V1);
#ifdef INSTRUMENTED
    for (unsigned i = 0; i < 4; ++i) assert(api_calls[i] == before[i] + (i == mode + 2));
#endif
    assert(recovered.used_bytes == raw && memcmp(dec.data, saved, raw) == 0);
    canary(src, raw); canary(dst, encoded); canary(dec, raw);
    // Exact decoded extent ends immediately at a protected page.
    guarded exact = allocate(raw, 0);
    recovered = buffer(exact.data, raw, 0, TSCB_DTYPE_U32_LE_V1, 0);
    assert(tscb_decompress(fresh, &wire, &recovered) == TSCB_STATUS_OK_V1);
    assert(recovered.used_bytes == raw && memcmp(exact.data, saved, raw) == 0);
    canary(exact, raw); release(exact);
    assert(tscb_destroy(fresh) == TSCB_STATUS_OK_V1 && tscb_destroy(h) == TSCB_STATUS_OK_V1);
    release(src); release(dst); release(dec); free(saved); free(oracle); free(upstream);
}

static void invalid_config(void) {
    const char *invalid[] = {"{}", "null", "", "{\"isa\":\"SSE4_1\"}",
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":-1}",
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":4294967296}",
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":00}",
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":0.0}",
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":0e0}",
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":+1}",
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":1,\"x\":0}",
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":1,\"starting_point\":0}",
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\": 0}",
        "{\"api_mode\":\"INPLACE\",\"isa\":\"SCALAR\",\"starting_point\":0}",
        "{\"api_mode\":\"ALIEN\",\"isa\":\"SSE4_1\",\"starting_point\":0}"};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        tscb_codec_handle_v1 *h = NULL;
        assert(tscb_create(invalid[i], strlen(invalid[i]), &h) == TSCB_STATUS_INVALID_ARGUMENT_V1 && !h);
    }
    tscb_codec_handle_v1 *h = NULL;
    assert(tscb_create(NULL, UINT64_MAX, &h) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    assert(tscb_create("", 0, NULL) == TSCB_STATUS_INVALID_ARGUMENT_V1);
}

static void rejection_and_lifecycle(unsigned mode) {
    uint32_t input[] = {UINT32_MAX, 0, 1, UINT32_C(0x80000000), 4, 3, 2, 1};
    uint8_t storage[128], saved[128], valid[64];
    memset(storage, 0x73, sizeof(storage)); memcpy(saved, storage, sizeof(storage));
    tscb_codec_handle_v1 *h = create(mode, UINT32_MAX);
    tscb_buffer_v1 in = buffer(input, 32, 32, TSCB_DTYPE_U32_LE_V1, 1);
    tscb_buffer_v1 out = buffer(storage + 1, 63, 0, TSCB_DTYPE_BYTES_V1, 0);
    const char *text = NULL; uint64_t length = 0;
    assert(tscb_get_accounting_json(h, &text, &length) == TSCB_STATUS_FINALIZE_REQUIRED_V1);
    tscb_buffer_v1 final = buffer(NULL, 0, 0, TSCB_DTYPE_BYTES_V1, 0);
    assert(tscb_finalize(h, &final) == TSCB_STATUS_FINALIZE_REQUIRED_V1);
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_DST_TOO_SMALL_V1);
    assert(!out.used_bytes && !memcmp(storage, saved, sizeof(storage)));
    // Full and partial alias are forbidden in both original API modes.
    tscb_buffer_v1 alias = buffer(storage + 1, 32, 32, TSCB_DTYPE_U32_LE_V1, 1);
    out = buffer(storage + 1, 64, 0, TSCB_DTYPE_BYTES_V1, 0);
    assert(tscb_compress(h, &alias, &out) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    alias.data = storage + 9;
    assert(tscb_compress(h, &alias, &out) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    assert(!out.used_bytes && !memcmp(storage, saved, sizeof(storage)));
    // Descriptor rejection before reading fictitious large inputs.
    tscb_buffer_v1 bad = in;
    bad.capacity_bytes = bad.used_bytes = UINT64_C(4) * 16777217;
    bad.shape[0] = 16777217;
    uint64_t bound = 73;
    assert(tscb_compress_bound(h, &bad, &bound) == TSCB_STATUS_UNSUPPORTED_V1 && bound == 73);
    assert(tscb_compress(h, &bad, &out) == TSCB_STATUS_UNSUPPORTED_V1);
    for (unsigned field = 0; field < 12; ++field) {
        bad = in;
        switch (field) {
            case 0: bad.dtype = TSCB_DTYPE_I64_LE_V1; break;
            case 1: bad.rank = 2; break;
            case 2: bad.strides_bytes[0] = -4; break;
            case 3: bad.used_bytes = 33; break;
            case 4: bad.shape[0]++; break;
            case 5: bad.capacity_bytes++; break;
            case 6: bad.reserved = 1; break;
            case 7: bad.shape[1] = 1; break;
            case 8: bad.strides_bytes[1] = 1; break;
            case 9: bad.alignment_bytes = 3; break;
            case 10: bad.data = (void *)(UINTPTR_MAX - 1U); break;
            case 11: bad.ownership = 3; break;
        }
        assert(tscb_compress_bound(h, &bad, &bound) == TSCB_STATUS_INVALID_ARGUMENT_V1 && bound == 73);
        assert(tscb_compress(h, &bad, &out) == TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(!out.used_bytes && !memcmp(storage, saved, sizeof(storage)));
    }
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1);
    memcpy(valid, storage + 1, 64);
    out = buffer(storage + 1, 64, 0, TSCB_DTYPE_BYTES_V1, 0);
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_CODEC_ERROR_V1 && !out.used_bytes);
    finish(h);
    assert(tscb_finalize(h, &final) == TSCB_STATUS_CODEC_ERROR_V1);
    assert(tscb_reset(h, 1) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    assert(tscb_get_accounting_json(h, &text, &length) == TSCB_STATUS_OK_V1);
    assert(tscb_reset(h, 0) == TSCB_STATUS_OK_V1);
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1);
    assert(!memcmp(valid, storage + 1, 64)); finish(h);
    // Exact/truncated/excess frames; all corruption locations, including seed/payload.
    for (size_t cut = 0; cut < 64; ++cut) {
        tscb_buffer_v1 wire = buffer(valid, cut, cut, TSCB_DTYPE_BYTES_V1, 1);
        atomic_decode(h, wire, TSCB_STATUS_CODEC_ERROR_V1);
    }
    uint8_t corrupted[65];
    for (unsigned i = 0; i < 64; ++i) {
        memcpy(corrupted, valid, 64); corrupted[i] ^= 1;
        tscb_buffer_v1 wire = buffer(corrupted, 64, 64, TSCB_DTYPE_BYTES_V1, 1);
        atomic_decode(h, wire, TSCB_STATUS_CODEC_ERROR_V1);
    }
    memcpy(corrupted, valid, 64); corrupted[64] = 0;
    atomic_decode(h, buffer(corrupted, 65, 65, TSCB_DTYPE_BYTES_V1, 1), TSCB_STATUS_CODEC_ERROR_V1);
    // Semantic header errors remain rejected even if the wrapper checksum is recomputed.
    for (unsigned field = 0; field < 4; ++field) {
        memcpy(corrupted, valid, 64);
        if (field == 0) corrupted[0] ^= 1;
        if (field == 1) corrupted[8] = 9;
        if (field == 2) corrupted[16] = 2;
        if (field == 3) corrupted[20] = 1;
        resign(corrupted, 64);
        atomic_decode(h, buffer(corrupted, 64, 64, TSCB_DTYPE_BYTES_V1, 1), TSCB_STATUS_CODEC_ERROR_V1);
    }
    tscb_buffer_v1 wire = buffer(valid, 64, 64, TSCB_DTYPE_BYTES_V1, 1);
    out = buffer(storage + 1, 28, 0, TSCB_DTYPE_U32_LE_V1, 0);
    memcpy(saved, storage, sizeof(storage));
    assert(tscb_decompress(h, &wire, &out) == TSCB_STATUS_DST_TOO_SMALL_V1);
    assert(!out.used_bytes && !memcmp(storage, saved, sizeof(storage)));
    out = buffer(valid + 4, 32, 0, TSCB_DTYPE_U32_LE_V1, 0);
    assert(tscb_decompress(h, &wire, &out) == TSCB_STATUS_INVALID_ARGUMENT_V1 && !out.used_bytes);
    assert(tscb_query(h, NULL, 0, NULL, 0, &length) == TSCB_STATUS_UNSUPPORTED_V1);
    assert(tscb_get_last_error(h, &text, &length) == TSCB_STATUS_OK_V1 && length);
    assert(tscb_destroy(h) == TSCB_STATUS_OK_V1);
}

#ifdef INSTRUMENTED
static void faults(unsigned mode) {
    tscb_codec_handle_v1 *h = NULL;
    const char *json = "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":0}";
    calloc_fail = 1;
    assert(tscb_create(json, strlen(json), &h) == TSCB_STATUS_CODEC_ERROR_V1 && !h);
    h = create(mode, 1);
    uint32_t values[] = {UINT32_MAX, 0, 1, 0};
    uint8_t bytes[48], saved[48], reference[48];
    tscb_buffer_v1 in = buffer(values, 16, 16, TSCB_DTYPE_U32_LE_V1, 1);
    tscb_buffer_v1 out = buffer(bytes, 48, 0, TSCB_DTYPE_BYTES_V1, 0);
    tscb_native_timing_v1 t = {sizeof(t), 1, 0, 0}, again = t;
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_UNSUPPORTED_V1);
    assert(tscb_set_native_timing(h, 2) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    assert(tscb_set_native_timing(h, 1) == TSCB_STATUS_OK_V1);
    t.version = 2;
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_ABI_MISMATCH_V1); t.version = 1;
    clock_mode = 1; clock_tick = 100;
    // Reject each allocation separately without writing output or calling the API.
    for (int alloc = 0; alloc < (mode ? 1 : 2); ++alloc) {
        memset(bytes, 0x73, sizeof(bytes)); memcpy(saved, bytes, sizeof(bytes));
        unsigned calls = api_calls[mode]; malloc_until_failure = alloc;
        assert(tscb_compress(h, &in, &out) == TSCB_STATUS_CODEC_ERROR_V1);
        assert(!out.used_bytes && !memcmp(bytes, saved, sizeof(bytes)) && api_calls[mode] == calls);
        assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_OK_V1 && !t.native_encode_wall_ns);
    }
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1); finish(h);
    memcpy(reference, bytes, sizeof(bytes));
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_OK_V1 && t.native_encode_wall_ns == 10);
    assert(tscb_get_native_timing(h, &again) == TSCB_STATUS_OK_V1 && !memcmp(&t, &again, sizeof(t)));
    uint32_t restored[4], saved_values[4];
    tscb_buffer_v1 wire = buffer(bytes, 48, 48, TSCB_DTYPE_BYTES_V1, 1);
    tscb_buffer_v1 decoded = buffer(restored, 16, 0, TSCB_DTYPE_U32_LE_V1, 0);
    for (int alloc = 0; alloc < (mode ? 1 : 2); ++alloc) {
        memset(restored, 0x73, sizeof(restored)); memcpy(saved_values, restored, sizeof(restored));
        unsigned calls = api_calls[mode + 2]; malloc_until_failure = alloc;
        assert(tscb_decompress(h, &wire, &decoded) == TSCB_STATUS_CODEC_ERROR_V1);
        assert(!decoded.used_bytes && !memcmp(restored, saved_values, sizeof(restored)));
        assert(api_calls[mode + 2] == calls);
    }
    for (unsigned i = 0; i < 2; ++i) {
        decoded.used_bytes = 0;
        assert(tscb_decompress(h, &wire, &decoded) == TSCB_STATUS_OK_V1);
        assert(!memcmp(restored, values, sizeof(values)));
    }
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_OK_V1);
    assert(t.native_encode_wall_ns == 10 && t.native_decode_wall_ns == 20);
    assert(tscb_reset(h, 0) == TSCB_STATUS_OK_V1);
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_OK_V1);
    assert(!t.native_encode_wall_ns && !t.native_decode_wall_ns);
    assert(tscb_set_native_timing(h, 0) == TSCB_STATUS_OK_V1);
    out.used_bytes = 0;
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1); finish(h);
    assert(!memcmp(bytes, reference, sizeof(bytes)));
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_UNSUPPORTED_V1);
    for (int fault = 2; fault <= 3; ++fault) {
        assert(tscb_reset(h, 0) == TSCB_STATUS_OK_V1);
        assert(tscb_set_native_timing(h, 1) == TSCB_STATUS_OK_V1);
        clock_mode = fault; clock_tick = 0; out.used_bytes = 0;
        assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1); finish(h);
        assert(!memcmp(bytes, reference, sizeof(bytes)));
        assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_UNSUPPORTED_V1);
    }
    clock_mode = 0;
    assert(tscb_destroy(h) == TSCB_STATUS_OK_V1);
}
#endif

int main(void) {
    const char *text; uint64_t length;
    assert(tscb_get_abi_version() == 1);
    assert(tscb_get_manifest_json(&text, &length) == TSCB_STATUS_OK_V1 && length);
    assert(strstr(text, "fast-differential-u32"));
    invalid_config();
    const size_t lengths[] = {0,1,2,3,4,5,7,8,9,15,16,17,31,32,33,63,64,65,
                               127,128,129,255,256,257,1000,8193};
    const uint32_t seeds[] = {0,1,UINT32_C(0x80000000),UINT32_MAX};
    unsigned cases = 0;
    for (unsigned mode = 0; mode < 2; ++mode) {
        rejection_and_lifecycle(mode);
#ifdef INSTRUMENTED
        faults(mode);
#endif
        for (unsigned l = 0; l < sizeof(lengths) / sizeof(lengths[0]); ++l)
            for (unsigned s = 0; s < sizeof(seeds) / sizeof(seeds[0]); ++s)
                for (unsigned pattern = 0; pattern < 5; ++pattern)
                    for (unsigned shift = 0; shift < 4; ++shift) {
                        roundtrip(lengths[l], mode, seeds[s], pattern, shift); ++cases;
                    }
    }
    puts("config/descriptor/capacity/alias/corruption/lifecycle/atomic failure PASS");
#ifdef INSTRUMENTED
    puts("original API routing/allocation failure/native timer faults/accumulation PASS");
#endif
    printf("FastDifferential bounded ABI scalar and original-API/seed/mode/guard cases PASS: %u\n", cases);
    return 0;
}
