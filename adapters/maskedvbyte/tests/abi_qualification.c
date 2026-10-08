/* Guard-page and buffer-descriptor helpers follow FastDifferential qualification.
 * The independent oracle is unsigned LEB128, not a copy of the upstream encoder. */
#define _GNU_SOURCE
#include "tscb_adapter_v1.h"
#include "varintencode.h"
#include "varintdecode.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

tscb_status_v1 tscb_get_telemetry_json(tscb_codec_handle_v1 *, const char **, uint64_t *);

#ifdef INSTRUMENTED
static unsigned api_calls[6], allocation_calls, free_calls;
static size_t allocation_sizes[4];
static int malloc_until_failure = -1, calloc_fail, clock_mode, wrong_api_length;
static uint64_t clock_tick;
void *__real_malloc(size_t);
void *__real_calloc(size_t, size_t);
void __real_free(void *);
int __real_clock_gettime(clockid_t, struct timespec *);
void *__wrap_malloc(size_t n) {
    if (allocation_calls < 4) allocation_sizes[allocation_calls] = n;
    ++allocation_calls;
    if (malloc_until_failure == 0) { malloc_until_failure = -1; return NULL; }
    if (malloc_until_failure > 0) --malloc_until_failure;
    return __real_malloc(n);
}
void *__wrap_calloc(size_t n, size_t w) {
    if (calloc_fail) { calloc_fail = 0; return NULL; }
    return __real_calloc(n, w);
}
void __wrap_free(void *p) { if (p) ++free_calls; __real_free(p); }
int __wrap_clock_gettime(clockid_t id, struct timespec *p) {
    if (!clock_mode) return __real_clock_gettime(id, p);
    if (clock_mode == 2) return -1;
    uint64_t tick = clock_mode == 3 ? UINT64_C(100000) - clock_tick : clock_tick;
    clock_tick += 10;
    p->tv_sec = (time_t)(tick / UINT64_C(1000000000));
    p->tv_nsec = (long)(tick % UINT64_C(1000000000));
    return 0;
}
size_t __real_vbyte_encode(const uint32_t *, size_t, uint8_t *);
size_t __real_vbyte_encode_delta(const uint32_t *, size_t, uint8_t *, uint32_t);
size_t __real_masked_vbyte_decode(const uint8_t *, uint32_t *, uint64_t);
size_t __real_masked_vbyte_decode_delta(const uint8_t *, uint32_t *, uint64_t, uint32_t);
size_t __real_masked_vbyte_decode_fromcompressedsize(const uint8_t *, uint32_t *, size_t);
size_t __real_masked_vbyte_decode_fromcompressedsize_delta(const uint8_t *, uint32_t *, size_t, uint32_t);
size_t __wrap_vbyte_encode(const uint32_t *p, size_t n, uint8_t *q) {
    ++api_calls[0]; size_t r = __real_vbyte_encode(p, n, q); return r + (wrong_api_length != 0);
}
size_t __wrap_vbyte_encode_delta(const uint32_t *p, size_t n, uint8_t *q, uint32_t s) {
    ++api_calls[1]; size_t r = __real_vbyte_encode_delta(p, n, q, s); return r + (wrong_api_length != 0);
}
size_t __wrap_masked_vbyte_decode(const uint8_t *p, uint32_t *q, uint64_t n) {
    ++api_calls[2]; size_t r = __real_masked_vbyte_decode(p, q, n); return r + (wrong_api_length != 0);
}
size_t __wrap_masked_vbyte_decode_delta(const uint8_t *p, uint32_t *q, uint64_t n, uint32_t s) {
    ++api_calls[3]; size_t r = __real_masked_vbyte_decode_delta(p, q, n, s); return r + (wrong_api_length != 0);
}
size_t __wrap_masked_vbyte_decode_fromcompressedsize(const uint8_t *p, uint32_t *q, size_t n) {
    ++api_calls[4]; size_t r = __real_masked_vbyte_decode_fromcompressedsize(p, q, n); return r + (wrong_api_length != 0);
}
size_t __wrap_masked_vbyte_decode_fromcompressedsize_delta(const uint8_t *p, uint32_t *q, size_t n, uint32_t s) {
    ++api_calls[5]; size_t r = __real_masked_vbyte_decode_fromcompressedsize_delta(p, q, n, s); return r + (wrong_api_length != 0);
}
static void one_call(const unsigned *before, unsigned expected) {
    for (unsigned i = 0; i < 6; ++i) assert(api_calls[i] == before[i] + (i == expected));
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
static void readonly(guarded g) {
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    assert(mprotect(g.base + page, g.readable, PROT_READ) == 0);
}
static void canary(guarded g, size_t used) {
    for (unsigned i = 1; i <= 16; ++i) assert(g.data[-(int)i] == 0xa5);
    for (size_t i = used; i < g.bytes + g.shift; ++i) assert(g.data[i] == 0xa5);
}
static void release(guarded g) { assert(munmap(g.base, g.size) == 0); }
static tscb_buffer_v1 buffer(void *p, uint64_t cap, uint64_t used, uint32_t dtype, int source) {
    tscb_buffer_v1 b = {0};
    unsigned width = dtype == TSCB_DTYPE_U32_LE_V1 ? 4 : 1;
    b.data = p; b.capacity_bytes = cap; b.used_bytes = used;
    b.dtype = dtype; b.rank = 1; b.shape[0] = (source && width == 4 ? used : cap) / width;
    b.strides_bytes[0] = width; b.alignment_bytes = 1;
    b.ownership = TSCB_OWNERSHIP_CALLER_V1; return b;
}
static tscb_codec_handle_v1 *create(unsigned coding, unsigned decoder, uint32_t seed) {
    char json[160];
    int length = snprintf(json, sizeof(json),
        "{\"coding\":\"%s\",\"decoder_api\":\"%s\",\"isa\":\"SSE4_1\",\"starting_point\":%u}",
        coding ? "DELTA" : "PLAIN", decoder ? "COMPRESSED_SIZE" : "COUNT", seed);
    tscb_codec_handle_v1 *h = NULL;
    assert(tscb_create(json, (uint64_t)length, &h) == TSCB_STATUS_OK_V1 && h);
    return h;
}
static void finish(tscb_codec_handle_v1 *h) {
    tscb_buffer_v1 final = buffer(NULL, 0, 0, TSCB_DTYPE_BYTES_V1, 0);
    assert(tscb_finalize(h, &final) == TSCB_STATUS_OK_V1 && !final.used_bytes);
}
static uint64_t get(const uint8_t *p, unsigned width) {
    uint64_t n = 0; for (unsigned i = 0; i < width; ++i) n |= (uint64_t)p[i] << (8 * i);
    return n;
}
static void put(uint8_t *p, uint64_t n, unsigned width) {
    for (unsigned i = 0; i < width; ++i) p[i] = (uint8_t)(n >> (8 * i));
}
static uint64_t checksum(const uint8_t *p, size_t n) {
    uint64_t v = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < n; ++i) v = (v ^ p[i]) * UINT64_C(1099511628211);
    return v;
}
static void resign(uint8_t *p, size_t n) { put(p + n - 8, checksum(p, n - 8), 8); }
static size_t scalar(const uint32_t *p, size_t n, uint8_t *q, unsigned delta, uint32_t prev) {
    size_t bytes = 0;
    for (size_t i = 0; i < n; ++i) {
        uint32_t value = delta ? p[i] - prev : p[i]; prev = p[i];
        do {
            uint8_t byte = (uint8_t)(value & 127U); value >>= 7;
            q[bytes++] = (uint8_t)(byte | (value ? 128U : 0U));
        } while (value);
    }
    return bytes;
}
static void telemetry_number(tscb_codec_handle_v1 *h, const char *key, uint64_t value) {
    const char *text; uint64_t length;
    assert(tscb_get_telemetry_json(h, &text, &length) == TSCB_STATUS_OK_V1 && length);
    char field[160]; snprintf(field, sizeof(field), "\"%s\":%llu", key, (unsigned long long)value);
    const char *at = strstr(text, field); assert(at);
    char next = at[strlen(field)]; assert(next == ',' || next == '}');
}
static void telemetry_api(tscb_codec_handle_v1 *h, const char *api) {
    const char *text; uint64_t length;
    assert(tscb_get_telemetry_json(h, &text, &length) == TSCB_STATUS_OK_V1 && length);
    char field[160]; snprintf(field, sizeof(field), "\"actual_original_api\":\"%s\"", api);
    assert(strstr(text, field));
}

static void roundtrip(size_t n, unsigned coding, unsigned decoder, uint32_t seed,
                      unsigned pattern, unsigned shift) {
    size_t raw = 4 * n;
    guarded src = allocate(raw, shift), dec = allocate(raw + 4, shift);
    uint32_t *saved = malloc(raw + 4); uint8_t *oracle = malloc(5 * n + 1), *upstream = malloc(5 * n + 1);
    assert(saved && oracle && upstream);
    uint32_t random = 123456789U;
    const uint32_t edges[] = {0,1,127,128,16383,16384,2097151,2097152,268435455,268435456,0x7fffffffU,0x80000000U,UINT32_MAX};
    for (size_t i = 0; i < n; ++i) {
        random = random * 1664525U + 1013904223U;
        uint32_t value = pattern == 0 ? 0 : pattern == 1 ? UINT32_MAX
            : pattern == 2 ? (uint32_t)i * 257U : pattern == 3 ? (i % 2 ? 1U : UINT32_MAX)
            : pattern == 4 ? edges[i % (sizeof(edges) / sizeof(edges[0]))] : random;
        saved[i] = value; memcpy(src.data + 4 * i, &value, 4);
    }
    size_t payload = scalar(saved, n, oracle, coding, seed), encoded = payload + 40;
    guarded dst = allocate(encoded, shift);
    readonly(src);
    tscb_codec_handle_v1 *h = create(coding, decoder, seed);
    tscb_buffer_v1 in = buffer(src.data, raw, raw, TSCB_DTYPE_U32_LE_V1, 1);
    tscb_buffer_v1 out = buffer(dst.data, encoded, 0, TSCB_DTYPE_BYTES_V1, 0);
    uint64_t bound = 0;
    assert(tscb_compress_bound(h, &in, &bound) == TSCB_STATUS_OK_V1 && bound == 40 + 5 * n);
#ifdef INSTRUMENTED
    unsigned before[6]; memcpy(before, api_calls, sizeof(before));
    allocation_calls = free_calls = 0;
#endif
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1 && out.used_bytes == encoded);
#ifdef INSTRUMENTED
    one_call(before, coding);
    assert(allocation_calls == 2 && free_calls == 2);
    assert(allocation_sizes[0] == 4 * (n ? n : 1) && allocation_sizes[1] == (payload ? payload : 1));
#endif
    assert(!memcmp(dst.data, "TSCBMVB1", 8));
    assert(get(dst.data + 8, 4) == n && get(dst.data + 12, 4) == seed);
    assert(get(dst.data + 16, 4) == coding && get(dst.data + 20, 4) == 0);
    assert(get(dst.data + 24, 8) == payload && get(dst.data + encoded - 8, 8) == checksum(dst.data, encoded - 8));
    assert(!memcmp(dst.data + 32, oracle, payload) && !memcmp(src.data, saved, raw));
    size_t original = coding ? vbyte_encode_delta(saved, n, upstream, seed) : vbyte_encode(saved, n, upstream);
    assert(original == payload && !memcmp(upstream, oracle, payload));
    telemetry_api(h, coding ? "vbyte_encode_delta" : "vbyte_encode");
    telemetry_number(h, "native_payload_bytes", payload);
    telemetry_number(h, "native_raw_bytes", raw);
    telemetry_number(h, "native_staging_allocation_bytes", 4 * (n ? n : 1) + (payload ? payload : 1));
    telemetry_number(h, "native_staging_input_copy_bytes", raw);
    telemetry_number(h, "native_staging_output_copy_bytes", payload);
    finish(h); readonly(dst);
    const char *accounting; uint64_t length;
    assert(tscb_get_accounting_json(h, &accounting, &length) == TSCB_STATUS_OK_V1 && length);
    char field[96]; snprintf(field, sizeof(field), "\"payload_bytes\":%zu,\"count\":%zu", payload, n);
    assert(strstr(accounting, field) && strstr(accounting, "\"container_bytes\":8,\"metadata_bytes\":24,\"checksum_bytes\":8"));
    // Decoder API and handle seed/coding differ. Only the wire determines recovery.
    tscb_codec_handle_v1 *fresh = create(!coding, !decoder, coding ? 0 : ~seed);
    tscb_buffer_v1 wire = buffer(dst.data, encoded, encoded, TSCB_DTYPE_BYTES_V1, 1);
    tscb_buffer_v1 recovered = buffer(dec.data, raw + 4, 0, TSCB_DTYPE_U32_LE_V1, 0);
#ifdef INSTRUMENTED
    memcpy(before, api_calls, sizeof(before)); allocation_calls = free_calls = 0;
#endif
    assert(tscb_decompress(fresh, &wire, &recovered) == TSCB_STATUS_OK_V1);
#ifdef INSTRUMENTED
    one_call(before, 2 + 2 * (!decoder) + coding);
    assert(allocation_calls == 1 && free_calls == 1 && allocation_sizes[0] == 4 * (n ? n : 1));
#endif
    assert(recovered.used_bytes == raw && !memcmp(dec.data, saved, raw));
    telemetry_api(fresh, decoder ? (coding ? "masked_vbyte_decode_delta" : "masked_vbyte_decode")
        : (coding ? "masked_vbyte_decode_fromcompressedsize_delta" : "masked_vbyte_decode_fromcompressedsize"));
    telemetry_number(fresh, "native_staging_allocation_bytes", 4 * (n ? n : 1));
    telemetry_number(fresh, "native_staging_input_copy_bytes", 0);
    telemetry_number(fresh, "native_staging_output_copy_bytes", raw);
    canary(src, raw); canary(dst, encoded); canary(dec, raw);
    guarded exact = allocate(raw, 0);
    recovered = buffer(exact.data, raw, 0, TSCB_DTYPE_U32_LE_V1, 0);
    assert(tscb_decompress(fresh, &wire, &recovered) == TSCB_STATUS_OK_V1);
    assert(recovered.used_bytes == raw && !memcmp(exact.data, saved, raw));
    canary(exact, raw); release(exact);
    assert(tscb_destroy(fresh) == TSCB_STATUS_OK_V1 && tscb_destroy(h) == TSCB_STATUS_OK_V1);
    release(src); release(dst); release(dec); free(saved); free(oracle); free(upstream);
}

static void invalid_config(void) {
    const char *values[] = {"-1", "4294967296", "00", "0.0", "0e0", "+1", " 0", "1,\"x\":0", "1,\"starting_point\":0"};
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        char text[180];
        snprintf(text, sizeof(text), "{\"coding\":\"DELTA\",\"decoder_api\":\"COUNT\",\"isa\":\"SSE4_1\",\"starting_point\":%s}", values[i]);
        tscb_codec_handle_v1 *h = NULL;
        assert(tscb_create(text, strlen(text), &h) == TSCB_STATUS_INVALID_ARGUMENT_V1 && !h);
    }
    const char *invalid[] = {"{}", "null", "", "{\"isa\":\"SSE4_1\"}",
        "{\"coding\":\"PLAIN\",\"decoder_api\":\"COUNT\",\"isa\":\"SSE4_1\",\"starting_point\":1}",
        "{\"coding\":\"PLAIN\",\"decoder_api\":\"ALIEN\",\"isa\":\"SSE4_1\",\"starting_point\":0}",
        "{\"coding\":\"ALIEN\",\"decoder_api\":\"COUNT\",\"isa\":\"SSE4_1\",\"starting_point\":0}",
        "{\"coding\":\"PLAIN\",\"decoder_api\":\"COUNT\",\"isa\":\"AVX2\",\"starting_point\":0}"};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        tscb_codec_handle_v1 *h = NULL;
        assert(tscb_create(invalid[i], strlen(invalid[i]), &h) == TSCB_STATUS_INVALID_ARGUMENT_V1 && !h);
    }
    tscb_codec_handle_v1 *h = NULL;
    assert(tscb_create(NULL, UINT64_MAX, &h) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    assert(tscb_create("", 0, NULL) == TSCB_STATUS_INVALID_ARGUMENT_V1);
}
static void atomic_decode(tscb_codec_handle_v1 *h, tscb_buffer_v1 source, tscb_status_v1 expected) {
    uint8_t storage[48], saved[48]; memset(storage, 0x73, sizeof(storage)); memcpy(saved, storage, sizeof(storage));
    tscb_buffer_v1 out = buffer(storage + 1, 32, 0, TSCB_DTYPE_U32_LE_V1, 0);
#ifdef INSTRUMENTED
    unsigned before[6]; memcpy(before, api_calls, sizeof(before));
#endif
    assert(tscb_decompress(h, &source, &out) == expected);
    assert(!out.used_bytes && !memcmp(storage, saved, sizeof(storage)));
#ifdef INSTRUMENTED
    assert(!memcmp(before, api_calls, sizeof(before)));
#endif
}
static void rejection_and_lifecycle(unsigned coding, unsigned decoder) {
    uint32_t input[] = {UINT32_MAX,0,1,0x80000000U,4,3,2,1};
    uint8_t storage[160], saved[160], valid[80];
    memset(storage, 0x73, sizeof(storage)); memcpy(saved, storage, sizeof(storage));
    tscb_codec_handle_v1 *h = create(coding, decoder, coding ? UINT32_MAX : 0);
    tscb_buffer_v1 in = buffer(input, 32, 32, TSCB_DTYPE_U32_LE_V1, 1);
    tscb_buffer_v1 out = buffer(storage + 1, 39, 0, TSCB_DTYPE_BYTES_V1, 0);
    const char *text; uint64_t length;
    assert(tscb_get_accounting_json(h, &text, &length) == TSCB_STATUS_FINALIZE_REQUIRED_V1);
    assert(tscb_get_telemetry_json(h, &text, &length) == TSCB_STATUS_UNSUPPORTED_V1);
    tscb_buffer_v1 final = buffer(NULL, 0, 0, TSCB_DTYPE_BYTES_V1, 0);
    assert(tscb_finalize(h, &final) == TSCB_STATUS_FINALIZE_REQUIRED_V1);
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_DST_TOO_SMALL_V1);
    out.capacity_bytes = out.shape[0] = 40;
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_DST_TOO_SMALL_V1);
    assert(!out.used_bytes && !memcmp(storage, saved, sizeof(storage)));
    tscb_buffer_v1 alias = buffer(storage + 1, 32, 32, TSCB_DTYPE_U32_LE_V1, 1);
    out = buffer(storage + 1, 80, 0, TSCB_DTYPE_BYTES_V1, 0);
    assert(tscb_compress(h, &alias, &out) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    alias.data = storage + 9;
    assert(tscb_compress(h, &alias, &out) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    assert(!out.used_bytes && !memcmp(storage, saved, sizeof(storage)));
    tscb_buffer_v1 bad = in;
    bad.capacity_bytes = bad.used_bytes = UINT64_C(4) * 16777217; bad.shape[0] = 16777217;
    uint64_t bound = 73;
    assert(tscb_compress_bound(h, &bad, &bound) == TSCB_STATUS_UNSUPPORTED_V1 && bound == 73);
    assert(tscb_compress(h, &bad, &out) == TSCB_STATUS_UNSUPPORTED_V1);
    for (unsigned field = 0; field < 14; ++field) {
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
            case 12: bad.data = NULL; break;
            case 13: bad.alignment_bytes = 0; break;
        }
        assert(tscb_compress_bound(h, &bad, &bound) == TSCB_STATUS_INVALID_ARGUMENT_V1 && bound == 73);
        assert(tscb_compress(h, &bad, &out) == TSCB_STATUS_INVALID_ARGUMENT_V1);
        assert(!out.used_bytes && !memcmp(storage, saved, sizeof(storage)));
    }
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1);
    size_t size = (size_t)out.used_bytes; memcpy(valid, storage + 1, size);
    out.used_bytes = 0;
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_CODEC_ERROR_V1 && !out.used_bytes);
    finish(h);
    assert(tscb_finalize(h, &final) == TSCB_STATUS_CODEC_ERROR_V1);
    assert(tscb_reset(h, 1) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    assert(tscb_get_accounting_json(h, &text, &length) == TSCB_STATUS_OK_V1);
    assert(tscb_reset(h, 0) == TSCB_STATUS_OK_V1);
    assert(tscb_get_telemetry_json(h, &text, &length) == TSCB_STATUS_UNSUPPORTED_V1);
    assert(tscb_get_accounting_json(h, &text, &length) == TSCB_STATUS_FINALIZE_REQUIRED_V1);
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1 && out.used_bytes == size);
    assert(!memcmp(valid, storage + 1, size)); finish(h);
    for (size_t cut = 0; cut < size; ++cut)
        atomic_decode(h, buffer(valid, cut, cut, TSCB_DTYPE_BYTES_V1, 1), TSCB_STATUS_CODEC_ERROR_V1);
    uint8_t corrupted[81];
    for (size_t i = 0; i < size; ++i) {
        memcpy(corrupted, valid, size); corrupted[i] ^= 1;
        atomic_decode(h, buffer(corrupted, size, size, TSCB_DTYPE_BYTES_V1, 1), TSCB_STATUS_CODEC_ERROR_V1);
    }
    memcpy(corrupted, valid, size); corrupted[size] = 0;
    atomic_decode(h, buffer(corrupted, size + 1, size + 1, TSCB_DTYPE_BYTES_V1, 1), TSCB_STATUS_CODEC_ERROR_V1);
    for (unsigned field = 0; field < 6; ++field) {
        memcpy(corrupted, valid, size);
        if (field == 0) corrupted[0] ^= 1;
        if (field == 1) put(corrupted + 8, 16777217, 4);
        if (field == 2) put(corrupted + 16, 2, 4);
        if (field == 3) put(corrupted + 20, 1, 4);
        if (field == 4) put(corrupted + 24, UINT64_MAX, 8);
        if (field == 5) { put(corrupted + 16, 0, 4); put(corrupted + 12, 1, 4); }
        resign(corrupted, size);
        atomic_decode(h, buffer(corrupted, size, size, TSCB_DTYPE_BYTES_V1, 1), TSCB_STATUS_CODEC_ERROR_V1);
    }
    // Check canonical grammar after a correct wrapper checksum, before source calls.
    const uint8_t malformed[][6] = {{0x80,0}, {0xff,0xff,0xff,0xff,0x10}, {0x80},
        {0x80,0x80,0x80,0x80,0x80,0}, {1,0x80}, {0x81,0x80,0}};
    const unsigned lengths[] = {2,5,1,6,2,3}, counts[] = {1,1,1,2,2,1};
    for (unsigned i = 0; i < sizeof(lengths) / sizeof(lengths[0]); ++i) {
        memset(corrupted, 0, sizeof(corrupted)); memcpy(corrupted, "TSCBMVB1", 8);
        put(corrupted + 8, counts[i], 4); put(corrupted + 24, lengths[i], 8);
        memcpy(corrupted + 32, malformed[i], lengths[i]); resign(corrupted, 40 + lengths[i]);
        atomic_decode(h, buffer(corrupted, 40 + lengths[i], 40 + lengths[i], TSCB_DTYPE_BYTES_V1, 1), TSCB_STATUS_CODEC_ERROR_V1);
    }
    tscb_buffer_v1 wire = buffer(valid, size, size, TSCB_DTYPE_BYTES_V1, 1);
    out = buffer(storage + 1, 28, 0, TSCB_DTYPE_U32_LE_V1, 0); memcpy(saved, storage, sizeof(storage));
    assert(tscb_decompress(h, &wire, &out) == TSCB_STATUS_DST_TOO_SMALL_V1);
    assert(!out.used_bytes && !memcmp(storage, saved, sizeof(storage)));
    out = buffer(valid + 4, 32, 0, TSCB_DTYPE_U32_LE_V1, 0);
    assert(tscb_decompress(h, &wire, &out) == TSCB_STATUS_INVALID_ARGUMENT_V1 && !out.used_bytes);
    length = 73;
    assert(tscb_query(h, NULL, 0, NULL, 0, &length) == TSCB_STATUS_UNSUPPORTED_V1 && length == 73);
    assert(tscb_get_last_error(h, &text, &length) == TSCB_STATUS_OK_V1 && length);
    assert(tscb_destroy(h) == TSCB_STATUS_OK_V1);
}

#ifdef INSTRUMENTED
static void faults(unsigned coding, unsigned decoder) {
    tscb_codec_handle_v1 *h = NULL;
    const char *json = "{\"coding\":\"PLAIN\",\"decoder_api\":\"COUNT\",\"isa\":\"SSE4_1\",\"starting_point\":0}";
    calloc_fail = 1;
    assert(tscb_create(json, strlen(json), &h) == TSCB_STATUS_CODEC_ERROR_V1 && !h);
    h = create(coding, decoder, coding ? 1 : 0);
    uint32_t values[] = {UINT32_MAX,0,1,0};
    uint8_t bytes[64], saved[64], reference[64];
    tscb_buffer_v1 in = buffer(values, 16, 16, TSCB_DTYPE_U32_LE_V1, 1);
    tscb_buffer_v1 out = buffer(bytes, 64, 0, TSCB_DTYPE_BYTES_V1, 0);
    tscb_native_timing_v1 t = {sizeof(t),1,0,0}, again = t;
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_UNSUPPORTED_V1);
    assert(tscb_set_native_timing(h, 2) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    assert(tscb_set_native_timing(h, 1) == TSCB_STATUS_OK_V1);
    t.version = 2;
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_ABI_MISMATCH_V1); t.version = 1;
    clock_mode = 1; clock_tick = 100;
    for (int alloc = 0; alloc < 2; ++alloc) {
        memset(bytes, 0x73, sizeof(bytes)); memcpy(saved, bytes, sizeof(bytes));
        unsigned calls = api_calls[coding]; malloc_until_failure = alloc;
        allocation_calls = free_calls = 0;
        assert(tscb_compress(h, &in, &out) == TSCB_STATUS_CODEC_ERROR_V1);
        assert(!out.used_bytes && !memcmp(bytes, saved, sizeof(bytes)) && api_calls[coding] == calls);
        assert(free_calls == (unsigned)alloc);
        assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_OK_V1 && !t.native_encode_wall_ns);
    }
    wrong_api_length = 1;
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_CODEC_ERROR_V1);
    assert(!out.used_bytes && !memcmp(bytes, saved, sizeof(bytes)));
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_OK_V1 && t.native_encode_wall_ns == 10);
    wrong_api_length = 0;
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1); finish(h);
    size_t size = (size_t)out.used_bytes; memcpy(reference, bytes, size);
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_OK_V1 && t.native_encode_wall_ns == 20);
    assert(tscb_get_native_timing(h, &again) == TSCB_STATUS_OK_V1 && !memcmp(&t, &again, sizeof(t)));
    uint32_t restored[4], saved_values[4];
    tscb_buffer_v1 wire = buffer(bytes, size, size, TSCB_DTYPE_BYTES_V1, 1);
    tscb_buffer_v1 decoded = buffer(restored, 16, 0, TSCB_DTYPE_U32_LE_V1, 0);
    memset(restored, 0x73, sizeof(restored)); memcpy(saved_values, restored, sizeof(restored));
    unsigned calls = api_calls[2 + 2 * decoder + coding]; malloc_until_failure = 0;
    assert(tscb_decompress(h, &wire, &decoded) == TSCB_STATUS_CODEC_ERROR_V1);
    assert(!decoded.used_bytes && !memcmp(restored, saved_values, sizeof(restored)));
    assert(api_calls[2 + 2 * decoder + coding] == calls);
    wrong_api_length = 1;
    assert(tscb_decompress(h, &wire, &decoded) == TSCB_STATUS_CODEC_ERROR_V1);
    assert(!decoded.used_bytes && !memcmp(restored, saved_values, sizeof(restored)));
    wrong_api_length = 0;
    for (unsigned i = 0; i < 2; ++i) {
        decoded.used_bytes = 0;
        assert(tscb_decompress(h, &wire, &decoded) == TSCB_STATUS_OK_V1);
        assert(!memcmp(restored, values, sizeof(values)));
    }
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_OK_V1);
    assert(t.native_encode_wall_ns == 20 && t.native_decode_wall_ns == 30);
    assert(tscb_reset(h, 0) == TSCB_STATUS_OK_V1);
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_OK_V1);
    assert(!t.native_encode_wall_ns && !t.native_decode_wall_ns);
    assert(tscb_set_native_timing(h, 0) == TSCB_STATUS_OK_V1);
    out.used_bytes = 0;
    assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1); finish(h);
    assert(out.used_bytes == size && !memcmp(bytes, reference, size));
    assert(tscb_get_native_timing(h, &t) == TSCB_STATUS_UNSUPPORTED_V1);
    for (int fault = 2; fault <= 3; ++fault) {
        assert(tscb_reset(h, 0) == TSCB_STATUS_OK_V1);
        assert(tscb_set_native_timing(h, 1) == TSCB_STATUS_OK_V1);
        clock_mode = fault; clock_tick = 0; out.used_bytes = 0;
        assert(tscb_compress(h, &in, &out) == TSCB_STATUS_OK_V1); finish(h);
        assert(out.used_bytes == size && !memcmp(bytes, reference, size));
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
    assert(strstr(text, "maskedvbyte-source-u32")); invalid_config();
    const size_t lengths[] = {0,1,2,3,4,5,7,8,9,15,16,17,31,32,33,47,48,49,
        63,64,65,95,96,97,111,112,113,127,128,129,191,192,193,255,256,257,513,1000,8193};
    const uint32_t seeds[] = {0,1,0x80000000U,UINT32_MAX};
    unsigned cases = 0;
    for (unsigned coding = 0; coding < 2; ++coding)
        for (unsigned decoder = 0; decoder < 2; ++decoder) {
            rejection_and_lifecycle(coding, decoder);
#ifdef INSTRUMENTED
            faults(coding, decoder);
#endif
            for (unsigned l = 0; l < sizeof(lengths) / sizeof(lengths[0]); ++l)
                for (unsigned s = 0; s < (coding ? 4U : 1U); ++s)
                    for (unsigned pattern = 0; pattern < 6; ++pattern)
                        for (unsigned shift = 0; shift < 4; ++shift) {
                            roundtrip(lengths[l], coding, decoder, seeds[s], pattern, shift); ++cases;
                        }
        }
    puts("config/descriptor/capacity/alias/corruption/canonical LEB128/lifecycle/atomic failure PASS");
#ifdef INSTRUMENTED
    for (unsigned i = 0; i < 6; ++i) assert(api_calls[i] > 0);
    puts("six original API routes/allocation sizes and failures/API length faults/native timer faults/accumulation PASS");
#endif
    printf("MaskedVByte bounded ABI scalar/seed/coding/decoder/guard cases PASS: %u\n", cases);
    return 0;
}
