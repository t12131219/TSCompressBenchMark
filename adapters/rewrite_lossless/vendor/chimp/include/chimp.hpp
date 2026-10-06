#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace chimp {
inline constexpr unsigned api_version = 1;
inline constexpr const char* implementation_id = "chimp-canonical-cpp-v1";
using Bytes=std::vector<std::uint8_t>;
enum class Width : unsigned { binary32=32, binary64=64 };
enum class Variant : unsigned { chimp=1, chimp128=128 };
constexpr std::size_t max_count=16777216;
struct Encoded { Bytes bytes; std::uint64_t final_bits=0, meaningful_bits=0; };
struct Decoded { Bytes values; Width width=Width::binary64; Variant variant=Variant::chimp; std::uint64_t count=0, consumed_bits=0; };
std::size_t compress_bound(std::size_t count,Width width,Variant variant);
Encoded encode_raw(const std::uint8_t*,std::size_t count,Width,Variant);
Decoded decode_raw(const std::uint8_t*,std::size_t size,Width,Variant);
Encoded compress(const std::uint8_t*,std::size_t count,Width,Variant);
Decoded decompress(const std::uint8_t*,std::size_t size);
bool compress_into(const std::uint8_t*,std::size_t count,Width,Variant,std::uint8_t*,std::size_t capacity,std::size_t& written);
bool decompress_into(const std::uint8_t*,std::size_t size,std::uint8_t*,std::size_t capacity,std::size_t& written);
class Encoder {
public:
    Encoder(Width,Variant);
    ~Encoder();
    Encoder(Encoder&&) noexcept;
    Encoder& operator=(Encoder&&) noexcept;
    void append(const std::uint8_t*,std::size_t count);
    Encoded finalize();
    void reset();
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
class Decoder {
public:
    Decoder(const std::uint8_t*,std::size_t size,Width,Variant);
    ~Decoder();
    Decoder(Decoder&&) noexcept;
    Decoder& operator=(Decoder&&) noexcept;
    bool next(std::uint64_t& value_bits);
    void reset();
    std::uint64_t consumed_bits() const;
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
