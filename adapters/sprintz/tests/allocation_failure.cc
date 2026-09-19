#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <vector>

extern "C" {
int tscb_sprintz8_bound(size_t, size_t*);
int tscb_sprintz8_compress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t*);
int tscb_sprintz8_decompress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t, size_t*);
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

int main() {
    std::vector<uint8_t> input(128), decoded(128);
    for (size_t i = 0; i < input.size(); ++i) input[i] = static_cast<uint8_t>(i);
    for (unsigned variant = 0; variant < 2; ++variant) {
        size_t bound = 0, used = 0, recovered = 0;
        if (tscb_sprintz8_bound(input.size(), &bound)) return 1;
        std::vector<uint8_t> stream(bound);
        for (int failure = 0; failure < (variant ? 4 : 3); ++failure) {
            allocation_count = 0;
            fail_at = failure;
            const int status = tscb_sprintz8_compress(variant, input.data(), input.size(),
                                                       stream.data(), bound, &used);
            fail_at = -1;
            if (status != 4 || used != 0 || allocation_count != (variant ? 4 : 3)) return 2;
        }
        allocation_count = 0;
        if (tscb_sprintz8_compress(variant, input.data(), input.size(),
                                   stream.data(), bound, &used)) return 3;
        for (int failure = 0; failure < (variant ? 4 : 3); ++failure) {
            allocation_count = 0;
            fail_at = failure;
            const int status = tscb_sprintz8_decompress(variant, stream.data(), used,
                                                         decoded.data(), decoded.size(),
                                                         decoded.size(), &recovered);
            fail_at = -1;
            if (status != 4 || recovered != 0 || allocation_count != (variant ? 4 : 3)) return 4;
        }
    }
    std::puts("sprintz vendor allocation failure paths passed");
}
