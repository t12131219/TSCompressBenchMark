#pragma once
#include "deepzip/deepzip.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>

namespace deepzip {
struct Tensor { std::vector<std::uint32_t> shape; std::vector<float> data; };
struct Layer {
    std::uint32_t kind, flags, activation;
    float epsilon;
    std::vector<Tensor> tensors;
};
struct ModelData {
    std::string name;
    std::vector<Layer> layers;
    Bytes portable;
    std::uint32_t alphabet;
    bool half;
};
inline void require(bool ok, Status s, const char* message) {
    if (!ok) throw Error(s, message);
}
inline std::size_t checked_add(std::size_t a, std::size_t b) {
    require(a <= std::numeric_limits<std::size_t>::max() - b,
            Status::resource_limit, "size addition overflow");
    return a + b;
}
inline std::size_t checked_mul(std::size_t a, std::size_t b) {
    require(b == 0 || a <= std::numeric_limits<std::size_t>::max() / b,
            Status::resource_limit, "size multiplication overflow");
    return a * b;
}
inline void put(Bytes& b, std::uint64_t v, unsigned n) {
    for (unsigned i = 0; i < n; ++i) b.push_back(static_cast<std::uint8_t>(v >> (8*i)));
}
struct Reader {
    const Bytes& bytes;
    std::size_t pos = 0;
    std::uint64_t get(unsigned n) {
        require(n <= 8 && n <= bytes.size() - pos, Status::corrupt_stream, "truncated integer");
        std::uint64_t v = 0;
        for (unsigned i=0; i<n; ++i) v |= static_cast<std::uint64_t>(bytes[pos++]) << (8*i);
        return v;
    }
    Bytes take(std::size_t n) {
        require(n <= bytes.size() - pos, Status::corrupt_stream, "truncated byte array");
        Bytes b(bytes.begin() + static_cast<std::ptrdiff_t>(pos),
                bytes.begin() + static_cast<std::ptrdiff_t>(pos+n));
        pos += n;
        return b;
    }
};
inline float read_float(Reader& r) {
    std::uint32_t v = static_cast<std::uint32_t>(r.get(4));
    float f;
    std::memcpy(&f, &v, 4);
    return f;
}
inline void put_float(Bytes& b, float f) {
    std::uint32_t v;
    std::memcpy(&v, &f, 4);
    put(b, v, 4);
}
float round_half(float value);
std::vector<float> predict_scalar(const ModelData&, const std::vector<std::uint32_t>&);
std::vector<float> predict_cuda(const ModelData&, const std::vector<std::uint32_t>&);
Bytes serialize_model(const std::string&, const std::vector<Layer>&);
std::vector<Layer> profile_layers(const std::string&, std::uint32_t alphabet);
std::uint32_t crc32(const std::uint8_t*, std::size_t);
}  // namespace deepzip
