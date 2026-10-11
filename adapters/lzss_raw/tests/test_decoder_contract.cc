#include "tscb_adapter_v1.h"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <vector>

// Independent ABI tests construct the published MSB-first token grammar directly.
// They intentionally do not call the encoder to prepare decoder inputs.
#define CHECK(expression) do { \
    if (!(expression)) { \
        std::fprintf(stderr, "FAIL at %s:%d: %s\n", __FILE__, __LINE__, #expression); \
        std::abort(); \
    } \
} while (false)

namespace {

struct Bits {
    std::vector<unsigned char> bytes;
    size_t count = 0;

    void integer(unsigned value, unsigned width) {
        for (unsigned i = width; i != 0; --i) {
            if (count % 8 == 0) bytes.push_back(0);
            bytes.back() |= static_cast<unsigned char>(((value >> (i - 1)) & 1U)
                                                     << (7 - count % 8));
            ++count;
        }
    }

    void literal(unsigned char value) { integer(0x100U | value, 9); }
    void match(unsigned offset, unsigned length) {
        CHECK(offset < 1024 && length >= 2 && length <= 17);
        integer((offset << 4) | (length - 2), 15);
    }
};

tscb_buffer_v1 view(void* data, size_t capacity, size_t used) {
    tscb_buffer_v1 result{};
    result.data = data;
    result.capacity_bytes = capacity;
    result.used_bytes = used;
    result.dtype = TSCB_DTYPE_BYTES_V1;
    result.rank = 1;
    result.strides_bytes[0] = 1;
    return result;
}

struct Decoder {
    tscb_codec_handle_v1* handle = nullptr;
    size_t accepted = 0;
    size_t rejected = 0;

    Decoder() {
        const char config[] = "{\"ei\":10,\"ej\":4,\"initial_byte\":32}";
        CHECK(tscb_create(config, sizeof(config) - 1, &handle) == TSCB_STATUS_OK_V1);
        CHECK(handle != nullptr);
    }
    ~Decoder() { CHECK(tscb_destroy(handle) == TSCB_STATUS_OK_V1); }

    void accepts(std::vector<unsigned char> stream, const std::vector<unsigned char>& expected) {
        const auto original_stream = stream;
        // Keep both ends guarded and allow a nonzero used_bytes value on entry.
        std::vector<unsigned char> output(expected.size() + 32, 0xD3);
        auto input = view(stream.data(), stream.size(), stream.size());
        auto destination = view(output.data() + 16, expected.size(), expected.empty() ? 0 : 1);
        CHECK(tscb_decompress(handle, &input, &destination) == TSCB_STATUS_OK_V1);
        CHECK(destination.used_bytes == expected.size());
        CHECK(std::equal(expected.begin(), expected.end(), output.begin() + 16));
        CHECK(std::all_of(output.begin(), output.begin() + 16, [](auto v) { return v == 0xD3; }));
        CHECK(std::all_of(output.begin() + 16 + expected.size(), output.end(), [](auto v) { return v == 0xD3; }));
        CHECK(stream == original_stream);
        ++accepted;
    }

    void rejects(std::vector<unsigned char> stream, size_t expected_size) {
        const auto original_stream = stream;
        std::vector<unsigned char> output(expected_size + 32, 0xA5);
        const auto original_output = output;
        auto input = view(stream.data(), stream.size(), stream.size());
        auto destination = view(output.data() + 16, expected_size, expected_size ? 1 : 0);
        const auto original_used = destination.used_bytes;
        CHECK(tscb_decompress(handle, &input, &destination) == TSCB_STATUS_CODEC_ERROR_V1);
        CHECK(destination.used_bytes == original_used);
        CHECK(output == original_output);
        CHECK(stream == original_stream);
        ++rejected;
    }
};

void all_offsets_and_lengths(Decoder& decoder) {
    Bits prefix;
    std::vector<unsigned char> seed;
    for (unsigned i = 0; i < 1024; ++i) {
        // Variation across the whole dictionary makes an offset/wrap error visible.
        const auto value = static_cast<unsigned char>((i * 73U + (i >> 3U) * 29U) & 255U);
        seed.push_back(value);
        prefix.literal(value);
    }
    CHECK(prefix.count % 8 == 0);
    for (unsigned offset = 0; offset < 1024; ++offset) {
        for (unsigned length = 2; length <= 17; ++length) {
            Bits stream = prefix;
            stream.match(offset, length);
            auto expected = seed;
            // After 1024 literals cursor returns to 1007. A wrapped source that
            // enters already-written positions reads this match's new bytes.
            for (unsigned k = 0; k < length; ++k) {
                const unsigned index = (offset + k + 1024U - 1007U) & 1023U;
                expected.push_back(index < k ? expected[1024U + index] : seed[index]);
            }
            decoder.accepts(stream.bytes, expected);
        }
    }
}

void initial_dictionary_and_overlap(Decoder& decoder) {
    for (unsigned offset : {0U, 1006U, 1007U, 1008U, 1023U}) {
        for (unsigned length : {2U, 3U, 16U, 17U}) {
            Bits stream;
            stream.match(offset, length);
            decoder.accepts(stream.bytes, std::vector<unsigned char>(length, 0x20));
        }
    }
    // Seed one non-space byte, then use an overlapping match through the wrap.
    for (unsigned n : {1U, 16U, 17U, 1024U, 2048U}) {
        Bits stream;
        std::vector<unsigned char> expected(n, 0x5A);
        for (unsigned i = 0; i < n; ++i) stream.literal(0x5A);
        const unsigned previous = (1007U + n - 1U) & 1023U;
        stream.match(previous, 17);
        expected.insert(expected.end(), 17, 0x5A);
        decoder.accepts(stream.bytes, expected);
    }
}

void padding_truncation_and_exact_length(Decoder& decoder) {
    decoder.accepts({}, {});
    decoder.rejects({0}, 0);  // Even a zero trailing byte is a second frame/tail.
    for (unsigned n = 1; n <= 24; ++n) {
        Bits stream;
        std::vector<unsigned char> expected;
        for (unsigned i = 0; i < n; ++i) {
            const auto value = static_cast<unsigned char>(i * 19U + n);
            stream.literal(value);
            expected.push_back(value);
        }
        decoder.accepts(stream.bytes, expected);
        decoder.rejects(stream.bytes, n - 1);
        decoder.rejects(stream.bytes, n + 1);
        auto trailing = stream.bytes;
        trailing.push_back(0);
        decoder.rejects(trailing, n);
        auto concatenated = stream.bytes;
        concatenated.insert(concatenated.end(), stream.bytes.begin(), stream.bytes.end());
        decoder.rejects(concatenated, n);
        for (size_t cut = 0; cut < stream.bytes.size(); ++cut) {
            auto truncated = stream.bytes;
            truncated.resize(cut);
            decoder.rejects(truncated, n);
        }
        for (size_t bit = stream.count; bit < stream.bytes.size() * 8; ++bit) {
            auto bad_padding = stream.bytes;
            bad_padding[bit / 8] |= static_cast<unsigned char>(1U << (7 - bit % 8));
            decoder.rejects(bad_padding, n);
        }
    }
    // A literal followed by a max-length match ends at every bit alignment.
    for (unsigned n = 0; n < 8; ++n) {
        Bits stream;
        std::vector<unsigned char> expected(n, 0x20);
        for (unsigned i = 0; i < n; ++i) stream.literal(0x20);
        stream.match(1023, 17);
        expected.insert(expected.end(), 17, 0x20);
        decoder.accepts(stream.bytes, expected);
        decoder.rejects(stream.bytes, expected.size() - 1);
        decoder.rejects(stream.bytes, expected.size() + 1);
        for (size_t bit = stream.count; bit < stream.bytes.size() * 8; ++bit) {
            auto bad_padding = stream.bytes;
            bad_padding[bit / 8] |= static_cast<unsigned char>(1U << (7 - bit % 8));
            decoder.rejects(bad_padding, expected.size());
        }
    }
}

void invalid_descriptors_reject_before_access(Decoder& decoder) {
    std::array<unsigned char, 32> source;
    std::array<unsigned char, 32> output;
    source.fill(0x69);
    output.fill(0xC7);
    const auto original_source = source;
    const auto original_output = output;
    auto check = [&](tscb_buffer_v1 input, tscb_buffer_v1 destination, tscb_status_v1 status) {
        const auto original_used = destination.used_bytes;
        CHECK(tscb_decompress(decoder.handle, &input, &destination) == status);
        CHECK(destination.used_bytes == original_used);
        CHECK(source == original_source && output == original_output);
        ++decoder.rejected;
    };
    auto input = view(source.data(), 0, 0);
    auto destination = view(output.data(), 0, 0);
    auto changed = input;
    changed.used_bytes = changed.capacity_bytes = UINT64_C(1) + UINT32_MAX;
    check(changed, destination, TSCB_STATUS_CODEC_ERROR_V1);
    changed = destination;
    changed.capacity_bytes = UINT64_C(1) + UINT32_MAX;
    check(input, changed, TSCB_STATUS_CODEC_ERROR_V1);
    changed.capacity_bytes = static_cast<uint64_t>(PTRDIFF_MAX) + 1;
    check(input, changed, TSCB_STATUS_INVALID_ARGUMENT_V1);
    changed = input;
    changed.data = reinterpret_cast<void*>(std::numeric_limits<uintptr_t>::max() - 1);
    changed.used_bytes = changed.capacity_bytes = 4;
    check(changed, destination, TSCB_STATUS_INVALID_ARGUMENT_V1);
    changed = destination;
    changed.data = reinterpret_cast<void*>(std::numeric_limits<uintptr_t>::max() - 1);
    changed.capacity_bytes = 4;
    check(input, changed, TSCB_STATUS_INVALID_ARGUMENT_V1);
    changed = input;
    changed.used_bytes = 1;
    check(changed, destination, TSCB_STATUS_INVALID_ARGUMENT_V1);
    changed = destination;
    changed.used_bytes = 1;
    check(input, changed, TSCB_STATUS_INVALID_ARGUMENT_V1);
    changed = input;
    changed.data = nullptr;
    changed.used_bytes = changed.capacity_bytes = 1;
    check(changed, destination, TSCB_STATUS_INVALID_ARGUMENT_V1);
    changed = destination;
    changed.data = nullptr;
    changed.capacity_bytes = 1;
    check(input, changed, TSCB_STATUS_INVALID_ARGUMENT_V1);
    for (bool change_input : {false, true}) {
        auto bad_input = input;
        auto bad_destination = destination;
        (change_input ? bad_input : bad_destination).rank = 2;
        check(bad_input, bad_destination, TSCB_STATUS_INVALID_ARGUMENT_V1);
        bad_input = input;
        bad_destination = destination;
        (change_input ? bad_input : bad_destination).dtype = TSCB_DTYPE_U8_V1;
        check(bad_input, bad_destination, TSCB_STATUS_INVALID_ARGUMENT_V1);
    }
    // A huge size must be rejected without touching the short underlying buffer.
    uint64_t bound = UINT64_C(0xF00D);
    input.used_bytes = input.capacity_bytes = UINT64_C(1) + UINT32_MAX;
    CHECK(tscb_compress_bound(decoder.handle, &input, &bound) == TSCB_STATUS_UNSUPPORTED_V1);
    CHECK(bound == UINT64_C(0xF00D) && source == original_source && output == original_output);
    ++decoder.rejected;
}

}  // namespace

int main() {
    Decoder decoder;
    all_offsets_and_lengths(decoder);
    initial_dictionary_and_overlap(decoder);
    padding_truncation_and_exact_length(decoder);
    invalid_descriptors_reject_before_access(decoder);
    std::printf("PASS: %zu hand-built valid streams; %zu malformed streams/descriptors rejected atomically; all offsets/lengths, initial dictionary, overlap/wrap, padding, truncation, exact lengths, overflow preflight, canaries\n",
                decoder.accepted, decoder.rejected);
}
