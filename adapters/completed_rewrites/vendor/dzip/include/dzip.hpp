#pragma once
#include "dzip_nn.hpp"
#include <cstddef>
#include <cstdint>
#include <vector>
#include <optional>

namespace dzip {
enum class Mode : std::uint8_t { bootstrap=0, combined=1 };
struct Limits {
    std::size_t max_symbols=16u*1024u*1024u;
    std::size_t max_model_bytes=512u*1024u*1024u;
    std::size_t max_frame_bytes=600u*1024u*1024u;
};
struct Statistics {
    std::uint64_t final_bits=0,metadata_bits=0,model_bits=0,payload_bits=0,checksum_bits=0;
};
struct Encoded { Bytes bytes;Statistics statistics; };
Encoded compress(const Bytes& input,const Network& initial,Mode mode,const Limits& limits={});
Bytes decompress(const Bytes& frame,const Limits& limits={});
std::size_t compress_bound(std::size_t symbols,const Network& initial,const Limits& limits={});
bool compress_to(const Bytes& input,const Network& initial,Mode mode,std::uint8_t* output,
                 std::size_t capacity,std::size_t& required,const Limits& limits={});
std::size_t decompressed_size(const Bytes& frame,const Limits& limits={});
bool decompress_to(const Bytes& frame,std::uint8_t* output,std::size_t capacity,
                   std::size_t& required,const Limits& limits={});
class Encoder {
public:
    Encoder(Network initial,Mode mode,Limits limits={});
    void append(const std::uint8_t* input,std::size_t bytes);
    const Encoded& finalize();
    void reset();
    std::size_t size() const noexcept;
private:
    Network initial_;
    Mode mode_;
    Limits limits_;
    Bytes input_;
    std::optional<Encoded> finalized_;
};
// Original raw arithmetic payload. Length/alphabet/model are external arguments;
// callers account for them explicitly or use the self-contained frame above.
Bytes encode_raw(const std::vector<std::int32_t>& symbols,Network initial,Mode mode);
std::vector<std::int32_t> decode_raw(const Bytes& payload,std::size_t length,Network initial,Mode mode);
const char* version() noexcept;
}  // namespace dzip
