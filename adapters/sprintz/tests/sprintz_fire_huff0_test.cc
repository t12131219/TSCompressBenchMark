#include "tscb_adapter_v1.h"

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
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

static tscb_buffer_v1 buffer(void* data, size_t capacity, size_t used) {
    tscb_buffer_v1 value{};
    value.data = data;
    value.capacity_bytes = capacity;
    value.used_bytes = used;
    value.dtype = TSCB_DTYPE_BYTES_V1;
    value.rank = 1;
    value.shape[0] = used;
    value.alignment_bytes = 1;
    value.ownership = TSCB_OWNERSHIP_CALLER_V1;
    return value;
}

static bool canary(const std::vector<uint8_t>& bytes, size_t prefix, size_t used) {
    for (size_t i = 0; i < prefix; ++i) if (bytes[i] != 0xa5) return false;
    for (size_t i = prefix + used; i < bytes.size(); ++i)
        if (bytes[i] != 0xa5) return false;
    return true;
}

int main() {
    constexpr char config[] = "{\"algorithm\":\"sprintz-fire-huff0\"}";
    constexpr size_t guard = 16;
    bool saw_huff0 = false;
    bool saw_raw = false;
    uint32_t state = 0x53464830;
    for (uint8_t width : {uint8_t{1}, uint8_t{2}}) {
        for (uint16_t dimensions : {uint16_t{1}, uint16_t{4}, uint16_t{128}}) {
            for (size_t rows : {size_t{0}, size_t{1}, size_t{7}, size_t{8},
                                size_t{127}, size_t{128}, size_t{129}, size_t{4096}}) {
                const size_t raw_bytes = rows * dimensions * width;
                if (raw_bytes > 120 * 1024) continue;
                for (unsigned pattern = 0; pattern < 2; ++pattern) {
                    std::vector<uint8_t> input(16 + raw_bytes);
                    std::memcpy(input.data(), "TSI1", 4);
                    input[4] = width;
                    input[5] = 0;
                    write16(input.data() + 6, dimensions);
                    write64(input.data() + 8, rows * dimensions);
                    for (size_t i = 0; i < raw_bytes; ++i) {
                        state = state * 1664525u + 1013904223u;
                        input[16 + i] = pattern ? static_cast<uint8_t>(state >> 24)
                                                : static_cast<uint8_t>((i / width) & 7);
                    }
                    const auto original = input;
                    size_t sprintz_bound = 0;
                    if (tscb_sprintz_bound(input.data(), input.size(), &sprintz_bound)) return 11;
                    std::vector<uint8_t> sprintz(sprintz_bound);
                    size_t sprintz_used = 0;
                    const int direct_compress_status = tscb_sprintz_compress(
                        1, input.data(), input.size(), sprintz.data(), sprintz.size(),
                        &sprintz_used);
                    if (direct_compress_status) {
                        std::fprintf(stderr,
                                     "direct Sprintz compress failed: width=%u dims=%u "
                                     "rows=%zu pattern=%u status=%d\n",
                                     static_cast<unsigned>(width),
                                     static_cast<unsigned>(dimensions), rows, pattern,
                                     direct_compress_status);
                        return 12;
                    }
                    std::vector<uint8_t> sprintz_decoded(raw_bytes ? raw_bytes : 1);
                    size_t sprintz_decoded_size = 0;
                    if (tscb_sprintz_decompress(
                            1, sprintz.data(), sprintz_used, sprintz_decoded.data(), raw_bytes,
                            &sprintz_decoded_size) || sprintz_decoded_size != raw_bytes ||
                        std::memcmp(sprintz_decoded.data(), input.data() + 16, raw_bytes)) {
                        std::fprintf(stderr,
                                     "direct Sprintz roundtrip failed: width=%u dims=%u "
                                     "rows=%zu pattern=%u\n",
                                     static_cast<unsigned>(width),
                                     static_cast<unsigned>(dimensions), rows, pattern);
                        return 13;
                    }
                    tscb_codec_handle_v1* handle = nullptr;
                    if (tscb_create(config, sizeof(config) - 1, &handle) || !handle) return 1;
                    auto source = buffer(input.data(), input.size(), input.size());
                    uint64_t bound = 0;
                    if (tscb_compress_bound(handle, &source, &bound) || bound < 24) return 2;
                    std::vector<uint8_t> encoded(static_cast<size_t>(bound) + 2 * guard, 0xa5);
                    auto target = buffer(encoded.data() + guard, static_cast<size_t>(bound), 0);
                    const auto compress_status = tscb_compress(handle, &source, &target);
                    if (compress_status || target.used_bytes > target.capacity_bytes ||
                        input != original ||
                        !canary(encoded, guard, static_cast<size_t>(target.used_bytes))) {
                        std::fprintf(
                            stderr,
                            "compress contract failed: width=%u dims=%u rows=%zu pattern=%u "
                            "status=%u used=%llu capacity=%llu input_changed=%d canary=%d\n",
                            static_cast<unsigned>(width), static_cast<unsigned>(dimensions),
                            rows, pattern, static_cast<unsigned>(compress_status),
                            static_cast<unsigned long long>(target.used_bytes),
                            static_cast<unsigned long long>(target.capacity_bytes),
                            input != original,
                            canary(encoded, guard, static_cast<size_t>(target.used_bytes)));
                        return 3;
                    }
                    const auto* frame = encoded.data() + guard;
                    saw_huff0 = saw_huff0 || frame[5] == 1 || frame[5] == 2;
                    saw_raw = saw_raw || frame[5] == 0;
                    uint8_t finalize_byte = 0;
                    auto finalize = buffer(&finalize_byte, 0, 0);
                    if (tscb_finalize(handle, &finalize) || finalize.used_bytes) return 4;
                    std::vector<uint8_t> decoded(raw_bytes + 2 * guard, 0xa5);
                    auto compressed = buffer(
                        encoded.data() + guard, static_cast<size_t>(target.used_bytes),
                        static_cast<size_t>(target.used_bytes));
                    auto recovered = buffer(decoded.data() + guard, raw_bytes, 0);
                    const auto decompress_status =
                        tscb_decompress(handle, &compressed, &recovered);
                    if (decompress_status || recovered.used_bytes != raw_bytes ||
                        std::memcmp(decoded.data() + guard, input.data() + 16, raw_bytes) ||
                        !canary(decoded, guard, raw_bytes)) {
                        size_t mismatch = raw_bytes;
                        for (size_t i = 0; i < raw_bytes; ++i) {
                            if (decoded[guard + i] != input[16 + i]) {
                                mismatch = i;
                                break;
                            }
                        }
                        std::fprintf(
                            stderr,
                            "decompress contract failed: width=%u dims=%u rows=%zu "
                            "pattern=%u mode=%u status=%u used=%llu expected=%zu "
                            "mismatch=%zu canary=%d\n",
                            static_cast<unsigned>(width), static_cast<unsigned>(dimensions),
                            rows, pattern, static_cast<unsigned>(frame[5]),
                            static_cast<unsigned>(decompress_status),
                            static_cast<unsigned long long>(recovered.used_bytes), raw_bytes,
                            mismatch, canary(decoded, guard, raw_bytes));
                        return 5;
                    }
                    if (target.used_bytes > 24) {
                        auto truncated = compressed;
                        --truncated.used_bytes;
                        if (!tscb_decompress(handle, &truncated, &recovered)) return 6;
                        std::vector<uint8_t> surplus(
                            frame, frame + static_cast<size_t>(target.used_bytes));
                        surplus.push_back(0);
                        auto extra = buffer(surplus.data(), surplus.size(), surplus.size());
                        if (!tscb_decompress(handle, &extra, &recovered)) return 7;
                    }
                    std::vector<uint8_t> invalid(
                        frame, frame + static_cast<size_t>(target.used_bytes));
                    invalid[5] = 3;
                    auto malformed = buffer(invalid.data(), invalid.size(), invalid.size());
                    if (!tscb_decompress(handle, &malformed, &recovered)) return 8;
                    if (tscb_destroy(handle)) return 9;
                }
            }
        }
    }
    if (!saw_huff0 || !saw_raw) {
        std::fprintf(stderr, "missing mode coverage: huff0=%d raw=%d\n", saw_huff0, saw_raw);
        return 10;
    }
    std::puts("SprintzFIRE+Huf native qualification passed");
    return 0;
}
