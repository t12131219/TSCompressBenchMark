#ifndef TSBENCH_CUSZP_GPU_H
#define TSBENCH_CUSZP_GPU_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* This GPU ABI accepts opaque owners, never host-ABI device pointers. */
typedef struct tsgpu_info_v1 {
  uint32_t struct_size, version, device, dtype;
  uint64_t count;
  double error_bound;
  uint64_t payload_bytes, scratch_bytes, input_bytes, output_bytes;
  uint64_t output_capacity_bytes, owned_allocation_peak_bytes;
  double device_event_ms;
} tsgpu_info_v1;
uint32_t tsgpu_abi_version(void);
const char* tsgpu_last_error(void);
uint32_t tsgpu_device_json(int device, const char** text);
uint32_t tsgpu_diagnostics_json(const char** text);
uint32_t tsgpu_create(int device, uint32_t dtype, uint64_t count, double eb, void** session);
uint32_t tsgpu_close(void* session);
uint32_t tsgpu_prepare_input(int device, uint32_t dtype, uint64_t count, double eb,
                            const void* host, uint64_t nbytes, void** owner);
uint32_t tsgpu_release_input(void* owner);
uint32_t tsgpu_copy_input(void* owner, void* host, uint64_t capacity);
uint32_t tsgpu_encode_host(void* session, const void* host, uint64_t nbytes, void** payload);
uint32_t tsgpu_encode_device(void* session, void* input_owner, void** payload);
uint32_t tsgpu_install_payload(int device, uint32_t dtype, uint64_t count, double eb,
                              const void* host, uint64_t nbytes, void** payload);
uint32_t tsgpu_payload_info(void* payload, tsgpu_info_v1* info);
uint32_t tsgpu_copy_payload(void* payload, void* host, uint64_t capacity);
uint32_t tsgpu_release_payload(void* payload);
uint32_t tsgpu_decode_device(void* session, void* payload, void** decoded);
uint32_t tsgpu_decoded_info(void* decoded, tsgpu_info_v1* info);
uint32_t tsgpu_copy_decoded(void* decoded, void* host, uint64_t capacity);
uint32_t tsgpu_release_decoded(void* decoded);
#ifdef __cplusplus
}
#endif
#endif
