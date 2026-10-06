// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0

#include "prometheus_xor2_chunk.hpp"

#include <charconv>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

namespace codec = prometheus_xor2;

namespace {

int fail(const char* message) {
    std::cerr << message << '\n';
    return 2;
}

bool hex_nibble(char c, std::uint8_t* value) {
    if (c >= '0' && c <= '9') {
        *value = static_cast<std::uint8_t>(c - '0');
        return true;
    }
    if (c >= 'a' && c <= 'f') {
        *value = static_cast<std::uint8_t>(c - 'a' + 10);
        return true;
    }
    if (c >= 'A' && c <= 'F') {
        *value = static_cast<std::uint8_t>(c - 'A' + 10);
        return true;
    }
    return false;
}

bool decode_hex(const std::string& text, std::vector<std::uint8_t>* bytes) {
    if ((text.size() % 2) != 0) {
        return false;
    }
    bytes->resize(text.size() / 2);
    for (std::size_t index = 0; index < bytes->size(); ++index) {
        std::uint8_t high = 0;
        std::uint8_t low = 0;
        if (!hex_nibble(text[index * 2], &high) ||
            !hex_nibble(text[index * 2 + 1], &low)) {
            return false;
        }
        (*bytes)[index] = static_cast<std::uint8_t>((high << 4) | low);
    }
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        return fail("usage: xor2_chunk_cli encode|decode");
    }
    const std::string mode = argv[1];
    if (mode == "encode") {
        std::vector<codec::Sample> samples;
        std::int64_t st = 0;
        std::int64_t timestamp = 0;
        std::uint64_t value_bits = 0;
        while (std::cin >> st >> timestamp >> value_bits) {
            samples.push_back({st, timestamp, value_bits});
        }
        if (!std::cin.eof()) {
            return fail("invalid sample input");
        }
        std::size_t bound = 0;
        if (!codec::max_compressed_size(samples.size(), &bound).ok()) {
            return fail("compressed bound failed");
        }
        std::vector<std::uint8_t> encoded(bound);
        std::size_t written = 0;
        const codec::Status status = codec::encode(
            samples.data(), samples.size(), encoded.data(), encoded.size(), &written);
        if (!status.ok()) {
            return fail(status.message);
        }
        for (std::size_t index = 0; index < written; ++index) {
            std::cout << std::hex << std::setfill('0') << std::setw(2)
                      << static_cast<unsigned>(encoded[index]);
        }
        std::cout << '\n';
        return 0;
    }
    if (mode == "decode") {
        std::string text;
        if (!(std::cin >> text)) {
            return fail("missing encoded hex");
        }
        std::vector<std::uint8_t> encoded;
        if (!decode_hex(text, &encoded) || encoded.size() < codec::kChunkHeaderSize) {
            return fail("invalid encoded hex");
        }
        const std::size_t count =
            (static_cast<std::size_t>(encoded[0]) << 8) | encoded[1];
        std::vector<codec::Sample> samples(count);
        std::size_t written = 0;
        const codec::Status status = codec::decode(
            encoded.data(), encoded.size(), samples.data(), samples.size(), &written);
        if (!status.ok()) {
            return fail(status.message);
        }
        for (std::size_t index = 0; index < written; ++index) {
            std::cout << samples[index].start_timestamp << '\t'
                      << samples[index].timestamp << '\t'
                      << std::hex << std::setfill('0') << std::setw(16)
                      << samples[index].value_bits << std::dec << '\n';
        }
        return 0;
    }
    return fail("unknown mode");
}
