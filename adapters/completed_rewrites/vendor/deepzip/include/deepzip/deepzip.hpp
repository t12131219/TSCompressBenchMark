#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace deepzip {
using Bytes = std::vector<std::uint8_t>;
enum class Status { invalid_parameter, invalid_model, resource_limit,
                    insufficient_capacity, corrupt_stream, unsupported, device_failure };
class Error : public std::runtime_error {
public:
    Error(Status s, const std::string& message) : std::runtime_error(message), status(s) {}
    Status status;
};
enum class Backend : std::uint32_t { scalar = 0, cuda = 1 };
struct Limits {
    std::size_t max_input_bytes = 16 * 1024 * 1024;
    std::size_t max_model_bytes = 64 * 1024 * 1024;
    std::uint32_t max_lanes = 4096;
};
struct ModelData;
class Model {
public:
    static Model load(const Bytes& portable, const Limits& limits = {});
    static Model from_hdf5(const std::string& path, const std::string& name,
                           const Limits& limits = {});
    const Bytes& serialize() const;
    const std::string& name() const;
    std::uint32_t alphabet_size() const;
    bool half_precision() const;
    // Row-major [batch,64] IDs -> [batch,alphabet] probabilities.
    std::vector<float> predict(const std::vector<std::uint32_t>& contexts,
                               Backend backend = Backend::scalar) const;
private:
    explicit Model(std::shared_ptr<const ModelData> data) : data_(std::move(data)) {}
    std::shared_ptr<const ModelData> data_;
};
struct Config {
    std::uint32_t lanes = 1000;
    std::vector<std::uint8_t> alphabet;
    Backend backend = Backend::scalar;
    Limits limits;
};
struct Ledger {
    std::uint64_t metadata_bits = 0, model_bits = 0, lengths_bits = 0;
    std::uint64_t entropy_bits = 0, padding_bits = 0, checksum_bits = 0;
    std::uint64_t final_bits() const;
};
struct Encoded { Bytes bytes; Ledger ledger; Backend backend; };
const char* version() noexcept;
bool cuda_available() noexcept;
std::vector<std::string> supported_models();
// Conversion is exposed for independent differential testing.
std::vector<std::uint64_t> cumulative(const std::vector<float>& probabilities);
std::vector<std::uint64_t> uniform_cumulative(std::uint32_t alphabet);
Bytes encode_arithmetic(const Bytes& symbols,
    const std::vector<std::vector<std::uint64_t>>& cumulative_tables);
Bytes decode_arithmetic(const Bytes& stream,
    const std::vector<std::vector<std::uint64_t>>& cumulative_tables);
Encoded compress(const Model& model, const Bytes& input, const Config& config);
Bytes decompress(const Bytes& stream, const Limits& limits = {});
std::size_t compress_bound(const Model& model, std::size_t length, const Config& config);
std::size_t compress_to(const Model& model, const Bytes& input, const Config& config,
                        std::uint8_t* output, std::size_t capacity);
class Codec {
public:
    Codec(Model model, Config config);
    void append(const std::uint8_t* input, std::size_t length);
    const Encoded& finalize();
    void reset() noexcept;
    std::size_t buffered_bytes() const noexcept;
private:
    Model model_;
    Config config_;
    Bytes input_;
    std::unique_ptr<Encoded> encoded_;
};
}  // namespace deepzip
