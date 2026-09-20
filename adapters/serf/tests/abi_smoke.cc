#include "tscb_adapter_v1.h"

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <type_traits>
#include <vector>

namespace {

template <typename T> void append_integer(std::vector<uint8_t>& bytes, T value) {
    using U = std::make_unsigned_t<T>;
    U bits{};
    std::memcpy(&bits, &value, sizeof(bits));
    for (size_t i = 0; i < sizeof(bits); ++i)
        bytes.push_back(static_cast<uint8_t>(bits >> (i * 8)));
}

void append_raw(std::vector<uint8_t>& bytes, const void* data, size_t size) {
    const auto* first = static_cast<const uint8_t*>(data);
    bytes.insert(bytes.end(), first, first + size);
}

tscb_buffer_v1 buffer(void* data, uint64_t capacity, uint64_t used) {
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

template <typename T> bool roundtrip(size_t count, bool special) {
    std::vector<T> values(count);
    for (size_t i = 0; i < count; ++i)
        values[i] = static_cast<T>(std::sin(static_cast<double>(i) / 7.0) * 10.0);
    if (special && count >= 5) {
        values[0] = T{0};
        values[1] = -T{0};
        values[2] = std::numeric_limits<T>::infinity();
        values[3] = -std::numeric_limits<T>::infinity();
        values[4] = std::numeric_limits<T>::quiet_NaN();
    }
    std::vector<uint8_t> input;
    append_raw(input, "SRI1", 4);
    append_integer<uint8_t>(input, sizeof(T));
    append_integer<uint8_t>(input, 0);
    append_integer<uint16_t>(input, 1);
    append_integer<uint32_t>(input, 1000);
    append_integer<uint64_t>(input, count);
    const double error = 0.001;
    append_raw(input, &error, sizeof(error));
    append_integer<int64_t>(input, 0);
    append_raw(input, values.data(), values.size() * sizeof(T));

#if SMOKE_XOR
    constexpr char config[] = "{\"algorithm\":\"serf-xor\"}";
#else
    constexpr char config[] = "{\"algorithm\":\"serf-qt\"}";
#endif
    tscb_codec_handle_v1* handle{};
    if (tscb_create(config, sizeof(config) - 1, &handle) != TSCB_STATUS_OK_V1 || !handle)
        return false;
    auto source = buffer(input.data(), input.size(), input.size());
    uint64_t bound{};
    if (tscb_compress_bound(handle, &source, &bound) != TSCB_STATUS_OK_V1 || bound < 56)
        return false;
    std::vector<uint8_t> encoded(bound + 16, 0xA5);
    auto target = buffer(encoded.data(), bound, 0);
    if (tscb_compress(handle, &source, &target) != TSCB_STATUS_OK_V1 || target.used_bytes > bound)
        return false;
    for (size_t i = bound; i < encoded.size(); ++i)
        if (encoded[i] != 0xA5) return false;
    auto empty = buffer(nullptr, 0, 0);
    if (tscb_finalize(handle, &empty) != TSCB_STATUS_OK_V1 || empty.used_bytes != 0 ||
        tscb_finalize(handle, &empty) == TSCB_STATUS_OK_V1)
        return false;
    if (tscb_destroy(handle) != TSCB_STATUS_OK_V1) return false;

    if (tscb_create(config, sizeof(config) - 1, &handle) != TSCB_STATUS_OK_V1) return false;
    auto too_small = buffer(encoded.data(), target.used_bytes - 1, 0);
    if (tscb_compress(handle, &source, &too_small) != TSCB_STATUS_DST_TOO_SMALL_V1)
        return false;
    if (tscb_destroy(handle) != TSCB_STATUS_OK_V1) return false;

    if (tscb_create(config, sizeof(config) - 1, &handle) != TSCB_STATUS_OK_V1) return false;
    std::vector<T> decoded(count);
    auto compressed = buffer(encoded.data(), target.used_bytes, target.used_bytes);
    auto restored = buffer(decoded.data(), decoded.size() * sizeof(T), 0);
    if (tscb_decompress(handle, &compressed, &restored) != TSCB_STATUS_OK_V1 ||
        restored.used_bytes != decoded.size() * sizeof(T)) return false;
    for (size_t i = 0; i < count; ++i) {
        if (std::isnan(values[i])) {
            if (!std::isnan(decoded[i])) return false;
        } else if (std::isinf(values[i])) {
            if (values[i] != decoded[i]) return false;
        } else if (std::abs(static_cast<long double>(values[i]) - decoded[i]) > 0.001L) {
            return false;
        }
    }
    if (target.used_bytes > 16) {
        encoded[8] ^= 1;
        compressed = buffer(encoded.data(), target.used_bytes, target.used_bytes);
        if (tscb_decompress(handle, &compressed, &restored) == TSCB_STATUS_OK_V1) return false;
    }
    return tscb_destroy(handle) == TSCB_STATUS_OK_V1;
}

}  // namespace

int main() {
    if (tscb_get_abi_version() != TSCB_ADAPTER_ABI_V1) return 1;
    for (const size_t count : {size_t{0}, size_t{1}, size_t{2}, size_t{999},
                               size_t{1000}, size_t{1001}, size_t{2001}}) {
        if (!roundtrip<float>(count, false) || !roundtrip<double>(count, false)) return 2;
    }
    if (!roundtrip<float>(9, true) || !roundtrip<double>(9, true)) return 3;
    std::puts("serf ABI smoke PASS");
    return 0;
}
