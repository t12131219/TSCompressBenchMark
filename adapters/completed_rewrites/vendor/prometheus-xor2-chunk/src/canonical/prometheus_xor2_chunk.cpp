// Copyright The Prometheus Authors
// Copyright (c) 2015,2016 Damian Gryski <damian@gryski.com>
// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause

#include "prometheus_xor2_chunk.hpp"

#include <cstring>
#include <limits>
#include <memory>

namespace prometheus_xor2 {
namespace {

constexpr Status kOk{StatusCode::kOk, "ok"};
constexpr std::size_t kMaxFirstSTChangeOn = 127;

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
    BitWriter(std::uint8_t* data, std::size_t capacity) noexcept
        : data_(data), capacity_(capacity) {}

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

    bool write_bits(std::uint64_t value, unsigned count) noexcept {
        if (count > 64) {
            return false;
        }
        for (unsigned remaining = count; remaining > 0; --remaining) {
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

private:
    std::uint8_t* data_;
    std::size_t capacity_;
    std::size_t bit_position_ = 0;
};

class BitReader {
public:
    BitReader(const std::uint8_t* data, std::size_t size, std::size_t position = 0) noexcept
        : data_(data), size_(size), bit_position_(position) {}

    bool read_bit(bool* value) noexcept {
        if (value == nullptr || bit_position_ / 8 >= size_) {
            return false;
        }
        const unsigned bit_index = 7U - static_cast<unsigned>(bit_position_ % 8);
        *value = ((data_[bit_position_ / 8] >> bit_index) & UINT8_C(1)) != 0;
        ++bit_position_;
        return true;
    }

    bool read_bits(unsigned count, std::uint64_t* value) noexcept {
        if (value == nullptr || count > 64 || count > size_ * 8 - bit_position_) {
            return false;
        }
        std::uint64_t result = 0;
        for (unsigned index = 0; index < count; ++index) {
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

    [[nodiscard]] std::size_t bit_position() const noexcept {
        return bit_position_;
    }

    [[nodiscard]] std::size_t remaining_bits() const noexcept {
        return size_ * 8 - bit_position_;
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
    std::size_t bit_position_;
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
        if (!reader->read_byte(&byte) || (index == 9 && byte > 1)) {
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

bool prometheus_range(std::int64_t value, unsigned width) noexcept {
    const std::int64_t half = std::int64_t{1} << (width - 1);
    return -(half - 1) <= value && value <= half;
}

bool write_varbit(BitWriter* writer, std::int64_t value) noexcept {
    static constexpr unsigned widths[] = {3, 6, 9, 12, 18, 25, 56};
    if (value == 0) {
        return writer->write_bit(false);
    }
    for (unsigned prefix = 0; prefix < 7; ++prefix) {
        if (prometheus_range(value, widths[prefix])) {
            for (unsigned index = 0; index < prefix + 1; ++index) {
                if (!writer->write_bit(true)) {
                    return false;
                }
            }
            return writer->write_bit(false) &&
                   writer->write_bits(int64_bits(value), widths[prefix]);
        }
    }
    return writer->write_bits(UINT8_C(0xff), 8) &&
           writer->write_bits(int64_bits(value), 64);
}

bool read_varbit(BitReader* reader, std::int64_t* value) noexcept {
    static constexpr unsigned widths[] = {0, 3, 6, 9, 12, 18, 25, 56, 64};
    unsigned ones = 0;
    while (ones < 8) {
        bool bit = false;
        if (!reader->read_bit(&bit)) {
            return false;
        }
        if (!bit) {
            break;
        }
        ++ones;
    }
    const unsigned width = widths[ones];
    if (width == 0) {
        *value = 0;
        return true;
    }
    std::uint64_t raw = 0;
    if (!reader->read_bits(width, &raw)) {
        return false;
    }
    if (width < 64) {
        const std::uint64_t midpoint = UINT64_C(1) << (width - 1);
        if (raw > midpoint) {
            raw -= UINT64_C(1) << width;
        }
    }
    *value = bits_int64(raw);
    return true;
}

bool write_new_window(
    BitWriter* writer,
    std::uint64_t delta,
    std::uint8_t* leading,
    std::uint8_t* trailing) noexcept {
    std::uint8_t new_leading = static_cast<std::uint8_t>(leading_zeros(delta));
    const std::uint8_t new_trailing = static_cast<std::uint8_t>(trailing_zeros(delta));
    if (new_leading >= 32) {
        new_leading = 31;
    }
    *leading = new_leading;
    *trailing = new_trailing;
    const unsigned significant = 64U - new_leading - new_trailing;
    return writer->write_bits(new_leading, 5) &&
           writer->write_bits(significant == 64 ? 0 : significant, 6) &&
           writer->write_bits(delta >> new_trailing, significant);
}

bool can_reuse(
    std::uint64_t delta,
    std::uint8_t leading,
    std::uint8_t trailing) noexcept {
    if (leading == UINT8_C(0xff)) {
        return false;
    }
    unsigned new_leading = leading_zeros(delta);
    if (new_leading >= 32) {
        new_leading = 31;
    }
    return new_leading >= leading && trailing_zeros(delta) >= trailing;
}

bool write_value_general(
    BitWriter* writer,
    std::uint64_t value,
    std::uint64_t baseline,
    std::uint8_t* leading,
    std::uint8_t* trailing) noexcept {
    if (value == kStaleNaN) {
        return writer->write_bits(UINT8_C(0b111), 3);
    }
    const std::uint64_t delta = value ^ baseline;
    if (delta == 0) {
        return writer->write_bit(false);
    }
    if (can_reuse(delta, *leading, *trailing)) {
        const unsigned significant = 64U - *leading - *trailing;
        return writer->write_bits(UINT8_C(0b10), 2) &&
               writer->write_bits(delta >> *trailing, significant);
    }
    return writer->write_bits(UINT8_C(0b110), 3) &&
           write_new_window(writer, delta, leading, trailing);
}

bool write_value_known_changed(
    BitWriter* writer,
    std::uint64_t value,
    std::uint64_t baseline,
    std::uint8_t* leading,
    std::uint8_t* trailing) noexcept {
    const std::uint64_t delta = value ^ baseline;
    if (can_reuse(delta, *leading, *trailing)) {
        const unsigned significant = 64U - *leading - *trailing;
        return writer->write_bit(false) &&
               writer->write_bits(delta >> *trailing, significant);
    }
    return writer->write_bit(true) &&
           write_new_window(writer, delta, leading, trailing);
}

bool read_new_window(
    BitReader* reader,
    std::uint64_t* baseline,
    std::uint64_t* value,
    std::uint8_t* leading,
    std::uint8_t* trailing) noexcept {
    std::uint64_t raw_leading = 0;
    std::uint64_t raw_significant = 0;
    if (!reader->read_bits(5, &raw_leading) ||
        !reader->read_bits(6, &raw_significant)) {
        return false;
    }
    const unsigned significant = raw_significant == 0 ? 64U :
        static_cast<unsigned>(raw_significant);
    if (raw_leading + significant > 64U) {
        return false;
    }
    *leading = static_cast<std::uint8_t>(raw_leading);
    *trailing = static_cast<std::uint8_t>(64U - raw_leading - significant);
    std::uint64_t bits = 0;
    if (!reader->read_bits(significant, &bits)) {
        return false;
    }
    *baseline ^= bits << *trailing;
    *value = *baseline;
    return true;
}

bool read_reused_window(
    BitReader* reader,
    std::uint64_t* baseline,
    std::uint64_t* value,
    std::uint8_t leading,
    std::uint8_t trailing) noexcept {
    const unsigned significant = 64U - leading - trailing;
    if (significant == 0 || significant > 64) {
        return false;
    }
    std::uint64_t bits = 0;
    if (!reader->read_bits(significant, &bits)) {
        return false;
    }
    *baseline ^= bits << trailing;
    *value = *baseline;
    return true;
}

bool read_value_general(
    BitReader* reader,
    std::uint64_t* baseline,
    std::uint64_t* value,
    std::uint8_t* leading,
    std::uint8_t* trailing) noexcept {
    bool first = false;
    if (!reader->read_bit(&first)) {
        return false;
    }
    if (!first) {
        *value = *baseline;
        return true;
    }
    bool second = false;
    if (!reader->read_bit(&second)) {
        return false;
    }
    if (!second) {
        return read_reused_window(reader, baseline, value, *leading, *trailing);
    }
    bool third = false;
    if (!reader->read_bit(&third)) {
        return false;
    }
    if (third) {
        *value = kStaleNaN;
        return true;
    }
    return read_new_window(reader, baseline, value, leading, trailing);
}

bool read_value_known_changed(
    BitReader* reader,
    std::uint64_t* baseline,
    std::uint64_t* value,
    std::uint8_t* leading,
    std::uint8_t* trailing) noexcept {
    bool new_window = false;
    if (!reader->read_bit(&new_window)) {
        return false;
    }
    if (!new_window) {
        return read_reused_window(reader, baseline, value, *leading, *trailing);
    }
    return read_new_window(reader, baseline, value, leading, trailing);
}

bool write_joint(
    BitWriter* writer,
    std::int64_t dod,
    std::uint64_t value,
    std::uint64_t baseline,
    std::uint8_t* leading,
    std::uint8_t* trailing) noexcept {
    if (dod == 0) {
        if (value == kStaleNaN) {
            return writer->write_bits(UINT8_C(0b11111), 5);
        }
        if (value == baseline) {
            return writer->write_bit(false);
        }
        return writer->write_bits(UINT8_C(0b10), 2) &&
               write_value_known_changed(writer, value, baseline, leading, trailing);
    }
    if (-4096 <= dod && dod <= 4095) {
        if (!writer->write_bits(UINT8_C(0b110), 3) ||
            !writer->write_bits(int64_bits(dod), 13)) {
            return false;
        }
    } else if (-524288 <= dod && dod <= 524287) {
        if (!writer->write_bits(UINT8_C(0b1110), 4) ||
            !writer->write_bits(int64_bits(dod), 20)) {
            return false;
        }
    } else if (!writer->write_bits(UINT8_C(0b11110), 5) ||
               !writer->write_bits(int64_bits(dod), 64)) {
        return false;
    }
    return write_value_general(writer, value, baseline, leading, trailing);
}

bool read_signed_width(BitReader* reader, unsigned width, std::int64_t* value) noexcept {
    std::uint64_t raw = 0;
    if (!reader->read_bits(width, &raw)) {
        return false;
    }
    if (width < 64 && raw >= (UINT64_C(1) << (width - 1))) {
        raw -= UINT64_C(1) << width;
    }
    *value = bits_int64(raw);
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
    if (sample_count > (std::numeric_limits<std::size_t>::max() - kChunkHeaderSize) /
                           kMaxBytesPerSample) {
        return {StatusCode::kInvalidArgument, "compressed bound overflows size_t"};
    }
    *bound_bytes = kChunkHeaderSize + sample_count * kMaxBytesPerSample;
    return kOk;
}

Status encode(
    const Sample* samples,
    std::size_t sample_count,
    std::uint8_t* output,
    std::size_t output_capacity,
    std::size_t* bytes_written) noexcept {
    if (bytes_written == nullptr || output == nullptr ||
        (samples == nullptr && sample_count != 0)) {
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
    output[2] = 0;
    if (sample_count == 0) {
        *bytes_written = kChunkHeaderSize;
        return kOk;
    }

    std::size_t first_st_change = 0;
    for (std::size_t index = 1; index < sample_count; ++index) {
        if (samples[index].start_timestamp != samples[index - 1].start_timestamp) {
            first_st_change = index;
            break;
        }
        if (index == kMaxFirstSTChangeOn) {
            first_st_change = index;
            break;
        }
    }
    if (samples[0].start_timestamp != 0) {
        output[2] |= UINT8_C(0x80);
    }
    output[2] |= static_cast<std::uint8_t>(first_st_change);

    BitWriter writer(output + kChunkHeaderSize, output_capacity - kChunkHeaderSize);
    if (!write_varint(&writer, samples[0].timestamp) ||
        !writer.write_bits(samples[0].value_bits, 64)) {
        return {StatusCode::kOutputTooSmall, "output exhausted by first sample"};
    }
    if (samples[0].start_timestamp != 0) {
        const std::uint64_t diff = int64_bits(samples[0].timestamp) -
            int64_bits(samples[0].start_timestamp);
        if (!write_varint(&writer, bits_int64(diff))) {
            return {StatusCode::kOutputTooSmall, "output exhausted by first ST"};
        }
    }

    std::uint64_t previous_timestamp = int64_bits(samples[0].timestamp);
    std::uint64_t previous_delta = 0;
    std::uint64_t baseline = samples[0].value_bits == kStaleNaN ? 0 : samples[0].value_bits;
    std::uint64_t st_diff = 0;
    std::uint8_t leading = UINT8_C(0xff);
    std::uint8_t trailing = 0;

    for (std::size_t index = 1; index < sample_count; ++index) {
        const std::uint64_t timestamp = int64_bits(samples[index].timestamp);
        const std::uint64_t delta = timestamp - previous_timestamp;
        if (index == 1) {
            if (!write_uvarint(&writer, delta) ||
                !write_value_general(
                    &writer, samples[index].value_bits, baseline, &leading, &trailing)) {
                return {StatusCode::kOutputTooSmall, "output exhausted by second sample"};
            }
        } else {
            const std::int64_t dod = bits_int64(delta - previous_delta);
            if (!write_joint(
                    &writer, dod, samples[index].value_bits, baseline, &leading, &trailing)) {
                return {StatusCode::kOutputTooSmall, "output exhausted by joint sample"};
            }
        }

        if (first_st_change != 0 && index >= first_st_change) {
            const std::uint64_t new_st_diff = previous_timestamp -
                int64_bits(samples[index].start_timestamp);
            const std::uint64_t encoded_diff = index == first_st_change ?
                new_st_diff : new_st_diff - st_diff;
            if (!write_varbit(&writer, bits_int64(encoded_diff))) {
                return {StatusCode::kOutputTooSmall, "output exhausted by ST delta"};
            }
            st_diff = new_st_diff;
        }
        previous_timestamp = timestamp;
        previous_delta = delta;
        if (samples[index].value_bits != kStaleNaN) {
            baseline = samples[index].value_bits;
        }
    }

    *bytes_written = kChunkHeaderSize + writer.bytes_written();
    return kOk;
}

Status Cursor::reset(const std::uint8_t* input, std::size_t input_size) noexcept {
    *this = Cursor{};
    if (input == nullptr) {
        status_ = {StatusCode::kInvalidArgument, "input is null"};
        return status_;
    }
    if (input_size < kChunkHeaderSize) {
        status_ = {StatusCode::kMalformedStream, "chunk header is truncated"};
        return status_;
    }
    sample_count_ = (static_cast<std::size_t>(input[0]) << 8) | input[1];
    first_st_known_ = (input[2] & UINT8_C(0x80)) != 0;
    first_st_change_on_ = input[2] & UINT8_C(0x7f);
    if ((sample_count_ == 0 && input[2] != 0) ||
        (first_st_change_on_ != 0 && first_st_change_on_ >= sample_count_)) {
        status_ = {StatusCode::kMalformedStream, "ST header is inconsistent with sample count"};
        return status_;
    }
    std::size_t bound = 0;
    if (!max_compressed_size(sample_count_, &bound).ok() || input_size > bound) {
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
        if (value_bits_ != kStaleNaN) {
            baseline_value_bits_ = value_bits_;
        }
        if (first_st_known_) {
            std::int64_t diff = 0;
            if (!read_varint(&reader, &diff)) {
                status_ = {StatusCode::kMalformedStream, "first ST is truncated or invalid"};
                return status_;
            }
            start_timestamp_ = timestamp_ - int64_bits(diff);
        }
    } else {
        const std::uint64_t previous_timestamp = timestamp_;
        if (samples_read_ == 1) {
            if (!read_uvarint(&reader, &timestamp_delta_)) {
                status_ = {StatusCode::kMalformedStream, "second timestamp delta is invalid"};
                return status_;
            }
            timestamp_ += timestamp_delta_;
            if (!read_value_general(
                    &reader, &baseline_value_bits_, &value_bits_, &leading_, &trailing_)) {
                status_ = {StatusCode::kMalformedStream, "second value is invalid"};
                return status_;
            }
        } else {
            bool bit = false;
            if (!reader.read_bit(&bit)) {
                status_ = {StatusCode::kMalformedStream, "joint control is truncated"};
                return status_;
            }
            unsigned control = 0;
            if (!bit) {
                control = 0;
            } else {
                while (control < 4) {
                    ++control;
                    if (!reader.read_bit(&bit)) {
                        status_ = {StatusCode::kMalformedStream, "joint control is truncated"};
                        return status_;
                    }
                    if (!bit) {
                        break;
                    }
                }
                if (control == 4 && bit) {
                    control = 5;
                }
            }

            if (control == 0) {
                timestamp_ += timestamp_delta_;
                value_bits_ = baseline_value_bits_;
            } else if (control == 1) {
                timestamp_ += timestamp_delta_;
                if (!read_value_known_changed(
                        &reader, &baseline_value_bits_, &value_bits_, &leading_, &trailing_)) {
                    status_ = {StatusCode::kMalformedStream, "changed value is invalid"};
                    return status_;
                }
            } else if (control == 5) {
                timestamp_ += timestamp_delta_;
                value_bits_ = kStaleNaN;
            } else {
                const unsigned width = control == 2 ? 13U : control == 3 ? 20U : 64U;
                std::int64_t dod = 0;
                if (!read_signed_width(&reader, width, &dod)) {
                    status_ = {StatusCode::kMalformedStream, "delta-of-delta is invalid"};
                    return status_;
                }
                timestamp_delta_ += int64_bits(dod);
                timestamp_ += timestamp_delta_;
                if (!read_value_general(
                        &reader, &baseline_value_bits_, &value_bits_, &leading_, &trailing_)) {
                    status_ = {StatusCode::kMalformedStream, "value delta is invalid"};
                    return status_;
                }
            }
        }

        if (first_st_change_on_ != 0 && samples_read_ >= first_st_change_on_) {
            std::int64_t decoded = 0;
            if (!read_varbit(&reader, &decoded)) {
                status_ = {StatusCode::kMalformedStream, "ST delta is invalid"};
                return status_;
            }
            if (samples_read_ == first_st_change_on_) {
                st_diff_ = int64_bits(decoded);
            } else {
                st_diff_ += int64_bits(decoded);
            }
            start_timestamp_ = previous_timestamp - st_diff_;
        }
    }

    bit_position_ = reader.bit_position();
    ++samples_read_;
    *sample = {
        bits_int64(start_timestamp_),
        bits_int64(timestamp_),
        value_bits_,
    };
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
    if (samples_read_ != 0 && target_timestamp <= bits_int64(timestamp_)) {
        *sample = {bits_int64(start_timestamp_), bits_int64(timestamp_), value_bits_};
        *has_value = true;
        return status_;
    }
    do {
        const Status result = next(sample, has_value);
        if (!result.ok() || !*has_value) {
            return result;
        }
    } while (sample->timestamp < target_timestamp);
    return status_;
}

Status decode(
    const std::uint8_t* input,
    std::size_t input_size,
    Sample* samples,
    std::size_t sample_capacity,
    std::size_t* samples_written) noexcept {
    if (samples_written == nullptr || input == nullptr ||
        (samples == nullptr && sample_capacity != 0)) {
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
    std::size_t count_written = 0;
    bool has_value = false;
    do {
        Sample current{};
        status = cursor.next(&current, &has_value);
        if (!status.ok()) {
            return status;
        }
        if (has_value) {
            samples[count_written++] = current;
        }
    } while (has_value);
    *samples_written = count_written;
    return status;
}

Status append(
    const std::uint8_t* input,
    std::size_t input_size,
    const Sample* appended_samples,
    std::size_t appended_count,
    std::uint8_t* output,
    std::size_t output_capacity,
    std::size_t* bytes_written) noexcept {
    if (bytes_written == nullptr || output == nullptr || input == nullptr ||
        (appended_samples == nullptr && appended_count != 0) ||
        input_size < kChunkHeaderSize) {
        return {StatusCode::kInvalidArgument, "invalid append argument"};
    }
    *bytes_written = 0;
    const std::size_t existing_count =
        (static_cast<std::size_t>(input[0]) << 8) | input[1];
    if (appended_count > kMaxSampleCount - existing_count) {
        return {StatusCode::kSampleLimitExceeded, "sample count exceeds uint16 chunk header"};
    }
    const std::size_t total_count = existing_count + appended_count;
    std::unique_ptr<Sample[]> combined(new (std::nothrow) Sample[total_count == 0 ? 1 : total_count]);
    if (!combined) {
        return {StatusCode::kInvalidArgument, "sample workspace allocation failed"};
    }
    std::size_t decoded = 0;
    Status status = decode(
        input, input_size, combined.get(), existing_count, &decoded);
    if (!status.ok() || decoded != existing_count) {
        return status.ok() ? Status{StatusCode::kMalformedStream, "decoded count differs"} : status;
    }
    for (std::size_t index = 0; index < appended_count; ++index) {
        combined[existing_count + index] = appended_samples[index];
    }
    return encode(
        combined.get(), total_count, output, output_capacity, bytes_written);
}

}  // namespace prometheus_xor2
