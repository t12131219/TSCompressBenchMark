#include "tscb_adapter_v1.h"

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#if TSCB_ALP_RD
static constexpr char kConfig[] = "{\"algorithm\":\"alp-rd\"}";
#else
static constexpr char kConfig[] = "{\"algorithm\":\"alp\"}";
#endif

static void append16(std::vector<uint8_t>& out, uint16_t value) {
    out.push_back(static_cast<uint8_t>(value));
    out.push_back(static_cast<uint8_t>(value >> 8));
}

static void append64(std::vector<uint8_t>& out, uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) out.push_back(static_cast<uint8_t>(value >> (8 * i)));
}

static tscb_buffer_v1 buffer(void* data, uint64_t capacity, uint64_t used) {
    tscb_buffer_v1 result{};
    result.data = data;
    result.capacity_bytes = capacity;
    result.used_bytes = used;
    result.dtype = TSCB_DTYPE_BYTES_V1;
    result.rank = 1;
    result.shape[0] = used;
    result.strides_bytes[0] = 1;
    result.alignment_bytes = 1;
    result.ownership = TSCB_OWNERSHIP_CALLER_V1;
    return result;
}

template <typename T>
static bool check_case(uint64_t rows) {
    constexpr uint16_t columns = 2;
    std::vector<T> values(rows * columns);
    for (uint16_t column = 0; column < columns; ++column) {
        for (uint64_t row = 0; row < rows; ++row) {
            values[static_cast<uint64_t>(column) * rows + row] =
                static_cast<T>((row % 10000) / 10.0 + column);
        }
    }
    if (rows >= 128) {
        if constexpr (sizeof(T) == 8) {
            const std::array<uint64_t, 7> bits{{
                0x8000000000000000ULL, 0x7ff0000000000000ULL,
                0xfff0000000000000ULL, 1ULL, 0x8000000000000001ULL,
                0x7ff8000000000001ULL, 0x7ff8000000001234ULL,
            }};
            for (size_t i = 0; i < bits.size(); ++i)
                std::memcpy(&values[3 + i * 17], &bits[i], sizeof(T));
        } else {
            const std::array<uint32_t, 7> bits{{
                0x80000000U, 0x7f800000U, 0xff800000U, 1U,
                0x80000001U, 0x7fc00001U, 0x7fc01234U,
            }};
            for (size_t i = 0; i < bits.size(); ++i)
                std::memcpy(&values[3 + i * 17], &bits[i], sizeof(T));
        }
    }
    std::vector<uint8_t> input;
    input.insert(input.end(), {'T', 'A', 'I', '1'});
    input.push_back(sizeof(T));
    input.push_back(0);
    append16(input, columns);
    append64(input, rows);
    if (!values.empty()) {
        const auto* raw = reinterpret_cast<const uint8_t*>(values.data());
        input.insert(input.end(), raw, raw + values.size() * sizeof(T));
    }

    tscb_codec_handle_v1* handle = nullptr;
    if (tscb_create(kConfig, sizeof(kConfig) - 1, &handle) || !handle) return false;
    auto source = buffer(input.data(), input.size(), input.size());
    uint64_t bound = 0;
    if (tscb_compress_bound(handle, &source, &bound) || bound < 24) return false;
    std::vector<uint8_t> encoded(bound + 32, 0xa5);
    auto target = buffer(encoded.data(), bound, 0);
    if (tscb_compress(handle, &source, &target) || target.used_bytes > bound) return false;
    for (size_t i = static_cast<size_t>(bound); i < encoded.size(); ++i)
        if (encoded[i] != 0xa5) return false;
    auto empty = buffer(encoded.data(), 0, 0);
    if (tscb_finalize(handle, &empty) || !tscb_finalize(handle, &empty)) return false;

    std::vector<uint8_t> decoded(values.size() * sizeof(T) + 32, 0x5a);
    auto compressed = buffer(encoded.data(), target.used_bytes, target.used_bytes);
    auto destination = buffer(decoded.data(), values.size() * sizeof(T), 0);
    if (tscb_decompress(handle, &compressed, &destination) ||
        destination.used_bytes != values.size() * sizeof(T) ||
        (!values.empty() &&
         std::memcmp(decoded.data(), values.data(), values.size() * sizeof(T)))) return false;
    for (size_t i = values.size() * sizeof(T); i < decoded.size(); ++i)
        if (decoded[i] != 0x5a) return false;
    if (target.used_bytes > 24) {
        compressed.used_bytes--;
        if (!tscb_decompress(handle, &compressed, &destination)) return false;
    }
    if (tscb_reset(handle, 0) || tscb_destroy(handle)) return false;
    return true;
}

int main() {
    for (uint64_t rows : {0ULL, 1ULL, 2ULL, 1023ULL, 1024ULL, 1025ULL,
                          102399ULL, 102400ULL, 102401ULL}) {
        if (!check_case<float>(rows) || !check_case<double>(rows)) {
            std::fprintf(stderr, "ALP ABI qualification failed at rows=%llu\n",
                         static_cast<unsigned long long>(rows));
            return 1;
        }
    }
    std::puts("ALP ABI qualification PASS");
    return 0;
}
