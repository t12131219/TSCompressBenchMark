#include "fabba.hpp"

#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

template <typename T>
void print_scalars(const std::vector<T>& values) {
  std::cout << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    std::cout << (i == 0 ? "" : ",") << values[i];
  }
  std::cout << ']';
}

void print_centers(const std::vector<fabba::Center>& values) {
  std::cout << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    std::cout << (i == 0 ? "" : ",") << '[' << values[i].length << ','
              << values[i].increment << ']';
  }
  std::cout << ']';
}

void print_pieces(const std::vector<fabba::Piece>& values) {
  std::cout << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    std::cout << (i == 0 ? "" : ",") << '[' << values[i].length << ','
              << values[i].increment << ',' << values[i].error << ']';
  }
  std::cout << ']';
}

void print_digitized(const fabba::Digitized& value) {
  std::cout << "\"length_std\":" << value.length_std
            << ",\"increment_std\":" << value.increment_std
            << ",\"sorted_indices\":";
  print_scalars(value.sorted_indices);
  std::cout << ",\"starting_points\":";
  print_scalars(value.starting_points);
  std::cout << ",\"labels_raw\":";
  print_scalars(value.raw_labels);
  std::cout << ",\"centers_raw\":";
  print_centers(value.raw_centers);
  std::cout << ",\"symbols\":";
  print_scalars(value.symbols);
  std::cout << ",\"centers\":";
  print_centers(value.centers);
}

void print_accounting(const fabba::Accounting& value) {
  std::cout << "{\"header_bits\":" << value.header_bits
            << ",\"codebook_bits\":" << value.codebook_bits
            << ",\"symbol_stream_bits\":" << value.symbol_stream_bits
            << ",\"checksum_bits\":" << value.checksum_bits
            << ",\"serialized_bits\":" << value.serialized_bits
            << ",\"external_side_information_bits\":"
            << value.external_side_information_bits
            << ",\"final_bits\":" << value.final_bits << '}';
}

std::string to_hex(const std::vector<std::uint8_t>& bytes) {
  static constexpr char digits[] = "0123456789abcdef";
  std::string result;
  result.reserve(bytes.size() * 2U);
  for (const auto byte : bytes) {
    result.push_back(digits[byte >> 4U]);
    result.push_back(digits[byte & 0x0fU]);
  }
  return result;
}

unsigned hex_digit(const char value) {
  if (value >= '0' && value <= '9') return static_cast<unsigned>(value - '0');
  if (value >= 'a' && value <= 'f') return static_cast<unsigned>(value - 'a' + 10);
  if (value >= 'A' && value <= 'F') return static_cast<unsigned>(value - 'A' + 10);
  throw std::invalid_argument("invalid hex");
}

std::vector<std::uint8_t> from_hex(const std::string& text) {
  if (text.size() % 2U != 0) throw std::invalid_argument("odd hex");
  std::vector<std::uint8_t> result;
  result.reserve(text.size() / 2U);
  for (std::size_t i = 0; i < text.size(); i += 2U) {
    result.push_back(static_cast<std::uint8_t>((hex_digit(text[i]) << 4U) |
                                               hex_digit(text[i + 1U])));
  }
  return result;
}

std::vector<double> read_values() {
  std::size_t count = 0;
  if (!(std::cin >> count)) throw std::invalid_argument("missing count");
  std::vector<double> values(count);
  for (double& value : values) {
    if (!(std::cin >> value)) throw std::invalid_argument("missing value");
  }
  return values;
}

}  // namespace

int main(int argc, char** argv) {
  std::string operation = "transform";
  fabba::Config config;
  try {
    for (int index = 1; index < argc; ++index) {
      const std::string key = argv[index];
      if (index + 1 >= argc) throw std::invalid_argument("missing option value");
      const std::string value = argv[++index];
      if (key == "--operation") operation = value;
      else if (key == "--tol") config.tolerance = std::stod(value);
      else if (key == "--alpha") config.alpha = std::stod(value);
      else if (key == "--scl") config.scl = std::stod(value);
      else if (key == "--max-len") config.max_len = value == "-1" ?
          std::numeric_limits<std::uint64_t>::max() : std::stoull(value);
      else if (key == "--partition") config.partition = static_cast<std::uint32_t>(std::stoul(value));
      else if (key == "--threads") config.threads = static_cast<std::uint32_t>(std::stoul(value));
      else throw std::invalid_argument("unknown option");
    }
    std::cout << std::setprecision(17) << "{\"ok\":true,\"result\":{";
    if (operation == "compress") {
      const auto values = read_values();
      std::cout << "\"pieces\":";
      print_pieces(fabba::compress(values.data(), values.size(), config));
    } else if (operation == "parallel-compress") {
      const auto values = read_values();
      fabba::ParallelExecutionInfo execution;
      const auto partitions = fabba::parallel_compress(
          values.data(), values.size(), config, &execution);
      std::cout << "\"partitions\":[";
      for (std::size_t i = 0; i < partitions.size(); ++i) {
        if (i != 0U) std::cout << ',';
        print_pieces(partitions[i]);
      }
      std::cout << "],\"execution\":{\"partitions_requested\":"
                << execution.partitions_requested
                << ",\"partitions_used\":" << execution.partitions_used
                << ",\"threads_requested\":" << execution.threads_requested
                << ",\"threads_used\":" << execution.threads_used
                << ",\"samples_per_partition\":"
                << execution.samples_per_partition
                << ",\"samples_consumed\":" << execution.samples_consumed
                << ",\"samples_discarded\":" << execution.samples_discarded
                << '}';
    } else if (operation == "digitize") {
      std::size_t count = 0;
      if (!(std::cin >> count)) throw std::invalid_argument("missing piece count");
      std::vector<fabba::Piece> pieces(count);
      for (auto& piece : pieces) {
        if (!(std::cin >> piece.length >> piece.increment))
          throw std::invalid_argument("missing piece");
      }
      print_digitized(fabba::digitize(pieces, config));
    } else if (operation == "decode") {
      double first = 0.0;
      std::size_t symbol_count = 0;
      std::size_t center_count = 0;
      if (!(std::cin >> first >> symbol_count >> center_count))
        throw std::invalid_argument("missing decode header");
      std::vector<fabba::Center> centers(center_count);
      for (auto& center : centers) {
        if (!(std::cin >> center.length >> center.increment))
          throw std::invalid_argument("missing center");
      }
      std::vector<fabba::Center> expanded;
      for (std::size_t i = 0; i < symbol_count; ++i) {
        unsigned symbol = 0;
        if (!(std::cin >> symbol) || symbol >= centers.size())
          throw std::invalid_argument("invalid symbol");
        expanded.push_back(centers[symbol]);
      }
      const auto quantized = fabba::quantize(expanded);
      std::size_t sample_count = 1;
      for (const auto& piece : quantized)
        sample_count += static_cast<std::size_t>(piece.length);
      std::cout << "\"quantized_pieces\":";
      print_centers(quantized);
      std::cout << ",\"reconstructed\":";
      print_scalars(fabba::reconstruct(first, quantized, sample_count));
    } else if (operation == "decode-container") {
      std::string hex;
      if (!(std::cin >> hex)) throw std::invalid_argument("missing hex");
      const auto bytes = from_hex(hex);
      fabba::Accounting accounting;
      const auto values = fabba::decode(bytes.data(), bytes.size(), &accounting);
      std::cout << "\"reconstructed\":";
      print_scalars(values);
      std::cout << ",\"accounting\":";
      print_accounting(accounting);
    } else if (operation == "transform") {
      const auto values = read_values();
      const auto result = fabba::transform(values.data(), values.size(), config);
      std::cout << "\"pieces\":";
      print_pieces(result.pieces);
      std::cout << ',';
      print_digitized(result.digitized);
      std::cout << ",\"quantized_pieces\":";
      print_centers(result.quantized_pieces);
      std::cout << ",\"reconstructed\":";
      print_scalars(result.reconstructed);
      fabba::Accounting accounting;
      const auto bytes = fabba::encode(values.data(), values.size(), config, &accounting);
      std::cout << ",\"container_hex\":\"" << to_hex(bytes) << "\",\"accounting\":";
      print_accounting(accounting);
    } else {
      throw std::invalid_argument("unknown operation");
    }
    std::cout << "}}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cout << "{\"ok\":false,\"error\":\"" << error.what() << "\"}\n";
    return 1;
  }
}
