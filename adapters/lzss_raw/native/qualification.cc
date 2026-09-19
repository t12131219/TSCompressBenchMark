#include "tscb_adapter_v1.h"
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

static tscb_buffer_v1 view(void* data, size_t capacity, size_t used) {
    tscb_buffer_v1 value{};
    value.data = data;
    value.capacity_bytes = capacity;
    value.used_bytes = used;
    value.dtype = TSCB_DTYPE_BYTES_V1;
    value.rank = 1;
    value.strides_bytes[0] = 1;
    return value;
}

int main() {
    std::mt19937 random(20260918);
    const char config[] = "{\"ei\":10,\"ej\":4,\"initial_byte\":32}";
    for (size_t n : {0U, 1U, 2U, 1023U, 1024U, 1025U, 2047U, 2048U, 2049U,
                     65535U, 65536U, 65537U, 131073U}) {
        for (int mode = 0; mode < 3; ++mode) {
            std::vector<unsigned char> source(std::max<size_t>(1, n));
            for (size_t i = 0; i < n; ++i)
                source[i] = mode == 0 ? 0 : mode == 1 ? static_cast<unsigned char>(i) : random();
            const auto original = source;
            auto input = view(source.data(), n, n);
            tscb_codec_handle_v1* encoder = nullptr;
            assert(tscb_create(config, sizeof(config) - 1, &encoder) == 0);
            assert(tscb_set_native_timing(encoder, 1) == 0);
            uint64_t bound = 0;
            assert(tscb_compress_bound(encoder, &input, &bound) == 0);
            assert(bound == n + (n + 7) / 8);
            std::vector<unsigned char> encoded(bound + 16, 0xCA);
            auto output = view(encoded.data(), bound, 0);
            if (bound > 0) {
                output.capacity_bytes = bound - 1;
                assert(tscb_compress(encoder, &input, &output) == 3);
                output.capacity_bytes = bound;
            }
            auto alias = view(source.data(), n, 0);
            if (n > 0) assert(tscb_compress(encoder, &input, &alias) == 1);
            assert(tscb_compress(encoder, &input, &output) == 0);
            const size_t written = output.used_bytes;
            assert(written <= bound && source == original);
            assert(std::all_of(encoded.begin() + bound, encoded.end(), [](auto v) { return v == 0xCA; }));
            assert(tscb_compress(encoder, &input, &output) == 4);
            tscb_native_timing_v1 before{sizeof(before), 1, 0, 0};
            assert(tscb_get_native_timing(encoder, &before) == 0);
            assert(tscb_finalize(encoder, &output) == 0 && output.used_bytes == 0);
            tscb_native_timing_v1 after{sizeof(after), 1, 0, 0};
            assert(tscb_get_native_timing(encoder, &after) == 0);
            assert(before.native_encode_wall_ns == after.native_encode_wall_ns);
            assert(tscb_finalize(encoder, &output) == 4);
            tscb_codec_handle_v1* decoder = nullptr;
            assert(tscb_create(config, sizeof(config) - 1, &decoder) == 0);
            std::vector<unsigned char> decoded(n + 16, 0xCB);
            auto compressed = view(encoded.data(), written, written);
            auto destination = view(decoded.data(), n, 0);
            assert(tscb_decompress(decoder, &compressed, &destination) == 0);
            assert(destination.used_bytes == n && std::memcmp(source.data(), decoded.data(), n) == 0);
            assert(std::all_of(decoded.begin() + n, decoded.end(), [](auto v) { return v == 0xCB; }));
            if (n > 0) {
                destination.capacity_bytes = n - 1;
                destination.used_bytes = 0;
                assert(tscb_decompress(decoder, &compressed, &destination) == 4);
                destination.capacity_bytes = n;
            }
            if (n == 1) {
                encoded[written - 1] ^= 1;
                assert(tscb_decompress(decoder, &compressed, &destination) == 4);
                encoded[written - 1] ^= 1;
            }
            if (written) {
                compressed.used_bytes = written - 1;
                assert(tscb_decompress(decoder, &compressed, &destination) == 4);
            }
            compressed.capacity_bytes = written + 1;
            compressed.used_bytes = written + 1;
            encoded[written] = 0;
            assert(tscb_decompress(decoder, &compressed, &destination) == 4);
            assert(tscb_reset(encoder, 0) == 0);
            assert(tscb_get_native_timing(encoder, &after) == 0 && after.native_encode_wall_ns == 0);
            assert(tscb_finalize(encoder, &output) == 5);
            assert(tscb_destroy(encoder) == 0 && tscb_destroy(decoder) == 0);
        }
    }
    std::puts("PASS: 39 native cases; exact decode, capacity, canary, immutable input, overlap, tails, lifecycle, timing");
}
