#include "tscb_adapter_v1.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

extern "C" tscb_status_v1 tscb_neats_query_i64(
    const uint8_t*, uint64_t, uint16_t, uint32_t, uint32_t, int64_t*, uint64_t, uint64_t*);

#if TSCB_TEST_NEATS
static const char config[] = "{\"algorithm\":\"neats-lossless-i64\",\"max_bpc\":16}";
#else
static const char config[] = "{\"algorithm\":\"leats-lossless-i64\",\"max_bpc\":16}";
#endif

static void store_u16(uint8_t* p, uint16_t value) {
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8);
}

static void store_u32(uint8_t* p, uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) p[i] = static_cast<uint8_t>(value >> (8 * i));
}

static void store_signed(uint8_t* p, uint8_t width, int64_t value) {
    uint64_t raw = static_cast<uint64_t>(value);
    for (uint8_t i = 0; i < width; ++i) p[i] = static_cast<uint8_t>(raw >> (8 * i));
}

static int64_t load_signed(const uint8_t* p, uint8_t width) {
    uint64_t raw = 0;
    for (uint8_t i = 0; i < width; ++i) raw |= static_cast<uint64_t>(p[i]) << (8 * i);
    if (width < 8 && (raw & (UINT64_C(1) << (width * 8 - 1))))
        raw |= UINT64_MAX << (width * 8);
    return static_cast<int64_t>(raw);
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
    result.ownership = TSCB_OWNERSHIP_BORROWED_V1;
    return result;
}

static int run_case(uint8_t width, uint32_t rows) {
    const uint16_t columns = 2;
    const uint64_t raw_size = static_cast<uint64_t>(rows) * columns * width;
    std::vector<uint8_t> input(12 + raw_size);
    std::memcpy(input.data(), "NTI1", 4);
    input[4] = width;
    input[5] = 0;
    store_u16(input.data() + 6, columns);
    store_u32(input.data() + 8, rows);
    for (uint16_t column = 0; column < columns; ++column) {
        for (uint32_t row = 0; row < rows; ++row) {
            int64_t value = static_cast<int64_t>((row * row + 7 * column) % 101) - 50;
            store_signed(input.data() + 12 + (static_cast<uint64_t>(column) * rows + row) * width,
                         width, value);
        }
    }
    const auto original = input;
    auto source = buffer(input.data(), input.size(), input.size());
    tscb_codec_handle_v1* handle = nullptr;
    uint64_t bound = 0;
    if (tscb_create(config, sizeof(config) - 1, &handle) != TSCB_STATUS_OK_V1 ||
        tscb_set_native_timing(handle, 1) != TSCB_STATUS_OK_V1 ||
        tscb_compress_bound(handle, &source, &bound) != TSCB_STATUS_OK_V1)
        return 1;
    std::vector<uint8_t> encoded(bound + 16, 0xa5);
    auto target = buffer(encoded.data(), bound, 0);
    if (tscb_compress(handle, &source, &target) != TSCB_STATUS_OK_V1 ||
        input != original || target.used_bytes > bound) return 2;
    for (uint64_t i = bound; i < bound + 16; ++i) if (encoded[i] != 0xa5) return 3;
    auto zero = buffer(nullptr, 0, 0);
    if (tscb_finalize(handle, &zero) != TSCB_STATUS_OK_V1 ||
        tscb_finalize(handle, &zero) == TSCB_STATUS_OK_V1) return 4;
    std::vector<uint8_t> decoded(raw_size);
    source = buffer(encoded.data(), target.used_bytes, target.used_bytes);
    auto restored = buffer(decoded.data(), decoded.size(), 0);
    if (tscb_decompress(handle, &source, &restored) != TSCB_STATUS_OK_V1 ||
        restored.used_bytes != raw_size ||
        std::memcmp(decoded.data(), input.data() + 12, raw_size) != 0) return 5;
    uint32_t start = rows > 2 ? 1 : 0;
    uint32_t length = rows > 2 ? rows - 2 : rows;
    std::vector<int64_t> queried(length);
    uint64_t touched = 0;
    if (tscb_neats_query_i64(encoded.data(), target.used_bytes, 1, start, length,
                             queried.data(), queried.size(), &touched) != TSCB_STATUS_OK_V1 ||
        touched != target.used_bytes) return 6;
    for (uint32_t i = 0; i < length; ++i) {
        auto expected = load_signed(
            input.data() + 12 + (static_cast<uint64_t>(rows) + start + i) * width, width);
        if (queried[i] != expected) return 7;
    }
    encoded[target.used_bytes - 1] ^= 1;
    if (tscb_decompress(handle, &source, &restored) == TSCB_STATUS_OK_V1) return 8;
    encoded[target.used_bytes - 1] ^= 1;
    source.used_bytes--;
    if (tscb_decompress(handle, &source, &restored) == TSCB_STATUS_OK_V1) return 9;
    tscb_codec_handle_v1* small_handle = nullptr;
    if (tscb_create(config, sizeof(config) - 1, &small_handle) != TSCB_STATUS_OK_V1) return 10;
    source = buffer(input.data(), input.size(), input.size());
    uint8_t tiny[1]{};
    target = buffer(tiny, sizeof(tiny), 0);
    if (tscb_compress(small_handle, &source, &target) != TSCB_STATUS_DST_TOO_SMALL_V1)
        return 11;
    tscb_destroy(small_handle);
    tscb_destroy(handle);
    return 0;
}

int main() {
    static const uint32_t lengths[] = {1, 2, 3, 17, 128};
    if (tscb_get_abi_version() != TSCB_ADAPTER_ABI_V1) return 1;
    for (uint8_t width : {uint8_t(1), uint8_t(2), uint8_t(4), uint8_t(8)}) {
        for (uint32_t length : lengths) {
            int status = run_case(width, length);
            if (status) {
                std::fprintf(stderr, "NeaTS/LeaTS smoke failed width=%u rows=%u stage=%d\n",
                             width, length, status);
                return 1;
            }
        }
    }
    std::puts("NeaTS/LeaTS native ABI smoke: PASS");
}
