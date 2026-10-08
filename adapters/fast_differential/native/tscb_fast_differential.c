#include "tscb_native_timing.h"
#include "fastdelta.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_COUNT UINT64_C(16777216)
#define FRAME_OVERHEAD UINT64_C(32)

struct tscb_codec_handle_v1 {
    uint32_t mode, seed;
    int updated, finalized;
    tscb_native_timer native_timer;
    char last_error[256];
};

static const char MANIFEST[] =
    "{\"abi_version\":1,\"algorithm\":\"fast-differential-u32\","
    "\"isa\":\"SSE4_1\",\"encoder\":\"ORIGINAL_FOUR_API_MODE_SELECTED\","
    "\"decoder\":\"ORIGINAL_FOUR_API_MODE_SELECTED\",\"padding\":0,"
    "\"object_level\":\"P0_PRIMITIVE\",\"frame\":\"FDC1\"}";

static tscb_status_v1 fail(tscb_codec_handle_v1 *h, tscb_status_v1 status,
                           const char *message) {
    if (h) snprintf(h->last_error, sizeof(h->last_error), "%s", message);
    return status;
}

static int span(const void *p, uint64_t length) {
    return length <= SIZE_MAX && (!length || (p && length <= UINTPTR_MAX - (uintptr_t)p));
}

static int common(const tscb_buffer_v1 *b) {
    if (!b || b->rank != 1 || b->reserved || b->ownership > TSCB_OWNERSHIP_CODEC_V1
        || b->used_bytes > b->capacity_bytes || !span(b->data, b->capacity_bytes)
        || !b->alignment_bytes || b->alignment_bytes > SIZE_MAX
        || (b->alignment_bytes & (b->alignment_bytes - 1U))
        || (b->data && ((uintptr_t)b->data % b->alignment_bytes))) return 0;
    for (unsigned i = 1; i < TSCB_MAX_RANK_V1; ++i)
        if (b->shape[i] || b->strides_bytes[i]) return 0;
    return 1;
}

static int vector(const tscb_buffer_v1 *b, int source) {
    return common(b) && b->dtype == TSCB_DTYPE_U32_LE_V1
        && b->capacity_bytes % 4U == 0 && b->used_bytes % 4U == 0
        && b->strides_bytes[0] == 4
        && b->shape[0] == (source ? b->used_bytes : b->capacity_bytes) / 4U
        && (source || !b->used_bytes);
}

static int bytes(const tscb_buffer_v1 *b) {
    return common(b) && b->dtype == TSCB_DTYPE_BYTES_V1
        && b->strides_bytes[0] == 1 && b->shape[0] == b->capacity_bytes;
}

static int overlap(const void *a, uint64_t na, const void *b, uint64_t nb) {
    if (!na || !nb) return 0;
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    return x <= y ? (uint64_t)(y - x) < na : (uint64_t)(x - y) < nb;
}

static void put32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8U * i));
}

static uint32_t get32(const uint8_t *p) {
    uint32_t v = 0;
    for (unsigned i = 0; i < 4; ++i) v |= (uint32_t)p[i] << (8U * i);
    return v;
}

static void put64(uint8_t *p, uint64_t v) {
    for (unsigned i = 0; i < 8; ++i) p[i] = (uint8_t)(v >> (8U * i));
}

static uint64_t get64(const uint8_t *p) {
    uint64_t v = 0;
    for (unsigned i = 0; i < 8; ++i) v |= (uint64_t)p[i] << (8U * i);
    return v;
}

static uint64_t checksum(const uint8_t *p, uint64_t n) {
    uint64_t v = UINT64_C(14695981039346656037);
    for (uint64_t i = 0; i < n; ++i) v = (v ^ p[i]) * UINT64_C(1099511628211);
    return v;
}

static int config(const char *c, uint64_t n, uint32_t *mode, uint32_t *seed) {
    const char *prefix[2] = {
        "{\"api_mode\":\"DISTINCT\",\"isa\":\"SSE4_1\",\"starting_point\":",
        "{\"api_mode\":\"INPLACE\",\"isa\":\"SSE4_1\",\"starting_point\":"
    };
    if (!c || n > 128U) return 0;
    for (uint32_t m = 0; m < 2; ++m) {
        size_t start = strlen(prefix[m]);
        if (n <= start + 1 || memcmp(c, prefix[m], start) || c[n - 1] != '}') continue;
        if (n > start + 2 && c[start] == '0') return 0;
        uint64_t v = 0;
        for (uint64_t i = start; i < n - 1; ++i) {
            if (c[i] < '0' || c[i] > '9') return 0;
            v = v * 10U + (uint64_t)(c[i] - '0');
            if (v > UINT32_MAX) return 0;
        }
        *mode = m; *seed = (uint32_t)v; return 1;
    }
    return 0;
}

uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }

tscb_status_v1 tscb_get_manifest_json(const char **p, uint64_t *n) {
    if (!p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p = MANIFEST; *n = sizeof(MANIFEST) - 1U; return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(const char *c, uint64_t n, tscb_codec_handle_v1 **h) {
    uint32_t mode, seed;
    if (!h) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *h = NULL;
    if (!config(c, n, &mode, &seed)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
#if defined(__x86_64__) && defined(__GNUC__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    if (!__builtin_cpu_supports("sse4.1")) return TSCB_STATUS_UNSUPPORTED_V1;
#else
    return TSCB_STATUS_UNSUPPORTED_V1;
#endif
    *h = calloc(1, sizeof(**h));
    if (!*h) return TSCB_STATUS_CODEC_ERROR_V1;
    (*h)->mode = mode; (*h)->seed = seed;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *h) { free(h); return TSCB_STATUS_OK_V1; }

tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *h, uint32_t mode) {
    if (!h || mode) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    h->updated = h->finalized = 0; h->last_error[0] = '\0';
    h->native_timer.available = 1;
    h->native_timer.encode_ns = h->native_timer.decode_ns = 0;
    return TSCB_STATUS_OK_V1;
}

TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *h,
                                  const tscb_buffer_v1 *in, uint64_t *bound) {
    if (!h || !bound || !vector(in, 1)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (in->shape[0] > MAX_COUNT)
        return fail(h, TSCB_STATUS_UNSUPPORTED_V1, "count resource limit");
    *bound = FRAME_OVERHEAD + in->used_bytes; return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *h,
                            const tscb_buffer_v1 *in, tscb_buffer_v1 *out) {
    if (!h || !vector(in, 1) || !bytes(out) || out->used_bytes)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (h->updated || h->finalized)
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "update lifecycle");
    if (in->shape[0] > MAX_COUNT)
        return fail(h, TSCB_STATUS_UNSUPPORTED_V1, "count resource limit");
    if (overlap(in->data, in->used_bytes, out->data, out->capacity_bytes))
        return fail(h, TSCB_STATUS_INVALID_ARGUMENT_V1, "input/output alias");
    uint64_t length = FRAME_OVERHEAD + in->used_bytes;
    if (out->capacity_bytes < length)
        return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "bound capacity");
    size_t n = (size_t)in->shape[0], allocation = 4U * (n ? n : 1U);
    uint32_t *staged = malloc(allocation), *result = h->mode ? staged : malloc(allocation);
    if (!staged || !result) {
        if (result != staged) free(result);
        free(staged); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "staging allocation");
    }
    if (n) memcpy(staged, in->data, (size_t)in->used_bytes);
    if (h->mode) {
        TSCB_TIME_CODEC(h->native_timer, encode_ns,
            compute_deltas_inplace(staged, n, h->seed));
    } else {
        TSCB_TIME_CODEC(h->native_timer, encode_ns,
            compute_deltas(staged, n, result, h->seed));
    }
    uint8_t *p = out->data;
    memcpy(p, "TSCBFDC1", 8); put32(p + 8, (uint32_t)n);
    put32(p + 12, h->seed); put32(p + 16, h->mode); put32(p + 20, 0);
    if (n) memcpy(p + 24, result, (size_t)in->used_bytes);
    put64(p + length - 8, checksum(p, length - 8));
    if (result != staged) free(result);
    free(staged); out->used_bytes = length; h->updated = 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *h, tscb_buffer_v1 *out) {
    if (!h || !bytes(out) || out->used_bytes) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->updated) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (h->finalized) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "finalize lifecycle");
    h->finalized = 1; return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *h,
                              const tscb_buffer_v1 *in, tscb_buffer_v1 *out) {
    if (!h || !bytes(in) || !vector(out, 0)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (overlap(in->data, in->used_bytes, out->data, out->capacity_bytes))
        return fail(h, TSCB_STATUS_INVALID_ARGUMENT_V1, "input/output alias");
    if (in->used_bytes < FRAME_OVERHEAD)
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "truncated FDC1");
    const uint8_t *p = in->data;
    uint32_t n = get32(p + 8), seed = get32(p + 12), mode = get32(p + 16);
    if (memcmp(p, "TSCBFDC1", 8) || n > MAX_COUNT || mode > 1 || get32(p + 20)
        || in->used_bytes != FRAME_OVERHEAD + UINT64_C(4) * n)
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "FDC1 identity/geometry");
    if (get64(p + in->used_bytes - 8) != checksum(p, in->used_bytes - 8))
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "FDC1 checksum");
    uint64_t used = UINT64_C(4) * n;
    if (out->capacity_bytes < used)
        return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "decode capacity");
    size_t allocation = 4U * (n ? (size_t)n : 1U);
    uint32_t *staged = malloc(allocation), *result = mode ? staged : malloc(allocation);
    if (!staged || !result) {
        if (result != staged) free(result);
        free(staged); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "staging allocation");
    }
    if (n) memcpy(staged, p + 24, (size_t)used);
    if (mode) {
        TSCB_TIME_CODEC(h->native_timer, decode_ns,
            compute_prefix_sum_inplace(staged, n, seed));
    } else {
        TSCB_TIME_CODEC(h->native_timer, decode_ns,
            compute_prefix_sum(staged, n, result, seed));
    }
    if (n) memcpy(out->data, result, (size_t)used);
    if (result != staged) free(result);
    free(staged); out->used_bytes = used; return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *h,
                                       const char **p, uint64_t *n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->finalized) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    static const char value[] =
        "{\"container_bytes\":8,\"metadata_bytes\":16,\"checksum_bytes\":8,"
        "\"payload\":\"EXACT_UINT32_D1_WORDS\",\"external_padding_bytes\":0}";
    *p = value; *n = sizeof(value) - 1U; return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1 *h,
                                  const char **p, uint64_t *n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p = h->last_error; *n = strlen(*p); return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1 *h, const char *request,
                         uint64_t request_length, char *response,
                         uint64_t response_capacity, uint64_t *response_used) {
    (void)request; (void)request_length; (void)response; (void)response_capacity;
    (void)response_used;
    if (!h) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return fail(h, TSCB_STATUS_UNSUPPORTED_V1, "query unsupported");
}
