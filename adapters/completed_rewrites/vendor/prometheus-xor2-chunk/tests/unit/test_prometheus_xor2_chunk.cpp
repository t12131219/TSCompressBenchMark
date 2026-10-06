// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0

#include "prometheus_xor2_chunk.hpp"

#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <vector>

namespace codec = prometheus_xor2;

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

std::int64_t signed_bits(std::uint64_t bits) {
    std::int64_t value = 0;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

std::vector<std::uint8_t> encode(const std::vector<codec::Sample>& samples) {
    std::size_t bound = 0;
    require(codec::max_compressed_size(samples.size(), &bound).ok(), "bound failed");
    std::vector<std::uint8_t> bytes(bound, UINT8_C(0xa5));
    std::size_t written = 0;
    require(codec::encode(samples.data(), samples.size(), bytes.data(), bytes.size(), &written).ok(),
            "encode failed");
    bytes.resize(written);
    return bytes;
}

void roundtrip(const std::vector<codec::Sample>& samples) {
    const std::vector<std::uint8_t> bytes = encode(samples);
    std::vector<codec::Sample> decoded(samples.size());
    std::size_t count = 0;
    require(codec::decode(bytes.data(), bytes.size(), decoded.data(), decoded.size(), &count).ok(),
            "decode failed");
    require(count == samples.size(), "decoded count differs");
    require((count == 0 ||
             std::memcmp(samples.data(), decoded.data(), count * sizeof(codec::Sample)) == 0),
            "decoded samples differ");

    codec::Cursor cursor;
    require(cursor.reset(bytes.data(), bytes.size()).ok(), "cursor reset failed");
    bool monotonic = true;
    for (std::size_t index = 1; index < samples.size(); ++index) {
        monotonic = monotonic && samples[index - 1].timestamp <= samples[index].timestamp;
    }
    if (!samples.empty() && monotonic) {
        codec::Sample sought{};
        bool found = false;
        require(cursor.seek(samples[samples.size() / 2].timestamp, &sought, &found).ok() && found,
                "cursor seek failed");
        require(sought.timestamp == samples[samples.size() / 2].timestamp, "seek timestamp differs");
    }

    for (std::size_t split = 0; split <= samples.size(); ++split) {
        using Difference = std::vector<codec::Sample>::difference_type;
        std::vector<codec::Sample> prefix(
            samples.begin(), samples.begin() + static_cast<Difference>(split));
        const std::vector<std::uint8_t> prefix_bytes = encode(prefix);
        std::size_t bound = 0;
        require(codec::max_compressed_size(samples.size(), &bound).ok(), "append bound failed");
        std::vector<std::uint8_t> resumed(bound);
        std::size_t written = 0;
        require(codec::append(
                    prefix_bytes.data(), prefix_bytes.size(),
                    split == samples.size() ? nullptr : samples.data() + split,
                    samples.size() - split, resumed.data(), resumed.size(), &written).ok(),
                "append failed");
        resumed.resize(written);
        require(resumed == bytes, "append bytes differ from one-shot bytes");
    }
}

std::uint64_t random_next(std::uint64_t* state) {
    std::uint64_t value = *state;
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    *state = value;
    return value;
}

void property_smoke() {
    std::uint64_t state = UINT64_C(0x20260928a55a1234);
    const std::size_t trials = std::getenv("PXOR2_LONG_FUZZ") == nullptr ? 256 : 8192;
    for (std::size_t trial = 0; trial < trials; ++trial) {
        std::vector<codec::Sample> samples;
        const std::size_t count = static_cast<std::size_t>(random_next(&state) % 160);
        std::uint64_t timestamp = random_next(&state);
        std::uint64_t delta = random_next(&state);
        std::int64_t st = 0;
        std::uint64_t value = random_next(&state);
        for (std::size_t index = 0; index < count; ++index) {
            if (index != 0) {
                delta += random_next(&state);
                timestamp += delta;
                value = index % 11 == 0 ? codec::kStaleNaN : value ^ random_next(&state);
                if (trial % 3 == 0 && index >= trial % 17) {
                    st = signed_bits(timestamp - random_next(&state));
                }
            }
            samples.push_back({st, signed_bits(timestamp), value});
        }
        roundtrip(samples);
        const std::vector<std::uint8_t> bytes = encode(samples);
        if (bytes.size() > codec::kChunkHeaderSize) {
            std::vector<codec::Sample> decoded(samples.size());
            std::size_t written = 99;
            require(codec::decode(bytes.data(), bytes.size() - 1, decoded.data(), decoded.size(), &written).code ==
                        codec::StatusCode::kMalformedStream,
                    "truncated stream accepted");
            require(written == 0, "failed decode reported output");
        }
    }
}

void malformed_smoke() {
    std::uint64_t state = UINT64_C(0x6d616c666f726d32);
    const std::size_t trials = std::getenv("PXOR2_LONG_FUZZ") == nullptr ? 4096 : 1000000;
    for (std::size_t trial = 0; trial < trials; ++trial) {
        const std::size_t size = static_cast<std::size_t>(random_next(&state) % 200);
        std::vector<std::uint8_t> bytes(size == 0 ? 1 : size);
        for (std::size_t index = 0; index < size; ++index) {
            bytes[index] = static_cast<std::uint8_t>(random_next(&state));
        }
        if (size >= 3) {
            bytes[0] = 0;
            bytes[1] = static_cast<std::uint8_t>(random_next(&state) % 64);
        }
        std::array<codec::Sample, 64> decoded{};
        std::size_t count = 99;
        const codec::Status status = codec::decode(bytes.data(), size, decoded.data(), decoded.size(), &count);
        if (!status.ok()) {
            require(count == 0, "failed malformed decode reported output");
        }
    }
}

}  // namespace

int main() {
    roundtrip({});
    roundtrip({{0, -1, UINT64_C(0x8000000000000000)}});
    roundtrip({
        {900, 1000, UINT64_C(0x3ff0000000000000)},
        {900, 1010, UINT64_C(0x3ff0000000000001)},
        {950, 1020, codec::kStaleNaN},
        {960, 1031, UINT64_C(0x3ff0000000000003)},
        {970, 1031 + (INT64_C(1) << 40), UINT64_C(0x4000000000000000)},
    });
    std::vector<codec::Sample> forced;
    for (std::size_t index = 0; index < 129; ++index) {
        forced.push_back({0, static_cast<std::int64_t>(1000 + index * 10), UINT64_C(0x3ff0000000000000)});
    }
    roundtrip(forced);
    require(encode(forced)[2] == UINT8_C(0x7f), "sample 127 did not force ST header");
    property_smoke();
    malformed_smoke();
    std::cout << "prometheus-xor2-chunk canonical tests passed\n";
    return 0;
}
