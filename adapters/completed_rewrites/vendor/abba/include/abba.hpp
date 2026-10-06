#ifndef TSCB_ABBA_HPP
#define TSCB_ABBA_HPP

#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace abba {

struct Config {
  double compression_tolerance = 0.1;
  double digitization_tolerance = 0.1;
  std::uint32_t min_k = 1;
  std::uint32_t max_k = 100;
  std::uint64_t max_len = std::numeric_limits<std::uint64_t>::max();
  double scl = 0.0;
  std::uint8_t norm = 2;
  enum class ClusteringMethod : std::uint8_t { Kmeans = 0, Incremental = 1 };
  ClusteringMethod clustering = ClusteringMethod::Kmeans;
  bool weighted = false;
  bool symmetric = true;
};

struct Piece {
  double length = 0.0;
  double increment = 0.0;
  double error = 0.0;
};

struct Center {
  double length = 0.0;
  double increment = 0.0;
};

struct Digitized {
  double variance_bound = 0.0;
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
                            const Config& config);
Digitized digitize(const std::vector<Piece>& pieces,
                   std::size_t original_sample_count, const Config& config);
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

}  // namespace abba

#endif
