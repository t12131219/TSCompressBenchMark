// Source-only forensic probe; this is not the benchmark adapter.
#include "compression.h"
#include "turbocompression.h"
#include <cstring>
#include <memory>
#include <sys/mman.h>
#include <unistd.h>

static void append(std::vector<uint8_t>& wire, uint64_t value, unsigned bytes) {
    for (unsigned i = 0; i < bytes; ++i) wire.push_back(uint8_t(value >> (8 * i)));
}

// Independent description of the source's little-endian wire grammar.
template<class T>
static std::vector<uint8_t> reference(const std::vector<T>& values, bool basic) {
    std::vector<uint8_t> wire;
    append(wire, values.size(), 4);
    if (values.empty()) return wire;
    T low = *std::min_element(values.begin(), values.end());
    T high = *std::max_element(values.begin(), values.end());
    append(wire, low, sizeof(T));
    append(wire, high, sizeof(T));
    uint64_t range = high - low;
    unsigned width = 0;
    while (range) { ++width; range >>= 1; }
    size_t at = 0;
    const unsigned sizes[] = {32, 16, 8};
    for (unsigned group : sizes) {
        if (!basic && group != 32) break;
        while (values.size() - at >= group) {
            const size_t bytes = basic ? ((size_t(group) * width + 31) / 32) * 4
                                       : (size_t(group) * width / 8);
            const size_t start = wire.size();
            wire.resize(start + bytes, 0);
            for (unsigned j = 0; j < group; ++j) {
                uint64_t delta = values[at + j] - low;
                for (unsigned bit = 0; bit < width; ++bit) {
                    size_t position = size_t(j) * width + bit;
                    wire[start + position / 8] |= uint8_t(((delta >> bit) & 1) << (position % 8));
                }
            }
            at += group;
        }
    }
    for (; at < values.size(); ++at) append(wire, values[at], sizeof(T));
    return wire;
}

template<class T>
static int probe(bool basic, unsigned width, unsigned length, const std::string& mode) {
    const uint64_t maximum = width == 64 ? UINT64_MAX : (width ? (UINT64_C(1) << width) - 1 : 0);
    const T base = width == sizeof(T) * 8 ? 0 : 7;
    std::vector<T> input(length);
    for (unsigned i = 0; i < length; ++i) input[i] = T(base + ((i % 2) ? maximum : 0));
    auto wire = reference(input, basic);
    std::vector<T> recovered(length, T(3));
    uint32_t decoded = 0;
    size_t touched = 0;
    const bool encode = mode.find("encode") != std::string::npos || mode == "check";
    const bool guard = mode.find("guard") == 0;
    const bool padded = mode == "check";
    std::unique_ptr<uint32_t[]> words;
    std::unique_ptr<uint8_t[]> bytes;
    uint8_t* storage = nullptr;
    void* mapping = MAP_FAILED;
    size_t mapping_size = 0;
    if (guard) {
        size_t page = size_t(sysconf(_SC_PAGESIZE));
        if (wire.size() > page) return 3;
        mapping_size = page * 2;
        mapping = mmap(nullptr, mapping_size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (mapping == MAP_FAILED || mprotect(static_cast<uint8_t*>(mapping) + page, page, PROT_NONE)) return 3;
        storage = static_cast<uint8_t*>(mapping) + page - wire.size();
    } else if (basic) {
        words.reset(new uint32_t[wire.size() / 4 + (padded ? 4 : 0)]);
        storage = reinterpret_cast<uint8_t*>(words.get());
    } else {
        bytes.reset(new uint8_t[wire.size() + (padded ? 16 : 0)]);
        storage = bytes.get();
    }
    std::memset(storage, 0xa5, wire.size() + (padded ? 16 : 0));
    if (encode) {
        if (basic) {
            auto* begin = reinterpret_cast<uint32_t*>(storage);
            auto* end = compress(reinterpret_cast<uint32_t*>(input.data()), length, begin);
            touched = size_t(end - begin) * 4;
        } else if (sizeof(T) == 4) {
            touched = size_t(turbocompress(reinterpret_cast<const uint32_t*>(input.data()), length, storage) - storage);
        } else {
            touched = size_t(turbocompress64(reinterpret_cast<const uint64_t*>(input.data()), length, storage) - storage);
        }
        if (touched != wire.size() || std::memcmp(storage, wire.data(), wire.size())) {
            std::cout << "{\"status\":\"WIRE_MISMATCH\"}" << std::endl;
            return 1;
        }
        if (padded) {
            unsigned overwritten = 0;
            for (unsigned i = 0; i < 16; ++i) overwritten += storage[wire.size() + i] != 0xa5;
            if (overwritten) {
                std::cout << "{\"status\":\"WRITE_PAST_REPORTED_END\",\"overwritten_bytes\":" << overwritten << "}" << std::endl;
                return 1;
            }
        }
    } else {
        std::memcpy(storage, wire.data(), wire.size());
    }
    if (!encode || padded) {
        if (basic) {
            auto* begin = reinterpret_cast<uint32_t*>(storage);
            touched = size_t(uncompress(begin, reinterpret_cast<uint32_t*>(recovered.data()), decoded) - begin) * 4;
        } else if (sizeof(T) == 4) {
            touched = size_t(turbouncompress(storage, reinterpret_cast<uint32_t*>(recovered.data()), decoded) - storage);
        } else {
            touched = size_t(turbouncompress64(storage, reinterpret_cast<uint64_t*>(recovered.data()), decoded) - storage);
        }
        if (decoded != length || touched != wire.size() || recovered != input) {
            unsigned mismatches = 0;
            for (unsigned i = 0; i < length; ++i) mismatches += recovered[i] != input[i];
            std::cout << "{\"status\":\"ROUNDTRIP_MISMATCH\",\"mismatched_values\":" << mismatches << "}" << std::endl;
            return 1;
        }
    }
    if (mapping != MAP_FAILED) munmap(mapping, mapping_size);
    std::cout << "{\"status\":\"PASS\",\"wire_bytes\":" << wire.size() << "}" << std::endl;
    return 0;
}

int main(int argc, char** argv) {
    if (argc != 5) return 2;
    std::string variant = argv[1], mode = argv[4];
    unsigned width = unsigned(std::stoul(argv[2])), length = unsigned(std::stoul(argv[3]));
    if (length > 1024 || (variant != "basic32" && variant != "turbo32" && variant != "turbo64")
        || width > (variant == "turbo64" ? 64U : 32U)
        || (mode != "check" && mode != "heap-encode" && mode != "heap-decode"
            && mode != "guard-encode" && mode != "guard-decode")) return 2;
    return variant == "turbo64" ? probe<uint64_t>(false, width, length, mode)
                                  : probe<uint32_t>(variant == "basic32", width, length, mode);
}
