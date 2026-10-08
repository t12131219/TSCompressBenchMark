// Independent uint32 RLE wire oracle and exact-buffer tests of the source APIs.
#include "simple8b_rle.h"
#include <sys/mman.h>
#include <unistd.h>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>

namespace {
constexpr unsigned widths[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 30, 60};
constexpr unsigned capacities[] = {0, 60, 30, 20, 15, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1};
unsigned seen[16] = {};
uint64_t cases = 0, guards = 0;

void check(bool valid, const char *message) {
    if (!valid) throw std::runtime_error(message);
}

unsigned bit_length(uint32_t value) {
    unsigned result = 0;
    while (value) { ++result; value >>= 1; }
    return result;
}

std::vector<uint64_t> oracle(const std::vector<uint32_t>& data) {
    std::vector<uint64_t> words;
    size_t pos = 0;
    while (pos < data.size()) {
        size_t run = 1;
        while (pos + run < data.size() && data[pos + run] == data[pos]) ++run;
        if (uint64_t(bit_length(data[pos] | 1U)) * run >= 60) {
            run = std::min<size_t>(run, 0x0fffffffU);
            words.push_back((uint64_t(15) << 60) | (uint64_t(run) << 32) | data[pos]);
            ++seen[15];
            pos += run;
            continue;
        }
        bool found = false;
        for (unsigned selector = 1; selector <= 14; ++selector) {
            const size_t n = std::min<size_t>(capacities[selector], data.size() - pos);
            bool fits = true;
            for (size_t i = 0; i < n; ++i)
                if (bit_length(data[pos + i]) > widths[selector]) fits = false;
            if (!fits) continue;
            uint64_t word = uint64_t(selector) << 60;
            // Place individual value bits rather than using the source's word shifts.
            for (size_t i = 0; i < n; ++i)
                for (unsigned b = 0; b < 32 && b < widths[selector]; ++b)
                    if (data[pos + i] & (uint32_t(1) << b))
                        word |= uint64_t(1) << (i * widths[selector] + b);
            words.push_back(word);
            ++seen[selector];
            pos += n;
            found = true;
            break;
        }
        check(found, "oracle did not represent uint32 value");
    }
    return words;
}

std::vector<uint32_t> pattern(size_t n, unsigned width, unsigned kind) {
    const uint32_t mask = width == 32 ? UINT32_MAX : uint32_t((uint64_t(1) << width) - 1);
    std::vector<uint32_t> input(n);
    uint32_t random = 0x9e3779b9U ^ uint32_t(n) ^ (width << 16) ^ kind;
    for (size_t i = 0; i < n; ++i) {
        random ^= random << 13; random ^= random >> 17; random ^= random << 5;
        switch (kind) {
        case 0: input[i] = 0; break;
        case 1: input[i] = mask; break;
        case 2: input[i] = width ? uint32_t(1) << (width - 1) : 0; break;
        case 3: input[i] = uint32_t(i) & mask; break;
        case 4: input[i] = random & mask; break;
        default: input[i] = i % 2 ? mask : 0; break;
        }
    }
    return input;
}

template<bool Marked>
void roundtrip(const std::vector<uint32_t>& input, const std::vector<uint64_t>& expected,
               unsigned offset, bool wire_only) {
    FastPForLib::Simple8b_RLE<Marked> codec;
    const size_t words = expected.size() * 2 + (Marked ? 1 : 0);
    const auto immutable = input;
    std::vector<uint32_t> encoded(words + offset + 16, 0xa5a5a5a5U);
    uint32_t *start = encoded.data() + offset;
    size_t used = words;
    codec.encodeArray(input.data(), input.size(), start, used);
#ifdef TSCB_ORIGINAL_RLE
    used += Marked ? 1 : 0; // Original API omits the marker; compare its complete wire.
#endif
    check(used == words, "encode returned incomplete length");
    if (Marked) check(start[0] == input.size(), "marked count differs");
    for (size_t i = 0; i < expected.size(); ++i) {
        uint64_t actual;
        std::memcpy(&actual, start + (Marked ? 1 : 0) + i * 2, sizeof(actual));
        check(actual == expected[i], "source wire differs from independent oracle");
    }
    for (size_t i = 0; i < offset; ++i)
        check(encoded[i] == 0xa5a5a5a5U, "encode prefix overwritten");
    for (size_t i = offset + words; i < encoded.size(); ++i)
        check(encoded[i] == 0xa5a5a5a5U, "encode tail overwritten");
    check(input == immutable, "source modified input");
    if (!wire_only) {
        const auto packed_immutable = encoded;
        std::vector<uint32_t> decoded(input.size() + 16, 0xa5a5a5a5U);
        size_t count = input.size();
        const auto *end = codec.decodeArray(start, words, decoded.data(), count);
        check(count == input.size() && end == start + words, "decode count/consumption differs");
        check(std::equal(input.begin(), input.end(), decoded.begin()), "inverse differs");
        for (size_t i = input.size(); i < decoded.size(); ++i)
            check(decoded[i] == 0xa5a5a5a5U, "decode tail overwritten");
        check(encoded == packed_immutable, "source modified packed input");
    }
    ++cases;
}

class GuardBuffer {
    void *mapping_;
    size_t page_, pages_;
public:
    unsigned char *data;
    explicit GuardBuffer(size_t bytes) {
        page_ = size_t(sysconf(_SC_PAGESIZE));
        pages_ = std::max<size_t>(1, (bytes + page_ - 1) / page_);
        mapping_ = mmap(nullptr, (pages_ + 2) * page_, PROT_NONE,
                        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        check(mapping_ != MAP_FAILED, "guard mmap failed");
        check(mprotect(static_cast<char *>(mapping_) + page_, pages_ * page_,
                       PROT_READ | PROT_WRITE) == 0, "guard mprotect failed");
        data = static_cast<unsigned char *>(mapping_) + (pages_ + 1) * page_ - bytes;
    }
    void readonly() {
        check(mprotect(static_cast<char *>(mapping_) + page_, pages_ * page_, PROT_READ) == 0,
              "guard readonly failed");
    }
    ~GuardBuffer() { munmap(mapping_, (pages_ + 2) * page_); }
};

template<bool Marked>
void exact_guard(const std::vector<uint32_t>& input) {
    const auto expected = oracle(input);
    const size_t words = expected.size() * 2 + (Marked ? 1 : 0);
    GuardBuffer original(input.size() * 4), encoded(words * 4), decoded(input.size() * 4);
    if (!input.empty()) std::memcpy(original.data, input.data(), input.size() * 4);
    original.readonly();
    FastPForLib::Simple8b_RLE<Marked> codec;
    size_t used = words;
    codec.encodeArray(reinterpret_cast<const uint32_t *>(original.data), input.size(),
                      reinterpret_cast<uint32_t *>(encoded.data), used);
    check(used == words, "guard encoded count differs");
    if (Marked) {
        uint32_t count;
        std::memcpy(&count, encoded.data, 4);
        check(count == input.size(), "guard marker differs");
    }
    for (size_t i = 0; i < expected.size(); ++i) {
        uint64_t word;
        std::memcpy(&word, encoded.data + (Marked ? 4 : 0) + i * 8, 8);
        check(word == expected[i], "guard wire differs");
    }
    encoded.readonly();
    size_t count = input.size();
    const auto *end = codec.decodeArray(reinterpret_cast<const uint32_t *>(encoded.data), words,
                                       reinterpret_cast<uint32_t *>(decoded.data), count);
    check(count == input.size() && reinterpret_cast<const unsigned char *>(end) ==
          encoded.data + words * 4, "guard decoded count/consumption differs");
    if (!input.empty()) {
        check(std::memcmp(decoded.data, input.data(), input.size() * 4) == 0, "guard inverse differs");
        check(std::memcmp(original.data, input.data(), input.size() * 4) == 0,
              "guard input was modified");
    }
    ++guards;
}
} // namespace

int main(int argc, char **argv) {
    try {
        const bool wire_only = argc == 2 && std::strcmp(argv[1], "wire-only") == 0;
#ifdef TSCB_ORIGINAL_RLE
        check(wire_only, "original decoder safety is not granted by this matrix");
#endif
        std::vector<size_t> lengths;
        for (size_t i = 0; i <= 64; ++i) lengths.push_back(i);
        for (size_t i : {79, 80, 81, 119, 120, 121, 127, 128, 129, 239, 240, 241,
                         255, 256, 257, 511, 512, 513, 1023, 1024, 1025, 4095, 4096, 4097})
            lengths.push_back(i);
        for (unsigned width = 0; width <= 32; ++width) {
            for (size_t n : lengths) for (unsigned kind = 0; kind < 6; ++kind) {
                const auto input = pattern(n, width, kind);
                const auto expected = oracle(input);
                for (unsigned offset = 0; offset < 2; ++offset) {
                    roundtrip<false>(input, expected, offset, wire_only);
                    roundtrip<true>(input, expected, offset, wire_only);
                }
            }
        }
        if (!wire_only) {
            for (size_t n : {0, 1, 2, 3, 7, 8, 9, 14, 15, 16, 29, 30, 31,
                             59, 60, 61, 127, 128, 129})
                for (unsigned width : {0, 1, 7, 20, 30, 31, 32})
                    for (unsigned kind = 0; kind < 6; ++kind) {
                        const auto input = pattern(n, width, kind);
                        exact_guard<false>(input);
                        exact_guard<true>(input);
                    }
        }
        for (unsigned selector = 1; selector <= 15; ++selector)
            check(seen[selector] > 0, "selector not exercised");
        std::printf("{\"status\":\"PASS\",\"cases\":%llu,\"guard_roundtrips\":%llu,"
                    "\"selectors\":15,\"wire_only\":%s}\n",
                    static_cast<unsigned long long>(cases),
                    static_cast<unsigned long long>(guards), wire_only ? "true" : "false");
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "RLE_MATRIX_FAIL: %s\n", error.what());
        return 2;
    }
}
