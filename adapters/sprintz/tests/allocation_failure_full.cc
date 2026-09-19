#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

extern "C" {
int tscb_sprintz_bound(const uint8_t*, size_t, size_t*);
int tscb_sprintz_compress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t*);
int tscb_sprintz_decompress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t*);
void* __real_malloc(size_t);
void* __real_calloc(size_t, size_t);
}

static int fail_at = -1;
static int allocation_count = 0;

extern "C" void* __wrap_malloc(size_t size) {
    if (allocation_count++ == fail_at) return nullptr;
    return __real_malloc(size);
}

extern "C" void* __wrap_calloc(size_t count, size_t size) {
    if (allocation_count++ == fail_at) return nullptr;
    return __real_calloc(count, size);
}

static void write16(uint8_t* p, uint16_t value) {
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8);
}

static void write64(uint8_t* p, uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) p[i] = static_cast<uint8_t>(value >> (8 * i));
}

int main() {
    constexpr uint16_t ndims = 5;
    constexpr size_t rows = 137;
    for (unsigned variant = 0; variant < 2; ++variant) {
        for (uint8_t width : {uint8_t{1}, uint8_t{2}}) {
            const size_t elements = rows * ndims;
            std::vector<uint8_t> input(16 + elements * width);
            std::memcpy(input.data(), "TSI1", 4);
            input[4] = width;
            input[5] = 0;
            write16(input.data() + 6, ndims);
            write64(input.data() + 8, elements);
            for (size_t i = 16; i < input.size(); ++i)
                input[i] = static_cast<uint8_t>(i * 29 + 7);
            size_t bound = 0;
            if (tscb_sprintz_bound(input.data(), input.size(), &bound)) return 1;
            std::vector<uint8_t> stream(bound);
            size_t used = 0;
            allocation_count = 0;
            if (tscb_sprintz_compress(variant, input.data(), input.size(),
                                      stream.data(), stream.size(), &used)) return 2;
            const int compress_allocations = allocation_count;
            if (compress_allocations < 6) return 3;
            for (int failure = 0; failure < compress_allocations; ++failure) {
                allocation_count = 0;
                fail_at = failure;
                size_t failed_used = 99;
                const int status = tscb_sprintz_compress(
                    variant, input.data(), input.size(), stream.data(), stream.size(),
                    &failed_used);
                fail_at = -1;
                if (status != 4 || failed_used != 0) return 4;
            }
            std::vector<uint8_t> decoded(elements * width);
            allocation_count = 0;
            size_t recovered = 0;
            if (tscb_sprintz_decompress(variant, stream.data(), used, decoded.data(),
                                        decoded.size(), &recovered)) return 5;
            const int decompress_allocations = allocation_count;
            if (decompress_allocations < 7) return 6;
            for (int failure = 0; failure < decompress_allocations; ++failure) {
                allocation_count = 0;
                fail_at = failure;
                size_t failed_used = 99;
                const int status = tscb_sprintz_decompress(
                    variant, stream.data(), used, decoded.data(), decoded.size(),
                    &failed_used);
                fail_at = -1;
                if (status != 4 || failed_used != 0) return 7;
            }
        }
    }
    std::puts("Sprintz generic allocation-failure paths passed");
    return 0;
}
