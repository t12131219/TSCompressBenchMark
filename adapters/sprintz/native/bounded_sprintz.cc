#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

#include "sprintz.h"

namespace {
constexpr size_t kEnvelopeBytes = 16;
constexpr size_t kMetadataBytes = 8;
constexpr size_t kMaxElements = 16 * 1024 * 1024;
constexpr uint8_t kInputMagic[4] = {'T', 'S', 'I', '1'};
constexpr uint8_t kFrameMagic[4] = {'T', 'S', 'F', '1'};

uint16_t read16(const uint8_t* p) {
    return static_cast<uint16_t>(p[0]) |
        static_cast<uint16_t>(static_cast<uint16_t>(p[1]) << 8);
}

uint32_t read32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) |
        (static_cast<uint32_t>(p[1]) << 8) |
        (static_cast<uint32_t>(p[2]) << 16) |
        (static_cast<uint32_t>(p[3]) << 24);
}

uint64_t read64(const uint8_t* p) {
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= static_cast<uint64_t>(p[i]) << (8 * i);
    return value;
}

void write16(uint8_t* p, uint16_t value) {
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8);
}

void write64(uint8_t* p, uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) p[i] = static_cast<uint8_t>(value >> (8 * i));
}

bool checked_add(size_t a, size_t b, size_t* result) {
    if (a > std::numeric_limits<size_t>::max() - b) return false;
    *result = a + b;
    return true;
}

bool checked_mul(size_t a, size_t b, size_t* result) {
    if (a && b > std::numeric_limits<size_t>::max() / a) return false;
    *result = a * b;
    return true;
}

struct Shape {
    uint8_t element_bytes;
    uint16_t dimensions;
    size_t elements;
    size_t payload_bytes;
};

bool parse_envelope(const uint8_t* src, size_t size, const uint8_t magic[4], Shape* shape) {
    if (!src || !shape || size < kEnvelopeBytes || std::memcmp(src, magic, 4) ||
        (src[4] != 1 && src[4] != 2) || src[5] != 0) return false;
    const uint16_t dimensions = read16(src + 6);
    const uint64_t elements64 = read64(src + 8);
    if (!dimensions || dimensions > 128 || elements64 > kMaxElements ||
        elements64 % dimensions) return false;
    size_t payload_bytes = 0;
    if (!checked_mul(static_cast<size_t>(elements64), src[4], &payload_bytes)) return false;
    *shape = Shape{src[4], dimensions, static_cast<size_t>(elements64), payload_bytes};
    return true;
}

bool bound_for(const Shape& shape, size_t* bytes) {
    size_t expanded = 0;
    return checked_mul(shape.payload_bytes, 4, &expanded) &&
        checked_add(expanded, kEnvelopeBytes + kMetadataBytes + 64, bytes);
}

unsigned header_field(const uint8_t* header, size_t bit_offset, unsigned bits) {
    unsigned value = 0;
    for (unsigned bit = 0; bit < bits; ++bit) {
        value |= static_cast<unsigned>((header[(bit_offset + bit) / 8] >>
            ((bit_offset + bit) % 8)) & 1u) << bit;
    }
    return value;
}

bool validate_native(const uint8_t* src, size_t size, const Shape& shape,
                     bool require_exact_size, size_t* consumed) {
    if (!src || size < kMetadataBytes) return false;
    const uint32_t groups = read32(src);
    const uint16_t tail = read16(src + 4);
    const uint16_t dimensions = read16(src + 6);
    if (dimensions != shape.dimensions || tail > shape.elements) return false;
    if (groups == 0) {
        size_t tail_bytes = 0;
        if (!(tail == shape.elements &&
              checked_mul(tail, shape.element_bytes, &tail_bytes) &&
              kMetadataBytes + tail_bytes <= size &&
              (!require_exact_size || size == kMetadataBytes + tail_bytes))) return false;
        if (consumed) *consumed = kMetadataBytes + tail_bytes;
        return true;
    }
    if (shape.elements < 128) return false;

    const unsigned width_bits = shape.element_bytes == 1 ? 3 : 4;
    const unsigned stored_max = shape.element_bytes == 1 ? 7 : 15;
    const unsigned actual_max = shape.element_bytes * 8;
    const bool lowdim = shape.element_bytes == 1 ? shape.dimensions <= 4
                                                 : shape.dimensions <= 2;
    const size_t header_bits = static_cast<size_t>(dimensions) * width_bits * 2;
    const size_t header_bytes = (header_bits + 7) / 8;
    size_t pos = kMetadataBytes;
    size_t produced = 0;
    for (uint32_t group = 0; group < groups; ++group) {
        if (header_bytes > size - pos) return false;
        const uint8_t* header = src + pos;
        if ((header_bits & 7u) &&
            (header[header_bytes - 1] >> (header_bits & 7u))) return false;
        pos += header_bytes;
        bool previous_run = false;
        for (unsigned block = 0; block < 2; ++block) {
            size_t row_bits = 0;
            for (uint16_t dim = 0; dim < dimensions; ++dim) {
                unsigned width = header_field(
                    header, (static_cast<size_t>(block) * dimensions + dim) * width_bits,
                    width_bits);
                if (width == stored_max) width = actual_max;
                if (!checked_add(row_bits, width, &row_bits)) return false;
            }
            size_t block_elements = static_cast<size_t>(8) * dimensions;
            if (row_bits == 0) {
                if (pos == size) return false;
                const uint8_t low = src[pos++];
                unsigned run = low & 0x7f;
                if (low & 0x80) {
                    if (pos == size || src[pos] == 0) return false;
                    run += static_cast<unsigned>(src[pos++]) << 7;
                }
                if (run == 0 && !(previous_run && block == 1 && group + 1 == groups))
                    return false;
                if (!checked_mul(static_cast<size_t>(run) * 8, dimensions,
                                 &block_elements)) return false;
                previous_run = run != 0;
            } else {
                // Low-dimension kernels pack all eight rows contiguously;
                // generic kernels byte-align every row.
                const size_t packed_bytes = lowdim ? row_bits : ((row_bits + 7) / 8) * 8;
                if (packed_bytes > size - pos) return false;
                pos += packed_bytes;
                previous_run = false;
            }
            if (block_elements > shape.elements - produced) return false;
            produced += block_elements;
        }
    }
    size_t tail_bytes = 0;
    if (!(tail <= shape.elements - produced && produced + tail == shape.elements &&
          checked_mul(tail, shape.element_bytes, &tail_bytes) &&
          pos <= size && tail_bytes <= size - pos &&
          (!require_exact_size || size - pos == tail_bytes))) return false;
    if (consumed) *consumed = pos + tail_bytes;
    return true;
}
}  // namespace

extern "C" {

int tscb_sprintz_bound(const uint8_t* input, size_t input_size, size_t* bytes) {
    Shape shape{};
    if (!bytes || !parse_envelope(input, input_size, kInputMagic, &shape) ||
        input_size != kEnvelopeBytes + shape.payload_bytes || !bound_for(shape, bytes)) return 1;
    return 0;
}

int tscb_sprintz_compress(unsigned variant, const uint8_t* input, size_t input_size,
                          uint8_t* dest, size_t capacity, size_t* used) {
    Shape shape{};
    size_t bound = 0;
    if (variant > 1 || !used || !dest ||
        tscb_sprintz_bound(input, input_size, &bound) ||
        !parse_envelope(input, input_size, kInputMagic, &shape)) return 1;
    *used = 0;
    if (capacity < bound) return 2;
    try {
        std::vector<uint8_t> source(shape.payload_bytes + 64);
        std::vector<uint8_t> encoded(bound + 64);
        if (shape.payload_bytes) std::memcpy(source.data(), input + kEnvelopeBytes,
                                             shape.payload_bytes);
        int64_t encoded_elements = -1;
        if (shape.element_bytes == 1) {
            encoded_elements = variant == 0
                ? sprintz_compress_delta_8b(source.data(), static_cast<uint32_t>(shape.elements),
                    reinterpret_cast<int8_t*>(encoded.data()), shape.dimensions, true)
                : sprintz_compress_xff_8b(source.data(), static_cast<uint32_t>(shape.elements),
                    reinterpret_cast<int8_t*>(encoded.data()), shape.dimensions, true);
        } else {
            encoded_elements = variant == 0
                ? sprintz_compress_delta_16b(reinterpret_cast<const uint16_t*>(source.data()),
                    static_cast<uint32_t>(shape.elements),
                    reinterpret_cast<int16_t*>(encoded.data()), shape.dimensions, true)
                : sprintz_compress_xff_16b(reinterpret_cast<const uint16_t*>(source.data()),
                    static_cast<uint32_t>(shape.elements),
                    reinterpret_cast<int16_t*>(encoded.data()), shape.dimensions, true);
        }
        if (encoded_elements < 0 ||
            static_cast<uint64_t>(encoded_elements) >
                static_cast<uint64_t>(std::numeric_limits<size_t>::max())) return 4;
        size_t returned_bytes = 0;
        size_t encoded_bytes = 0;
        if (!checked_mul(static_cast<size_t>(encoded_elements), shape.element_bytes,
                         &returned_bytes) ||
            !validate_native(encoded.data(), encoded.size(), shape, false, &encoded_bytes) ||
            encoded_bytes < returned_bytes ||
            encoded_bytes - returned_bytes >= shape.element_bytes ||
            encoded_bytes > bound - kEnvelopeBytes) return 4;
        std::memcpy(dest, kFrameMagic, 4);
        dest[4] = shape.element_bytes;
        dest[5] = 0;
        write16(dest + 6, shape.dimensions);
        write64(dest + 8, shape.elements);
        std::memcpy(dest + kEnvelopeBytes, encoded.data(), encoded_bytes);
        *used = kEnvelopeBytes + encoded_bytes;
        return 0;
    } catch (const std::bad_alloc&) { return 5; }
}

int tscb_sprintz_decompress(unsigned variant, const uint8_t* src, size_t size,
                            uint8_t* dest, size_t capacity, size_t* used) {
    Shape shape{};
    if (variant > 1 || !used || !src || !dest ||
        !parse_envelope(src, size, kFrameMagic, &shape)) return 1;
    *used = 0;
    if (capacity < shape.payload_bytes) return 2;
    if (size < kEnvelopeBytes ||
        !validate_native(src + kEnvelopeBytes, size - kEnvelopeBytes, shape, true,
                         nullptr)) return 3;
    try {
        std::vector<uint8_t> input(size - kEnvelopeBytes + 32);
        std::vector<uint8_t> output(shape.payload_bytes + 64);
        std::memcpy(input.data(), src + kEnvelopeBytes, size - kEnvelopeBytes);
        int64_t decoded_elements = -1;
        if (shape.element_bytes == 1) {
            decoded_elements = variant == 0
                ? sprintz_decompress_delta_8b(reinterpret_cast<const int8_t*>(input.data()),
                                               output.data())
                : sprintz_decompress_xff_8b(reinterpret_cast<const int8_t*>(input.data()),
                                             output.data());
        } else {
            decoded_elements = variant == 0
                ? sprintz_decompress_delta_16b(reinterpret_cast<const int16_t*>(input.data()),
                    reinterpret_cast<uint16_t*>(output.data()))
                : sprintz_decompress_xff_16b(reinterpret_cast<const int16_t*>(input.data()),
                    reinterpret_cast<uint16_t*>(output.data()));
        }
        if (decoded_elements != static_cast<int64_t>(shape.elements)) return 4;
        if (shape.payload_bytes) std::memcpy(dest, output.data(), shape.payload_bytes);
        *used = shape.payload_bytes;
        return 0;
    } catch (const std::bad_alloc&) { return 5; }
}

}  // extern "C"
