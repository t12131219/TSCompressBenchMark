#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include "tscb_adapter_v1.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void store_u16(uint8_t *p, uint16_t value) {
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
}

static void store_u64(uint8_t *p, uint64_t value) {
    unsigned i;
    for (i = 0; i < 8; ++i)
        p[i] = (uint8_t)(value >> (8 * i));
}

static void store_f64(uint8_t *p, double value) {
    uint64_t bits;
    memcpy(&bits, &value, 8);
    store_u64(p, bits);
}

static tscb_buffer_v1 buffer(void *data, uint64_t capacity, uint64_t used) {
    tscb_buffer_v1 result;
    memset(&result, 0, sizeof(result));
    result.data = data;
    result.capacity_bytes = capacity;
    result.used_bytes = used;
    result.dtype = TSCB_DTYPE_BYTES_V1;
    result.rank = 1;
    result.shape[0] = used;
    result.strides_bytes[0] = 1;
    result.alignment_bytes = 1;
    result.ownership = TSCB_OWNERSHIP_BORROWED_V1;
    return result;
}

static int run_case(uint8_t width, uint64_t rows, int exceptional) {
    static const char config[] = "{\"algorithm\":\"zfp-accuracy-1d\"}";
    const uint16_t columns = 2;
    const double tolerance = 0.001;
    const uint64_t raw_size = rows * columns * width;
    const uint64_t input_size = 24 + raw_size;
    uint8_t *input = calloc(1, input_size ? (size_t)input_size : 1);
    uint8_t *copy = NULL, *encoded = NULL, *decoded = NULL, *small = NULL;
    tscb_codec_handle_v1 *handle = NULL, *small_handle = NULL;
    tscb_buffer_v1 source, target, restored, zero;
    uint64_t bound = 0, i;
    int status = 1;
    if (input == NULL)
        goto done;
    memcpy(input, "ZFI1", 4);
    input[4] = width;
    store_u16(input + 6, columns);
    store_u64(input + 8, rows);
    store_f64(input + 16, tolerance);
    for (i = 0; i < rows * columns; ++i) {
        double value = sin((double)i * 0.17) * 10.0 + (double)(i % 7);
        if (width == 4) {
            float item = (float)value;
            memcpy(input + 24 + i * 4, &item, 4);
        } else {
            memcpy(input + 24 + i * 8, &value, 8);
        }
    }
    if (exceptional && rows >= 5) {
        if (width == 4) {
            const uint32_t special[] = {0x80000000u, 1u, 0x7f800000u, 0xff800000u,
                                        0x7fc01234u};
            memcpy(input + 24, special, sizeof(special));
        } else {
            const uint64_t special[] = {UINT64_C(0x8000000000000000), UINT64_C(1),
                                        UINT64_C(0x7ff0000000000000),
                                        UINT64_C(0xfff0000000000000),
                                        UINT64_C(0x7ff8000000001234)};
            memcpy(input + 24, special, sizeof(special));
        }
    }
    copy = malloc((size_t)input_size);
    if (copy == NULL)
        goto done;
    memcpy(copy, input, (size_t)input_size);
    source = buffer(input, input_size, input_size);
    if (tscb_create(config, sizeof(config) - 1, &handle) != TSCB_STATUS_OK_V1 ||
        tscb_set_native_timing(handle, 1) != TSCB_STATUS_OK_V1 ||
        tscb_compress_bound(handle, &source, &bound) != TSCB_STATUS_OK_V1 || bound < 50)
        goto done;
    encoded = malloc((size_t)bound + 16);
    decoded = malloc(raw_size ? (size_t)raw_size : 1);
    small = malloc(bound ? (size_t)bound : 1);
    if (encoded == NULL || decoded == NULL || small == NULL)
        goto done;
    memset(encoded + bound, 0xa5, 16);
    target = buffer(encoded, bound, 0);
    if (tscb_compress(handle, &source, &target) != TSCB_STATUS_OK_V1 ||
        target.used_bytes > bound || memcmp(input, copy, (size_t)input_size) != 0)
        goto done;
    for (i = 0; i < 16; ++i)
        if (encoded[bound + i] != 0xa5)
            goto done;
    zero = buffer(NULL, 0, 0);
    if (tscb_finalize(handle, &zero) != TSCB_STATUS_OK_V1 || zero.used_bytes != 0 ||
        tscb_finalize(handle, &zero) == TSCB_STATUS_OK_V1)
        goto done;
    restored = buffer(decoded, raw_size, 0);
    source = buffer(encoded, target.used_bytes, target.used_bytes);
    if (tscb_decompress(handle, &source, &restored) != TSCB_STATUS_OK_V1 ||
        restored.used_bytes != raw_size)
        goto done;
    if (exceptional && rows >= 5) {
        if (memcmp(input + 24, decoded, (size_t)(rows * width)) != 0)
            goto done;
    } else {
        for (i = 0; i < rows * columns; ++i) {
            double before, after;
            if (width == 4) {
                float a, b;
                memcpy(&a, input + 24 + i * 4, 4);
                memcpy(&b, decoded + i * 4, 4);
                before = a;
                after = b;
            } else {
                memcpy(&before, input + 24 + i * 8, 8);
                memcpy(&after, decoded + i * 8, 8);
            }
            if (fabs(before - after) > tolerance)
                goto done;
        }
    }
    encoded[target.used_bytes - 1] ^= 1;
    if (tscb_decompress(handle, &source, &restored) == TSCB_STATUS_OK_V1)
        goto done;
    encoded[target.used_bytes - 1] ^= 1;
    source.used_bytes--;
    if (tscb_decompress(handle, &source, &restored) == TSCB_STATUS_OK_V1)
        goto done;
    if (tscb_create(config, sizeof(config) - 1, &small_handle) != TSCB_STATUS_OK_V1)
        goto done;
    source = buffer(input, input_size, input_size);
    target = buffer(small, bound - 1, 0);
    if (tscb_compress(small_handle, &source, &target) != TSCB_STATUS_DST_TOO_SMALL_V1)
        goto done;
    status = 0;
done:
    tscb_destroy(small_handle);
    tscb_destroy(handle);
    free(small);
    free(decoded);
    free(encoded);
    free(copy);
    free(input);
    return status;
}

int main(void) {
    static const uint64_t lengths[] = {0, 1, 2, 3, 4, 5, 7, 8, 9, 17};
    size_t width_index, length_index;
    if (tscb_get_abi_version() != TSCB_ADAPTER_ABI_V1)
        return 1;
    for (width_index = 0; width_index < 2; ++width_index)
        for (length_index = 0; length_index < sizeof(lengths) / sizeof(lengths[0]);
             ++length_index)
            if (run_case(width_index == 0 ? 4 : 8, lengths[length_index], 0)) {
                fprintf(stderr, "zfp smoke failed: width=%u rows=%llu\n",
                        width_index == 0 ? 4u : 8u,
                        (unsigned long long)lengths[length_index]);
                return 1;
            }
    if (run_case(4, 9, 1) || run_case(8, 9, 1)) {
        fprintf(stderr, "zfp exceptional-value smoke failed\n");
        return 1;
    }
    puts("zfp native ABI smoke: PASS");
    return 0;
}
