#pragma once
#include "sf_codec.hpp"
#include <cpuid.h>

namespace tsbench::sprintz_fire {
inline constexpr sf::Config profile{1, 16, 4, 0};
inline constexpr size_t max_bytes = 65536;

// Do not call code from the AVX2/BMI-targeted DSO before this check. In
// particular, the DSO's own supported() shares those compile flags.
inline bool supported_host() noexcept {
    unsigned a, b, c, d;
    __builtin_cpu_init();
    return __get_cpuid(0x80000001, &a, &b, &c, &d) && (c & (1u << 5)) &&
           __builtin_cpu_supports("avx2") && __builtin_cpu_supports("bmi") &&
           __builtin_cpu_supports("bmi2") && __builtin_cpu_supports("popcnt");
}
}
