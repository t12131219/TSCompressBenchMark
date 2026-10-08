#include "tscb_native_timing.h"
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(TSCB_SVB_MODERN)
#include "streamvbyte.h"
#define BACKEND_ENCODE(p,v,n) streamvbyte_encode(v,n,(p)+4U)
#define BACKEND_DECODE(v,p,n) streamvbyte_decode((p)+4U,v,n)
#define ENCODER_NAME "UPSTREAM_SSE4_1_WITH_SCALAR_TAIL"
#else
/* Public C entry points retained in the frozen FastPFOR/lzbench translation unit. */
extern uint64_t svb_encode(uint8_t *, uint32_t *, uint32_t, int, int);
extern uint64_t svb_decode(uint32_t *, uint8_t *, int, int);
#define BACKEND_ENCODE(p,v,n) svb_encode(p,v,n,0,1)
#define BACKEND_DECODE(v,p,n) svb_decode(v,p,0,5)
#define ENCODER_NAME "UPSTREAM_SCALAR"
#endif

#ifndef TSCB_SVB_DELTA64
#define TSCB_SVB_DELTA64 0
#endif
#if TSCB_SVB_DELTA64
#ifndef KEY
#define KEY "delta-zigzag-streamvbyte64"
#endif
#define DTYPE TSCB_DTYPE_I64_LE_V1
#define WIDTH 8U
#define PREFIX 20U
#define STAGE_VERSION "1"
#else
#ifndef KEY
#define KEY "streamvbyte-u32"
#endif
#define DTYPE TSCB_DTYPE_U32_LE_V1
#define WIDTH 4U
#define PREFIX 0U
#define STAGE_VERSION "0"
#endif
#define MAX_COUNT 16777216U

struct tscb_codec_handle_v1 {
    int updated, finalized;
    tscb_native_timer native_timer;
    char last_error[256];
};
static const char MANIFEST[] = "{\"abi_version\":1,\"algorithm\":\"" KEY
    "\",\"isa\":\"SSE4_1\",\"encoder\":\"" ENCODER_NAME "\","
    "\"decoder\":\"UPSTREAM_SSE4_1_WITH_SCALAR_TAIL\",\"padding\":16,\"stage_api_version\":" STAGE_VERSION "}";

static tscb_status_v1 fail(tscb_codec_handle_v1 *h, tscb_status_v1 s, const char *m) {
    if (h) snprintf(h->last_error, sizeof(h->last_error), "%s", m);
    return s;
}
static int vector(const tscb_buffer_v1 *b, int source) {
    return b && b->rank == 1 && b->dtype == DTYPE && b->reserved == 0
        && b->used_bytes <= b->capacity_bytes && b->capacity_bytes % WIDTH == 0
        && b->used_bytes % WIDTH == 0 && b->strides_bytes[0] == WIDTH
        && b->shape[0] == (source ? b->used_bytes : b->capacity_bytes) / WIDTH
        && (b->capacity_bytes == 0 || b->data)
        && (source || b->used_bytes == 0)
        && b->shape[0] <= MAX_COUNT;
}
static int bytes(const tscb_buffer_v1 *b) {
    return b && b->rank == 1 && b->dtype == TSCB_DTYPE_BYTES_V1 && b->reserved == 0
        && b->used_bytes <= b->capacity_bytes && b->shape[0] == b->capacity_bytes
        && b->strides_bytes[0] == 1 && (b->capacity_bytes == 0 || b->data);
}
static uint32_t words_for(uint32_t n) {
    return TSCB_SVB_DELTA64 ? (n ? 2U * (n - 1U) : 0U) : n;
}
static uint64_t bound_for(uint32_t n) {
    uint64_t w = words_for(n);
    return PREFIX + 4U + (w + 3U) / 4U + 4U * w;
}
static uint32_t read32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static int valid_payload(const uint8_t *p, uint64_t len, uint32_t count) {
    uint64_t k = ((uint64_t)count + 3U) / 4U, need = 4U + k;
    if (len < need || read32(p) != count) return 0;
    for (uint32_t i = 0; i < count; ++i)
        need += ((p[4U + i / 4U] >> (2U * (i % 4U))) & 3U) + 1U;
    if (count % 4U && (p[4U + k - 1U] >> (2U * (count % 4U)))) return 0;
    return len == need;
}

uint32_t tscb_get_abi_version(void) { return 1; }
tscb_status_v1 tscb_get_manifest_json(const char **p, uint64_t *n) {
    if (!p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p = MANIFEST; *n = sizeof(MANIFEST) - 1U; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_create(const char *c, uint64_t n, tscb_codec_handle_v1 **h) {
    static const char expected[] = "{\"isa\":\"SSE4_1\"}";
    if (!h) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *h = NULL;
    if (!c || n != sizeof(expected)-1U || memcmp(c, expected, n))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
#if defined(__x86_64__) && defined(__GNUC__)
    if (!__builtin_cpu_supports("sse4.1")) return TSCB_STATUS_UNSUPPORTED_V1;
#else
    return TSCB_STATUS_UNSUPPORTED_V1;
#endif
    *h = calloc(1, sizeof(**h));
    return *h ? TSCB_STATUS_OK_V1 : TSCB_STATUS_CODEC_ERROR_V1;
}
tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *h) { free(h); return TSCB_STATUS_OK_V1; }
tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *h, uint32_t mode) {
    if (!h || mode) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    int enabled = h->native_timer.enabled;
    memset(h, 0, sizeof(*h)); h->native_timer.enabled = enabled;
    h->native_timer.available = 1; return TSCB_STATUS_OK_V1;
}
TSCB_NATIVE_TIMING_API
tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1 *h, const tscb_buffer_v1 *in, uint64_t *b) {
    if (!h || !b || !vector(in, 1)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *b = bound_for((uint32_t)in->shape[0]); return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_compress(tscb_codec_handle_v1 *h, const tscb_buffer_v1 *in, tscb_buffer_v1 *out) {
    if (!h || !vector(in, 1) || !bytes(out) || out->used_bytes)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (h->updated || h->finalized) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "update lifecycle");
    uint32_t n = (uint32_t)in->shape[0], w = words_for(n);
    uint64_t bound = bound_for(n);
    if (out->capacity_bytes < bound) return fail(h, TSCB_STATUS_DST_TOO_SMALL_V1, "bound capacity");
    uint32_t *values = calloc(w ? w : 1U, 4);
    uint8_t *encoded = calloc((size_t)bound + 16U, 1);
    if (!values || !encoded) { free(values); free(encoded); return TSCB_STATUS_CODEC_ERROR_V1; }
#if TSCB_SVB_DELTA64
    memcpy(encoded, "TSCBS641", 8); memcpy(encoded + 8, &n, 4);
    int64_t prev = 0;
    if (n) { memcpy(&prev, in->data, 8); memcpy(encoded + 12, &prev, 8); }
    for (uint32_t i = 1; i < n; ++i) {
        int64_t cur, d;
        memcpy(&cur, (const uint8_t *)in->data + 8U*(uint64_t)i, 8);
        if (__builtin_sub_overflow(cur, prev, &d)) {
            free(values); free(encoded);
            return fail(h, TSCB_STATUS_UNSUPPORTED_V1, "checked int64 delta overflow");
        }
        uint64_t z = ((uint64_t)d << 1U) ^ (uint64_t)-(d < 0);
        values[2U*(i-1U)] = (uint32_t)z; values[2U*(i-1U)+1U] = (uint32_t)(z >> 32U);
        prev = cur;
    }
#else
    if (n) memcpy(values, in->data, 4U*(uint64_t)n);
#endif
    uint64_t used;
#if defined(TSCB_SVB_MODERN)
    memcpy(encoded + PREFIX,&w,4);
#endif
    TSCB_TIME_CODEC(h->native_timer, encode_ns,
        used = BACKEND_ENCODE(encoded + PREFIX, values, w));
#if defined(TSCB_SVB_MODERN)
    used += 4U;
#endif
    used += PREFIX;
    if (used > bound) { free(values); free(encoded); return TSCB_STATUS_CODEC_ERROR_V1; }
    memcpy(out->data, encoded, (size_t)used); out->used_bytes = used;
    free(values); free(encoded); h->updated = 1; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_finalize(tscb_codec_handle_v1 *h, tscb_buffer_v1 *out) {
    if (!h || !bytes(out)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->updated) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (h->finalized) return TSCB_STATUS_CODEC_ERROR_V1;
    out->used_bytes = 0; h->finalized = 1; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_decompress(tscb_codec_handle_v1 *h, const tscb_buffer_v1 *in, tscb_buffer_v1 *out) {
    if (!h || !bytes(in) || !vector(out, 0)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    uint32_t n = (uint32_t)out->shape[0], w = words_for(n);
    const uint8_t *p = in->data;
    if (in->used_bytes < PREFIX + 4U) return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "truncated stream");
#if TSCB_SVB_DELTA64
    if (memcmp(p, "TSCBS641", 8) || read32(p + 8) != n
        || (!n && memcmp(p + 12, "\0\0\0\0\0\0\0\0", 8)))
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "pipeline identity/count");
#endif
    if (!valid_payload(p + PREFIX, in->used_bytes - PREFIX, w))
        return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "malformed control/data stream");
    uint8_t *padded = calloc((size_t)in->used_bytes + 16U, 1);
    uint32_t *values = calloc(w ? w : 1U, 4);
    uint8_t *decoded = calloc(n ? n : 1U, WIDTH);
    if (!padded || !values || !decoded) {
        free(padded); free(values); free(decoded); return TSCB_STATUS_CODEC_ERROR_V1;
    }
    memcpy(padded, p, (size_t)in->used_bytes);
    uint64_t consumed;
    TSCB_TIME_CODEC(h->native_timer, decode_ns,
        consumed = BACKEND_DECODE(values, padded + PREFIX, w));
#if defined(TSCB_SVB_MODERN)
    consumed += 4U;
#endif
    if (w && consumed != in->used_bytes - PREFIX) {
        free(padded); free(values); free(decoded); return TSCB_STATUS_CODEC_ERROR_V1;
    }
#if TSCB_SVB_DELTA64
    int64_t prev; memcpy(&prev, p + 12, 8);
    if (n) memcpy(decoded, &prev, 8);
    for (uint32_t i = 1; i < n; ++i) {
        uint64_t z = values[2U*(i-1U)] | ((uint64_t)values[2U*(i-1U)+1U] << 32U);
        uint64_t bits = (z >> 1U) ^ (uint64_t)-(int64_t)(z & 1U);
        int64_t d, cur; memcpy(&d, &bits, 8);
        if (__builtin_add_overflow(prev, d, &cur)) {
            free(padded); free(values); free(decoded);
            return fail(h, TSCB_STATUS_CODEC_ERROR_V1, "checked int64 recovery overflow");
        }
        memcpy(decoded + 8U*(uint64_t)i, &cur, 8); prev = cur;
    }
#else
    if (n) memcpy(decoded, values, 4U*(uint64_t)n);
#endif
    if (n) memcpy(out->data, decoded, WIDTH*(uint64_t)n);
    out->used_bytes = WIDTH*(uint64_t)n;
    free(padded); free(values); free(decoded); return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1 *h, const char **p, uint64_t *n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->finalized) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    *p = "{}"; *n = 2; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1 *h, const char **p, uint64_t *n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p = h->last_error; *n = strlen(h->last_error); return TSCB_STATUS_OK_V1;
}

#if TSCB_SVB_DELTA64
#include "tscb_streamvbyte_stages.h"
static int stage_overlap(const void *a, uint64_t na, const void *b, uint64_t nb) {
    if(!na||!nb) return 0;
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=y ? (uint64_t)(y-x)<na : (uint64_t)(x-y)<nb;
}
static int stage_vector(const tscb_buffer_v1 *b, uint32_t dtype, uint64_t width,
                        uint64_t max_count, int source) {
    return b && b->rank == 1 && b->dtype == dtype && !b->reserved
        && b->used_bytes <= b->capacity_bytes && b->capacity_bytes % width == 0
        && b->used_bytes % width == 0 && b->strides_bytes[0] == (int64_t)width
        && b->shape[0] == (source ? b->used_bytes : b->capacity_bytes)/width
        && b->shape[0] <= max_count && (!b->capacity_bytes || b->data)
        && (source || !b->used_bytes);
}
tscb_status_v1 tscb_svb_stage_a(tscb_codec_handle_v1 *h, const tscb_buffer_v1 *in,
    tscb_buffer_v1 *out, int64_t *seed, uint32_t inverse, uint32_t enabled) {
    if (!h || !seed || inverse>1 || enabled>1
        || !stage_vector(in,inverse?8U:7U,8,MAX_COUNT,1)
        || !stage_vector(out,inverse?7U:8U,8,MAX_COUNT,0)
        || stage_overlap(in->data,in->used_bytes,out->data,out->capacity_bytes)
        || stage_overlap(seed,8,in->data,in->used_bytes)
        || stage_overlap(seed,8,out->data,out->capacity_bytes))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    uint64_t n=in->shape[0], need;
    if (inverse) {
        need=out->shape[0];
        if (n != (enabled?(need?need-1U:0U):need))
            return fail(h,TSCB_STATUS_DST_TOO_SMALL_V1,"stage A output geometry");
    } else need=enabled?(n?n-1U:0U):n;
    if(out->capacity_bytes<need*8U)
        return fail(h,TSCB_STATUS_DST_TOO_SMALL_V1,"stage A output capacity");
    uint8_t *result=calloc(need?need:1U,8);
    if(!result) return TSCB_STATUS_CODEC_ERROR_V1;
    int64_t initial=0;
    if(!enabled) {
        if(n) memcpy(result,in->data,n*8U);
    } else if(!inverse) {
        int64_t prev=0;
        if(n) {memcpy(&prev,in->data,8); initial=prev;}
        for(uint64_t i=1;i<n;++i) {
            int64_t cur,d; memcpy(&cur,(const uint8_t *)in->data+8U*i,8);
            if(__builtin_sub_overflow(cur,prev,&d)) {
                free(result);
                return fail(h,TSCB_STATUS_UNSUPPORTED_V1,"checked int64 delta overflow");
            }
            uint64_t z=((uint64_t)d<<1U)^(uint64_t)-(d<0);
            memcpy(result+8U*(i-1U),&z,8); prev=cur;
        }
    } else {
        int64_t prev; memcpy(&prev,seed,8);
        if(need) memcpy(result,&prev,8);
        for(uint64_t i=0;i<n;++i) {
            uint64_t z,bits; int64_t d,cur;
            memcpy(&z,(const uint8_t *)in->data+8U*i,8);
            bits=(z>>1U)^(uint64_t)-(int64_t)(z&1U); memcpy(&d,&bits,8);
            if(__builtin_add_overflow(prev,d,&cur)) {
                free(result);
                return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"checked int64 recovery overflow");
            }
            memcpy(result+8U*(i+1U),&cur,8); prev=cur;
        }
    }
    if(need) memcpy(out->data,result,need*8U);
    out->used_bytes=need*8U;
    if(!inverse) memcpy(seed,&initial,8);
    free(result); return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_svb_stage_b(tscb_codec_handle_v1 *h, const tscb_buffer_v1 *in,
    tscb_buffer_v1 *out, uint32_t inverse, uint32_t enabled) {
    if(!h || inverse>1 || enabled>1
        || !stage_vector(in,inverse?6U:8U,inverse?4U:8U,
                         inverse?2ULL*MAX_COUNT:MAX_COUNT,1)
        || !stage_vector(out,inverse?8U:6U,inverse?8U:4U,
                         inverse?MAX_COUNT:2ULL*MAX_COUNT,0)
        || (inverse && in->shape[0]%2U)
        || stage_overlap(in->data,in->used_bytes,out->data,out->capacity_bytes))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if(out->capacity_bytes<in->used_bytes)
        return fail(h,TSCB_STATUS_DST_TOO_SMALL_V1,"stage B output capacity");
    uint64_t n=inverse?in->shape[0]/2U:in->shape[0];
    if(!enabled) {
        /* Byte-preserving little-endian u64/u32 view; no arithmetic transform. */
        if(n) memmove(out->data,in->data,n*8U);
    } else for(uint64_t i=0;i<n;++i) {
        if(inverse) {
            uint32_t lo,hi; uint64_t value;
            memcpy(&lo,(const uint8_t *)in->data+8U*i,4);
            memcpy(&hi,(const uint8_t *)in->data+8U*i+4U,4);
            value=lo|((uint64_t)hi<<32U); memcpy((uint8_t *)out->data+8U*i,&value,8);
        } else {
            uint64_t value; uint32_t lo,hi; memcpy(&value,(const uint8_t *)in->data+8U*i,8);
            lo=(uint32_t)value; hi=(uint32_t)(value>>32U);
            memcpy((uint8_t *)out->data+8U*i,&lo,4);
            memcpy((uint8_t *)out->data+8U*i+4U,&hi,4);
        }
    }
    out->used_bytes=n*8U; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_svb_stage_c(tscb_codec_handle_v1 *h, const tscb_buffer_v1 *in,
    tscb_buffer_v1 *out, uint32_t inverse, uint32_t enabled) {
    if(!h || inverse>1 || enabled>1) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if((inverse && (!bytes(in)||!stage_vector(out,6,4,2ULL*MAX_COUNT,0)))
        || (!inverse && (!stage_vector(in,6,4,2ULL*MAX_COUNT,1)||!bytes(out)||out->used_bytes))
        || stage_overlap(in->data,in->used_bytes,out->data,out->capacity_bytes))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    uint32_t n=(uint32_t)(inverse?out->shape[0]:in->shape[0]);
    uint64_t bound=4U+4ULL*n+(enabled?((uint64_t)n+3U)/4U:0U);
    if(!inverse && (h->updated||h->finalized))
        return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"update lifecycle");
    if(!inverse && out->capacity_bytes<bound)
        return fail(h,TSCB_STATUS_DST_TOO_SMALL_V1,"stage C output capacity");
    if(inverse && (in->used_bytes<4U || read32(in->data)!=n
        || (enabled?!valid_payload(in->data,in->used_bytes,n):in->used_bytes!=4U+4ULL*n)))
        return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"stage C malformed control/data");
    uint32_t *values=calloc(n?n:1U,4);
    uint8_t *packed=calloc((size_t)(inverse?in->used_bytes:bound)+16U,1);
    if(!values||!packed) {free(values);free(packed);return TSCB_STATUS_CODEC_ERROR_V1;}
    uint64_t used=4U+4ULL*n;
    if(inverse) {
        memcpy(packed,in->data,(size_t)in->used_bytes);
        if(enabled) {
            uint64_t consumed;
            TSCB_TIME_CODEC(h->native_timer,decode_ns,consumed=BACKEND_DECODE(values,packed,n));
#if defined(TSCB_SVB_MODERN)
            consumed+=4U;
#endif
            if(n && consumed!=in->used_bytes) {
                free(values);free(packed);return TSCB_STATUS_CODEC_ERROR_V1;
            }
        } else if(n) memcpy(values,packed+4U,4ULL*n);
        if(n) memcpy(out->data,values,4ULL*n);
        out->used_bytes=4ULL*n;
    } else {
        if(n) memcpy(values,in->data,4ULL*n);
        if(enabled) {
#if defined(TSCB_SVB_MODERN)
            memcpy(packed,&n,4);
#endif
            TSCB_TIME_CODEC(h->native_timer,encode_ns,used=BACKEND_ENCODE(packed,values,n));
#if defined(TSCB_SVB_MODERN)
            used+=4U;
#endif
        }
        else {memcpy(packed,&n,4);if(n)memcpy(packed+4U,values,4ULL*n);}
        if(used>bound) {free(values);free(packed);return TSCB_STATUS_CODEC_ERROR_V1;}
        memcpy(out->data,packed,(size_t)used); out->used_bytes=used; h->updated=1;
    }
    free(values);free(packed);return TSCB_STATUS_OK_V1;
}
#endif
