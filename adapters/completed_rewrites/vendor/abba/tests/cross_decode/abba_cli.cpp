#include "abba.hpp"

#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void print_centers(const std::vector<abba::Center>& values) {
  std::cout << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    std::cout << (i == 0 ? "" : ",") << '[' << values[i].length << ','
              << values[i].increment << ']';
  }
  std::cout << ']';
}

void print_pieces(const std::vector<abba::Piece>& values) {
  std::cout << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    std::cout << (i == 0 ? "" : ",") << '[' << values[i].length << ','
              << values[i].increment << ',' << values[i].error << ']';
  }
  std::cout << ']';
}

template <typename T>
void print_scalars(const std::vector<T>& values) {
  std::cout << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    std::cout << (i == 0 ? "" : ",") << values[i];
  }
  std::cout << ']';
}

std::string to_hex(const std::vector<std::uint8_t>& bytes) {
  static constexpr char kHex[] = "0123456789abcdef";
  std::string result;
  result.reserve(bytes.size() * 2U);
  for (const std::uint8_t byte : bytes) {
    result.push_back(kHex[byte >> 4U]);
    result.push_back(kHex[byte & 0x0fU]);
  }
  return result;
}

unsigned hex_digit(const char value) {
  if (value >= '0' && value <= '9') {
    return static_cast<unsigned>(value - '0');
  }
  if (value >= 'a' && value <= 'f') {
    return static_cast<unsigned>(value - 'a' + 10);
  }
  if (value >= 'A' && value <= 'F') {
    return static_cast<unsigned>(value - 'A' + 10);
  }
  throw std::invalid_argument("invalid hex input");
}

std::vector<std::uint8_t> from_hex(const std::string& text) {
  if (text.size() % 2U != 0) {
    throw std::invalid_argument("odd hex input");
  }
  std::vector<std::uint8_t> result;
  result.reserve(text.size() / 2U);
  for (std::size_t i = 0; i < text.size(); i += 2U) {
    result.push_back(static_cast<std::uint8_t>((hex_digit(text[i]) << 4U) |
                                               hex_digit(text[i + 1])));
  }
  return result;
}

void print_accounting(const abba::Accounting& value) {
  std::cout << "{\"header_bits\":" << value.header_bits
            << ",\"codebook_bits\":" << value.codebook_bits
            << ",\"symbol_stream_bits\":" << value.symbol_stream_bits
            << ",\"checksum_bits\":" << value.checksum_bits
            << ",\"serialized_bits\":" << value.serialized_bits
            << ",\"external_side_information_bits\":"
            << value.external_side_information_bits << ",\"final_bits\":"
            << value.final_bits << '}';
}

void print_digitized(const abba::Digitized& value) {
  std::cout << "\"variance_bound\":" << value.variance_bound
            << ",\"labels_raw\":";
  print_scalars(value.raw_labels);
  std::cout << ",\"centers_raw\":";
  print_centers(value.raw_centers);
  std::cout << ",\"symbols\":";
  print_scalars(value.symbols);
  std::cout << ",\"centers\":";
  print_centers(value.centers);
}

std::vector<double> read_values() {
  std::size_t count = 0;
  if (!(std::cin >> count)) {
    throw std::invalid_argument("missing value count");
  }
  std::vector<double> values(count);
  for (double& value : values) {
    if (!(std::cin >> value)) {
      throw std::invalid_argument("missing value");
    }
  }
  return values;
}

}  // namespace

int main(int argc, char** argv) {
  std::string operation = "transform";
  abba::Config config;
  try {
    for (int index = 1; index < argc; ++index) {
      const std::string key = argv[index];
      if (index + 1 >= argc) {
        throw std::invalid_argument("missing argument value");
      }
      const std::string value = argv[++index];
      if (key == "--operation") {
        operation = value;
      } else if (key == "--compression-tol") {
        config.compression_tolerance = std::stod(value);
      } else if (key == "--digitization-tol") {
        config.digitization_tolerance = std::stod(value);
      } else if (key == "--min-k") {
        config.min_k = static_cast<std::uint32_t>(std::stoul(value));
      } else if (key == "--max-k") {
        config.max_k = static_cast<std::uint32_t>(std::stoul(value));
      } else if (key == "--max-len") {
        config.max_len = value == "inf" ? std::numeric_limits<std::uint64_t>::max()
                                         : std::stoull(value);
      } else if (key == "--scl") {
        config.scl = value == "inf" ? std::numeric_limits<double>::infinity()
                                      : std::stod(value);
      } else if (key == "--norm") {
        config.norm = static_cast<std::uint8_t>(std::stoul(value));
      } else if (key == "--clustering") {
        if (value == "incremental") {
          config.clustering = abba::Config::ClusteringMethod::Incremental;
        } else if (value == "kmeans") {
          config.clustering = abba::Config::ClusteringMethod::Kmeans;
        } else {
          throw std::invalid_argument("unknown clustering method");
        }
      } else if (key == "--weighted") {
        config.weighted = value == "1" || value == "true";
      } else if (key == "--symmetric") {
        config.symmetric = value == "1" || value == "true";
      } else {
        throw std::invalid_argument("unknown argument");
      }
    }

    std::cout << std::setprecision(17) << "{\"ok\":true,\"result\":{";
    if (operation == "compress") {
      const auto values = read_values();
      const auto pieces = abba::compress(values.data(), values.size(), config);
      std::cout << "\"pieces\":";
      print_pieces(pieces);
    } else if (operation == "digitize") {
      std::size_t count = 0;
      if (!(std::cin >> count)) {
        throw std::invalid_argument("missing piece count");
      }
      std::vector<abba::Piece> pieces(count);
      std::size_t sample_count = 1;
      for (abba::Piece& piece : pieces) {
        if (!(std::cin >> piece.length >> piece.increment)) {
          throw std::invalid_argument("missing piece");
        }
        piece.error = 0.0;
        sample_count += static_cast<std::size_t>(piece.length);
      }
      print_digitized(abba::digitize(pieces, sample_count, config));
    } else if (operation == "decode") {
      double first_value = 0.0;
      std::size_t symbol_count = 0;
      std::size_t center_count = 0;
      if (!(std::cin >> first_value >> symbol_count >> center_count)) {
        throw std::invalid_argument("missing decode header");
      }
      std::vector<abba::Center> centers(center_count);
      for (abba::Center& center : centers) {
        if (!(std::cin >> center.length >> center.increment)) {
          throw std::invalid_argument("missing center");
        }
      }
      std::vector<std::uint16_t> symbols(symbol_count);
      for (std::uint16_t& symbol : symbols) {
        unsigned parsed = 0;
        if (!(std::cin >> parsed) || parsed > 65535U) {
          throw std::invalid_argument("missing symbol");
        }
        symbol = static_cast<std::uint16_t>(parsed);
      }
      std::vector<abba::Center> expanded;
      for (const std::uint16_t symbol : symbols) {
        if (symbol >= centers.size()) {
          throw std::invalid_argument("symbol outside codebook");
        }
        expanded.push_back(centers[symbol]);
      }
      const auto quantized = abba::quantize(expanded);
      std::size_t sample_count = 1;
      for (const auto& piece : quantized) {
        sample_count += static_cast<std::size_t>(piece.length);
      }
      const auto reconstructed =
          abba::reconstruct(first_value, quantized, sample_count);
      std::cout << "\"quantized_pieces\":";
      print_centers(quantized);
      std::cout << ",\"reconstructed\":";
      print_scalars(reconstructed);
    } else if (operation == "decode-container") {
      std::string hex;
      if (!(std::cin >> hex)) {
        throw std::invalid_argument("missing container hex");
      }
      const auto bytes = from_hex(hex);
      abba::Accounting accounting;
      const auto reconstructed =
          abba::decode(bytes.data(), bytes.size(), &accounting);
      std::cout << "\"reconstructed\":";
      print_scalars(reconstructed);
      std::cout << ",\"accounting\":";
      print_accounting(accounting);
    } else if (operation == "transform") {
      const auto values = read_values();
      const auto result = abba::transform(values.data(), values.size(), config);
      std::cout << "\"pieces\":";
      print_pieces(result.pieces);
      std::cout << ',';
      print_digitized(result.digitized);
      std::cout << ",\"quantized_pieces\":";
      print_centers(result.quantized_pieces);
      std::cout << ",\"reconstructed\":";
      print_scalars(result.reconstructed);
      abba::Accounting accounting;
      const auto encoded =
          abba::encode(values.data(), values.size(), config, &accounting);
      std::cout << ",\"container_hex\":\"" << to_hex(encoded)
                << "\",\"accounting\":";
      print_accounting(accounting);
    } else {
      throw std::invalid_argument("unknown operation");
    }
    std::cout << "}}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cout << "{\"ok\":false,\"error\":\"" << error.what() << "\"}\n";
    return 2;
  }
}
