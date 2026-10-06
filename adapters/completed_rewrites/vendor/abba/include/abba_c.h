#ifndef TSCB_ABBA_C_H
#define TSCB_ABBA_C_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#if defined(ABBA_C_BUILD)
#define ABBA_C_API __declspec(dllexport)
#else
#define ABBA_C_API __declspec(dllimport)
#endif
#else
#define ABBA_C_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef enum abba_status_v1 {
  ABBA_STATUS_OK_V1 = 0,
  ABBA_STATUS_INVALID_ARGUMENT_V1 = 1,
  ABBA_STATUS_BUFFER_TOO_SMALL_V1 = 2,
  ABBA_STATUS_MALFORMED_INPUT_V1 = 3,
  ABBA_STATUS_ALLOCATION_FAILURE_V1 = 4,
  ABBA_STATUS_INTERNAL_ERROR_V1 = 5
} abba_status_v1;

typedef struct abba_config_v1 {
  double compression_tolerance;
  double digitization_tolerance;
  uint32_t min_k;
  uint32_t max_k;
  uint64_t max_len;
} abba_config_v1;

typedef struct abba_accounting_v1 {
  uint64_t header_bits;
  uint64_t codebook_bits;
  uint64_t symbol_stream_bits;
  uint64_t checksum_bits;
  uint64_t serialized_bits;
  uint64_t external_side_information_bits;
  uint64_t final_bits;
} abba_accounting_v1;

ABBA_C_API abba_config_v1 abba_config_default_v1(void);
ABBA_C_API size_t abba_max_encoded_size_v1(size_t sample_count);

ABBA_C_API abba_status_v1 abba_encode_v1(
    const double* values, size_t sample_count, const abba_config_v1* config,
    uint8_t* output, size_t output_capacity, size_t* output_size,
    abba_accounting_v1* accounting);

ABBA_C_API abba_status_v1 abba_decode_v1(
    const uint8_t* encoded, size_t encoded_size, double* output,
    size_t output_capacity, size_t* output_count,
    abba_accounting_v1* accounting);

ABBA_C_API const char* abba_status_string_v1(abba_status_v1 status);

#ifdef __cplusplus
}
#endif

#endif
