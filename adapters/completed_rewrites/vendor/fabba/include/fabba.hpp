#ifndef TSCB_FABBA_HPP
#define TSCB_FABBA_HPP

#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace fabba {

struct Config {
  double tolerance = 0.1;
  double alpha = 0.1;
  double scl = 1.0;
  std::uint64_t max_len = std::numeric_limits<std::uint64_t>::max();
  std::uint32_t partition = 0;
  std::uint32_t threads = 1;
};

struct Piece {
  double length = 0.0;
  double increment = 0.0;
  double error = 0.0;
};

struct ParallelExecutionInfo {
  std::size_t partitions_requested = 0;
  std::size_t partitions_used = 0;
  std::size_t threads_requested = 0;
  std::size_t threads_used = 0;
  std::size_t samples_per_partition = 0;
  std::size_t samples_consumed = 0;
  std::size_t samples_discarded = 0;
};

struct Center {
  double length = 0.0;
  double increment = 0.0;
};

struct Digitized {
  double length_std = 1.0;
  double increment_std = 1.0;
  std::vector<std::size_t> sorted_indices;
  std::vector<std::size_t> starting_points;
  std::vector<int> raw_labels;
  std::vector<Center> raw_centers;
  std::vector<std::uint16_t> symbols;
  std::vector<Center> centers;
};

struct TransformResult {
  std::vector<Piece> pieces;
  Digitized digitized;
  std::vector<Center> quantized_pieces;
  std::vector<double> reconstructed;
};

struct Accounting {
  std::uint64_t header_bits = 0;
  std::uint64_t codebook_bits = 0;
  std::uint64_t symbol_stream_bits = 0;
  std::uint64_t checksum_bits = 0;
  std::uint64_t serialized_bits = 0;
  std::uint64_t external_side_information_bits = 0;
  std::uint64_t final_bits = 0;
};

std::vector<Piece> compress(const double* values, std::size_t count,
                            const Config& config = Config{});
std::vector<std::vector<Piece>> parallel_compress(
    const double* values, std::size_t count, const Config& config = Config{},
    ParallelExecutionInfo* execution_info = nullptr);
Digitized digitize(const std::vector<Piece>& pieces,
                   const Config& config = Config{});
std::vector<Center> quantize(const std::vector<Center>& pieces);
std::vector<double> reconstruct(double first_value,
                                const std::vector<Center>& pieces,
                                std::size_t original_sample_count);
TransformResult transform(const double* values, std::size_t count,
                          const Config& config = Config{});

std::vector<std::uint8_t> encode(const double* values, std::size_t count,
                                 const Config& config = Config{},
                                 Accounting* accounting = nullptr);
std::vector<double> decode(const std::uint8_t* encoded, std::size_t size,
                           Accounting* accounting = nullptr);
Accounting inspect_accounting(const std::uint8_t* encoded, std::size_t size);
std::size_t max_encoded_size(std::size_t sample_count);

}  // namespace fabba

#endif
