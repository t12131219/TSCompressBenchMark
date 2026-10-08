// Direct original APIs: independent selector wire plus isolated guard-page probes.
// This is a qualification executable, not a replacement encoder or decoder.
#include <iostream>
#include <vector>
#include <array>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <unistd.h>
#include "simple9.h"
#include "simple16.h"

using FastPForLib::IntegerCODEC;

static void need(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

static std::vector<std::vector<unsigned>> selectors(bool sixteen) {
    if (!sixteen) return {
        std::vector<unsigned>(28, 1), std::vector<unsigned>(14, 2),
        std::vector<unsigned>(9, 3), std::vector<unsigned>(7, 4),
        std::vector<unsigned>(5, 5), std::vector<unsigned>(4, 7),
        std::vector<unsigned>(3, 9), std::vector<unsigned>(2, 14), {28}
    };
    return {
        std::vector<unsigned>(28, 1),
        {2,2,2,2,2,2,2,1,1,1,1,1,1,1,1,1,1,1,1,1,1},
        {1,1,1,1,1,1,1,2,2,2,2,2,2,2,1,1,1,1,1,1,1},
        {1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2},
        std::vector<unsigned>(14, 2), {4,3,3,3,3,3,3,3,3},
        {3,4,4,4,4,3,3,3}, std::vector<unsigned>(7, 4),
        {5,5,5,5,4,4}, {4,4,5,5,5,5}, {6,6,6,5,5},
        {5,5,6,6,6}, std::vector<unsigned>(4, 7),
        {10,9,9}, {14,14}, {28}
    };
}

// Greedy first-fit layout derived from the published selector widths, independently
// of source tryme/unpack routines. Values occupy the high end of the 28-bit payload.
static std::vector<uint32_t> oracle(const std::vector<uint32_t>& input,
                                    bool sixteen, bool marked, bool hacked) {
    auto table = selectors(sixteen);
    std::vector<uint32_t> words;
    if (marked) words.push_back(static_cast<uint32_t>(input.size()));
    size_t at = 0;
    while (at < input.size()) {
        const size_t zero_count = std::min<size_t>(28, input.size() - at);
        if (hacked && std::all_of(input.begin() + at, input.begin() + at + zero_count,
                                 [](uint32_t value) { return value == 0; })) {
            words.push_back(uint32_t(9) << 28);
            at += zero_count;
            continue;
        }
        bool found = false;
        for (size_t selector = 0; selector < table.size(); ++selector) {
            const auto& widths = table[selector];
            const size_t count = std::min(widths.size(), input.size() - at);
            bool fits = true;
            for (size_t i = 0; i < count; ++i)
                fits = fits && input[at + i] < (uint32_t(1) << widths[i]);
            if (!fits) continue;
            uint32_t word = static_cast<uint32_t>(selector) << 28;
            unsigned remaining = 28;
            for (size_t i = 0; i < count; ++i) {
                remaining -= widths[i];
                word |= input[at + i] << remaining;
            }
            words.push_back(word);
            at += count;
            found = true;
            break;
        }
        need(found, "oracle value exceeds 28-bit source domain");
    }
    return words;
}

static void normal(IntegerCODEC& codec, bool sixteen, bool marked, bool hacked) {
    const size_t lengths[] = {0,1,2,3,4,5,7,8,9,14,15,16,17,27,28,29,55,56,57,
                              127,128,129,255,256,257};
    uint64_t cases = 0;
    std::array<uint64_t, 16> observed{};
    for (unsigned bits = 0; bits <= 28; ++bits) {
        const uint32_t mask = (uint32_t(1) << bits) - 1;
        for (const size_t length : lengths) for (unsigned pattern = 0; pattern < 7; ++pattern) {
            std::vector<uint32_t> logical(length);
            uint32_t random = 0x6d2b79f5;
            for (size_t i = 0; i < length; ++i) {
                random = random * 1664525U + 1013904223U;
                logical[i] = pattern == 0 ? 0 : pattern == 1 ? mask :
                             pattern == 2 ? static_cast<uint32_t>(i) & mask :
                             pattern == 3 ? (i % 2 ? mask : 0) :
                             pattern == 4 ? random & mask :
                             pattern == 5 ? (i % 21 >= 7 && i % 21 < 14 ? 3U : 1U) & mask :
                                            (i % 21 >= 14 ? 3U : 1U) & mask;
            }
            // The original hacked tail requires readable zero padding. This does
            // not qualify exact logical inputs; a separate process proves that risk.
            std::vector<uint32_t> input = logical;
            input.resize(length + 28, 0);
            const auto input_before = input;
            std::vector<uint32_t> encoded(length + 2, 0xd8e9fa0bU);
            size_t used = length + 1;
            codec.encodeArray(input.data(), length, encoded.data(), used);
            const auto expected = oracle(logical, sixteen, marked, hacked);
            need(used == expected.size(), "original encoded length differs from scalar oracle");
            need(std::equal(expected.begin(), expected.end(), encoded.begin()),
                 "original encoded words differ from scalar oracle");
            need(encoded[length + 1] == 0xd8e9fa0bU, "encoder exceeded worst-case words");
            need(input == input_before, "encoder modified input");
            if (sixteen) {
                size_t fake = 0;
                if (marked)
                    dynamic_cast<FastPForLib::Simple16<true>&>(codec).fakeencodeArray(
                        input.data(), length, fake);
                else
                    dynamic_cast<FastPForLib::Simple16<false>&>(codec).fakeencodeArray(
                        input.data(), length, fake);
                need(fake + (marked ? 1 : 0) == used,
                     "original Simple16 fake payload count differs");
            }
            encoded.resize(used);
            // Keep a non-null pointer for the zero-length unmarked input.
            if (encoded.empty()) encoded.reserve(1);
            const auto compressed_before = encoded;
            for (const size_t declared : {used, size_t(0)}) {
                std::vector<uint32_t> decoded(length + 29, 0xd8e9fa0bU);
                size_t actual = length + 28;
                if (!marked) actual = length;
                const auto* end = codec.decodeArray(encoded.data(), declared,
                                                    decoded.data(), actual);
                need(actual == length && end == encoded.data() + used,
                     "original decoder count/consumption differs");
                need(std::equal(logical.begin(), logical.end(), decoded.begin()),
                     "original reconstructed values differ");
                need(decoded[length + 28] == 0xd8e9fa0bU,
                     "original decoder exceeded declared headroom");
                need(encoded == compressed_before, "decoder modified input");
            }
            for (size_t i = marked ? 1 : 0; i < used; ++i) ++observed[encoded[i] >> 28];
            ++cases;
        }
    }
    const unsigned legal_selectors = sixteen ? 16 : (hacked ? 10 : 9);
    for (unsigned i = 0; i < legal_selectors; ++i)
        need(observed[i] > 0, "source wire matrix omitted a legal selector");
    std::cout << "{\"status\":\"PASS\",\"cases\":" << cases
              << ",\"input_padding_words\":28,\"decode_headroom_words\":28,"
              << "\"selector_counts\":[";
    for (size_t i = 0; i < observed.size(); ++i) std::cout << (i ? "," : "") << observed[i];
    std::cout << "]}" << std::endl;
}

struct Protected {
    size_t page;
    void* base;
    uint32_t* data;
    explicit Protected(size_t words) : page(static_cast<size_t>(sysconf(_SC_PAGESIZE))),
        base(mmap(nullptr, 3 * page, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)) {
        need(base != MAP_FAILED && words * 4 <= page, "guard allocation failed");
        need(mprotect(static_cast<char*>(base) + page, page, PROT_READ | PROT_WRITE) == 0,
             "guard mprotect failed");
        data = reinterpret_cast<uint32_t*>(static_cast<char*>(base) + 2 * page - words * 4);
    }
    void read_only() {
        need(mprotect(static_cast<char*>(base) + page, page, PROT_READ) == 0,
             "read-only mprotect failed");
    }
    ~Protected() { munmap(base, 3 * page); }
};

static void probe(IntegerCODEC& codec, bool sixteen, bool marked, bool hacked,
                  const std::string& mode) {
    if (mode == "decode-tail") {
        auto words = oracle({1}, sixteen, marked, hacked);
        Protected input(words.size()), output(1);
        std::copy(words.begin(), words.end(), input.data);
        input.read_only();
        size_t count = 1;
        codec.decodeArray(input.data, words.size(), output.data, count);
    } else if (mode == "decode-truncated") {
        Protected input(1);
        input.data[0] = marked ? 29 : 0;
        input.read_only();
        std::vector<uint32_t> output(60, 0);
        size_t count = 29;
        codec.decodeArray(input.data, 1, output.data(), count);
    } else if (mode == "encode-short") {
        std::vector<uint32_t> input(29, (uint32_t(1) << 28) - 1);
        Protected output(1);
        size_t capacity = 1;
        codec.encodeArray(input.data(), 29, output.data, capacity);
    } else if (mode == "hacked-tail-read") {
        need(hacked, "probe requires hacked Simple9");
        Protected input(1);
        input.data[0] = 0;
        input.read_only();
        std::vector<uint32_t> output(64, 0);
        size_t capacity = output.size();
        codec.encodeArray(input.data, 1, output.data(), capacity);
    } else if (mode == "invalid-selector") {
        need(!sixteen, "Simple16 has no invalid four-bit selectors");
        const uint32_t stream[] = {1, uint32_t(15) << 28};
        std::vector<uint32_t> output(29, 0);
        size_t capacity = 1;
        codec.decodeArray(stream + (marked ? 0 : 1), marked ? 2 : 1,
                          output.data(), capacity);
    } else if (mode == "range-rejection") {
        const uint32_t input = uint32_t(1) << 28;
        std::vector<uint32_t> output(64, 0xa5a5a5a5U);
        size_t capacity = output.size();
        try { codec.encodeArray(&input, 1, output.data(), capacity); }
        catch (const std::runtime_error&) {
            need(input == (uint32_t(1) << 28), "range failure modified input");
            need(output[0] == (marked ? 1U : 0xa5a5a5a5U),
                 "unexpected partial-output behavior on range failure");
            std::cout << "{\"status\":\"RANGE_REJECTED\",\"output_unchanged\":"
                      << (marked ? "false" : "true") << "}" << std::endl;
            return;
        }
        throw std::runtime_error("source silently accepted 29-bit value");
    } else throw std::runtime_error("unknown probe");
    throw std::runtime_error("guard probe unexpectedly survived");
}

int main(int argc, char** argv) {
    try {
        need(argc == 4, "expected codec marked mode");
        const std::string name = argv[1], mode = argv[3];
        const bool marked = std::string(argv[2]) == "1";
        need(marked || std::string(argv[2]) == "0", "invalid marked flag");
        const bool sixteen = name == "simple16", hacked = name == "simple9hacked";
        std::unique_ptr<IntegerCODEC> codec;
        if (sixteen) {
            if (marked) codec.reset(new FastPForLib::Simple16<true>());
            else codec.reset(new FastPForLib::Simple16<false>());
        } else if (hacked) {
            if (marked) codec.reset(new FastPForLib::Simple9<true, true>());
            else codec.reset(new FastPForLib::Simple9<false, true>());
        } else {
            need(name == "simple9", "unknown codec");
            if (marked) codec.reset(new FastPForLib::Simple9<true>());
            else codec.reset(new FastPForLib::Simple9<false>());
        }
        if (mode == "normal") normal(*codec, sixteen, marked, hacked);
        else probe(*codec, sixteen, marked, hacked, mode);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << std::endl;
        return 2;
    }
}
