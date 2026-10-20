#ifndef TSCB_LZSS_RAW_CODEC_H
#define TSCB_LZSS_RAW_CODEC_H

#include <cstddef>
#include <cstdint>

// C++ translation of alexkazik/lzss 0.9.1's Lzss<10, 4, 0x20, 1024, 2048>.
// This raw format contains no decoded length, framing, or checksum.
namespace tscb_lzss_raw {

// The caller provides disjoint valid buffers and at least n + ceil(n / 8)
// output bytes. Empty input produces an empty stream. No allocation is used.
std::size_t encode(const std::uint8_t* src, std::size_t n,
                   std::uint8_t* dst) noexcept;

// Require exactly expected output bytes, no partial/trailing tokens, and at
// most seven zero padding bits. Validation does not touch the output buffer.
bool strict_stream(const std::uint8_t* src, std::size_t n,
                   std::size_t expected) noexcept;

// The caller must first validate strict_stream(src, n, expected), and provide
// disjoint valid buffers and expected output bytes. References are copied one
// byte at a time so overlapping matches observe the updated ring dictionary.
void decode(const std::uint8_t* src, std::size_t n, std::uint8_t* dst,
            std::size_t expected) noexcept;

// Direct benchmark decoder: combine token validation and restoration in one
// pass. No separate whole-stream pre-scan is part of its decode measurement.
bool decode_checked(const std::uint8_t* src, std::size_t n, std::uint8_t* dst,
                    std::size_t expected) noexcept;

}  // namespace tscb_lzss_raw

#endif
