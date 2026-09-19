#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <random>
#include <vector>

extern "C" {
int tscb_sprintz8_bound(size_t, size_t*);
int tscb_sprintz8_compress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t*);
int tscb_sprintz8_decompress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t, size_t*);
}

int main() {
    std::mt19937 rng(20260919);
    for (unsigned variant = 0; variant < 2; ++variant) {
        for (size_t n : {0u, 1u, 2u, 7u, 8u, 15u, 16u, 127u, 128u, 129u,
                         143u, 144u, 255u, 256u, 1000u, 16384u, 131072u}) {
            for (unsigned pattern = 0; pattern < 4; ++pattern) {
                std::vector<uint8_t> input(n), decoded(n + 1, 0xcc);
                for (size_t i = 0; i < n; ++i) {
                    input[i] = pattern == 0 ? 0 : pattern == 1 ? 255
                        : pattern == 2 ? static_cast<uint8_t>(i) : static_cast<uint8_t>(rng());
                }
                size_t bound = 0, used = 0, recovered = 0;
                if (tscb_sprintz8_bound(n, &bound)) return 1;
                std::vector<uint8_t> stream(bound + 1, 0xcd);
                if (tscb_sprintz8_compress(variant, input.data(), n, stream.data(), bound, &used) ||
                    used > bound || stream[bound] != 0xcd) return 2;
                if (tscb_sprintz8_decompress(variant, stream.data(), used, decoded.data(),
                                              n, n, &recovered) || recovered != n ||
                    !std::equal(input.begin(), input.end(), decoded.begin()) || decoded[n] != 0xcc)
                    return 3;
                if (tscb_sprintz8_decompress(variant, stream.data(), used - 1, decoded.data(),
                                              n, n, &recovered) == 0) return 4;
                if (n && tscb_sprintz8_decompress(variant, stream.data(), used, decoded.data(),
                                                   n - 1, n, &recovered) != 2) return 5;
                stream[6] = 2;
                if (tscb_sprintz8_decompress(variant, stream.data(), used, decoded.data(),
                                              n, n, &recovered) != 3) return 6;
            }
        }
        for (unsigned trial = 0; trial < 2048; ++trial) {
            size_t n = trial % 4 == 0 ? 128 + rng() % 2048 : rng() % 128;
            std::vector<uint8_t> input(n), decoded(n + 1, 0xcc);
            for (auto& value : input) value = static_cast<uint8_t>(rng());
            size_t bound = 0, used = 0, recovered = 0;
            if (tscb_sprintz8_bound(n, &bound)) return 7;
            std::vector<uint8_t> stream(bound);
            if (tscb_sprintz8_compress(variant, input.data(), n, stream.data(), bound, &used) ||
                tscb_sprintz8_decompress(variant, stream.data(), used, decoded.data(),
                                          n, n, &recovered) || recovered != n ||
                !std::equal(input.begin(), input.end(), decoded.begin())) return 8;
            // Corruption can retain valid grammar; decode may succeed, but must stay bounded.
            if (used) stream[rng() % used] ^= static_cast<uint8_t>(1u << (rng() % 8));
            tscb_sprintz8_decompress(variant, stream.data(), used, decoded.data(),
                                      n, n, &recovered);
            if (decoded[n] != 0xcc) return 9;
            std::vector<uint8_t> hostile(8 + rng() % 128);
            for (auto& value : hostile) value = static_cast<uint8_t>(rng());
            tscb_sprintz8_decompress(variant, hostile.data(), hostile.size(), decoded.data(),
                                      n, n, &recovered);
            if (decoded[n] != 0xcc) return 10;
        }
    }
    std::puts("sprintz 8-bit bounded qualification roundtrips passed");
}
