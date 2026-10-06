#include "fabba.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <vector>

namespace {

template <typename Function>
std::vector<double> measure(Function function) {
  for (int warmup = 0; warmup < 3; ++warmup) {
    const auto until = std::chrono::steady_clock::now() + std::chrono::milliseconds(500);
    while (std::chrono::steady_clock::now() < until) {
      function();
    }
  }
  std::vector<double> observations;
  for (int repetition = 0; repetition < 10; ++repetition) {
    std::size_t iterations = 0;
    const auto start = std::chrono::steady_clock::now();
    do {
      function();
      ++iterations;
    } while (std::chrono::steady_clock::now() - start < std::chrono::seconds(1));
    const double seconds =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    observations.push_back(seconds / static_cast<double>(iterations));
  }
  return observations;
}

void print_array(const std::vector<double>& values) {
  std::cout << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    std::cout << (i == 0 ? "" : ",") << values[i];
  }
  std::cout << ']';
}

}  // namespace

int main() {
  constexpr std::size_t kSamples = 8192;
  std::vector<double> input(kSamples);
  for (std::size_t i = 0; i < input.size(); ++i) {
    input[i] = std::sin(static_cast<double>(i) * 0.013) +
               0.25 * std::cos(static_cast<double>(i) * 0.071) +
               static_cast<double>(i % 17U) * 0.001;
  }
  std::vector<std::uint8_t> encoded;
  std::vector<double> decoded;
  const auto encode_seconds = measure([&] {
    encoded = fabba::encode(input.data(), input.size());
  });
  encoded = fabba::encode(input.data(), input.size());
  const auto decode_seconds = measure([&] {
    decoded = fabba::decode(encoded.data(), encoded.size());
  });
  volatile double sink = decoded.empty() ? 0.0 : decoded.back();
  (void)sink;
  std::cout << std::setprecision(17)
            << "{\"schema_version\":\"tscb.fabba-performance.v1\",";
  std::cout << "\"sample_count\":" << kSamples
            << ",\"encoded_bytes\":" << encoded.size()
            << ",\"encode_seconds\":";
  print_array(encode_seconds);
  std::cout << ",\"decode_seconds\":";
  print_array(decode_seconds);
  std::cout << "}\n";
  return 0;
}
