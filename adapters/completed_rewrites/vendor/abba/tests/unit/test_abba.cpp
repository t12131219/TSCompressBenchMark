#include "abba.hpp"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <vector>

namespace {

void require(const bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

bool close(const double left, const double right) {
  return std::abs(left - right) <= 1e-10 + 1e-12 * std::abs(left);
}

template <typename Function>
void require_throws(Function function, const char* message) {
  try {
    function();
  } catch (const std::exception&) {
    return;
  }
  throw std::runtime_error(message);
}

void test_upstream_examples() {
  const std::vector<double> input = {0, 2, 3, 2, 4, -1, 0, -1, 1, 0, -4, 0};
  abba::Config config;
  config.compression_tolerance = 2.0;
  config.digitization_tolerance = 0.1;
  config.min_k = 2;
  const auto pieces = abba::compress(input.data(), input.size(), config);
  const std::vector<abba::Piece> expected = {
      {4, 4, 3}, {1, -5, 0}, {4, 1, 38.0 / 16.0},
      {1, -4, 0}, {1, 4, 0}};
  require(pieces.size() == expected.size(), "compression piece count");
  for (std::size_t i = 0; i < pieces.size(); ++i) {
    require(close(pieces[i].length, expected[i].length), "compression length");
    require(close(pieces[i].increment, expected[i].increment), "compression increment");
    require(close(pieces[i].error, expected[i].error), "compression error");
  }
  const auto digitized = abba::digitize(pieces, input.size(), config);
  const std::vector<std::uint16_t> symbols = {0, 1, 0, 1, 0};
  require(digitized.symbols == symbols, "upstream scl0 symbols");
  require(digitized.centers.size() == 2, "upstream scl0 center count");
  require(close(digitized.centers[0].length, 3.0) &&
              close(digitized.centers[0].increment, 3.0),
          "upstream first center");
  require(close(digitized.centers[1].length, 1.0) &&
              close(digitized.centers[1].increment, -4.5),
          "upstream second center");
}

void test_quantization() {
  std::vector<abba::Center> pieces(8, {1.5, 1.0});
  const auto quantized = abba::quantize(pieces);
  const std::vector<double> expected = {2, 1, 2, 1, 2, 1, 2, 1};
  for (std::size_t i = 0; i < expected.size(); ++i) {
    require(quantized[i].length == expected[i], "ties-to-even quantization");
  }
}

void test_container_and_malformed() {
  std::vector<double> input(129);
  for (std::size_t i = 0; i < input.size(); ++i) {
    input[i] = std::sin(static_cast<double>(i) * 0.13) +
               static_cast<double>(i % 7) * 0.01;
  }
  const auto expected = abba::transform(input.data(), input.size());
  abba::Accounting accounting;
  const auto encoded = abba::encode(input.data(), input.size(), {}, &accounting);
  const auto decoded = abba::decode(encoded.data(), encoded.size());
  require(decoded.size() == input.size(), "container decoded length");
  for (std::size_t i = 0; i < decoded.size(); ++i) {
    require(close(decoded[i], expected.reconstructed[i]), "container reconstruction");
  }
  require(accounting.header_bits + accounting.codebook_bits +
              accounting.symbol_stream_bits + accounting.checksum_bits ==
              accounting.final_bits,
          "accounting closure");
  require(accounting.serialized_bits == encoded.size() * 8U,
          "serialized bit count");
  require(abba::max_encoded_size(input.size()) >= encoded.size(),
          "maximum encoded size");

  for (std::size_t i = 0; i < encoded.size(); ++i) {
    auto corrupt = encoded;
    corrupt[i] ^= 0x01U;
    require_throws([&] { (void)abba::decode(corrupt.data(), corrupt.size()); },
                   "single-byte corruption accepted");
  }
  require_throws([&] { (void)abba::decode(encoded.data(), encoded.size() - 1); },
                 "truncated container accepted");
}

void test_validation_and_properties() {
  const double singleton = 1.0;
  require_throws([&] { (void)abba::encode(&singleton, 1); },
                 "singleton input accepted");
  const double invalid[] = {0.0, std::numeric_limits<double>::quiet_NaN()};
  require_throws([&] { (void)abba::encode(invalid, 2); },
                 "NaN input accepted");
  abba::Config bad;
  bad.min_k = 0;
  const double valid[] = {0.0, 1.0};
  require_throws([&] { (void)abba::encode(valid, 2, bad); },
                 "invalid config accepted");

  std::mt19937_64 generator(20260928U);
  std::uniform_real_distribution<double> delta(-1.0, 1.0);
  for (std::size_t trial = 0; trial < 256; ++trial) {
    const std::size_t count = 2 + (trial * 29U) % 257U;
    std::vector<double> input(count);
    for (std::size_t i = 1; i < count; ++i) {
      input[i] = input[i - 1] + delta(generator);
    }
    abba::Config config;
    config.compression_tolerance = static_cast<double>(trial % 5U) * 0.05;
    config.digitization_tolerance = static_cast<double>(trial % 7U) * 0.04;
    config.max_k = 1U + static_cast<std::uint32_t>(trial % 32U);
    config.max_len = trial % 3U == 0 ? 5U :
        std::numeric_limits<std::uint64_t>::max();
    const auto transformed = abba::transform(input.data(), input.size(), config);
    double length_sum = 0.0;
    for (const auto& piece : transformed.pieces) {
      length_sum += piece.length;
    }
    require(length_sum + 1.0 == static_cast<double>(count),
            "piece length invariant");
    const auto encoded = abba::encode(input.data(), input.size(), config);
    const auto decoded = abba::decode(encoded.data(), encoded.size());
    require(decoded.size() == transformed.reconstructed.size(),
            "property decoded length");
    for (std::size_t i = 0; i < decoded.size(); ++i) {
      require(close(decoded[i], transformed.reconstructed[i]),
              "property reconstruction");
    }
  }
}

void test_alternate_clustering_paths() {
  std::vector<double> input(96);
  for (std::size_t i = 0; i < input.size(); ++i) {
    input[i] = std::sin(static_cast<double>(i) * 0.17) +
               static_cast<double>(i % 5U) * 0.03;
  }
  for (const auto method : {abba::Config::ClusteringMethod::Kmeans,
                            abba::Config::ClusteringMethod::Incremental}) {
    for (const double scl : {0.0, 1.0, std::numeric_limits<double>::infinity()}) {
      abba::Config config;
      config.clustering = method;
      config.scl = scl;
      config.norm = 1U;
      config.min_k = 1U;
      config.max_k = 8U;
      const auto transformed = abba::transform(input.data(), input.size(), config);
      require(transformed.reconstructed.size() == input.size(),
              "alternate ABBA reconstruction length");
      const auto encoded = abba::encode(input.data(), input.size(), config);
      const auto decoded = abba::decode(encoded.data(), encoded.size());
      require(decoded.size() == input.size(), "alternate ABBA container length");
    }
  }
}

}  // namespace

int main() {
  try {
    test_upstream_examples();
    test_quantization();
    test_container_and_malformed();
    test_validation_and_properties();
    test_alternate_clustering_paths();
    std::cout << "ABBA unit tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
