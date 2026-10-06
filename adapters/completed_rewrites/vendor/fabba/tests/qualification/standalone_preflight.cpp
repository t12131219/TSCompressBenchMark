#include "fabba_c.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {

void require(const bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

void qualify(const std::size_t count) {
  std::vector<double> input(count);
  for (std::size_t i = 0; i < count; ++i) {
    input[i] = std::sin(static_cast<double>(i) * 0.19) +
               static_cast<double>(i % 11U) * 0.03;
  }
  const auto input_copy = input;
  const fabba_config_v1 config = fabba_config_default_v1();
  size_t required = 0;
  fabba_accounting_v1 accounting{};
  require(fabba_encode_v1(input.data(), input.size(), &config, nullptr, 0,
                         &required, &accounting) ==
              FABBA_STATUS_BUFFER_TOO_SMALL_V1,
          "encode size query");
  require(required > 68U && required <= fabba_max_encoded_size_v1(count),
          "encode bound");
  require(std::memcmp(input.data(), input_copy.data(),
                      input.size() * sizeof(double)) == 0,
          "encode changed input");

  std::vector<std::uint8_t> guarded(required + 2U, 0xa5U);
  size_t written = 0;
  require(fabba_encode_v1(input.data(), input.size(), &config,
                         guarded.data() + 1U, required, &written,
                         &accounting) == FABBA_STATUS_OK_V1,
          "encode exact capacity");
  require(written == required && guarded.front() == 0xa5U &&
              guarded.back() == 0xa5U,
          "encode canary");
  std::vector<std::uint8_t> too_small(required == 0 ? 0 : required - 1U, 0x5aU);
  size_t repeated_required = 0;
  require(fabba_encode_v1(input.data(), input.size(), &config, too_small.data(),
                         too_small.size(), &repeated_required, nullptr) ==
              FABBA_STATUS_BUFFER_TOO_SMALL_V1 &&
              repeated_required == required,
          "encode bound minus one");
  require(std::all_of(too_small.begin(), too_small.end(),
                      [](const std::uint8_t value) { return value == 0x5aU; }),
          "small encode buffer changed");

  const std::uint8_t* encoded = guarded.data() + 1U;
  size_t output_count = 0;
  fabba_accounting_v1 decoded_accounting{};
  require(fabba_decode_v1(encoded, written, nullptr, 0, &output_count,
                         &decoded_accounting) ==
              FABBA_STATUS_BUFFER_TOO_SMALL_V1 &&
              output_count == count,
          "decode size query");
  std::vector<double> decoded(count + 2U,
                              std::numeric_limits<double>::quiet_NaN());
  size_t decoded_count = 0;
  require(fabba_decode_v1(encoded, written, decoded.data() + 1U, count,
                         &decoded_count, &decoded_accounting) ==
              FABBA_STATUS_OK_V1 &&
              decoded_count == count,
          "decode exact capacity");
  require(std::isnan(decoded.front()) && std::isnan(decoded.back()),
          "decode canary");
  require(decoded_accounting.header_bits + decoded_accounting.codebook_bits +
              decoded_accounting.symbol_stream_bits +
              decoded_accounting.checksum_bits ==
              decoded_accounting.final_bits,
          "FinalBits closure");
  require(decoded_accounting.final_bits == written * 8U &&
              decoded_accounting.external_side_information_bits == 0,
          "physical accounting");

  std::vector<double> short_output(count - 1U, 123.0);
  size_t needed = 0;
  require(fabba_decode_v1(encoded, written, short_output.data(),
                         short_output.size(), &needed, nullptr) ==
              FABBA_STATUS_BUFFER_TOO_SMALL_V1 &&
              needed == count,
          "decode bound minus one");
  require(std::all_of(short_output.begin(), short_output.end(),
                      [](const double value) { return value == 123.0; }),
          "small decode buffer changed");

  auto corrupt = std::vector<std::uint8_t>(encoded, encoded + written);
  corrupt[0] ^= 1U;
  require(fabba_decode_v1(corrupt.data(), corrupt.size(), nullptr, 0, &needed,
                         nullptr) == FABBA_STATUS_MALFORMED_INPUT_V1,
          "malformed magic");
  corrupt.assign(encoded, encoded + written);
  corrupt[written / 2U] ^= 1U;
  require(fabba_decode_v1(corrupt.data(), corrupt.size(), nullptr, 0, &needed,
                         nullptr) == FABBA_STATUS_MALFORMED_INPUT_V1,
          "malformed checksum");
  require(fabba_decode_v1(encoded, written - 1U, nullptr, 0, &needed, nullptr) ==
              FABBA_STATUS_MALFORMED_INPUT_V1,
          "truncated input");
}

}  // namespace

int main() {
  try {
    const double short_input[] = {0.0};
    size_t size = 0;
    require(fabba_encode_v1(short_input, 1, nullptr, nullptr, 0, &size, nullptr) ==
                FABBA_STATUS_INVALID_ARGUMENT_V1,
            "singleton C API input");
    require(fabba_encode_v1(nullptr, 0, nullptr, nullptr, 0, &size, nullptr) ==
                FABBA_STATUS_INVALID_ARGUMENT_V1,
            "empty C API input");
    qualify(2);
    qualify(3);
    qualify(127);
    qualify(128);
    qualify(129);
    qualify(1024);
    qualify(257);
    std::cout << "FABBA standalone qualification passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
