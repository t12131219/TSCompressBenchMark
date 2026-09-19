#include <cstddef>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

#include "sprintz_delta.h"
#include "sprintz_xff.h"

namespace {
constexpr size_t kMaxElements = 128 * 1024;
constexpr size_t kMetadata = 8;

uint16_t read16(const uint8_t* p) {
    return static_cast<uint16_t>(p[0] | (static_cast<uint16_t>(p[1]) << 8));
}

uint32_t read32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) |
        (static_cast<uint32_t>(p[1]) << 8) |
        (static_cast<uint32_t>(p[2]) << 16) |
        (static_cast<uint32_t>(p[3]) << 24);
}

bool validate(const uint8_t* p, size_t size, size_t expected) {
    if (size < kMetadata || expected > kMaxElements || size > kMetadata + 4 * expected + 64 ||
        read16(p + 6) != 1) return false;
    const uint32_t groups = read32(p);
    const uint16_t tail = read16(p + 4);
    if (groups == 0) {
        return expected < 128 && tail == expected && size == kMetadata + tail;
    }
    if (expected < 128 || groups > size - kMetadata || tail > expected) return false;
    size_t pos = kMetadata;
    size_t written = 0;
    for (uint32_t g = 0; g < groups; ++g) {
        if (pos == size) return false;
        const uint8_t header = p[pos++];
        if (header & 0xc0) return false;
        bool previous_run = false;
        for (unsigned b = 0; b < 2; ++b) {
            const unsigned width = (header >> (b * 3)) & 7;
            size_t block_elements = 8;
            if (width == 0) {
                if (pos == size) return false;
                const uint8_t low = p[pos++];
                unsigned run = low & 0x7f;
                if (low & 0x80) {
                    if (pos == size) return false;
                    const uint8_t high = p[pos++];
                    if (high == 0) return false;
                    run += static_cast<unsigned>(high) << 7;
                }
                // A zero-length block is only the vendor's terminal RLE filler.
                if (run == 0 && !(previous_run && b == 1 && g + 1 == groups)) return false;
                block_elements = static_cast<size_t>(run) * 8;
                previous_run = run != 0;
            } else {
                const size_t packed_bytes = width == 7 ? 8 : width;
                if (packed_bytes > size - pos) return false;
                pos += packed_bytes;
                previous_run = false;
            }
            if (block_elements > expected - written) return false;
            written += block_elements;
        }
    }
    return tail <= expected - written && written + tail == expected &&
        pos <= size && size - pos == tail;
}

size_t bound(size_t n) { return kMetadata + 4 * n + 64; }
}  // namespace

extern "C" {

// Internal qualification interface; this is not a registered benchmark ABI.
int tscb_sprintz8_bound(size_t elements, size_t* bytes) {
    if (!bytes || elements > kMaxElements) return 1;
    *bytes = bound(elements);
    return 0;
}

int tscb_sprintz8_compress(unsigned variant, const uint8_t* src, size_t elements,
                           uint8_t* dest, size_t capacity, size_t* used) {
    if (variant > 1 || !used || !dest || (!src && elements) || elements > kMaxElements)
        return 1;
    *used = 0;
    if (capacity < bound(elements)) return 2;
    try {
        // Vendor writes 8-byte packed words past logical fields; these bytes
        // are never part of the stream and never reach the caller's buffer.
        std::vector<int8_t> scratch(bound(elements) + 64);
        const uint8_t empty = 0;
        const uint8_t* input = elements ? src : &empty;
        const int64_t length = variant == 0
            ? compress_rowmajor_delta_rle_lowdim_8b(input, elements, scratch.data(), 1, true)
            : compress_rowmajor_xff_rle_lowdim_8b(input, elements, scratch.data(), 1, true);
        if (length < 0 || static_cast<size_t>(length) > bound(elements) ||
            !validate(reinterpret_cast<const uint8_t*>(scratch.data()), length, elements)) return 4;
        std::memcpy(dest, scratch.data(), length);
        *used = static_cast<size_t>(length);
        return 0;
    } catch (const std::bad_alloc&) { return 5; }
}

int tscb_sprintz8_decompress(unsigned variant, const uint8_t* src, size_t size,
                             uint8_t* dest, size_t capacity, size_t expected,
                             size_t* used) {
    if (variant > 1 || !used || !src || !dest || expected > kMaxElements) return 1;
    *used = 0;
    if (capacity < expected) return 2;
    if (!validate(src, size, expected)) return 3;
    try {
        std::vector<int8_t> input(size + 16);
        std::vector<uint8_t> output(expected + 64);
        std::memcpy(input.data(), src, size);
        const int64_t count = variant == 0
            ? decompress_rowmajor_delta_rle_lowdim_8b(input.data(), output.data())
            : decompress_rowmajor_xff_rle_lowdim_8b(input.data(), output.data());
        if (count != static_cast<int64_t>(expected)) return 4;
        std::memcpy(dest, output.data(), expected);
        *used = expected;
        return 0;
    } catch (const std::bad_alloc&) { return 5; }
}

}  // extern "C"
