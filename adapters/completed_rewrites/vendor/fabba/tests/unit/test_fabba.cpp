#include "fabba.hpp"

#include <cmath>
#include <cstdint>
#include <future>
#include <limits>
#include <random>
#include <stdexcept>
#include <vector>

namespace {

void require(const bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

bool close(const double left, const double right) {
  return std::abs(left - right) <= 1e-10 + 1e-12 * std::abs(left);
}

template <typename Function>
void require_throws(Function function, const char* message) {
  try { function(); } catch (const std::exception&) { return; }
  throw std::runtime_error(message);
}

void test_stages() {
  const double input[] = {0, 1, 4, 9};
  fabba::Config config;
  config.tolerance = 0.0;
  config.alpha = 0.0;
  const auto pieces = fabba::compress(input, 4, config);
  require(pieces.size() == 3, "segmentation count");
  for (std::size_t i = 0; i < pieces.size(); ++i) {
    require(pieces[i].length == 1.0, "segmentation length");
    require(pieces[i].increment == static_cast<double>(2U * i + 1U),
            "segmentation increment");
  }
  const std::vector<fabba::Piece> tied = {
      {1, 1, 0}, {1, -1, 0}, {2, 2, 0}, {2, -2, 0}};
  const auto digitized = fabba::digitize(tied, config);
  const std::vector<std::size_t> expected_order = {0, 1, 2, 3};
  require(digitized.sorted_indices == expected_order, "stable norm tie order");
  require(digitized.starting_points == expected_order, "starting point order");
  const std::vector<std::uint16_t> expected_symbols = {0, 1, 2, 3};
  require(digitized.symbols == expected_symbols, "cluster labels");
}

void test_quantization() {
  std::vector<fabba::Center> pieces(8, {1.5, 1.0});
  const auto quantized = fabba::quantize(pieces);
  const std::vector<double> expected = {2, 1, 2, 1, 2, 1, 2, 1};
  for (std::size_t i = 0; i < expected.size(); ++i) {
    require(quantized[i].length == expected[i], "nearest-even correction carry");
  }
}

void test_container() {
  std::vector<double> input(129);
  for (std::size_t i = 0; i < input.size(); ++i) {
    input[i] = std::sin(static_cast<double>(i) * 0.13) +
               static_cast<double>(i % 7U) * 0.01;
  }
  const auto expected = fabba::transform(input.data(), input.size());
  fabba::Accounting accounting;
  const auto encoded = fabba::encode(input.data(), input.size(), {}, &accounting);
  const auto decoded = fabba::decode(encoded.data(), encoded.size());
  require(decoded.size() == input.size(), "decoded size");
  for (std::size_t i = 0; i < decoded.size(); ++i) {
    require(close(decoded[i], expected.reconstructed[i]), "decoded values");
  }
  require(accounting.header_bits + accounting.codebook_bits +
              accounting.symbol_stream_bits + accounting.checksum_bits ==
              accounting.final_bits, "FinalBits closure");
  require(accounting.serialized_bits == encoded.size() * 8U, "serialized bits");
  for (std::size_t i = 0; i < encoded.size(); ++i) {
    auto corrupt = encoded;
    corrupt[i] ^= 1U;
    require_throws([&] { (void)fabba::decode(corrupt.data(), corrupt.size()); },
                   "corruption accepted");
  }
  require_throws([&] { (void)fabba::decode(encoded.data(), encoded.size() - 1U); },
                 "truncation accepted");
}

void test_properties() {
  const double singleton = 1.0;
  require_throws([&] { (void)fabba::encode(&singleton, 1); }, "singleton accepted");
  const double invalid[] = {0.0, std::numeric_limits<double>::quiet_NaN()};
  require_throws([&] { (void)fabba::encode(invalid, 2); }, "NaN accepted");
  std::mt19937_64 generator(20260928U);
  std::uniform_real_distribution<double> delta(-1.0, 1.0);
  for (std::size_t trial = 0; trial < 256; ++trial) {
    const std::size_t count = 2U + (trial * 29U) % 257U;
    std::vector<double> input(count);
    for (std::size_t i = 1; i < count; ++i) input[i] = input[i - 1U] + delta(generator);
    fabba::Config config;
    config.tolerance = static_cast<double>(trial % 5U) * 0.05;
    config.alpha = static_cast<double>(trial % 7U) * 0.04;
    config.max_len = trial % 3U == 0 ? 5U : std::numeric_limits<std::uint64_t>::max();
    const auto transformed = fabba::transform(input.data(), input.size(), config);
    double length_sum = 0.0;
    for (const auto& piece : transformed.pieces) length_sum += piece.length;
    require(length_sum + 1.0 == static_cast<double>(count), "piece length invariant");
    const auto encoded = fabba::encode(input.data(), input.size(), config);
    const auto decoded = fabba::decode(encoded.data(), encoded.size());
    require(decoded.size() == count, "property decode size");
  }
}

void test_partitioned_parallel_compress() {
  std::vector<double> input(256);
  for (std::size_t i = 0; i < input.size(); ++i) {
    input[i] = std::sin(static_cast<double>(i) * 0.11) +
               static_cast<double>(i % 9U) * 0.02;
  }
  fabba::Config config;
  config.partition = 4U;
  config.threads = 2U;
  fabba::ParallelExecutionInfo execution;
  const auto first = fabba::parallel_compress(
      input.data(), input.size(), config, &execution);
  const auto second = fabba::parallel_compress(input.data(), input.size(), config);
  require(first.size() == 4U, "parallel partition count");
  require(execution.partitions_requested == 4U &&
              execution.partitions_used == 4U,
          "parallel partition execution evidence");
  require(execution.threads_requested == 2U && execution.threads_used == 2U,
          "parallel thread execution evidence");
  require(execution.samples_per_partition == 64U &&
              execution.samples_consumed == input.size() &&
              execution.samples_discarded == 0U,
          "parallel sample accounting");
  require(first.size() == second.size(), "parallel repeat count");
  for (std::size_t part = 0; part < first.size(); ++part) {
    require(!first[part].empty(), "parallel partition empty");
    require(first[part].size() == second[part].size(), "parallel nondeterministic piece count");
    for (std::size_t i = 0; i < first[part].size(); ++i) {
      require(first[part][i].length == second[part][i].length &&
                  first[part][i].increment == second[part][i].increment &&
                  first[part][i].error == second[part][i].error,
              "parallel compression is nondeterministic");
    }
  }

  config.partition = 7U;
  config.threads = 99U;
  const auto uneven = fabba::parallel_compress(
      input.data(), input.size() - 1U, config, &execution);
  require(uneven.size() == 7U && execution.threads_used == 7U,
          "parallel worker clamp");
  require(execution.samples_per_partition == 36U &&
              execution.samples_consumed == 252U &&
              execution.samples_discarded == 3U,
          "parallel tail policy");

  config.partition = 4U;
  config.threads = 2U;
  auto concurrent_left = std::async(std::launch::async, [&] {
    return fabba::parallel_compress(input.data(), input.size(), config);
  });
  auto concurrent_right = std::async(std::launch::async, [&] {
    return fabba::parallel_compress(input.data(), input.size(), config);
  });
  const auto left_result = concurrent_left.get();
  const auto right_result = concurrent_right.get();
  require(left_result.size() == right_result.size(),
          "concurrent parallel partition count diverged");
  for (std::size_t part = 0; part < left_result.size(); ++part) {
    require(left_result[part].size() == right_result[part].size(),
            "concurrent parallel piece count diverged");
    for (std::size_t i = 0; i < left_result[part].size(); ++i) {
      require(left_result[part][i].length == right_result[part][i].length &&
                  left_result[part][i].increment ==
                      right_result[part][i].increment &&
                  left_result[part][i].error == right_result[part][i].error,
              "concurrent parallel calls diverged");
    }
  }

  config.threads = 0U;
  require_throws(
      [&] { (void)fabba::parallel_compress(input.data(), input.size(), config); },
      "zero parallel thread count accepted");
}

}  // namespace

int main() {
  try {
    test_stages();
    test_quantization();
    test_container();
    test_properties();
    test_partitioned_parallel_compress();
    return 0;
  } catch (const std::exception&) {
    return 1;
  }
}
