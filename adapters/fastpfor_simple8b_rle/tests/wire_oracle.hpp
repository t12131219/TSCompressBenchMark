// Independent wire helpers only: no codec class, implementation, RTTI or vtable definitions.
#ifndef TSCB_SIMPLE8B_RLE_WIRE_ORACLE_HPP
#define TSCB_SIMPLE8B_RLE_WIRE_ORACLE_HPP
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>
namespace {
constexpr unsigned widths[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 30, 60};
constexpr unsigned capacities[] = {0, 60, 30, 20, 15, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1};
unsigned seen[16] = {};

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

} // namespace
#endif
