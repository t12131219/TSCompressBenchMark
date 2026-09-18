#ifndef TSCB_ADAPTER_V1_H
#define TSCB_ADAPTER_V1_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TSCB_ADAPTER_ABI_V1 1u
#define TSCB_MAX_RANK_V1 8u

typedef struct tscb_codec_handle_v1 tscb_codec_handle_v1;

typedef struct tscb_native_timing_v1 {
    uint32_t struct_size;
    uint32_t version;
    uint64_t native_encode_wall_ns;
    uint64_t native_decode_wall_ns;
} tscb_native_timing_v1;

typedef enum tscb_status_v1 {
    TSCB_STATUS_OK_V1 = 0,
    TSCB_STATUS_INVALID_ARGUMENT_V1 = 1,
    TSCB_STATUS_UNSUPPORTED_V1 = 2,
    TSCB_STATUS_DST_TOO_SMALL_V1 = 3,
    TSCB_STATUS_CODEC_ERROR_V1 = 4,
    TSCB_STATUS_FINALIZE_REQUIRED_V1 = 5,
    TSCB_STATUS_ABI_MISMATCH_V1 = 6
} tscb_status_v1;

typedef enum tscb_dtype_v1 {
    TSCB_DTYPE_INVALID_V1 = 0,
    TSCB_DTYPE_I8_V1 = 1,
    TSCB_DTYPE_U8_V1 = 2,
    TSCB_DTYPE_I16_LE_V1 = 3,
    TSCB_DTYPE_U16_LE_V1 = 4,
    TSCB_DTYPE_I32_LE_V1 = 5,
    TSCB_DTYPE_U32_LE_V1 = 6,
    TSCB_DTYPE_I64_LE_V1 = 7,
    TSCB_DTYPE_U64_LE_V1 = 8,
    TSCB_DTYPE_F32_LE_V1 = 9,
    TSCB_DTYPE_F64_LE_V1 = 10,
    TSCB_DTYPE_BYTES_V1 = 11,
    TSCB_DTYPE_BITMAP_LSB0_V1 = 12
} tscb_dtype_v1;

typedef enum tscb_ownership_v1 {
    TSCB_OWNERSHIP_BORROWED_V1 = 0,
    TSCB_OWNERSHIP_CALLER_V1 = 1,
    TSCB_OWNERSHIP_CODEC_V1 = 2
} tscb_ownership_v1;

typedef struct tscb_buffer_v1 {
    void *data;
    uint64_t capacity_bytes;
    uint64_t used_bytes;
    uint32_t dtype;
    uint32_t rank;
    uint64_t shape[TSCB_MAX_RANK_V1];
    int64_t strides_bytes[TSCB_MAX_RANK_V1];
    uint64_t alignment_bytes;
    uint32_t ownership;
    uint32_t reserved;
} tscb_buffer_v1;

uint32_t tscb_get_abi_version(void);

/* Returned JSON is UTF-8 and owned by the adapter for the process lifetime. */
tscb_status_v1 tscb_get_manifest_json(const char **json, uint64_t *length);

/* Config JSON must be canonical UTF-8 JSON matching the codec parameter schema. */
tscb_status_v1 tscb_create(
    const char *config_json,
    uint64_t config_length,
    tscb_codec_handle_v1 **handle
);

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1 *handle);
tscb_status_v1 tscb_reset(tscb_codec_handle_v1 *handle, uint32_t reset_mode);

/* Optional extension. Enable before codec work; reset preserves enablement and clears totals.
 * Queries are non-destructive. Disabled/unavailable clocks return UNSUPPORTED. */
tscb_status_v1 tscb_set_native_timing(tscb_codec_handle_v1 *handle, uint32_t enabled);
tscb_status_v1 tscb_get_native_timing(
    tscb_codec_handle_v1 *handle, tscb_native_timing_v1 *timing
);

tscb_status_v1 tscb_compress_bound(
    tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input,
    uint64_t *bound_bytes
);

tscb_status_v1 tscb_compress(
    tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input,
    tscb_buffer_v1 *output
);

tscb_status_v1 tscb_finalize(
    tscb_codec_handle_v1 *handle,
    tscb_buffer_v1 *output
);

tscb_status_v1 tscb_decompress(
    tscb_codec_handle_v1 *handle,
    const tscb_buffer_v1 *input,
    tscb_buffer_v1 *output
);

tscb_status_v1 tscb_query(
    tscb_codec_handle_v1 *handle,
    const char *request_json,
    uint64_t request_length,
    char *response_json,
    uint64_t response_capacity,
    uint64_t *response_used
);

tscb_status_v1 tscb_get_accounting_json(
    tscb_codec_handle_v1 *handle,
    const char **json,
    uint64_t *length
);

/* Error text is adapter-owned and invalidated by the next adapter call. */
tscb_status_v1 tscb_get_last_error(
    tscb_codec_handle_v1 *handle,
    const char **message,
    uint64_t *length
);

#ifdef __cplusplus
}
#endif

#endif
