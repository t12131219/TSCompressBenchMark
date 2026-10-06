#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace elf_plus {
inline constexpr unsigned api_version = 1;
inline constexpr const char* implementation_id = "elf-plus-canonical-cpp-v1";
using Bytes = std::vector<std::uint8_t>;
enum class Width : unsigned { binary32=32, binary64=64 };
struct Encoded { Bytes bytes; std::uint64_t final_bits=0, payload_bits=0, data_bits=0; };
struct Decoded { Bytes values; Width width; std::uint64_t count=0, consumed_bits=0; };
std::size_t compress_bound(std::size_t count, Width width);
// Raw format compatibility includes the source's NaN-as-END behavior.
Encoded encode_raw(const std::uint8_t* values, std::size_t count, Width width);
Decoded decode_raw(const std::uint8_t* bytes, std::size_t size, Width width);
Encoded compress(const std::uint8_t* values, std::size_t count, Width width);
Decoded decompress(const std::uint8_t* bytes, std::size_t size);
bool compress_into(const std::uint8_t* values, std::size_t count, Width width,
                   std::uint8_t* output, std::size_t capacity, std::size_t& written);
bool decompress_into(const std::uint8_t* bytes, std::size_t size,
                     std::uint8_t* output, std::size_t capacity, std::size_t& written);
class Encoder {
public:
    explicit Encoder(Width width);
    ~Encoder();
    Encoder(Encoder&&) noexcept;
    Encoder& operator=(Encoder&&) noexcept;
    Encoder(const Encoder&)=delete;
    Encoder& operator=(const Encoder&)=delete;
    void append(const std::uint8_t* values, std::size_t count);
    Encoded finalize();
    void reset();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace elf_plus
