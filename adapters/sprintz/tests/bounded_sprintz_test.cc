#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

extern "C" {
int tscb_sprintz_bound(const uint8_t*, size_t, size_t*);
int tscb_sprintz_compress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t*);
int tscb_sprintz_decompress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t*);
}

static void write16(uint8_t* p, uint16_t value) {
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8);
}

static void write64(uint8_t* p, uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) p[i] = static_cast<uint8_t>(value >> (8 * i));
}

int main() {
    std::mt19937 generator(0x5350525a);
    const uint16_t dimensions[] = {1, 2, 3, 4, 5, 8, 9, 127, 128};
    const size_t rows[] = {0, 1, 7, 8, 15, 16, 127, 128, 129, 137};
    for (unsigned variant = 0; variant < 2; ++variant) {
        for (uint8_t width : {uint8_t{1}, uint8_t{2}}) {
            for (uint16_t ndims : dimensions) {
                for (size_t nrows : rows) {
                    const size_t elements = nrows * ndims;
                    const size_t payload_bytes = elements * width;
                    std::vector<uint8_t> input(16 + payload_bytes);
                    std::memcpy(input.data(), "TSI1", 4);
                    input[4] = width;
                    input[5] = 0;
                    write16(input.data() + 6, ndims);
                    write64(input.data() + 8, elements);
                    for (size_t i = 0; i < payload_bytes; ++i)
                        input[16 + i] = static_cast<uint8_t>(generator());
                    size_t bound = 0;
                    if (tscb_sprintz_bound(input.data(), input.size(), &bound)) return 1;
                    std::vector<uint8_t> encoded(bound);
                    size_t encoded_size = 0;
                    if (tscb_sprintz_compress(variant, input.data(), input.size(),
                                              encoded.data(), encoded.size(),
                                              &encoded_size)) {
                        std::fprintf(stderr,
                                     "compress failed: variant=%u width=%u ndims=%u rows=%zu\n",
                                     variant, width, ndims, nrows);
                        return 2;
                    }
                    if (encoded_size > bound) return 3;
                    std::vector<uint8_t> decoded(payload_bytes ? payload_bytes : 1);
                    size_t decoded_size = 0;
                    if (tscb_sprintz_decompress(variant, encoded.data(), encoded_size,
                                               decoded.data(), payload_bytes,
                                               &decoded_size)) return 4;
                    if (decoded_size != payload_bytes ||
                        std::memcmp(decoded.data(), input.data() + 16, payload_bytes)) return 5;
                    if (encoded_size > 1 &&
                        !tscb_sprintz_decompress(variant, encoded.data(), encoded_size - 1,
                                                decoded.data(), payload_bytes,
                                                &decoded_size)) return 6;
                    if (payload_bytes &&
                        !tscb_sprintz_decompress(variant, encoded.data(), encoded_size,
                                                decoded.data(), payload_bytes - 1,
                                                &decoded_size)) return 7;
                }
            }
        }
    }
    std::puts("bounded Sprintz 8/16-bit UTS/MTS qualification passed");
    return 0;
}
