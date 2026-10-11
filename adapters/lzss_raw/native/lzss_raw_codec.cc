// Derived from alexkazik/lzss 0.9.1 (MIT), based on Haruhiko Okumura's LZSS.
// See ../LICENSE and the source provenance card for attribution.
#include "lzss_raw_codec.h"

#include <algorithm>
#include <array>
#include <cstring>

namespace tscb_lzss_raw {
namespace {

constexpr std::size_t kN = 1024;
constexpr std::size_t kN2 = 2048;
constexpr unsigned kEi = 10;
constexpr unsigned kEj = 4;
constexpr std::size_t kP = (1 + kEi + kEj) / 9;
constexpr std::size_t kF = (1U << kEj) + kP;
constexpr std::uint8_t kInitialByte = 0x20;

// Match bits.rs: append to a uint32 buffer, emit most-significant bits first,
// and flush the final partial byte with zero padding on the right.
class BitWriter {
public:
    explicit BitWriter(std::uint8_t* dst) noexcept : dst_(dst) {}

    void write(std::uint32_t data, unsigned count) noexcept {
        buffer_ = (buffer_ << count) | data;
        buffered_bits_ += count;
        while (buffered_bits_ >= 8) {
            buffered_bits_ -= 8;
            dst_[written_++] = static_cast<std::uint8_t>(buffer_ >> buffered_bits_);
        }
    }

    std::size_t finish() noexcept {
        if (buffered_bits_ != 0) {
            dst_[written_++] = static_cast<std::uint8_t>(buffer_ << (8 - buffered_bits_));
        }
        return written_;
    }

private:
    std::uint8_t* dst_;
    std::uint32_t buffer_ = 0;
    unsigned buffered_bits_ = 0;
    std::size_t written_ = 0;
};

// Match bits.rs: bytes are consumed only when the buffered bits are insufficient.
class BitReader {
public:
    BitReader(const std::uint8_t* src, std::size_t n) noexcept : src_(src), size_(n) {}

    bool read(unsigned count, std::uint32_t& data) noexcept {
        while (buffered_bits_ < count) {
            if (position_ == size_) return false;
            buffer_ = (buffer_ << 8) | src_[position_++];
            buffered_bits_ += 8;
        }
        buffered_bits_ -= count;
        data = (buffer_ >> buffered_bits_) & ((1U << count) - 1U);
        return true;
    }

    bool zero_padding_only() const noexcept {
        return position_ == size_ && buffered_bits_ <= 7
            && (buffer_ & ((1U << buffered_bits_) - 1U)) == 0;
    }

private:
    const std::uint8_t* src_;
    std::size_t size_;
    std::size_t position_ = 0;
    std::uint32_t buffer_ = 0;
    unsigned buffered_bits_ = 0;
};

}  // namespace

std::size_t encode(const std::uint8_t* src, std::size_t n,
                   std::uint8_t* dst) noexcept {
    std::array<std::uint8_t, kN2> buffer;
    buffer.fill(kInitialByte);
    BitWriter writer(dst);

    std::size_t consumed = std::min(n, kN2 - (kN - kF));
    if (consumed != 0) std::memcpy(buffer.data() + kN - kF, src, consumed);
    std::size_t buffer_end = kN - kF + consumed;
    std::size_t r = kN - kF;
    std::size_t s = 0;

    while (r < buffer_end) {
        const std::size_t f1 = std::min(kF, buffer_end - r);
        std::size_t x = 0;
        std::size_t y = 1;
        const std::uint8_t c = buffer[r];
        // search_loop! reverses s..r. Strict improvement preserves the nearest
        // position when several candidates have the same match length.
        for (std::size_t i = r; i-- > s;) {
            if (buffer[i] != c) continue;
            std::size_t j = 1;
            while (j < f1 && buffer[i + j] == buffer[r + j]) ++j;
            if (j > y) {
                x = i;
                y = j;
                // No later candidate can improve a full lookahead match; all
                // equal matches would be ignored by the Rust strict comparison.
                if (y == f1) break;
            }
        }
        if (y <= kP) {
            writer.write(0x100U | c, 9);
            y = 1;
        } else {
            writer.write((static_cast<std::uint32_t>(x & (kN - 1)) << kEj)
                             | static_cast<std::uint32_t>(y - (kP + 1)),
                         1 + kEi + kEj);
        }
        r += y;
        s += y;
        if (r >= kN2 - kF) {
            // Rust copy_within(N..N2, 0) preserves both history and lookahead.
            std::memcpy(buffer.data(), buffer.data() + kN, kN);
            buffer_end -= kN;
            r -= kN;
            s -= kN;
            const std::size_t refill = std::min(n - consumed, kN2 - buffer_end);
            if (refill != 0) {
                std::memcpy(buffer.data() + buffer_end, src + consumed, refill);
            }
            consumed += refill;
            buffer_end += refill;
        }
    }
    return writer.finish();
}

bool strict_stream(const std::uint8_t* src, std::size_t n,
                   std::size_t expected) noexcept {
    if (n != 0 && src == nullptr) return false;
    BitReader reader(src, n);
    std::size_t produced = 0;
    while (produced < expected) {
        std::uint32_t token;
        if (!reader.read(9, token)) return false;
        if ((token & 0x100U) != 0) {
            ++produced;
        } else {
            std::uint32_t suffix;
            if (!reader.read(kEi + kEj - 8, suffix)) return false;
            token = (token << (kEi + kEj - 8)) | suffix;
            const std::size_t count = (token & ((1U << kEj) - 1U)) + kP + 1;
            if (count > expected - produced) return false;
            produced += count;
        }
    }
    return reader.zero_padding_only();
}

void decode(const std::uint8_t* src, std::size_t n, std::uint8_t* dst,
            std::size_t expected) noexcept {
    std::array<std::uint8_t, kN> buffer;
    buffer.fill(kInitialByte);
    BitReader reader(src, n);
    std::size_t r = kN - kF;
    std::size_t produced = 0;
    while (produced < expected) {
        std::uint32_t token;
        // These reads cannot fail after strict_stream validated exact coverage.
        if (!reader.read(9, token)) return;
        if ((token & 0x100U) != 0) {
            const std::uint8_t value = static_cast<std::uint8_t>(token);
            dst[produced++] = value;
            buffer[r] = value;
            r = (r + 1) & (kN - 1);
        } else {
            std::uint32_t suffix;
            if (!reader.read(kEi + kEj - 8, suffix)) return;
            token = (token << (kEi + kEj - 8)) | suffix;
            const std::size_t i = token >> kEj;
            const std::size_t count = (token & ((1U << kEj) - 1U)) + kP + 1;
            for (std::size_t k = 0; k < count; ++k) {
                const std::uint8_t value = buffer[(i + k) & (kN - 1)];
                dst[produced++] = value;
                buffer[r] = value;
                r = (r + 1) & (kN - 1);
            }
        }
    }
}

}  // namespace tscb_lzss_raw
