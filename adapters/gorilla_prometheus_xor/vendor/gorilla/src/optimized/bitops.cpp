// SPDX-License-Identifier: Apache-2.0 AND BSD-2-Clause
// Byte batching derived from Prometheus bstream fast read/write paths.
#include "bitops.hpp"
#include <algorithm>
namespace gorilla::detail {
std::uint64_t read_bits(const std::uint8_t* data, std::size_t& pos, unsigned width, std::size_t size, std::uint8_t last) noexcept {
    std::uint64_t value = 0;
    while (width) {
        const auto used = static_cast<unsigned>(pos % 8);
        const auto take = std::min(width, 8 - used);
        const auto shift = 8 - used - take;
        const auto byte = pos / 8 == size - 1 ? last : data[pos / 8];
        value = (value << take) | ((static_cast<unsigned>(byte) >> shift) & ((1U << take) - 1));
        pos += take; width -= take;
    }
    return value;
}
void write_bits(std::vector<std::uint8_t>& data, std::size_t& pos, std::uint64_t value, unsigned width) {
    const auto need = (pos + width + 7) / 8;
    if (need > data.size()) data.resize(need, 0);
    while (width) {
        const auto used = static_cast<unsigned>(pos % 8);
        const auto take = std::min(width, 8 - used);
        const auto part = static_cast<unsigned>((value >> (width - take)) & ((1U << take) - 1));
        data[pos / 8] |= static_cast<std::uint8_t>(part << (8 - used - take));
        pos += take; width -= take;
    }
}
}
