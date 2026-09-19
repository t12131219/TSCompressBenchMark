#include <cstdint>
#include <cstdio>
#include <random>
#include <vector>

#include "sprintz_delta.h"
#include "sprintz_xff.h"

int main() {
    std::mt19937 rng(20260919);
    for (unsigned variant = 0; variant < 2; ++variant) {
        for (size_t n : {0u, 1u, 2u, 7u, 8u, 15u, 16u, 127u, 128u, 129u,
                         143u, 144u, 255u, 256u, 1000u, 8192u}) {
            for (unsigned pattern = 0; pattern < 4; ++pattern) {
                std::vector<uint8_t> source(n + 1);
                for (size_t i = 0; i < n; ++i) {
                    source[i] = pattern == 0 ? 0 : pattern == 1 ? 255
                        : pattern == 2 ? static_cast<uint8_t>(i) : static_cast<uint8_t>(rng());
                }
                std::vector<int8_t> result(8 + 4 * n + 64);
                int64_t count = variant == 0
                    ? compress_rowmajor_delta_rle_lowdim_8b(source.data(), n, result.data(), 1, true)
                    : compress_rowmajor_xff_rle_lowdim_8b(source.data(), n, result.data(), 1, true);
                if (count < 0 || static_cast<size_t>(count) > result.size()) return 1;
                std::printf("%u %zu %u %ld ", variant, n, pattern, count);
                for (int64_t i = 0; i < count; ++i) {
                    std::printf("%02x", static_cast<unsigned>(static_cast<uint8_t>(result[i])));
                }
                std::putchar('\n');
            }
        }
    }
}
