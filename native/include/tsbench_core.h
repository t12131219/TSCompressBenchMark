#ifndef TSBENCH_CORE_H
#define TSBENCH_CORE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Direct algorithm entry contract, independent of the historical C1/RW APIs.
 * Input is the logical object's physical contiguous bytes, never an ABI frame.
 * All algorithm-dependent preparation/reset/serialization/finalize is encode
 * work. Metadata describes the task; it must not contain precomputed models.
 */
typedef struct tsbench_core_config {
    uint32_t version;               /* 1 */
    uint32_t dtype;                 /* TSCB_DTYPE_* from tscb_adapter_v1.h */
    uint32_t rank;                  /* 0..8 */
    uint32_t order;                 /* 0=C, 1=F */
    uint64_t shape[8];
    const char* parameters_json;    /* fully resolved encoder parameters */
    const char* model;              /* optional immutable pretrained model */
} tsbench_core_config;

typedef struct tsbench_core_result {
    const uint8_t* data;
    size_t size;
    size_t capacity;
    void* owner;                    /* NULL for borrowed caller storage */
} tsbench_core_result;

/* Status: 0 success, 1 algorithm/format error, 2 unsupported, 3 capacity.
 * A decoder is created with parameters_json="{}" and model=NULL. It must
 * recover codec parameters/models from the complete encoded output.
 * Each successful result survives context destruction until release. Native
 * vector-returning APIs transfer ownership without copying into an ABI buffer.
 * Caller-buffer APIs return that buffer with owner=NULL. The driver retains
 * every result, and releases owned products outside the batch clocks.
 */
uint32_t tsbench_core_version(void);
/* Bit 1: encode uses caller buffer; bit 2: decode uses caller buffer.
 * Zero bits mean the native result owns that operation's storage.
 */
uint32_t tsbench_core_storage(void);
/* Optional admission hooks, outside main clocks. validate_input checks source
 * domain only, never precomputes algorithm sampling/models. validate checks
 * complete stream bounds before an immutable product reaches a fast decoder.
 * Decoding an unvalidated arbitrary stream is outside the direct contract.
 */
int tsbench_core_validate_input(void*, const uint8_t*, size_t);
int tsbench_core_validate(void*, const uint8_t*, size_t);
int tsbench_core_create(const tsbench_core_config*, int decoder, void**);
int tsbench_core_destroy(void*);
int tsbench_core_bound(void*, const uint8_t*, size_t, size_t*);
int tsbench_core_encode(void*, const uint8_t*, size_t, uint8_t*, size_t, tsbench_core_result*);
int tsbench_core_decode(void*, const uint8_t*, size_t, uint8_t*, size_t, tsbench_core_result*);
void tsbench_core_release(tsbench_core_result*);
const char* tsbench_core_error(void*);

#ifdef __cplusplus
}
#endif
#endif
