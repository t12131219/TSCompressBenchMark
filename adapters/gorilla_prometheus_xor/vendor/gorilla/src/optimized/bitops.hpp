// SPDX-License-Identifier: Apache-2.0 AND BSD-2-Clause
#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
namespace gorilla::detail {
// Caller has validated width <=64 and input extent; no overread.
std::uint64_t read_bits(const std::uint8_t* data, std::size_t& position, unsigned width,
                        std::size_t size, std::uint8_t last) noexcept;
void write_bits(std::vector<std::uint8_t>& data, std::size_t& position, std::uint64_t value, unsigned width);
}
