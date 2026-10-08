/* Bounded framing and ownership use the existing FastDifferential/MaskedVByte contract. */
#include "tscb_native_timing.h"
#include "simdcomp.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_COUNT UINT64_C(16777216)
#define OVERHEAD UINT64_C(48)
enum { API_LENGTH, API_MASKED, API_WITHOUTMASK, API_FULL };
enum { PLAIN, DELTA, FOR_LENGTH, FOR_FULL, AVX_PLAIN };
struct tscb_codec_handle_v1 {
    uint32_t mode, api, seed;
    int updated, finalized;
    uint64_t count, blocks, payload, value_bits, padding_bits;
    tscb_native_timer native_timer;
    char last_error[256], accounting[512], telemetry[1536];
};
uint32_t tscb_simdcomp_avx2_width(const uint32_t *, tscb_native_timer *);
void tscb_simdcomp_avx2_pack(const uint32_t *, void *, uint32_t, int, tscb_native_timer *);
void tscb_simdcomp_avx2_unpack(const void *, uint32_t *, uint32_t, tscb_native_timer *);

static tscb_status_v1 fail(tscb_codec_handle_v1 *h, tscb_status_v1 status, const char *message) {
    if (h) snprintf(h->last_error, sizeof(h->last_error), "%s", message);
    return status;
}
static int span(const void *p, uint64_t n) {
    return n <= SIZE_MAX && (!n || (p && n <= UINTPTR_MAX - (uintptr_t)p));
}
static int common(const tscb_buffer_v1 *b) {
    if (!b || b->rank != 1 || b->reserved || b->ownership > TSCB_OWNERSHIP_CODEC_V1
        || b->used_bytes > b->capacity_bytes || !span(b->data, b->capacity_bytes)
        || !b->alignment_bytes || b->alignment_bytes > SIZE_MAX
        || (b->alignment_bytes & (b->alignment_bytes - 1))
        || (b->data && (uintptr_t)b->data % b->alignment_bytes)) return 0;
    for (unsigned i = 1; i < TSCB_MAX_RANK_V1; ++i)
        if (b->shape[i] || b->strides_bytes[i]) return 0;
    return 1;
}
static int vector(const tscb_buffer_v1 *b, int source) {
    return common(b) && b->dtype == TSCB_DTYPE_U32_LE_V1
        && !(b->capacity_bytes % 4) && !(b->used_bytes % 4) && b->strides_bytes[0] == 4
        && b->shape[0] == (source ? b->used_bytes : b->capacity_bytes) / 4
        && (source || !b->used_bytes);
}
static int bytes(const tscb_buffer_v1 *b) {
    return common(b) && b->dtype == TSCB_DTYPE_BYTES_V1
        && b->strides_bytes[0] == 1 && b->shape[0] == b->capacity_bytes;
}
static int overlap(const void *a, uint64_t na, const void *b, uint64_t nb) {
    if (!na || !nb) return 0;
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    return x <= y ? (uint64_t)(y-x) < na : (uint64_t)(x-y) < nb;
}
static void put16(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static uint32_t get16(const uint8_t *p) { return p[0] | (uint32_t)p[1] << 8; }
static void put32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8*i));
}
static uint32_t get32(const uint8_t *p) {
    uint32_t v = 0;
    for (unsigned i = 0; i < 4; ++i) v |= (uint32_t)p[i] << (8*i);
    return v;
}
static void put64(uint8_t *p, uint64_t v) {
    for (unsigned i = 0; i < 8; ++i) p[i] = (uint8_t)(v >> (8*i));
}
static uint64_t get64(const uint8_t *p) {
    uint64_t v = 0;
    for (unsigned i = 0; i < 8; ++i) v |= (uint64_t)p[i] << (8*i);
    return v;
}
static uint64_t checksum(const uint8_t *p, uint64_t n) {
    uint64_t value = UINT64_C(14695981039346656037);
    for (uint64_t i = 0; i < n; ++i) value = (value ^ p[i]) * UINT64_C(1099511628211);
    return value;
}
static unsigned scalar_bits(uint32_t x) {
    unsigned width = 0;
    while (x) { ++width; x >>= 1; }
    return width;
}
static uint32_t block_size(uint32_t mode) { return mode == AVX_PLAIN ? 256 : 128; }
static uint32_t layout_for(uint32_t mode, uint32_t n) {
    return mode == DELTA || mode == FOR_FULL ? 1 : mode == AVX_PLAIN && n == 256 ? 2 : 0;
}
static uint32_t physical_count(uint32_t n, uint32_t layout) {
    return layout == 1 ? 128 : layout == 2 ? 256 : n;
}
static uint32_t payload_size(uint32_t n, uint32_t width, uint32_t layout) {
    uint32_t physical = physical_count(n, layout), lanes = layout == 2 ? 8 : 4;
    if (!width) return 0;
    if (width == 32) return physical * 4;
    return (((physical + lanes-1) / lanes * width + 31) / 32) * lanes * 4;
}
static unsigned range_width(const uint32_t *values, uint32_t n, uint32_t mode, uint32_t seed) {
    uint32_t combined = 0, previous = seed;
    for (uint32_t i = 0; i < n; ++i) {
        combined |= mode == DELTA ? values[i] - previous
            : mode == FOR_LENGTH || mode == FOR_FULL ? values[i] - seed : values[i];
        previous = values[i];
    }
    return scalar_bits(combined);
}
static int configuration(const char *c, uint64_t n, uint32_t *mode, uint32_t *api, uint32_t *seed) {
    const char *apis[] = {"LENGTH", "MASKED", "WITHOUTMASK", "FULL"};
    if (!c || n > 160 || !span(c, n)) return 0;
    for (uint32_t m = 0; m <= AVX_PLAIN; ++m) for (uint32_t a = 0; a <= API_FULL; ++a) {
        if ((m == PLAIN && a == API_FULL) || (m == DELTA && a != API_MASKED && a != API_WITHOUTMASK)
            || (m == FOR_LENGTH && a != API_LENGTH) || (m == FOR_FULL && a != API_FULL)
            || (m == AVX_PLAIN && a != API_MASKED && a != API_WITHOUTMASK)) continue;
        char prefix[128];
        int start = snprintf(prefix, sizeof(prefix),
            "{\"api\":\"%s\",\"coding\":\"%s\",\"isa\":\"%s\",\"starting_point\":",
            apis[a], m == DELTA ? "DELTA" : m == FOR_LENGTH || m == FOR_FULL ? "FOR" : "PLAIN",
            m == AVX_PLAIN ? "AVX2" : "SSE4_1");
        if (start <= 0 || n <= (uint64_t)start + 1 || memcmp(c, prefix, (size_t)start) || c[n-1] != '}') continue;
        if (n > (uint64_t)start + 2 && c[start] == '0') return 0;
        uint64_t number = 0;
        for (uint64_t i = (uint64_t)start; i < n-1; ++i) {
            if (c[i] < '0' || c[i] > '9') return 0;
            number = number * 10 + (uint64_t)(c[i]-'0');
            if (number > UINT32_MAX) return 0;
        }
        if ((m == PLAIN || m == AVX_PLAIN) && number) return 0;
        *mode = m; *api = a; *seed = (uint32_t)number; return 1;
    }
    return 0;
}
static void observe(tscb_codec_handle_v1 *h, uint32_t mode, uint64_t count, uint64_t blocks,
                    uint64_t payload, uint64_t internal_padding, uint64_t allocation,
                    uint64_t copies_in, uint64_t copies_out, uint64_t full_calls,
                    uint64_t tail_calls, int encode) {
    const char *full = mode == AVX_PLAIN ? (encode ? (h->api == API_WITHOUTMASK ? "avxpackwithoutmask" : "avxpack") : "avxunpack")
        : mode == DELTA ? (encode ? (h->api == API_WITHOUTMASK ? "simdpackwithoutmaskd1" : "simdpackd1") : "simdunpackd1")
        : mode == FOR_FULL ? (encode ? "simdpackFOR" : "simdunpackFOR")
        : mode == FOR_LENGTH ? (encode ? "simdpackFOR_length" : "simdunpackFOR_length")
        : encode ? (h->api == API_LENGTH ? "simdpack_length" : h->api == API_WITHOUTMASK ? "simdpackwithoutmask" : "simdpack")
        : h->api == API_LENGTH ? "simdunpack_length" : "simdunpack";
    const char *tail = mode == AVX_PLAIN ? (encode ? "simdpack_length" : "simdunpack_length")
        : mode == PLAIN && h->api != API_LENGTH ? (encode ? "simdpack_shortlength" : "simdunpack_shortlength") : full;
    snprintf(h->telemetry, sizeof(h->telemetry),
        "{\"actual_full_api\":\"%s\",\"actual_tail_api\":\"%s\",\"actual_isa\":\"%s\","
        "\"full_calls\":%llu,\"tail_calls\":%llu,\"blocks\":%llu,\"native_raw_bytes\":%llu,"
        "\"native_payload_bytes\":%llu,\"internal_padding_bytes\":%llu,\"external_padding_bytes\":0,"
        "\"native_staging_allocation_bytes\":%llu,\"native_staging_allocation_count\":2,"
        "\"native_staging_input_copy_bytes\":%llu,\"native_staging_output_copy_bytes\":%llu,"
        "\"scope\":\"ONE_%s_OBJECT\"}", full, tail, mode == AVX_PLAIN ? "AVX2_WITH_SSE4_1_TAIL" : "SSE4_1",
        (unsigned long long)full_calls, (unsigned long long)tail_calls, (unsigned long long)blocks,
        (unsigned long long)(count*4), (unsigned long long)payload, (unsigned long long)internal_padding,
        (unsigned long long)allocation, (unsigned long long)copies_in, (unsigned long long)copies_out,
        encode ? "ENCODE" : "DECODE");
}

uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }
tscb_status_v1 tscb_get_manifest_json(const char **p, uint64_t *n) {
    static const char manifest[] = "{\"abi_version\":1,\"algorithm\":\"simdcomp-source-u32\","
        "\"frame\":\"SBP1\",\"source_widths\":[0,32],\"external_overread\":0,\"fallback\":false}";
    if (!p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p = manifest; *n = sizeof(manifest)-1; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_create(const char *c, uint64_t n, tscb_codec_handle_v1 **h) {
    uint32_t mode, api, seed;
    if (!h) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *h = NULL;
    if (!configuration(c, n, &mode, &api, &seed)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
#if defined(__x86_64__) && defined(__GNUC__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    if (!__builtin_cpu_supports("sse4.1") || (mode == AVX_PLAIN && !__builtin_cpu_supports("avx2")))
        return TSCB_STATUS_UNSUPPORTED_V1;
#else
    return TSCB_STATUS_UNSUPPORTED_V1;
#endif
    *h = calloc(1, sizeof(**h));
    if (!*h) return TSCB_STATUS_CODEC_ERROR_V1;
    (*h)->mode = mode; (*h)->api = api; (*h)->seed = seed;
    return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *h) { free(h); return TSCB_STATUS_OK_V1; }
tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *h, uint32_t mode) {
    if (!h || mode) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    h->updated = h->finalized = 0;
    h->count = h->blocks = h->payload = h->value_bits = h->padding_bits = 0;
    h->last_error[0] = h->telemetry[0] = h->accounting[0] = '\0';
    h->native_timer.available = 1; h->native_timer.encode_ns = h->native_timer.decode_ns = 0;
    return TSCB_STATUS_OK_V1;
}
TSCB_NATIVE_TIMING_API
tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *h, const tscb_buffer_v1 *in, uint64_t *bound) {
    if (!h || !bound || !vector(in, 1)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (in->shape[0] > MAX_COUNT) return fail(h, TSCB_STATUS_UNSUPPORTED_V1, "count resource limit");
    uint64_t b = block_size(h->mode), blocks = (in->shape[0]+b-1)/b;
    *bound = OVERHEAD + blocks * (8 + b*4); return TSCB_STATUS_OK_V1;
}
static uint32_t source_width(tscb_codec_handle_v1 *h, const uint32_t *values, uint32_t n, uint32_t seed) {
    uint32_t width;
    if (h->mode == AVX_PLAIN && n == 256) return tscb_simdcomp_avx2_width(values, &h->native_timer);
    if (h->mode == DELTA) {
        TSCB_TIME_CODEC(h->native_timer, encode_ns, width = simdmaxbitsd1_length(seed, values, n));
    } else if (h->mode == FOR_LENGTH || h->mode == FOR_FULL) {
        uint32_t combined = 0;
        for (uint32_t i = 0; i < n; ++i) combined |= values[i]-seed;
        TSCB_TIME_CODEC(h->native_timer, encode_ns, width = bits(combined));
    } else {
        TSCB_TIME_CODEC(h->native_timer, encode_ns, width = maxbits_length(values, n));
    }
    return width;
}
static int source_pack(tscb_codec_handle_v1 *h, uint32_t *values, void *packed,
                       uint32_t n, uint32_t width, uint32_t seed, uint32_t size) {
    const __m128i *end = NULL;
    int has_return_pointer = 0;
    if (h->mode == AVX_PLAIN && n == 256) {
        tscb_simdcomp_avx2_pack(values, packed, width, h->api == API_WITHOUTMASK, &h->native_timer);
    } else if (h->mode == DELTA) {
        if (h->api == API_WITHOUTMASK) {
            TSCB_TIME_CODEC(h->native_timer, encode_ns, simdpackwithoutmaskd1(seed, values, packed, width));
        } else {
            TSCB_TIME_CODEC(h->native_timer, encode_ns, simdpackd1(seed, values, packed, width));
        }
    } else if (h->mode == FOR_FULL) {
        TSCB_TIME_CODEC(h->native_timer, encode_ns, simdpackFOR(seed, values, packed, width));
    } else if (h->mode == FOR_LENGTH) {
        has_return_pointer = 1;
        TSCB_TIME_CODEC(h->native_timer, encode_ns, end = simdpackFOR_length(seed, values, (int)n, packed, width));
    } else if (h->mode == AVX_PLAIN || h->api == API_LENGTH) {
        has_return_pointer = 1;
        TSCB_TIME_CODEC(h->native_timer, encode_ns, end = simdpack_length(values, n, packed, width));
    } else if (n < 128) {
        has_return_pointer = 1;
        TSCB_TIME_CODEC(h->native_timer, encode_ns, end = simdpack_shortlength(values, (int)n, packed, width));
    } else if (h->api == API_WITHOUTMASK) {
        TSCB_TIME_CODEC(h->native_timer, encode_ns, simdpackwithoutmask(values, packed, width));
    } else {
        TSCB_TIME_CODEC(h->native_timer, encode_ns, simdpack(values, packed, width));
    }
    return !has_return_pointer || (const uint8_t *)end == (const uint8_t *)packed + size;
}
tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *h, const tscb_buffer_v1 *in, tscb_buffer_v1 *out) {
    uint64_t bound;
    if (!h || !vector(in, 1) || !bytes(out) || out->used_bytes) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (h->updated || h->finalized) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "update lifecycle");
    tscb_status_v1 status = tscb_compress_bound(h, in, &bound);
    if (status) return status;
    if (overlap(in->data, in->capacity_bytes, out->data, out->capacity_bytes))
        return fail(h, TSCB_STATUS_INVALID_ARGUMENT_V1, "input/output alias");
    if (out->capacity_bytes < OVERHEAD) return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "frame capacity");
    uint32_t b = block_size(h->mode), count = (uint32_t)in->shape[0];
    uint64_t blocks = (count+(uint64_t)b-1)/b, at = 40, payload = 0, value_bits = 0, padding = 0;
    uint32_t previous = h->seed;
    uint8_t *frame = malloc((size_t)bound);
    void *stage = NULL;
    if (!frame || posix_memalign(&stage, 32, b*8)) {
        free(frame); free(stage); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "staging allocation");
    }
    uint32_t *values = stage;
    uint8_t *packed = (uint8_t *)stage+b*4;
    for (uint32_t start = 0; start < count;) {
        uint32_t n = count-start < b ? count-start : b, layout = layout_for(h->mode, n);
        memcpy(values, (const uint8_t *)in->data + (uint64_t)start*4, n*4);
        uint32_t seed = h->mode == DELTA ? previous : h->seed;
        uint32_t width = source_width(h, values, n, seed);
        if (width > 32 || width != range_width(values, n, h->mode, seed)) {
            free(stage); free(frame); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "source width differs");
        }
        for (uint32_t i = n; i < b; ++i) values[i] = h->mode == DELTA ? values[n-1] : h->seed;
        uint32_t size = payload_size(n, width, layout);
        memset(packed, 0, b*4);
        if (!source_pack(h, values, packed, n, width, seed, size)) {
            free(stage); free(frame); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "source pack length differs");
        }
        put16(frame+at, n); frame[at+2] = (uint8_t)width; frame[at+3] = (uint8_t)layout;
        put32(frame+at+4, size); memcpy(frame+at+8, packed, size); at += 8+size;
        payload += size; value_bits += (uint64_t)n*width;
        if (layout == 1) padding += (uint64_t)(128-n)*4;
        previous = values[n-1]; start += n;
    }
    free(stage);
    uint64_t total = at+8;
    if (out->capacity_bytes < total) {
        free(frame); return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "exact object capacity");
    }
    memcpy(frame, "TSCBSBP1", 8); put32(frame+8, count); put32(frame+12, h->seed);
    put32(frame+16, h->mode); put32(frame+20, b); put32(frame+24, (uint32_t)blocks);
    put32(frame+28, 0); put64(frame+32, at-40); put64(frame+at, checksum(frame, at));
    memcpy(out->data, frame, (size_t)total); free(frame); out->used_bytes = total;
    h->count = count; h->blocks = blocks; h->payload = payload; h->value_bits = value_bits;
    h->padding_bits = payload*8-value_bits; h->updated = 1;
    uint64_t tails = count % b ? 1 : 0;
    observe(h, h->mode, count, blocks, payload, padding, bound+b*8, count*4,
            payload+total, blocks-tails, tails, 1);
    return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *h, tscb_buffer_v1 *out) {
    if (!h || !bytes(out) || out->used_bytes) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->updated) return fail(h, TSCB_STATUS_FINALIZE_REQUIRED_V1, "update required");
    if (h->finalized) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "already finalized");
    h->finalized = 1; return TSCB_STATUS_OK_V1;
}
/* Validate all unused serialized bits; source reconstruction is not used here. */
static int canonical_padding(const uint8_t *p, uint32_t n, uint32_t width, uint32_t layout,
                              uint32_t mode, uint32_t seed, uint32_t size) {
    if (!width) return 1;
    if (width == 32) {
        if (layout == 1) {
            uint32_t required = mode == DELTA ? get32(p+(n-1)*4) : seed;
            for (uint32_t i = n; i < 128; ++i) if (get32(p+i*4) != required) return 0;
        }
        return 1;
    }
    uint32_t lanes = layout == 2 ? 8 : 4, words = size/(lanes*4);
    for (uint32_t lane = 0; lane < lanes; ++lane) {
        uint32_t values = n > lane ? (n-1-lane)/lanes+1 : 0, valid = values*width;
        for (uint32_t word = valid/32; word < words; ++word) {
            uint32_t bits_ = word*32 < valid ? valid-word*32 : 0;
            uint32_t value = get32(p+(word*lanes+lane)*4);
            if (value >> bits_) return 0; /* bits_ is 0..31, never 32 */
        }
    }
    return 1;
}
static int source_unpack(tscb_codec_handle_v1 *h, const void *packed, uint32_t *values,
                         uint32_t n, uint32_t width, uint32_t seed, uint32_t size) {
    const __m128i *end = NULL;
    int has_return_pointer = 0;
    if (h->mode == AVX_PLAIN && n == 256) {
        tscb_simdcomp_avx2_unpack(packed, values, width, &h->native_timer);
    } else if (h->mode == DELTA) {
        TSCB_TIME_CODEC(h->native_timer, decode_ns, simdunpackd1(seed, packed, values, width));
    } else if (h->mode == FOR_FULL) {
        TSCB_TIME_CODEC(h->native_timer, decode_ns, simdunpackFOR(seed, packed, values, width));
    } else if (h->mode == FOR_LENGTH) {
        has_return_pointer = 1;
        TSCB_TIME_CODEC(h->native_timer, decode_ns, end = simdunpackFOR_length(seed, packed, (int)n, values, width));
    } else if (h->mode == AVX_PLAIN || h->api == API_LENGTH) {
        has_return_pointer = 1;
        TSCB_TIME_CODEC(h->native_timer, decode_ns, end = simdunpack_length(packed, n, values, width));
    } else if (n < 128) {
        has_return_pointer = 1;
        TSCB_TIME_CODEC(h->native_timer, decode_ns, end = simdunpack_shortlength(packed, (int)n, values, width));
    } else {
        TSCB_TIME_CODEC(h->native_timer, decode_ns, simdunpack(packed, values, width));
    }
    return !has_return_pointer || (const uint8_t *)end == (const uint8_t *)packed+size;
}
tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *h, const tscb_buffer_v1 *in, tscb_buffer_v1 *out) {
    if (!h || !bytes(in) || !vector(out, 0)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (overlap(in->data, in->capacity_bytes, out->data, out->capacity_bytes))
        return fail(h, TSCB_STATUS_INVALID_ARGUMENT_V1, "input/output alias");
    const uint8_t *p = in->data;
    if (in->used_bytes < OVERHEAD || memcmp(p, "TSCBSBP1", 8))
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "frame magic/length");
    uint32_t count = get32(p+8), seed = get32(p+12), mode = get32(p+16), b = get32(p+20), blocks = get32(p+24);
    uint64_t body = get64(p+32), at = 40;
    if (count > MAX_COUNT || mode != h->mode || b != block_size(mode) || get32(p+28)
        || blocks != ((uint64_t)count+b-1)/b || body != in->used_bytes-OVERHEAD
        || ((mode == PLAIN || mode == AVX_PLAIN) && seed)
        || checksum(p, in->used_bytes-8) != get64(p+in->used_bytes-8))
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "frame identity/geometry/checksum");
    if (out->capacity_bytes < (uint64_t)count*4)
        return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "decode capacity");
    for (uint32_t start = 0; start < count;) {
        if (at > in->used_bytes-8 || in->used_bytes-8-at < 8)
            return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "truncated block record");
        uint32_t n = count-start < b ? count-start : b, width = p[at+2], layout = p[at+3], size = get32(p+at+4);
        if (get16(p+at) != n || width > 32 || layout != layout_for(mode, n)
            || size != payload_size(n, width, layout) || size > in->used_bytes-8-at-8
            || !canonical_padding(p+at+8, n, width, layout, mode, seed, size))
            return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "block geometry/padding");
        at += 8+size; start += n;
    }
    if (at != in->used_bytes-8) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "trailing frame bytes");
    uint64_t raw = (uint64_t)count*4, payload = 0, padding = 0;
    uint8_t *restored = malloc((size_t)(raw ? raw : 1));
    void *stage = NULL;
    if (!restored || posix_memalign(&stage, 32, b*8)) {
        free(restored); free(stage); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "decode allocation");
    }
    uint32_t *values = stage, previous = seed;
    uint8_t *packed = (uint8_t *)stage+b*4; at = 40;
    for (uint32_t start = 0; start < count;) {
        uint32_t n = get16(p+at), width = p[at+2], layout = p[at+3], size = get32(p+at+4);
        memset(stage, 0, b*8); memcpy(packed, p+at+8, size);
        uint32_t base = mode == DELTA ? previous : seed;
        if (!source_unpack(h, packed, values, n, width, base, size)
            || range_width(values, n, mode, base) != width) {
            free(stage); free(restored); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "source decode/width differs");
        }
        if (layout == 1) {
            uint32_t required = mode == DELTA ? values[n-1] : seed;
            for (uint32_t i = n; i < 128; ++i) if (values[i] != required) {
                free(stage); free(restored); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "source padded reconstruction differs");
            }
            padding += (uint64_t)(128-n)*4;
        }
        memcpy(restored+(uint64_t)start*4, values, n*4);
        previous = values[n-1]; payload += size; at += 8+size; start += n;
    }
    free(stage);
    if (raw) memcpy(out->data, restored, (size_t)raw);
    free(restored); out->used_bytes = raw;
    uint64_t tails = count % b ? 1 : 0;
    observe(h, mode, count, blocks, payload, padding, (raw ? raw : 1)+b*8, payload,
            raw*2, blocks-tails, tails, 0);
    return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *h, const char **p, uint64_t *n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->finalized) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    snprintf(h->accounting, sizeof(h->accounting),
        "{\"container_bytes\":8,\"metadata_bytes\":%llu,\"checksum_bytes\":8,\"payload_bytes\":%llu,"
        "\"value_bits\":%llu,\"padding_bits\":%llu,\"count\":%llu,\"blocks\":%llu}",
        (unsigned long long)(32+h->blocks*8), (unsigned long long)h->payload,
        (unsigned long long)h->value_bits, (unsigned long long)h->padding_bits,
        (unsigned long long)h->count, (unsigned long long)h->blocks);
    *p = h->accounting; *n = strlen(*p); return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_get_telemetry_json(tscb_codec_handle_v1 *h, const char **p, uint64_t *n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->telemetry[0]) return TSCB_STATUS_UNSUPPORTED_V1;
    *p = h->telemetry; *n = strlen(*p); return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1 *h, const char **p, uint64_t *n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p = h->last_error; *n = strlen(*p); return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_query(tscb_codec_handle_v1 *h, const char *request, uint64_t n,
                         char *response, uint64_t capacity, uint64_t *used) {
    (void)request; (void)n; (void)response; (void)capacity; (void)used;
    return h ? fail(h, TSCB_STATUS_UNSUPPORTED_V1, "query workload not admitted") : TSCB_STATUS_INVALID_ARGUMENT_V1;
}
