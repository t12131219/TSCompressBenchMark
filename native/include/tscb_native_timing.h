#ifndef TSCB_NATIVE_TIMING_H
#define TSCB_NATIVE_TIMING_H

#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include "tscb_adapter_v1.h"
#include <time.h>

typedef struct tscb_native_timer {
    int enabled;
    int available;
    uint64_t encode_ns;
    uint64_t decode_ns;
} tscb_native_timer;

static inline uint64_t tscb_native_now(tscb_native_timer *timer) {
    struct timespec value;
    if (!timer->enabled || !timer->available) return 0U;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        timer->available = 0;
        return 0U;
    }
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
}

/* End the interval before wrapper status checks. Failed codec calls also contribute. */
#define TSCB_TIME_CODEC(timer, field, call) do { \
    uint64_t tscb_started = tscb_native_now(&(timer)); \
    call; \
    uint64_t tscb_ended = tscb_native_now(&(timer)); \
    if ((timer).enabled && (timer).available) { \
        if (tscb_ended < tscb_started || UINT64_MAX - (timer).field < tscb_ended - tscb_started) \
            (timer).available = 0; \
        else (timer).field += tscb_ended - tscb_started; \
    } \
} while (0)

#define TSCB_NATIVE_TIMING_API \
tscb_status_v1 tscb_set_native_timing(tscb_codec_handle_v1 *handle, uint32_t enabled) { \
    if (handle == NULL || enabled > 1U) return TSCB_STATUS_INVALID_ARGUMENT_V1; \
    handle->native_timer.enabled = (int)enabled; \
    handle->native_timer.available = 1; \
    handle->native_timer.encode_ns = handle->native_timer.decode_ns = 0U; \
    return TSCB_STATUS_OK_V1; \
} \
tscb_status_v1 tscb_get_native_timing( \
    tscb_codec_handle_v1 *handle, tscb_native_timing_v1 *timing) { \
    if (handle == NULL || timing == NULL) return TSCB_STATUS_INVALID_ARGUMENT_V1; \
    if (timing->struct_size != sizeof(*timing) || timing->version != 1U) \
        return TSCB_STATUS_ABI_MISMATCH_V1; \
    if (!handle->native_timer.enabled || !handle->native_timer.available) \
        return TSCB_STATUS_UNSUPPORTED_V1; \
    timing->native_encode_wall_ns = handle->native_timer.encode_ns; \
    timing->native_decode_wall_ns = handle->native_timer.decode_ns; \
    return TSCB_STATUS_OK_V1; \
}

#endif
