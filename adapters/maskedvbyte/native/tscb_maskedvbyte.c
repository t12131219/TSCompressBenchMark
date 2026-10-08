/* Descriptor/range helpers follow the existing bounded FastDifferential shim. */
#include "tscb_native_timing.h"
#include "varintencode.h"
#include "varintdecode.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_COUNT UINT64_C(16777216)
#define FRAME_OVERHEAD UINT64_C(40)
struct tscb_codec_handle_v1 {
    uint32_t coding, decoder, seed;
    int updated, finalized;
    uint64_t payload_bytes, count;
    tscb_native_timer native_timer;
    char last_error[256], telemetry[768], accounting[256];
};
static const char MANIFEST[] =
    "{\"abi_version\":1,\"algorithm\":\"maskedvbyte-source-u32\","
    "\"isa\":\"SSE4_1\",\"encoder\":\"ORIGINAL_PLAIN_OR_DELTA\","
    "\"decoder\":\"ORIGINAL_COUNT_OR_COMPRESSED_SIZE\",\"padding\":0,"
    "\"frame\":\"MVB1\",\"source_patch\":\"UNSIGNED_SHIFTS_ONLY\"}";

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

static int config(const char *c, uint64_t n, uint32_t *coding,
                  uint32_t *decoder, uint32_t *seed) {
    if (!c || n > 160U || !span(c, n)) return 0;
    for (uint32_t code = 0; code < 2; ++code)
        for (uint32_t dec = 0; dec < 2; ++dec) {
            char prefix[128];
            int start = snprintf(prefix, sizeof(prefix),
                "{\"coding\":\"%s\",\"decoder_api\":\"%s\",\"isa\":\"SSE4_1\",\"starting_point\":",
                code ? "DELTA" : "PLAIN", dec ? "COMPRESSED_SIZE" : "COUNT");
            if (start <= 0 || n <= (uint64_t)start + 1 ||
                memcmp(c, prefix, (size_t)start) || c[n - 1] != '}') continue;
            if (n > (uint64_t)start + 2 && c[start] == '0') return 0;
            uint64_t value = 0;
            for (uint64_t i = (uint64_t)start; i < n - 1; ++i) {
                if (c[i] < '0' || c[i] > '9') return 0;
                value = value * 10U + (uint64_t)(c[i] - '0');
                if (value > UINT32_MAX) return 0;
            }
            if (!code && value) return 0;
            *coding = code; *decoder = dec; *seed = (uint32_t)value; return 1;
        }
    return 0;
}

/* Validate canonical uint32 LEB128/count before entering the unbounded decoder.
 * This scanner validates grammar only; recovery remains the original SIMD API. */
static int validate_vbyte(const uint8_t *p, uint64_t bytes_, uint32_t count) {
    uint64_t at = 0;
    for (uint32_t i = 0; i < count; ++i) {
        unsigned width = 0;
        for (;;) {
            if (at == bytes_ || width == 5) return 0;
            uint8_t byte = p[at++]; ++width;
            if (width == 5 && byte > 15U) return 0;
            if (!(byte & 128U)) {
                if (width > 1 && byte == 0) return 0;
                break;
            }
        }
    }
    return at == bytes_;
}

static void telemetry(tscb_codec_handle_v1 *h, uint32_t coding, uint64_t count,
                       uint64_t payload, int encode) {
    const char *api = encode ? (coding ? "vbyte_encode_delta" : "vbyte_encode")
        : h->decoder ? (coding ? "masked_vbyte_decode_fromcompressedsize_delta"
                                : "masked_vbyte_decode_fromcompressedsize")
                     : (coding ? "masked_vbyte_decode_delta" : "masked_vbyte_decode");
    uint64_t staging = UINT64_C(4) * (count ? count : 1);
    if (encode) staging += payload ? payload : 1;
    snprintf(h->telemetry, sizeof(h->telemetry),
        "{\"actual_original_api\":\"%s\",\"coding\":\"%s\","
        "\"decoder_api\":\"%s\",\"internal_padding_bytes\":0,"
        "\"native_payload_bytes\":%llu,\"native_raw_bytes\":%llu,"
        "\"native_staging_allocation_bytes\":%llu,\"native_staging_allocation_count\":%u,"
        "\"native_staging_input_copy_bytes\":%llu,\"native_staging_output_copy_bytes\":%llu,"
        "\"scope\":\"ONE_%s_OBJECT\"}", api, coding ? "DELTA" : "PLAIN",
        h->decoder ? "COMPRESSED_SIZE" : "COUNT", (unsigned long long)payload,
        (unsigned long long)(4U * count), (unsigned long long)staging, encode ? 2U : 1U,
        (unsigned long long)(encode ? 4U * count : 0),
        (unsigned long long)(encode ? payload : 4U * count), encode ? "ENCODE" : "DECODE");
}

uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }
tscb_status_v1 tscb_get_manifest_json(const char **p, uint64_t *n) {
    if (!p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p = MANIFEST; *n = sizeof(MANIFEST) - 1U; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_create(const char *c, uint64_t n, tscb_codec_handle_v1 **h) {
    uint32_t coding, decoder, seed;
    if (!h) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *h = NULL;
    if (!config(c, n, &coding, &decoder, &seed)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
#if defined(__x86_64__) && defined(__GNUC__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    if (!__builtin_cpu_supports("sse4.1")) return TSCB_STATUS_UNSUPPORTED_V1;
#else
    return TSCB_STATUS_UNSUPPORTED_V1;
#endif
    *h = calloc(1, sizeof(**h));
    if (!*h) return TSCB_STATUS_CODEC_ERROR_V1;
    (*h)->coding = coding; (*h)->decoder = decoder; (*h)->seed = seed;
    return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *h) { free(h); return TSCB_STATUS_OK_V1; }
tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *h, uint32_t mode) {
    if (!h || mode) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    h->updated = h->finalized = 0; h->payload_bytes = h->count = 0;
    h->last_error[0] = h->telemetry[0] = h->accounting[0] = '\0';
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
    *bound = FRAME_OVERHEAD + UINT64_C(5) * in->shape[0]; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *h,
                            const tscb_buffer_v1 *in, tscb_buffer_v1 *out) {
    if (!h || !vector(in, 1) || !bytes(out) || out->used_bytes)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (h->updated || h->finalized) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "update lifecycle");
    if (in->shape[0] > MAX_COUNT) return fail(h, TSCB_STATUS_UNSUPPORTED_V1, "count resource limit");
    if (overlap(in->data, in->used_bytes, out->data, out->capacity_bytes))
        return fail(h, TSCB_STATUS_INVALID_ARGUMENT_V1, "input/output alias");
    if (out->capacity_bytes < FRAME_OVERHEAD)
        return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "frame capacity");
    size_t count = (size_t)in->shape[0];
    uint32_t *staged = malloc(4U * (count ? count : 1));
    if (!staged) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "staging allocation");
    if (count) memcpy(staged, in->data, (size_t)in->used_bytes);
    uint64_t payload = 0;
    uint32_t prev = h->seed;
    for (size_t i = 0; i < count; ++i) {
        uint32_t value = h->coding ? staged[i] - prev : staged[i]; prev = staged[i];
        do { ++payload; value >>= 7; } while (value);
    }
    uint64_t total = FRAME_OVERHEAD + payload;
    if (out->capacity_bytes < total) {
        free(staged); return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "exact payload capacity");
    }
    uint8_t *encoded = malloc((size_t)(payload ? payload : 1));
    if (!encoded) { free(staged); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "payload allocation"); }
    size_t written = 0;
    if (h->coding) {
        TSCB_TIME_CODEC(h->native_timer, encode_ns, written = vbyte_encode_delta(staged, count, encoded, h->seed));
    } else {
        TSCB_TIME_CODEC(h->native_timer, encode_ns, written = vbyte_encode(staged, count, encoded));
    }
    if (written != payload) {
        free(encoded); free(staged); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "original encode length differs");
    }
    uint8_t *p = out->data;
    memcpy(p, "TSCBMVB1", 8); put32(p + 8, (uint32_t)count); put32(p + 12, h->seed);
    put32(p + 16, h->coding); put32(p + 20, 0); put64(p + 24, payload);
    if (payload) memcpy(p + 32, encoded, (size_t)payload);
    put64(p + total - 8, checksum(p, total - 8));
    free(encoded); free(staged);
    out->used_bytes = total; h->payload_bytes = payload; h->count = count; h->updated = 1;
    telemetry(h, h->coding, count, payload, 1); return TSCB_STATUS_OK_V1;
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
    if (in->used_bytes < FRAME_OVERHEAD) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "truncated MVB1");
    const uint8_t *p = in->data;
    uint32_t count = get32(p + 8), seed = get32(p + 12), coding = get32(p + 16);
    uint64_t payload = get64(p + 24);
    if (memcmp(p, "TSCBMVB1", 8) || count > MAX_COUNT || coding > 1 || get32(p + 20)
        || (!coding && seed) || payload < count || payload > UINT64_C(5) * count
        || in->used_bytes != FRAME_OVERHEAD + payload)
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "MVB1 identity/geometry");
    if (get64(p + in->used_bytes - 8) != checksum(p, in->used_bytes - 8))
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "MVB1 checksum");
    if (!validate_vbyte(p + 32, payload, count))
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "noncanonical or truncated uint32 VByte");
    uint64_t raw = UINT64_C(4) * count;
    if (out->capacity_bytes < raw) return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "decode capacity");
    uint32_t *decoded = malloc(4U * (count ? (size_t)count : 1));
    if (!decoded) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "decode allocation");
    size_t observed = 0;
    if (h->decoder) {
        if (coding) {
            TSCB_TIME_CODEC(h->native_timer, decode_ns, observed = masked_vbyte_decode_fromcompressedsize_delta(p + 32, decoded, (size_t)payload, seed));
        } else {
            TSCB_TIME_CODEC(h->native_timer, decode_ns, observed = masked_vbyte_decode_fromcompressedsize(p + 32, decoded, (size_t)payload));
        }
    } else if (coding) {
        TSCB_TIME_CODEC(h->native_timer, decode_ns, observed = masked_vbyte_decode_delta(p + 32, decoded, count, seed));
    } else {
        TSCB_TIME_CODEC(h->native_timer, decode_ns, observed = masked_vbyte_decode(p + 32, decoded, count));
    }
    if (observed != (h->decoder ? count : payload)) {
        free(decoded); return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "original decode length differs");
    }
    if (raw) memcpy(out->data, decoded, (size_t)raw);
    free(decoded); out->used_bytes = raw;
    telemetry(h, coding, count, payload, 0); return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *h, const char **p, uint64_t *n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->finalized) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    snprintf(h->accounting, sizeof(h->accounting),
        "{\"container_bytes\":8,\"metadata_bytes\":24,\"checksum_bytes\":8,"
        "\"payload_bytes\":%llu,\"count\":%llu,\"external_padding_bytes\":0}",
        (unsigned long long)h->payload_bytes, (unsigned long long)h->count);
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
tscb_status_v1 tscb_query(tscb_codec_handle_v1 *h, const char *request,
                         uint64_t request_length, char *response,
                         uint64_t response_capacity, uint64_t *response_used) {
    (void)request; (void)request_length; (void)response; (void)response_capacity; (void)response_used;
    if (!h) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return fail(h, TSCB_STATUS_UNSUPPORTED_V1, "Benchmark query workload not admitted");
}
