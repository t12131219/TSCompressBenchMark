// Copyright The Prometheus Authors
// Copyright (c) 2015,2016 Damian Gryski <damian@gryski.com>
// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause

#ifndef PROMETHEUS_XOR_CHUNK_HPP
#define PROMETHEUS_XOR_CHUNK_HPP

#include <cstddef>
#include <cstdint>

namespace prometheus_xor {

constexpr std::size_t kChunkHeaderSize = 2;
constexpr std::size_t kMaxSampleCount = 65535;
constexpr std::size_t kMaxBytesPerSample = 19;

struct Sample {
    std::int64_t timestamp;
    std::uint64_t value_bits;
};

enum class StatusCode {
    kOk = 0,
    kInvalidArgument,
    kOutputTooSmall,
    kMalformedStream,
    kSampleLimitExceeded,
};

struct Status {
    StatusCode code;
    const char* message;

    [[nodiscard]] constexpr bool ok() const noexcept {
        return code == StatusCode::kOk;
    }
};

class Cursor {
public:
    Cursor() noexcept = default;

    [[nodiscard]] Status reset(
        const std::uint8_t* input,
        std::size_t input_size) noexcept;

    [[nodiscard]] Status next(
        Sample* sample,
        bool* has_value) noexcept;

    [[nodiscard]] Status seek(
        std::int64_t target_timestamp,
        Sample* sample,
        bool* has_value) noexcept;

    [[nodiscard]] std::size_t samples_read() const noexcept {
        return samples_read_;
    }

private:
    friend Status append(
        const std::uint8_t*,
        std::size_t,
        const Sample*,
        std::size_t,
        std::uint8_t*,
        std::size_t,
        std::size_t*) noexcept;

    const std::uint8_t* payload_ = nullptr;
    std::size_t payload_size_ = 0;
    std::size_t bit_position_ = 0;
    std::size_t sample_count_ = 0;
    std::size_t samples_read_ = 0;
    std::uint64_t timestamp_ = 0;
    std::uint64_t timestamp_delta_ = 0;
    std::uint64_t value_bits_ = 0;
    std::uint8_t leading_ = 0;
    std::uint8_t trailing_ = 0;
    bool initialized_ = false;
    bool finished_ = false;
    Status status_{StatusCode::kOk, "ok"};
};

[[nodiscard]] Status max_compressed_size(
    std::size_t sample_count,
    std::size_t* bound_bytes) noexcept;

[[nodiscard]] Status encode(
    const Sample* samples,
    std::size_t sample_count,
    std::uint8_t* output,
    std::size_t output_capacity,
    std::size_t* bytes_written) noexcept;

[[nodiscard]] Status decode(
    const std::uint8_t* input,
    std::size_t input_size,
    Sample* samples,
    std::size_t sample_capacity,
    std::size_t* samples_written) noexcept;

[[nodiscard]] Status append(
    const std::uint8_t* input,
    std::size_t input_size,
    const Sample* appended_samples,
    std::size_t appended_count,
    std::uint8_t* output,
    std::size_t output_capacity,
    std::size_t* bytes_written) noexcept;

}  // namespace prometheus_xor

#endif
