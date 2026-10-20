#ifndef SPRINTZ_PORT_H
#define SPRINTZ_PORT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* ABI v1. No handles; each operation resets predictor state. All sizes in bytes.
 * Output is unchanged on error; *produced=0. Caller owns all buffers.
 * Config and produced must not alias input/output buffers. Input/output may overlap.
 * width=8/16; predictor=0 Delta /1 FIRE; huffman=0/1;
 * path=0 auto RLE,1 general RLE,2 lowdim RLE,3 bitpack,4 Delta noRLE,
 * 5 legacy FIRE noRLE (8-bit only). Paths3/4 require predictor0, path5 predictor1.
 * Limit 65536 input bytes; native bit patterns, little endian, no float mapping.
 * Raw decoder requires expected_bytes; external framing/config is caller's job.
 */
typedef struct {uint32_t width,predictor,huffman,path,ndims;} sz_config;
enum {SZ_OK=0,SZ_ARGUMENT=1,SZ_CAPACITY=2,SZ_MALFORMED=3,SZ_MEMORY=4,SZ_PLATFORM=5,SZ_CORE=6};
#if defined(__GNUC__)
#define SZ_API __attribute__((visibility("default")))
#else
#define SZ_API
#endif
SZ_API int sz_supported(void);
SZ_API int sz_bound(const sz_config*,size_t input_bytes,size_t* bound);
SZ_API int sz_encode(const sz_config*,const void*,size_t,void*,size_t,size_t* produced);
SZ_API int sz_decode(const sz_config*,const void*,size_t,size_t expected_bytes,void*,size_t,size_t* produced);
/* Deterministic thread-local native allocation fault hook; -1 disables,
 * 0 fails next allocation, k fails after k successful native allocations. */
SZ_API void sz_test_fail_allocation(int64_t k);
#ifdef __cplusplus
}
#endif
#endif
