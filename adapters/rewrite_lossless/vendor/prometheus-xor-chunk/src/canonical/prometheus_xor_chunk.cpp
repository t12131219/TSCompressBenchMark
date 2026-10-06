// Copyright The Prometheus Authors
// Copyright (c) 2015,2016 Damian Gryski <damian@gryski.com>
// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause
//
// This file is a C++ translation of Prometheus tsdb/chunkenc/xor.go and
// bstream.go. The upstream attribution and BSD-3-Clause notice are preserved
// in LICENSES/BSD-3-Clause.txt and validation/porting_report.md.

#include "prometheus_xor_chunk.hpp"

#include <cstring>
#include <limits>

namespace prometheus_xor {
namespace {

constexpr Status kOk{StatusCode::kOk, "ok"};

std::uint64_t int64_bits(std::int64_t value) noexcept {
    std::uint64_t result = 0;
    static_assert(sizeof(result) == sizeof(value));
    std::memcpy(&result, &value, sizeof(result));
    return result;
}

std::int64_t bits_int64(std::uint64_t value) noexcept {
    std::int64_t result = 0;
    std::memcpy(&result, &value, sizeof(result));
    return result;
}

unsigned leading_zeros(std::uint64_t value) noexcept {
    if (value == 0) {
        return 64;
    }
#if defined(__GNUC__) || defined(__clang__)
    return static_cast<unsigned>(__builtin_clzll(value));
#else
    unsigned count = 0;
    for (std::uint64_t mask = UINT64_C(1) << 63; (value & mask) == 0; mask >>= 1) {
        ++count;
    }
    return count;
#endif
}

unsigned trailing_zeros(std::uint64_t value) noexcept {
    if (value == 0) {
        return 64;
    }
#if defined(__GNUC__) || defined(__clang__)
    return static_cast<unsigned>(__builtin_ctzll(value));
#else
    unsigned count = 0;
    while ((value & UINT64_C(1)) == 0) {
        value >>= 1;
        ++count;
    }
    return count;
#endif
}

class BitWriter {
public:
    BitWriter(
        std::uint8_t* data,
        std::size_t capacity,
        std::size_t initial_bit_position = 0) noexcept
        : data_(data), capacity_(capacity), bit_position_(initial_bit_position) {}

    bool write_bit(bool value) noexcept {
        const std::size_t byte_index = bit_position_ / 8;
        if (byte_index >= capacity_) {
            return false;
        }
        const unsigned bit_index = 7U - static_cast<unsigned>(bit_position_ % 8);
        if ((bit_position_ % 8) == 0) {
            data_[byte_index] = 0;
        }
        if (value) {
            data_[byte_index] |= static_cast<std::uint8_t>(UINT8_C(1) << bit_index);
        }
        ++bit_position_;
        return true;
    }

    bool write_bits(std::uint64_t value, unsigned bit_count) noexcept {
        if (bit_count > 64) {
            return false;
        }
        for (unsigned remaining = bit_count; remaining > 0; --remaining) {
            if (!write_bit(((value >> (remaining - 1)) & UINT64_C(1)) != 0)) {
                return false;
            }
        }
        return true;
    }

    bool write_byte(std::uint8_t value) noexcept {
        return write_bits(value, 8);
    }

    [[nodiscard]] std::size_t bytes_written() const noexcept {
        return (bit_position_ + 7) / 8;
    }

    [[nodiscard]] std::size_t bit_position() const noexcept {
        return bit_position_;
    }

private:
    std::uint8_t* data_;
    std::size_t capacity_;
    std::size_t bit_position_ = 0;
};

class BitReader {
public:
    BitReader(
        const std::uint8_t* data,
        std::size_t size,
        std::size_t initial_bit_position = 0) noexcept
        : data_(data), size_(size), bit_position_(initial_bit_position) {}

    bool read_bit(bool* value) noexcept {
        if (value == nullptr || bit_position_ / 8 >= size_) {
            return false;
        }
        const std::size_t byte_index = bit_position_ / 8;
        const unsigned bit_index = 7U - static_cast<unsigned>(bit_position_ % 8);
        *value = ((data_[byte_index] >> bit_index) & UINT8_C(1)) != 0;
        ++bit_position_;
        return true;
    }

    bool read_bits(unsigned bit_count, std::uint64_t* value) noexcept {
        if (value == nullptr || bit_count > 64 || bit_count > size_ * 8 - bit_position_) {
            return false;
        }
        std::uint64_t result = 0;
        for (unsigned index = 0; index < bit_count; ++index) {
            bool bit = false;
            if (!read_bit(&bit)) {
                return false;
            }
            result = (result << 1) | static_cast<std::uint64_t>(bit);
        }
        *value = result;
        return true;
    }

    bool read_byte(std::uint8_t* value) noexcept {
        std::uint64_t decoded = 0;
        if (!read_bits(8, &decoded)) {
            return false;
        }
        *value = static_cast<std::uint8_t>(decoded);
        return true;
    }

    [[nodiscard]] std::size_t remaining_bits() const noexcept {
        return size_ * 8 - bit_position_;
    }

    [[nodiscard]] std::size_t bit_position() const noexcept {
        return bit_position_;
    }

    bool remaining_bits_are_zero() const noexcept {
        for (std::size_t position = bit_position_; position < size_ * 8; ++position) {
            const unsigned bit_index = 7U - static_cast<unsigned>(position % 8);
            if (((data_[position / 8] >> bit_index) & UINT8_C(1)) != 0) {
                return false;
            }
        }
        return true;
    }

private:
    const std::uint8_t* data_;
    std::size_t size_;
    std::size_t bit_position_ = 0;
};

bool write_uvarint(BitWriter* writer, std::uint64_t value) noexcept {
    while (value >= UINT64_C(0x80)) {
        if (!writer->write_byte(static_cast<std::uint8_t>(value) | UINT8_C(0x80))) {
            return false;
        }
        value >>= 7;
    }
    return writer->write_byte(static_cast<std::uint8_t>(value));
}

bool write_varint(BitWriter* writer, std::int64_t value) noexcept {
    std::uint64_t encoded = int64_bits(value) << 1;
    if (value < 0) {
        encoded = ~encoded;
    }
    return write_uvarint(writer, encoded);
}

bool read_uvarint(BitReader* reader, std::uint64_t* value) noexcept {
    std::uint64_t result = 0;
    for (unsigned index = 0; index < 10; ++index) {
        std::uint8_t byte = 0;
        if (!reader->read_byte(&byte)) {
            return false;
        }
        if (index == 9 && byte > 1) {
            return false;
        }
        result |= static_cast<std::uint64_t>(byte & UINT8_C(0x7f)) << (7U * index);
        if (byte < UINT8_C(0x80)) {
            *value = result;
            return true;
        }
    }
    return false;
}

bool read_varint(BitReader* reader, std::int64_t* value) noexcept {
    std::uint64_t encoded = 0;
    if (!read_uvarint(reader, &encoded)) {
        return false;
    }
    std::uint64_t decoded = encoded >> 1;
    if ((encoded & UINT64_C(1)) != 0) {
        decoded = ~decoded;
    }
    *value = bits_int64(decoded);
    return true;
}

bool in_prometheus_bit_range(std::int64_t value, unsigned bit_count) noexcept {
    const std::int64_t half = std::int64_t{1} << (bit_count - 1);
    return -(half - 1) <= value && value <= half;
}

bool write_value_delta(
    BitWriter* writer,
    std::uint64_t new_value,
    std::uint64_t current_value,
    std::uint8_t* leading,
    std::uint8_t* trailing) noexcept {
    const std::uint64_t delta = new_value ^ current_value;
    if (delta == 0) {
        return writer->write_bit(false);
    }
    if (!writer->write_bit(true)) {
        return false;
    }

    std::uint8_t new_leading = static_cast<std::uint8_t>(leading_zeros(delta));
    const std::uint8_t new_trailing = static_cast<std::uint8_t>(trailing_zeros(delta));
    if (new_leading >= 32) {
        new_leading = 31;
    }

    if (*leading != UINT8_C(0xff) && new_leading >= *leading && new_trailing >= *trailing) {
        const unsigned significant = 64U - *leading - *trailing;
        return writer->write_bit(false) && writer->write_bits(delta >> *trailing, significant);
    }

    *leading = new_leading;
    *trailing = new_trailing;
    const unsigned significant = 64U - new_leading - new_trailing;
    return writer->write_bit(true) &&
           writer->write_bits(new_leading, 5) &&
           writer->write_bits(significant == 64 ? 0 : significant, 6) &&
           writer->write_bits(delta >> new_trailing, significant);
}

bool read_value_delta(
    BitReader* reader,
    std::uint64_t* value,
    std::uint8_t* leading,
    std::uint8_t* trailing) noexcept {
    bool changed = false;
    if (!reader->read_bit(&changed)) {
        return false;
    }
    if (!changed) {
        return true;
    }

    bool new_window = false;
    if (!reader->read_bit(&new_window)) {
        return false;
    }
    std::uint8_t decoded_leading = *leading;
    std::uint8_t decoded_trailing = *trailing;
    unsigned significant = 64U - decoded_leading - decoded_trailing;
    if (new_window) {
        std::uint64_t raw_leading = 0;
        std::uint64_t raw_significant = 0;
        if (!reader->read_bits(5, &raw_leading) ||
            !reader->read_bits(6, &raw_significant)) {
            return false;
        }
        decoded_leading = static_cast<std::uint8_t>(raw_leading);
        significant = raw_significant == 0 ? 64U : static_cast<unsigned>(raw_significant);
        if (decoded_leading + significant > 64U) {
            return false;
        }
        decoded_trailing = static_cast<std::uint8_t>(64U - decoded_leading - significant);
        *leading = decoded_leading;
        *trailing = decoded_trailing;
    }
    if (significant == 0 || significant > 64U || decoded_trailing >= 64U) {
        return false;
    }

    std::uint64_t bits = 0;
    if (!reader->read_bits(significant, &bits)) {
        return false;
    }
    *value ^= bits << decoded_trailing;
    return true;
}

bool write_delta_of_delta(BitWriter* writer, std::int64_t delta_of_delta) noexcept {
    if (delta_of_delta == 0) {
        return writer->write_bit(false);
    }
    if (in_prometheus_bit_range(delta_of_delta, 14)) {
        const std::uint64_t bits = int64_bits(delta_of_delta);
        return writer->write_bits(UINT64_C(0b10), 2) && writer->write_bits(bits, 14);
    }
    if (in_prometheus_bit_range(delta_of_delta, 17)) {
        return writer->write_bits(UINT64_C(0b110), 3) &&
               writer->write_bits(int64_bits(delta_of_delta), 17);
    }
    if (in_prometheus_bit_range(delta_of_delta, 20)) {
        return writer->write_bits(UINT64_C(0b1110), 4) &&
               writer->write_bits(int64_bits(delta_of_delta), 20);
    }
    return writer->write_bits(UINT64_C(0b1111), 4) &&
           writer->write_bits(int64_bits(delta_of_delta), 64);
}

bool read_delta_of_delta(BitReader* reader, std::int64_t* delta_of_delta) noexcept {
    unsigned prefix_ones = 0;
    for (; prefix_ones < 4; ++prefix_ones) {
        bool bit = false;
        if (!reader->read_bit(&bit)) {
            return false;
        }
        if (!bit) {
            break;
        }
    }
    if (prefix_ones == 0) {
        *delta_of_delta = 0;
        return true;
    }

    const unsigned width = prefix_ones == 1 ? 14U : prefix_ones == 2 ? 17U : prefix_ones == 3 ? 20U : 64U;
    std::uint64_t bits = 0;
    if (!reader->read_bits(width, &bits)) {
        return false;
    }
    if (width == 64U) {
        *delta_of_delta = bits_int64(bits);
        return true;
    }
    const std::uint64_t midpoint = UINT64_C(1) << (width - 1);
    if (bits > midpoint) {
        bits -= UINT64_C(1) << width;
    }
    *delta_of_delta = bits_int64(bits);
    return true;
}

}  // namespace

Status max_compressed_size(std::size_t sample_count, std::size_t* bound_bytes) noexcept {
    if (bound_bytes == nullptr) {
        return {StatusCode::kInvalidArgument, "bound_bytes is null"};
    }
    if (sample_count > kMaxSampleCount) {
        return {StatusCode::kSampleLimitExceeded, "sample count exceeds uint16 chunk header"};
    }
    if (sample_count > (std::numeric_limits<std::size_t>::max() - kChunkHeaderSize) / kMaxBytesPerSample) {
        return {StatusCode::kInvalidArgument, "compressed bound overflows size_t"};
    }
    *bound_bytes = kChunkHeaderSize + sample_count * kMaxBytesPerSample;
    return kOk;
}

Status Cursor::reset(const std::uint8_t* input, std::size_t input_size) noexcept {
    payload_ = nullptr;
    payload_size_ = 0;
    bit_position_ = 0;
    sample_count_ = 0;
    samples_read_ = 0;
    timestamp_ = 0;
    timestamp_delta_ = 0;
    value_bits_ = 0;
    leading_ = 0;
    trailing_ = 0;
    initialized_ = false;
    finished_ = false;
    status_ = kOk;

    if (input == nullptr) {
        status_ = {StatusCode::kInvalidArgument, "input is null"};
        return status_;
    }
    if (input_size < kChunkHeaderSize) {
        status_ = {StatusCode::kMalformedStream, "chunk header is truncated"};
        return status_;
    }
    sample_count_ = (static_cast<std::size_t>(input[0]) << 8) | input[1];
    std::size_t maximum_size = 0;
    const Status bound_status = max_compressed_size(sample_count_, &maximum_size);
    if (!bound_status.ok() || input_size > maximum_size) {
        status_ = {StatusCode::kMalformedStream, "chunk exceeds the format size bound"};
        return status_;
    }
    if (sample_count_ == 0 && input_size != kChunkHeaderSize) {
        status_ = {StatusCode::kMalformedStream, "empty chunk contains trailing data"};
        return status_;
    }

    payload_ = input + kChunkHeaderSize;
    payload_size_ = input_size - kChunkHeaderSize;
    initialized_ = true;
    return status_;
}

Status Cursor::next(Sample* sample, bool* has_value) noexcept {
    if (sample == nullptr || has_value == nullptr) {
        return {StatusCode::kInvalidArgument, "cursor output is null"};
    }
    *has_value = false;
    if (!status_.ok()) {
        return status_;
    }
    if (!initialized_) {
        status_ = {StatusCode::kInvalidArgument, "cursor is not initialized"};
        return status_;
    }
    BitReader reader(payload_, payload_size_, bit_position_);
    if (samples_read_ == sample_count_) {
        if (!finished_) {
            if (reader.remaining_bits() >= 8 || !reader.remaining_bits_are_zero()) {
                status_ = {StatusCode::kMalformedStream, "chunk has non-padding trailing bits"};
                return status_;
            }
            finished_ = true;
        }
        return status_;
    }

    if (samples_read_ == 0) {
        std::int64_t timestamp = 0;
        if (!read_varint(&reader, &timestamp) || !reader.read_bits(64, &value_bits_)) {
            status_ = {StatusCode::kMalformedStream, "first sample is truncated or invalid"};
            return status_;
        }
        timestamp_ = int64_bits(timestamp);
    } else {
        if (samples_read_ == 1) {
            if (!read_uvarint(&reader, &timestamp_delta_)) {
                status_ = {StatusCode::kMalformedStream, "second timestamp delta is invalid"};
                return status_;
            }
        } else {
            std::int64_t delta_of_delta = 0;
            if (!read_delta_of_delta(&reader, &delta_of_delta)) {
                status_ = {StatusCode::kMalformedStream, "timestamp delta-of-delta is invalid"};
                return status_;
            }
            timestamp_delta_ += int64_bits(delta_of_delta);
        }
        timestamp_ += timestamp_delta_;
        if (!read_value_delta(&reader, &value_bits_, &leading_, &trailing_)) {
            status_ = {StatusCode::kMalformedStream, "value delta is invalid"};
            return status_;
        }
    }

    bit_position_ = reader.bit_position();
    ++samples_read_;
    *sample = {bits_int64(timestamp_), value_bits_};
    *has_value = true;
    return status_;
}

Status Cursor::seek(
    std::int64_t target_timestamp,
    Sample* sample,
    bool* has_value) noexcept {
    if (sample == nullptr || has_value == nullptr) {
        return {StatusCode::kInvalidArgument, "cursor output is null"};
    }
    *has_value = false;
    if (!status_.ok()) {
        return status_;
    }
    if (!initialized_) {
        status_ = {StatusCode::kInvalidArgument, "cursor is not initialized"};
        return status_;
    }
    if (samples_read_ != 0 && target_timestamp <= bits_int64(timestamp_)) {
        *sample = {bits_int64(timestamp_), value_bits_};
        *has_value = true;
        return status_;
    }
    do {
        const Status next_status = next(sample, has_value);
        if (!next_status.ok() || !*has_value) {
            return next_status;
        }
    } while (sample->timestamp < target_timestamp);
    return status_;
}

Status encode(
    const Sample* samples,
    std::size_t sample_count,
    std::uint8_t* output,
    std::size_t output_capacity,
    std::size_t* bytes_written) noexcept {
    if (bytes_written == nullptr || output == nullptr || (samples == nullptr && sample_count != 0)) {
        return {StatusCode::kInvalidArgument, "invalid null argument"};
    }
    *bytes_written = 0;
    if (sample_count > kMaxSampleCount) {
        return {StatusCode::kSampleLimitExceeded, "sample count exceeds uint16 chunk header"};
    }
    if (output_capacity < kChunkHeaderSize) {
        return {StatusCode::kOutputTooSmall, "output cannot hold chunk header"};
    }

    output[0] = static_cast<std::uint8_t>(sample_count >> 8);
    output[1] = static_cast<std::uint8_t>(sample_count);
    BitWriter writer(output + kChunkHeaderSize, output_capacity - kChunkHeaderSize);
    if (sample_count == 0) {
        *bytes_written = kChunkHeaderSize;
        return kOk;
    }

    if (!write_varint(&writer, samples[0].timestamp) ||
        !writer.write_bits(samples[0].value_bits, 64)) {
        return {StatusCode::kOutputTooSmall, "output exhausted by first sample"};
    }

    std::uint64_t previous_timestamp = int64_bits(samples[0].timestamp);
    std::uint64_t previous_delta = 0;
    std::uint64_t previous_value = samples[0].value_bits;
    std::uint8_t leading = UINT8_C(0xff);
    std::uint8_t trailing = 0;

    for (std::size_t index = 1; index < sample_count; ++index) {
        const std::uint64_t timestamp = int64_bits(samples[index].timestamp);
        const std::uint64_t delta = timestamp - previous_timestamp;
        if (index == 1) {
            if (!write_uvarint(&writer, delta)) {
                return {StatusCode::kOutputTooSmall, "output exhausted by second timestamp"};
            }
        } else {
            const std::int64_t delta_of_delta = bits_int64(delta - previous_delta);
            if (!write_delta_of_delta(&writer, delta_of_delta)) {
                return {StatusCode::kOutputTooSmall, "output exhausted by timestamp delta"};
            }
        }
        if (!write_value_delta(
                &writer, samples[index].value_bits, previous_value, &leading, &trailing)) {
            return {StatusCode::kOutputTooSmall, "output exhausted by value delta"};
        }
        previous_timestamp = timestamp;
        previous_delta = delta;
        previous_value = samples[index].value_bits;
    }

    *bytes_written = kChunkHeaderSize + writer.bytes_written();
    return kOk;
}

Status append(
    const std::uint8_t* input,
    std::size_t input_size,
    const Sample* appended_samples,
    std::size_t appended_count,
    std::uint8_t* output,
    std::size_t output_capacity,
    std::size_t* bytes_written) noexcept {
    if (bytes_written == nullptr || output == nullptr ||
        (appended_samples == nullptr && appended_count != 0)) {
        return {StatusCode::kInvalidArgument, "invalid null argument"};
    }
    *bytes_written = 0;

    Cursor cursor;
    Status status = cursor.reset(input, input_size);
    if (!status.ok()) {
        return status;
    }
    Sample last{};
    bool has_value = false;
    do {
        status = cursor.next(&last, &has_value);
        if (!status.ok()) {
            return status;
        }
    } while (has_value);

    if (appended_count > kMaxSampleCount - cursor.sample_count_) {
        return {StatusCode::kSampleLimitExceeded, "sample count exceeds uint16 chunk header"};
    }
    const std::size_t total_count = cursor.sample_count_ + appended_count;
    std::size_t maximum_size = 0;
    status = max_compressed_size(total_count, &maximum_size);
    if (!status.ok()) {
        return status;
    }
    if (output_capacity < input_size) {
        return {StatusCode::kOutputTooSmall, "output cannot hold existing chunk"};
    }

    std::memmove(output, input, input_size);
    BitWriter writer(
        output + kChunkHeaderSize,
        output_capacity - kChunkHeaderSize,
        cursor.bit_position_);
    std::uint64_t previous_timestamp = cursor.timestamp_;
    std::uint64_t previous_delta = cursor.timestamp_delta_;
    std::uint64_t previous_value = cursor.value_bits_;
    std::uint8_t leading = cursor.sample_count_ == 0 ? UINT8_C(0xff) : cursor.leading_;
    std::uint8_t trailing = cursor.trailing_;
    std::size_t count = cursor.sample_count_;

    for (std::size_t index = 0; index < appended_count; ++index) {
        const Sample& current = appended_samples[index];
        std::uint64_t delta = 0;
        if (count == 0) {
            if (!write_varint(&writer, current.timestamp) ||
                !writer.write_bits(current.value_bits, 64)) {
                return {StatusCode::kOutputTooSmall, "output exhausted by first appended sample"};
            }
        } else {
            const std::uint64_t timestamp = int64_bits(current.timestamp);
            delta = timestamp - previous_timestamp;
            if (count == 1) {
                if (!write_uvarint(&writer, delta)) {
                    return {StatusCode::kOutputTooSmall, "output exhausted by second timestamp"};
                }
            } else {
                const std::int64_t delta_of_delta = bits_int64(delta - previous_delta);
                if (!write_delta_of_delta(&writer, delta_of_delta)) {
                    return {StatusCode::kOutputTooSmall, "output exhausted by timestamp delta"};
                }
            }
            if (!write_value_delta(
                    &writer, current.value_bits, previous_value, &leading, &trailing)) {
                return {StatusCode::kOutputTooSmall, "output exhausted by value delta"};
            }
            previous_timestamp = timestamp;
        }
        if (count == 0) {
            previous_timestamp = int64_bits(current.timestamp);
        }
        previous_delta = delta;
        previous_value = current.value_bits;
        ++count;
    }

    output[0] = static_cast<std::uint8_t>(total_count >> 8);
    output[1] = static_cast<std::uint8_t>(total_count);
    *bytes_written = kChunkHeaderSize + writer.bytes_written();
    return kOk;
}

Status decode(
    const std::uint8_t* input,
    std::size_t input_size,
    Sample* samples,
    std::size_t sample_capacity,
    std::size_t* samples_written) noexcept {
    if (samples_written == nullptr || input == nullptr || (samples == nullptr && sample_capacity != 0)) {
        return {StatusCode::kInvalidArgument, "invalid null argument"};
    }
    *samples_written = 0;
    if (input_size < kChunkHeaderSize) {
        return {StatusCode::kMalformedStream, "chunk header is truncated"};
    }
    const std::size_t count = (static_cast<std::size_t>(input[0]) << 8) | input[1];
    if (count > sample_capacity) {
        return {StatusCode::kOutputTooSmall, "sample output capacity is too small"};
    }
    Cursor cursor;
    Status status = cursor.reset(input, input_size);
    if (!status.ok()) {
        return status;
    }
    bool has_value = false;
    std::size_t decoded_count = 0;
    do {
        Sample decoded{};
        status = cursor.next(&decoded, &has_value);
        if (!status.ok()) {
            return status;
        }
        if (has_value) {
            samples[decoded_count] = decoded;
            ++decoded_count;
        }
    } while (has_value);
    *samples_written = decoded_count;
    return status;
}

}  // namespace prometheus_xor
