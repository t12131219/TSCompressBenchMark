#ifndef ALP_PORT_H
#define ALP_PORT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
enum alp_status {
    ALP_OK = 0, ALP_INVALID_ARGUMENT = 1, ALP_CAPACITY = 2,
    ALP_MALFORMED = 3, ALP_RESOURCE_LIMIT = 4, ALP_FP_ENV = 5,
    ALP_OUT_OF_MEMORY = 6, ALP_INTERNAL = 7
};
enum alp_dtype { ALP_FLOAT32 = 4, ALP_FLOAT64 = 8 };
enum alp_method { ALP_ADAPTIVE = 0, ALP_RD = 1 };
#define ALP_PORT_MAX_VALUES UINT64_C(16777216)
/* v1, stateless. Buffers borrowed, unaligned input allowed. On failure output
 * bytes unchanged; result scalars zeroed. Scalar result pointers must not alias
 * buffers or one another. See docs/CONTRACT.md for the complete contract. */
const char* alp_port_profile(void);
const char* alp_port_status_string(int status);
int alp_port_bound(uint64_t count, uint8_t dtype, uint8_t method, size_t* bound);
int alp_port_encode(const void* input, uint64_t count, uint8_t dtype, uint8_t method,
                    void* output, size_t capacity, size_t* used);
int alp_port_decode(const void* input, size_t input_bytes, void* output,
                    size_t capacity, size_t* used, size_t* consumed,
                    uint64_t* count, uint8_t* dtype, uint8_t* method);
#ifdef __cplusplus
}
#endif
#endif
