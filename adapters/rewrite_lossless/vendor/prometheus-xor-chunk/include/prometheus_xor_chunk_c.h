// Copyright The Prometheus Authors
// Copyright (c) 2015,2016 Damian Gryski <damian@gryski.com>
// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause

#ifndef PROMETHEUS_XOR_CHUNK_C_H
#define PROMETHEUS_XOR_CHUNK_C_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PXOR_STANDALONE_API_VERSION_V1 UINT32_C(1)

typedef enum pxor_status_v1 {
    PXOR_STATUS_OK_V1 = 0,
    PXOR_STATUS_INVALID_ARGUMENT_V1 = 1,
    PXOR_STATUS_DST_TOO_SMALL_V1 = 2,
    PXOR_STATUS_CORRUPT_STREAM_V1 = 3,
    PXOR_STATUS_SAMPLE_LIMIT_EXCEEDED_V1 = 4,
    PXOR_STATUS_INVALID_STATE_V1 = 5,
    PXOR_STATUS_ALLOCATION_FAILED_V1 = 6
} pxor_status_v1;

typedef struct pxor_sample_v1 {
    /* Signed timestamp and opaque IEEE-754 binary64 payload bits. */
    int64_t timestamp;
    uint64_t value_bits;
} pxor_sample_v1;

typedef struct pxor_accounting_v1 {
    uint64_t struct_size;
    uint64_t sample_count;
    uint64_t canonical_raw_bits;
    uint64_t serialized_bytes;
    uint64_t serialized_bits;
    uint64_t container_bits;
    uint64_t timestamp_value_joint_and_padding_bits;
    uint64_t external_side_information_bits;
    uint64_t final_bits;
} pxor_accounting_v1;

typedef struct pxor_codec_v1 pxor_codec_v1;

/* Returned strings remain owned by the library and must not be freed. */
uint32_t pxor_get_api_version_v1(void);

pxor_status_v1 pxor_get_manifest_json_v1(
    const char** json,
    uint64_t* length);

pxor_status_v1 pxor_create_v1(pxor_codec_v1** codec);

/* Destroy accepts NULL. All other functions require a live handle. */
pxor_status_v1 pxor_destroy_v1(pxor_codec_v1* codec);

/* Reset discards lifecycle and accounting state without retaining input data. */
pxor_status_v1 pxor_reset_v1(pxor_codec_v1* codec);

pxor_status_v1 pxor_compress_bound_v1(
    pxor_codec_v1* codec,
    const pxor_sample_v1* samples,
    uint64_t sample_count,
    uint64_t* bound_bytes);

pxor_status_v1 pxor_compress_v1(
    pxor_codec_v1* codec,
    const pxor_sample_v1* samples,
    uint64_t sample_count,
    uint8_t* output,
    uint64_t output_capacity,
    uint64_t* bytes_written);

/* Finalize is mandatory, emits zero bytes, and succeeds once per reset. */
pxor_status_v1 pxor_finalize_v1(
    pxor_codec_v1* codec,
    uint8_t* output,
    uint64_t output_capacity,
    uint64_t* bytes_written);

pxor_status_v1 pxor_decompress_v1(
    pxor_codec_v1* codec,
    const uint8_t* input,
    uint64_t input_size,
    pxor_sample_v1* samples,
    uint64_t sample_capacity,
    uint64_t* samples_written);

/* Accounting is available only after successful compression and finalize. */
pxor_status_v1 pxor_get_accounting_v1(
    pxor_codec_v1* codec,
    pxor_accounting_v1* accounting);

pxor_status_v1 pxor_get_last_error_v1(
    pxor_codec_v1* codec,
    const char** message,
    uint64_t* length);

#ifdef __cplusplus
}
#endif

#endif
