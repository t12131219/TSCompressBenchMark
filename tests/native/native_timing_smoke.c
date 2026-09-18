#define clock_gettime tscb_test_clock_gettime
#include "tscb_native_timing.h"
#include <assert.h>

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer;
};

TSCB_NATIVE_TIMING_API

static int clock_failure;
static int clock_backwards;
static uint64_t ticks = 10U;

int tscb_test_clock_gettime(clockid_t clock, struct timespec *value) {
    assert(clock == CLOCK_MONOTONIC);
    if (clock_failure) return -1;
    ticks = clock_backwards ? ticks - 1U : ticks + 3U;
    value->tv_sec = 0;
    value->tv_nsec = (long)ticks;
    return 0;
}

int main(void) {
    tscb_codec_handle_v1 handle = {0};
    tscb_native_timing_v1 result = {sizeof(result), 1U, 0U, 0U};
    int calls = 0;
    assert(tscb_get_native_timing(&handle, &result) == TSCB_STATUS_UNSUPPORTED_V1);
    assert(tscb_set_native_timing(&handle, 2U) == TSCB_STATUS_INVALID_ARGUMENT_V1);
    assert(tscb_set_native_timing(&handle, 1U) == TSCB_STATUS_OK_V1);
    TSCB_TIME_CODEC(handle.native_timer, encode_ns, calls++);
    TSCB_TIME_CODEC(handle.native_timer, encode_ns, calls++);
    TSCB_TIME_CODEC(handle.native_timer, decode_ns, calls++);
    assert(calls == 3);
    assert(tscb_get_native_timing(&handle, &result) == TSCB_STATUS_OK_V1);
    assert(result.native_encode_wall_ns == 6U && result.native_decode_wall_ns == 3U);
    assert(tscb_get_native_timing(&handle, &result) == TSCB_STATUS_OK_V1);
    assert(result.native_encode_wall_ns == 6U);
    result.struct_size = 0U;
    assert(tscb_get_native_timing(&handle, &result) == TSCB_STATUS_ABI_MISMATCH_V1);
    result.struct_size = sizeof(result);
    clock_failure = 1;
    TSCB_TIME_CODEC(handle.native_timer, encode_ns, calls++);
    assert(calls == 4);
    assert(tscb_get_native_timing(&handle, &result) == TSCB_STATUS_UNSUPPORTED_V1);
    clock_failure = 0;
    assert(tscb_set_native_timing(&handle, 1U) == TSCB_STATUS_OK_V1);
    handle.native_timer.encode_ns = UINT64_MAX;
    TSCB_TIME_CODEC(handle.native_timer, encode_ns, calls++);
    assert(tscb_get_native_timing(&handle, &result) == TSCB_STATUS_UNSUPPORTED_V1);
    assert(tscb_set_native_timing(&handle, 1U) == TSCB_STATUS_OK_V1);
    clock_backwards = 1;
    TSCB_TIME_CODEC(handle.native_timer, encode_ns, calls++);
    assert(tscb_get_native_timing(&handle, &result) == TSCB_STATUS_UNSUPPORTED_V1);
    return 0;
}
