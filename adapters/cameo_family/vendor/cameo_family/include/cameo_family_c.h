/* SPDX-License-Identifier: Apache-2.0 */
#ifndef CAMEO_FAMILY_C_H
#define CAMEO_FAMILY_C_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* ABI v1. Caller owns buffers; no padding/alignment required. Config.version=1.
   Algorithms: 1 CAMEO/SIP,2 VW,3 PIP,4 TP,5 SWAB,6 SimPiece,7 PMC-Mean,
   8 connected SWING,9 DFT,10 DWT(DCT-II).
   Flags: 1 FGC lookahead,2 integer ratio stop,4 Cython bottom-up,8 Python bottom-up,16 scalar DCT baseline.
   Counters are aligned, distinct writable size_t objects, disjoint from input/output/config.
   Invalid counters/ranges are rejected without writes, including to counters.
   Failure: produced=0, output unchanged. Capacity query uses output=NULL,cap=0.
   input/output may overlap. Repeated independent calls have no hidden state. */
typedef struct cf_config_v1 {
    uint32_t version, algorithm, flags, reserved;
    double error_bound, fraction, window_fraction;
    size_t nlags, hops, kappa, threads;
} cf_config_v1;
enum { CF_OK = 0, CF_CAPACITY = 1, CF_INVALID = 2, CF_NOMEM = 3, CF_INTERNAL = 4 };
enum {
    CF_CAMEO = 1,
    CF_VW = 2,
    CF_PIP = 3,
    CF_TP = 4,
    CF_SWAB = 5,
    CF_SIM_PIECE = 6,
    CF_PMC = 7,
    CF_SWING = 8,
    CF_DFT = 9,
    CF_DWT_DCT_II = 10
};
uint32_t cf_api_version_v1(void);
int cf_encode_v1(const double *, size_t, const cf_config_v1 *, uint8_t *, size_t, size_t *,
                 size_t *);
int cf_decode_v1(const uint8_t *, size_t, double *, size_t, size_t *, size_t *);
#ifdef __cplusplus
}
#endif
#endif
