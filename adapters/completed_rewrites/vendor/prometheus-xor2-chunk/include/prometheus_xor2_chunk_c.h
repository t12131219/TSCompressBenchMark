// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause

#ifndef PROMETHEUS_XOR2_CHUNK_C_H
#define PROMETHEUS_XOR2_CHUNK_C_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PXOR2_STANDALONE_API_VERSION_V1 UINT32_C(1)

typedef enum pxor2_status_v1 {
    PXOR2_STATUS_OK_V1 = 0,
    PXOR2_STATUS_INVALID_ARGUMENT_V1 = 1,
    PXOR2_STATUS_DST_TOO_SMALL_V1 = 2,
    PXOR2_STATUS_CORRUPT_STREAM_V1 = 3,
    PXOR2_STATUS_SAMPLE_LIMIT_EXCEEDED_V1 = 4,
    PXOR2_STATUS_INVALID_STATE_V1 = 5,
    PXOR2_STATUS_ALLOCATION_FAILED_V1 = 6
} pxor2_status_v1;

typedef struct pxor2_sample_v1 {
    int64_t start_timestamp;
    int64_t timestamp;
    uint64_t value_bits;
} pxor2_sample_v1;

typedef struct pxor2_accounting_v1 {
    uint64_t struct_size;
    uint64_t sample_count;
    uint64_t canonical_raw_bits;
    uint64_t serialized_bytes;
    uint64_t serialized_bits;
    uint64_t container_and_st_header_bits;
    uint64_t joint_timestamp_value_st_and_padding_bits;
    uint64_t external_side_information_bits;
    uint64_t final_bits;
} pxor2_accounting_v1;

typedef struct pxor2_codec_v1 pxor2_codec_v1;

uint32_t pxor2_get_api_version_v1(void);
pxor2_status_v1 pxor2_get_manifest_json_v1(const char** json, uint64_t* length);
pxor2_status_v1 pxor2_create_v1(pxor2_codec_v1** codec);
pxor2_status_v1 pxor2_destroy_v1(pxor2_codec_v1* codec);
pxor2_status_v1 pxor2_reset_v1(pxor2_codec_v1* codec);

pxor2_status_v1 pxor2_compress_bound_v1(
    pxor2_codec_v1* codec,
    const pxor2_sample_v1* samples,
    uint64_t sample_count,
    uint64_t* bound_bytes);

pxor2_status_v1 pxor2_compress_v1(
    pxor2_codec_v1* codec,
    const pxor2_sample_v1* samples,
    uint64_t sample_count,
    uint8_t* output,
    uint64_t output_capacity,
    uint64_t* bytes_written);

pxor2_status_v1 pxor2_finalize_v1(
    pxor2_codec_v1* codec,
    uint8_t* output,
    uint64_t output_capacity,
    uint64_t* bytes_written);

pxor2_status_v1 pxor2_decompress_v1(
    pxor2_codec_v1* codec,
    const uint8_t* input,
    uint64_t input_size,
    pxor2_sample_v1* samples,
    uint64_t sample_capacity,
    uint64_t* samples_written);

pxor2_status_v1 pxor2_get_accounting_v1(
    pxor2_codec_v1* codec,
    pxor2_accounting_v1* accounting);

pxor2_status_v1 pxor2_get_last_error_v1(
    pxor2_codec_v1* codec,
    const char** message,
    uint64_t* length);

#ifdef __cplusplus
}
#endif

#endif
