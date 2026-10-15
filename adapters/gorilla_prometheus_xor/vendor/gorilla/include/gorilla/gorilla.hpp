// SPDX-License-Identifier: Apache-2.0 AND BSD-2-Clause
// Derived from Prometheus xor.go and Damian Gryski go-tsz; see LICENSES/.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace gorilla {
inline constexpr std::uint32_t api_version = 1;
inline constexpr std::size_t max_samples = 65535;
enum class Path { Canonical, Optimized };
enum class InputStorage { Snapshot, Borrowed };
enum class Code { InvalidArgument, Capacity, Malformed, Limit, State, Unsupported };
class Error : public std::runtime_error {
public:
    Error(Code code, const char* message) : std::runtime_error(message), code_(code) {}
    Code code() const noexcept { return code_; }
private:
    Code code_;
};
struct Sample {
    std::int64_t timestamp;
    std::uint64_t value_bits;
};
std::uint64_t double_bits(double value) noexcept;
double bits_double(std::uint64_t bits) noexcept;
std::int64_t signed_bits(std::uint64_t bits) noexcept;
std::size_t compress_bound(std::size_t count);
const char* path_name(Path path) noexcept;
struct ExecutionStats {
    std::uint64_t canonical_bit_ops = 0;
    std::uint64_t optimized_fields = 0;
    std::uint64_t repeated_pair_shortcuts = 0;
};
struct Accounting {
    std::uint64_t metadata_bits = 16;
    std::uint64_t timestamp_bits = 0;
    std::uint64_t value_bits = 0;
    std::uint64_t padding_bits = 0;
    std::uint64_t external_bits = 0;
    std::uint64_t serialized_bits = 16;
    std::uint64_t final_bits = 16;
};

// Owns raw bytes and bounded predictor state. Same writer requires caller locking.
class Encoder {
public:
    explicit Encoder(Path path = Path::Canonical);
    void reset();
    // Mirrors source Reset(raw), including its documented partial-byte resume defect.
    void reset(const std::uint8_t* data, std::size_t size);
    // Transfers a vector without copying its raw payload; validation precedes transfer.
    void reset_owned(std::vector<std::uint8_t>&& raw);
    void append(Sample sample);
    void reacquire();
    void compact();
    // Flush does not seal; Bytes view is invalidated by mutation. Snapshot by copying.
    const std::vector<std::uint8_t>& flush() const noexcept { return bytes_; }
    const std::vector<std::uint8_t>& finalize() noexcept;
    std::size_t count() const noexcept { return count_; }
    Path path() const noexcept { return path_; }
    Accounting accounting() const noexcept;
    std::array<std::uint64_t, 5> trace() const noexcept;
    ExecutionStats execution_stats() const noexcept { return stats_; }
private:
    void put(std::uint64_t value, unsigned width);
    void put_varint(std::uint64_t value);
    void put_value(std::uint64_t value);
    ExecutionStats stats_;
    Path path_;
    std::vector<std::uint8_t> bytes_;
    std::size_t position_ = 16;
    std::size_t count_ = 0;
    std::uint64_t timestamp_ = 0, value_ = 0, delta_ = 0;
    unsigned leading_ = 255, trailing_ = 0;
    std::uint64_t timestamp_bits_ = 0, value_bits_ = 0;
    bool sealed_ = false;
};

// Owns an immutable snapshot. No overread; byte input supports any alignment.
class Iterator {
public:
    Iterator(const std::uint8_t* data, std::size_t size,
             Path path = Path::Canonical, bool strict = true,
             InputStorage storage = InputStorage::Snapshot);
    Iterator(const Iterator&) = delete;
    Iterator& operator=(const Iterator&) = delete;
    // Borrowed storage requires valid, stable backing memory until reset/destruction.
    const std::uint8_t* input_data() const noexcept { return data_; }
    InputStorage input_storage() const noexcept { return storage_; }
    void reset(const std::uint8_t* data, std::size_t size);
    bool next();
    bool seek(std::int64_t timestamp);
    Sample at() const;
    std::int64_t at_timestamp() const { return at().timestamp; }
    std::int64_t at_start_timestamp() const noexcept { return 0; }
    std::size_t count() const noexcept { return total_; }
    std::size_t consumed_bits() const noexcept { return position_; }
    // Available after successful exhaustion; premature query throws State.
    Accounting accounting() const;
    std::array<std::uint64_t, 5> trace() const noexcept;
    ExecutionStats execution_stats() const noexcept { return stats_; }
private:
    friend class Encoder;
    std::uint64_t get(unsigned width);
    std::uint64_t get_varint();
    void get_value();
    void check_tail();
    ExecutionStats stats_;
    Path path_;
    InputStorage storage_;
    const std::uint8_t* data_ = nullptr;
    std::size_t raw_size_ = 0;
    std::uint8_t last_ = 0;
    bool strict_, failed_ = false;
    std::vector<std::uint8_t> bytes_;
    std::size_t position_ = 16, total_ = 0, read_ = 0;
    std::uint64_t timestamp_ = 0, value_ = 0, delta_ = 0;
    unsigned leading_ = 0, trailing_ = 0;
    std::uint64_t timestamp_bits_ = 0, value_bits_ = 0;
};

// One-shot buffers: require natural Sample alignment, valid extents and no overlap.
// Short capacity or malformed input throws before modifying caller output.
std::size_t compress(const Sample* input, std::size_t count,
                     std::uint8_t* output, std::size_t capacity,
                     Path path = Path::Canonical);
std::size_t decompress(const std::uint8_t* input, std::size_t size,
                       Sample* output, std::size_t capacity,
                       Path path = Path::Canonical, bool strict = true);
std::vector<std::uint8_t> encode(const Sample* input, std::size_t count,
                                 Path path = Path::Canonical);
std::vector<Sample> decode(const std::uint8_t* input, std::size_t size,
                          Path path = Path::Canonical, bool strict = true);
} // namespace gorilla
