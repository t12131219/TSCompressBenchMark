#ifndef TSCB_FABBA_C_H
#define TSCB_FABBA_C_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#if defined(FABBA_C_BUILD)
#define FABBA_C_API __declspec(dllexport)
#else
#define FABBA_C_API __declspec(dllimport)
#endif
#else
#define FABBA_C_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef enum fabba_status_v1 {
  FABBA_STATUS_OK_V1 = 0,
  FABBA_STATUS_INVALID_ARGUMENT_V1 = 1,
  FABBA_STATUS_BUFFER_TOO_SMALL_V1 = 2,
  FABBA_STATUS_MALFORMED_INPUT_V1 = 3,
  FABBA_STATUS_ALLOCATION_FAILURE_V1 = 4,
  FABBA_STATUS_INTERNAL_ERROR_V1 = 5
} fabba_status_v1;

typedef struct fabba_config_v1 {
  double tolerance;
  double alpha;
  double scl;
  uint64_t max_len;
} fabba_config_v1;

typedef struct fabba_accounting_v1 {
  uint64_t header_bits;
  uint64_t codebook_bits;
  uint64_t symbol_stream_bits;
  uint64_t checksum_bits;
  uint64_t serialized_bits;
  uint64_t external_side_information_bits;
  uint64_t final_bits;
} fabba_accounting_v1;

FABBA_C_API fabba_config_v1 fabba_config_default_v1(void);
FABBA_C_API size_t fabba_max_encoded_size_v1(size_t sample_count);
FABBA_C_API fabba_status_v1 fabba_encode_v1(
    const double* values, size_t sample_count, const fabba_config_v1* config,
    uint8_t* output, size_t output_capacity, size_t* output_size,
    fabba_accounting_v1* accounting);
FABBA_C_API fabba_status_v1 fabba_decode_v1(
    const uint8_t* encoded, size_t encoded_size, double* output,
    size_t output_capacity, size_t* output_count,
    fabba_accounting_v1* accounting);
FABBA_C_API const char* fabba_status_string_v1(fabba_status_v1 status);

#ifdef __cplusplus
}
#endif
#endif
