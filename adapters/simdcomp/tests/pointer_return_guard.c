/* Return-pointer faults must fail atomically; these use the shipped shim object. */
#include "tscb_adapter_v1.h"
#include "simdcomp.h"
#include <stdio.h>
#include <string.h>

static int inject;
#define PACK_WRAP(name, declaration, arguments) \
    __m128i *__real_##name declaration; \
    __m128i *__wrap_##name declaration { \
        __m128i *end = __real_##name arguments; return inject ? NULL : end; \
    }
#define UNPACK_WRAP(name, declaration, arguments) \
    const __m128i *__real_##name declaration; \
    const __m128i *__wrap_##name declaration { \
        const __m128i *end = __real_##name arguments; return inject ? NULL : end; \
    }
PACK_WRAP(simdpack_length, (const uint32_t *v, size_t n, __m128i *p, uint32_t w), (v,n,p,w))
PACK_WRAP(simdpack_shortlength, (const uint32_t *v, int n, __m128i *p, uint32_t w), (v,n,p,w))
PACK_WRAP(simdpackFOR_length, (uint32_t s, const uint32_t *v, int n, __m128i *p, uint32_t w), (s,v,n,p,w))
UNPACK_WRAP(simdunpack_length, (const __m128i *p, size_t n, uint32_t *v, uint32_t w), (p,n,v,w))
UNPACK_WRAP(simdunpack_shortlength, (const __m128i *p, int n, uint32_t *v, uint32_t w), (p,n,v,w))
UNPACK_WRAP(simdunpackFOR_length, (uint32_t s, const __m128i *p, int n, uint32_t *v, uint32_t w), (s,p,n,v,w))

static tscb_buffer_v1 buffer(void *p, uint64_t cap, uint64_t used, uint32_t dtype) {
    tscb_buffer_v1 b = {0};
    b.data = p; b.capacity_bytes = cap; b.used_bytes = used; b.dtype = dtype;
    b.rank = 1; b.shape[0] = cap / (dtype == TSCB_DTYPE_U32_LE_V1 ? 4 : 1);
    b.strides_bytes[0] = dtype == TSCB_DTYPE_U32_LE_V1 ? 4 : 1;
    b.alignment_bytes = 1; b.ownership = TSCB_OWNERSHIP_CALLER_V1; return b;
}
int main(void) {
    const char *configs[] = {
        "{\"api\":\"LENGTH\",\"coding\":\"PLAIN\",\"isa\":\"SSE4_1\",\"starting_point\":0}",
        "{\"api\":\"MASKED\",\"coding\":\"PLAIN\",\"isa\":\"SSE4_1\",\"starting_point\":0}",
        "{\"api\":\"LENGTH\",\"coding\":\"FOR\",\"isa\":\"SSE4_1\",\"starting_point\":0}",
    };
    unsigned failures = 0;
    for (unsigned route = 0; route < 3; ++route) for (unsigned decode = 0; decode < 2; ++decode) {
        uint32_t value = 7, restored = 0xa5a5a5a5U;
        uint8_t frame[1080], snapshot[1080]; memset(frame, 0xa5, sizeof(frame));
        tscb_buffer_v1 in = buffer(&value, 4, 4, TSCB_DTYPE_U32_LE_V1);
        tscb_buffer_v1 out = buffer(frame, sizeof(frame), 0, TSCB_DTYPE_BYTES_V1);
        tscb_buffer_v1 dec = buffer(&restored, 4, 0, TSCB_DTYPE_U32_LE_V1);
        tscb_codec_handle_v1 *h = NULL;
        if (tscb_create(configs[route], strlen(configs[route]), &h)) return 2;
        inject = 0;
        if (decode && tscb_compress(h, &in, &out)) return 3;
        memcpy(snapshot, frame, sizeof(frame)); inject = 1;
        tscb_status_v1 status = decode ? tscb_decompress(h, &out, &dec) : tscb_compress(h, &in, &out);
        int atomic = decode ? !dec.used_bytes && restored == 0xa5a5a5a5U : !out.used_bytes && !memcmp(frame, snapshot, sizeof(frame));
        printf("route=%u direction=%s NULL-return status=%u atomic=%d\n", route, decode ? "decode" : "encode", status, atomic);
        failures += status != TSCB_STATUS_CODEC_ERROR_V1 || !atomic;
        tscb_destroy(h);
    }
    printf("SIMDComp NULL-return qualification: %u/6 rejected atomically\n", 6-failures);
    return failures ? 1 : 0;
}
