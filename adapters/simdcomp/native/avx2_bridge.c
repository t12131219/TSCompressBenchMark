#include "tscb_native_timing.h"
#include "simdcomp.h"

uint32_t tscb_simdcomp_avx2_width(const uint32_t *values, tscb_native_timer *timer) {
    uint32_t width;
    TSCB_TIME_CODEC(*timer, encode_ns, width = avxmaxbits(values));
    return width;
}
void tscb_simdcomp_avx2_pack(const uint32_t *values, void *packed, uint32_t width,
                            int without_mask, tscb_native_timer *timer) {
    if (without_mask) {
        TSCB_TIME_CODEC(*timer, encode_ns,
            avxpackwithoutmask(values, (__m256i *)packed, width));
    } else {
        TSCB_TIME_CODEC(*timer, encode_ns, avxpack(values, (__m256i *)packed, width));
    }
}
void tscb_simdcomp_avx2_unpack(const void *packed, uint32_t *values, uint32_t width,
                              tscb_native_timer *timer) {
    TSCB_TIME_CODEC(*timer, decode_ns, avxunpack((const __m256i *)packed, values, width));
}

/* Direct core dispatch keeps AVX2 in this separately compiled TU. The C++
 * driver times complete operations, so these calls do not start inner clocks. */
uint32_t tsbench_simdcomp_core_avx2_width(const uint32_t *values) {
    return avxmaxbits(values);
}
void tsbench_simdcomp_core_avx2_pack(const uint32_t *values, void *packed,
                                    uint32_t width, int without_mask) {
    if (without_mask) avxpackwithoutmask(values, (__m256i *)packed, width);
    else avxpack(values, (__m256i *)packed, width);
}
void tsbench_simdcomp_core_avx2_unpack(const void *packed, uint32_t *values,
                                      uint32_t width) {
    avxunpack((const __m256i *)packed, values, width);
}
