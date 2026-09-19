#include <cstdint>
#include <cstdio>
#include <vector>

#include "sprintz_delta.h"
#include "sprintz_xff.h"

int main() {
    std::vector<uint8_t> input(128);
    for (size_t i = 0; i < input.size(); ++i) input[i] = static_cast<uint8_t>(i);
    for (int algorithm = 0; algorithm < 2; ++algorithm) {
        std::vector<int8_t> encoded(1024);
        std::vector<uint8_t> decoded(input.size() + 64);
        const int64_t size = algorithm == 0
            ? compress_rowmajor_delta_rle_lowdim_8b(input.data(), input.size(), encoded.data(), 1, true)
            : compress_rowmajor_xff_rle_lowdim_8b(input.data(), input.size(), encoded.data(), 1, true);
        if (size <= 0) return 1;
        const int64_t count = algorithm == 0
            ? decompress_rowmajor_delta_rle_lowdim_8b(encoded.data(), decoded.data())
            : decompress_rowmajor_xff_rle_lowdim_8b(encoded.data(), decoded.data());
        if (count != static_cast<int64_t>(input.size()) ||
            !std::equal(input.begin(), input.end(), decoded.begin())) return 2;
        std::printf("%s: %ld bytes\n", algorithm == 0 ? "delta" : "xff", size);
    }
}
