/* Native profile-only event ABI. All hot hooks are allocation and I/O free. */
#ifndef TSBENCH_TRACE_API_H
#define TSBENCH_TRACE_API_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

enum bmk_trace_stage {
    BMK_TRACE_OPERATION = 1, BMK_TRACE_PREPARE, BMK_TRACE_CODEC, BMK_TRACE_SERIALIZE,
    BMK_TRACE_ALP_FUSED_AVX2, BMK_TRACE_ZSTD_MT_JOB
};
uint64_t bmk_trace_begin(enum bmk_trace_stage stage);
void bmk_trace_end(uint64_t token);

#ifdef __cplusplus
}
#endif
#endif
