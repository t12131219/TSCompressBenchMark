#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace self_star {
inline constexpr unsigned api_version = 1;
inline constexpr const char* implementation_id = "self-star-canonical-cpp-v1";
using Bytes = std::vector<std::uint8_t>;
enum class Width : unsigned { binary32=32, binary64=64 };
struct Encoded { Bytes bytes; std::uint64_t final_bits=0, meaningful_bits=0; };
struct Decoded { Bytes values; std::uint64_t count=0, consumed_bits=0; };
// Each finish/decode_block advances the session to its next block, preserving
// adaptive tables, Huffman frequencies and saved XOR window. reset starts fresh.
class Encoder {
public:
    explicit Encoder(Width width, bool lossless=true);
    ~Encoder();
    Encoder(Encoder&&) noexcept;
    Encoder& operator=(Encoder&&) noexcept;
    Encoder(const Encoder&)=delete;
    Encoder& operator=(const Encoder&)=delete;
    void append(const std::uint8_t* little_endian_values, std::size_t count);
    Encoded finish_block();
    // Binary64 only; includes the source transport's reserved zero byte.
    // last=true closes the block and advances the session.
    Encoded fragment(std::uint64_t little_endian_value_bits, bool last);
    void reset();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
class Decoder {
public:
    explicit Decoder(Width width);
    ~Decoder();
    Decoder(Decoder&&) noexcept;
    Decoder& operator=(Decoder&&) noexcept;
    Decoder(const Decoder&)=delete;
    Decoder& operator=(const Decoder&)=delete;
    Decoded decode_block(const std::uint8_t* bytes, std::size_t size);
    // Includes reserved byte, which this wrapper strips before decoding.
    Decoded fragment(const std::uint8_t* bytes, std::size_t size, bool last);
    void reset();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
struct Session { Width width=Width::binary64; bool network=false; std::vector<Bytes> blocks; };
std::size_t compress_bound(const Session& session);
Encoded compress(const Session& session);
Session decompress(const std::uint8_t* bytes, std::size_t size);
bool compress_into(const Session& session, std::uint8_t* output, std::size_t capacity, std::size_t& written);
bool decompress_into(const std::uint8_t* bytes, std::size_t size, std::uint8_t* output, std::size_t capacity, std::size_t& written);
} // namespace self_star
