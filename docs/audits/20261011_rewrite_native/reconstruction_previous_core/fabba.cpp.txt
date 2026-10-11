#include "fabba.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <future>
#include <thread>
#include <type_traits>
#include <vector>

namespace fabba {
namespace {

constexpr std::size_t kHeaderBytes = 72;
constexpr std::size_t kChecksumBytes = 4;
constexpr std::uint16_t kVersion = 1;
constexpr std::uint16_t kProfileFlags = 1;
constexpr std::uint32_t kSortingStableNorm2 = 2;
constexpr std::uint32_t kAlphabetSet = 0;

void validate_config(const Config& config) {
  if (!std::isfinite(config.tolerance) || config.tolerance < 0.0 ||
      !std::isfinite(config.alpha) || config.alpha < 0.0 ||
      !std::isfinite(config.scl) || config.scl <= 0.0 ||
      config.max_len == 0 || config.threads == 0) {
    throw std::invalid_argument("invalid fABBA configuration");
  }
}

void validate_values(const double* values, const std::size_t count) {
  if (values == nullptr || count < 2) {
    throw std::invalid_argument("fABBA requires at least two samples");
  }
  for (std::size_t i = 0; i < count; ++i) {
    if (!std::isfinite(values[i])) {
      throw std::invalid_argument("fABBA input must be finite");
    }
  }
}

double round_ties_even(const double value) {
  if (!std::isfinite(value)) {
    throw std::invalid_argument("cannot quantize a non-finite length");
  }
  const double lower = std::floor(value);
  const double fraction = value - lower;
  if (fraction < 0.5) {
    return lower;
  }
  if (fraction > 0.5) {
    return lower + 1.0;
  }
  return std::fmod(std::fabs(lower), 2.0) == 0.0 ? lower : lower + 1.0;
}

std::uint64_t double_bits(const double value) {
  std::uint64_t bits = 0;
  static_assert(sizeof(bits) == sizeof(value), "binary64 is required");
  std::memcpy(&bits, &value, sizeof(bits));
  return bits;
}

double bits_double(const std::uint64_t bits) {
  double value = 0.0;
  std::memcpy(&value, &bits, sizeof(value));
  return value;
}

template <typename T>
void append_le(std::vector<std::uint8_t>& output, const T value) {
  static_assert(std::is_unsigned<T>::value, "unsigned integer required");
  for (std::size_t byte = 0; byte < sizeof(T); ++byte) {
    output.push_back(static_cast<std::uint8_t>((value >> (8U * byte)) & 0xffU));
  }
}

template <typename T>
T read_le(const std::uint8_t* data, const std::size_t size,
          std::size_t& offset) {
  static_assert(std::is_unsigned<T>::value, "unsigned integer required");
  if (offset > size || sizeof(T) > size - offset) {
    throw std::invalid_argument("truncated fABBA container");
  }
  std::uint64_t value = 0;
  for (std::size_t byte = 0; byte < sizeof(T); ++byte) {
    value |= static_cast<std::uint64_t>(data[offset + byte]) << (8U * byte);
  }
  offset += sizeof(T);
  return static_cast<T>(value);
}

std::uint32_t crc32(const std::uint8_t* data, const std::size_t size) {
  std::uint32_t crc = 0xffffffffU;
  for (std::size_t i = 0; i < size; ++i) {
    crc ^= data[i];
    for (int bit = 0; bit < 8; ++bit) {
      const std::uint32_t mask = 0U - (crc & 1U);
      crc = (crc >> 1U) ^ (0xedb88320U & mask);
    }
  }
  return ~crc;
}

Accounting make_accounting(const std::size_t center_count,
                           const std::size_t symbol_count,
                           const std::size_t total_bytes) {
  Accounting result;
  result.header_bits = static_cast<std::uint64_t>(kHeaderBytes) * 8U;
  result.codebook_bits = static_cast<std::uint64_t>(center_count) * 16U * 8U;
  result.symbol_stream_bits = static_cast<std::uint64_t>(symbol_count) * 2U * 8U;
  result.checksum_bits = static_cast<std::uint64_t>(kChecksumBytes) * 8U;
  result.serialized_bits = static_cast<std::uint64_t>(total_bytes) * 8U;
  result.final_bits = result.serialized_bits;
  if (result.header_bits + result.codebook_bits + result.symbol_stream_bits +
          result.checksum_bits != result.final_bits) {
    throw std::logic_error("fABBA accounting does not close");
  }
  return result;
}

struct ParsedContainer {
  Config config;
  std::size_t sample_count = 0;
  double first_value = 0.0;
  std::vector<Center> centers;
  std::vector<std::uint16_t> symbols;
  Accounting accounting;
};

ParsedContainer parse_container(const std::uint8_t* data, const std::size_t size) {
  if (data == nullptr || size < kHeaderBytes + kChecksumBytes) {
    throw std::invalid_argument("truncated fABBA container");
  }
  if (std::memcmp(data, "FABB", 4) != 0) {
    throw std::invalid_argument("invalid fABBA magic");
  }
  std::size_t offset = 4;
  const auto version = read_le<std::uint16_t>(data, size, offset);
  const auto flags = read_le<std::uint16_t>(data, size, offset);
  const auto sample_count_u64 = read_le<std::uint64_t>(data, size, offset);
  const auto symbol_count = read_le<std::uint32_t>(data, size, offset);
  const auto center_count = read_le<std::uint32_t>(data, size, offset);
  Config config;
  config.tolerance = bits_double(read_le<std::uint64_t>(data, size, offset));
  config.alpha = bits_double(read_le<std::uint64_t>(data, size, offset));
  config.max_len = read_le<std::uint64_t>(data, size, offset);
  config.scl = bits_double(read_le<std::uint64_t>(data, size, offset));
  const double first_value = bits_double(read_le<std::uint64_t>(data, size, offset));
  const auto sorting = read_le<std::uint32_t>(data, size, offset);
  const auto alphabet_set = read_le<std::uint32_t>(data, size, offset);

  if (version != kVersion || flags != kProfileFlags ||
      sorting != kSortingStableNorm2 || alphabet_set != kAlphabetSet) {
    throw std::invalid_argument("unsupported fABBA container profile");
  }
  validate_config(config);
  if (sample_count_u64 < 2 ||
      sample_count_u64 > static_cast<std::uint64_t>(
                             std::numeric_limits<std::size_t>::max()) ||
      symbol_count == 0 || center_count == 0 || center_count > 65535U ||
      center_count > symbol_count || !std::isfinite(first_value)) {
    throw std::invalid_argument("invalid fABBA container counts");
  }
  const std::uint64_t expected =
      static_cast<std::uint64_t>(kHeaderBytes + kChecksumBytes) +
      static_cast<std::uint64_t>(center_count) * 16U +
      static_cast<std::uint64_t>(symbol_count) * 2U;
  if (expected != size) {
    throw std::invalid_argument("fABBA container size mismatch");
  }
  const std::uint32_t stored_crc = static_cast<std::uint32_t>(data[size - 4]) |
      (static_cast<std::uint32_t>(data[size - 3]) << 8U) |
      (static_cast<std::uint32_t>(data[size - 2]) << 16U) |
      (static_cast<std::uint32_t>(data[size - 1]) << 24U);
  if (crc32(data, size - kChecksumBytes) != stored_crc) {
    throw std::invalid_argument("fABBA container checksum mismatch");
  }

  ParsedContainer parsed;
  parsed.config = config;
  parsed.sample_count = static_cast<std::size_t>(sample_count_u64);
  parsed.first_value = first_value;
  parsed.centers.reserve(center_count);
  for (std::uint32_t i = 0; i < center_count; ++i) {
    const double length = bits_double(read_le<std::uint64_t>(data, size, offset));
    const double increment = bits_double(read_le<std::uint64_t>(data, size, offset));
    if (!std::isfinite(length) || !std::isfinite(increment) || length <= 0.0) {
      throw std::invalid_argument("invalid fABBA codebook center");
    }
    parsed.centers.push_back({length, increment});
  }
  parsed.symbols.reserve(symbol_count);
  for (std::uint32_t i = 0; i < symbol_count; ++i) {
    const auto symbol = read_le<std::uint16_t>(data, size, offset);
    if (symbol >= center_count) {
      throw std::invalid_argument("fABBA symbol outside codebook");
    }
    parsed.symbols.push_back(symbol);
  }
  if (offset != size - kChecksumBytes) {
    throw std::logic_error("fABBA parser offset mismatch");
  }
  parsed.accounting = make_accounting(center_count, symbol_count, size);
  return parsed;
}

double population_std(const std::vector<double>& values) {
  const double mean = std::accumulate(values.begin(), values.end(), 0.0) /
                      static_cast<double>(values.size());
  double variance = 0.0;
  for (const double value : values) {
    const double delta = value - mean;
    variance += delta * delta;
  }
  const double result = std::sqrt(variance / static_cast<double>(values.size()));
  return result <= std::numeric_limits<double>::epsilon() ? 1.0 : result;
}

}  // namespace

std::vector<Piece> compress(const double* values, const std::size_t count,
                            const Config& config) {
  validate_config(config);
  validate_values(values, count);
  const double epsilon = std::numeric_limits<double>::epsilon();
  std::vector<Piece> pieces;
  std::size_t start = 0;
  std::size_t end = 1;
  double last_increment = 0.0;
  double last_error = 0.0;
  while (end < count) {
    const double increment = values[end] - values[start];
    const double width = static_cast<double>(end - start);
    double error = 0.0;
    for (std::size_t index = start; index <= end; ++index) {
      const double expected = values[start] +
          (increment / width) * static_cast<double>(index - start);
      const double residual = expected - values[index];
      error += residual * residual;
    }
    const std::size_t interior = end - start - 1U;
    if (error <= config.tolerance * static_cast<double>(interior) + epsilon &&
        static_cast<std::uint64_t>(interior) < config.max_len) {
      last_increment = increment;
      last_error = error;
      ++end;
    } else {
      pieces.push_back({static_cast<double>(interior), last_increment, last_error});
      start = end - 1U;
    }
  }
  pieces.push_back({static_cast<double>(end - start - 1U),
                    last_increment, last_error});
  for (const Piece& piece : pieces) {
    if (piece.length < 1.0) {
      throw std::logic_error("fABBA produced a zero-length piece");
    }
  }
  return pieces;
}

std::vector<std::vector<Piece>> parallel_compress(
    const double* values, const std::size_t count, const Config& config,
    ParallelExecutionInfo* const execution_info) {
  validate_config(config);
  validate_values(values, count);
  if (config.partition <= 1U) {
    if (execution_info != nullptr) {
      *execution_info = {config.partition, 1U, config.threads, 1U, count,
                         count, 0U};
    }
    return {compress(values, count, config)};
  }
  const std::size_t partition_count = std::min<std::size_t>(
      config.partition, count / 2U);
  if (partition_count < 1U) {
    return {compress(values, count, config)};
  }
  std::vector<std::pair<std::size_t, std::size_t>> ranges;
  ranges.reserve(partition_count);
  const std::size_t interval = count / partition_count;
  for (std::size_t index = 0; index < partition_count; ++index) {
    ranges.emplace_back(index * interval, interval);
  }
  const std::size_t worker_count = std::min<std::size_t>(
      config.threads, partition_count);
  if (execution_info != nullptr) {
    const std::size_t consumed = interval * partition_count;
    *execution_info = {config.partition, partition_count, config.threads,
                       worker_count, interval, consumed, count - consumed};
  }
  std::vector<std::vector<Piece>> result(partition_count);
  for (std::size_t batch = 0; batch < partition_count; batch += worker_count) {
    const std::size_t batch_size = std::min(worker_count, partition_count - batch);
    std::vector<std::future<std::vector<Piece>>> pending;
    pending.reserve(batch_size);
    for (std::size_t index = 0; index < batch_size; ++index) {
      const auto range = ranges[batch + index];
      pending.push_back(std::async(std::launch::async, [&, range] {
        return compress(values + range.first, range.second, config);
      }));
    }
    for (std::size_t index = 0; index < batch_size; ++index) {
      result[batch + index] = pending[index].get();
    }
  }
  return result;
}

Digitized digitize(const std::vector<Piece>& pieces, const Config& config) {
  validate_config(config);
  if (pieces.empty() || pieces.size() > 65535U) {
    throw std::invalid_argument("invalid fABBA piece count");
  }
  std::vector<double> lengths;
  std::vector<double> increments;
  lengths.reserve(pieces.size());
  increments.reserve(pieces.size());
  for (const Piece& piece : pieces) {
    if (!std::isfinite(piece.length) || !std::isfinite(piece.increment) ||
        piece.length < 1.0) {
      throw std::invalid_argument("invalid fABBA piece");
    }
    lengths.push_back(piece.length);
    increments.push_back(piece.increment);
  }
  Digitized result;
  result.length_std = population_std(lengths);
  result.increment_std = population_std(increments);
  std::vector<double> normalized_length(pieces.size());
  std::vector<double> normalized_increment(pieces.size());
  std::vector<double> norms(pieces.size());
  result.sorted_indices.resize(pieces.size());
  std::iota(result.sorted_indices.begin(), result.sorted_indices.end(), 0U);
  for (std::size_t i = 0; i < pieces.size(); ++i) {
    normalized_length[i] = pieces[i].length * config.scl / result.length_std;
    normalized_increment[i] = pieces[i].increment / result.increment_std;
    norms[i] = std::hypot(normalized_length[i], normalized_increment[i]);
  }
  std::stable_sort(result.sorted_indices.begin(), result.sorted_indices.end(),
                   [&norms](const std::size_t left, const std::size_t right) {
                     if (norms[left] != norms[right]) {
                       return norms[left] < norms[right];
                     }
                     return left < right;
                   });
  result.raw_labels.assign(pieces.size(), -1);
  int label = 0;
  const double alpha_squared = config.alpha * config.alpha;
  for (std::size_t pos = 0; pos < result.sorted_indices.size(); ++pos) {
    const std::size_t start = result.sorted_indices[pos];
    if (result.raw_labels[start] >= 0) {
      continue;
    }
    if (label > 65535) {
      throw std::invalid_argument("too many fABBA clusters");
    }
    result.raw_labels[start] = label;
    result.starting_points.push_back(start);
    for (std::size_t cursor = pos; cursor < result.sorted_indices.size(); ++cursor) {
      const std::size_t current = result.sorted_indices[cursor];
      if (result.raw_labels[current] >= 0) {
        continue;
      }
      const double dl = normalized_length[start] - normalized_length[current];
      const double di = normalized_increment[start] - normalized_increment[current];
      if (dl * dl + di * di <= alpha_squared) {
        result.raw_labels[current] = label;
      } else if (norms[current] - norms[start] > config.alpha) {
        break;
      }
    }
    ++label;
  }
  const std::size_t cluster_count = static_cast<std::size_t>(label);
  result.raw_centers.assign(cluster_count, {});
  std::vector<std::size_t> counts(cluster_count, 0U);
  for (std::size_t i = 0; i < pieces.size(); ++i) {
    const auto cluster = static_cast<std::size_t>(result.raw_labels[i]);
    result.raw_centers[cluster].length += pieces[i].length;
    result.raw_centers[cluster].increment += pieces[i].increment;
    ++counts[cluster];
  }
  for (std::size_t cluster = 0; cluster < cluster_count; ++cluster) {
    result.raw_centers[cluster].length /= static_cast<double>(counts[cluster]);
    result.raw_centers[cluster].increment /= static_cast<double>(counts[cluster]);
  }
  result.centers = result.raw_centers;
  result.symbols.reserve(pieces.size());
  for (const int raw_label : result.raw_labels) {
    result.symbols.push_back(static_cast<std::uint16_t>(raw_label));
  }
  return result;
}

std::vector<Center> quantize(const std::vector<Center>& pieces) {
  if (pieces.empty()) {
    throw std::invalid_argument("cannot quantize an empty fABBA stream");
  }
  std::vector<Center> result = pieces;
  if (result.size() == 1U) {
    result[0].length = round_ties_even(result[0].length);
  } else {
    for (std::size_t index = 0; index + 1U < result.size(); ++index) {
      const double correction =
          round_ties_even(result[index].length) - result[index].length;
      result[index].length = round_ties_even(result[index].length + correction);
      result[index + 1U].length -= correction;
      if (result[index].length == 0.0) {
        result[index].length = 1.0;
        result[index + 1U].length -= 1.0;
      }
    }
    result.back().length = round_ties_even(result.back().length);
  }
  for (const Center& piece : result) {
    if (!std::isfinite(piece.length) || !std::isfinite(piece.increment) ||
        piece.length < 1.0 || piece.length != std::floor(piece.length)) {
      throw std::invalid_argument("invalid quantized fABBA piece");
    }
  }
  return result;
}

std::vector<double> reconstruct(const double first_value,
                                const std::vector<Center>& pieces,
                                const std::size_t original_sample_count) {
  if (!std::isfinite(first_value) || original_sample_count < 2) {
    throw std::invalid_argument("invalid fABBA reconstruction request");
  }
  std::vector<double> result;
  result.reserve(original_sample_count);
  result.push_back(first_value);
  for (const Center& piece : pieces) {
    if (!std::isfinite(piece.length) || !std::isfinite(piece.increment) ||
        piece.length < 1.0 || piece.length != std::floor(piece.length) ||
        piece.length > static_cast<double>(std::numeric_limits<std::size_t>::max())) {
      throw std::invalid_argument("invalid fABBA reconstruction piece");
    }
    const auto length = static_cast<std::size_t>(piece.length);
    const double start = result.back();
    for (std::size_t position = 1; position <= length; ++position) {
      const double value = start +
          (static_cast<double>(position) / piece.length) * piece.increment;
      if (!std::isfinite(value)) {
        throw std::invalid_argument("non-finite fABBA reconstruction");
      }
      result.push_back(value);
    }
    if (result.size() > original_sample_count) {
      throw std::invalid_argument("fABBA reconstruction exceeds declared length");
    }
  }
  if (result.size() != original_sample_count) {
    throw std::invalid_argument("fABBA reconstruction length mismatch");
  }
  return result;
}

TransformResult transform(const double* values, const std::size_t count,
                          const Config& config) {
  TransformResult result;
  result.pieces = compress(values, count, config);
  result.digitized = digitize(result.pieces, config);
  std::vector<Center> expanded;
  expanded.reserve(result.digitized.symbols.size());
  for (const std::uint16_t symbol : result.digitized.symbols) {
    expanded.push_back(result.digitized.centers[symbol]);
  }
  result.quantized_pieces = quantize(expanded);
  result.reconstructed = reconstruct(values[0], result.quantized_pieces, count);
  return result;
}

std::vector<std::uint8_t> encode(const double* values, const std::size_t count,
                                 const Config& config, Accounting* accounting) {
  if (count > static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max()) + 1ULL) {
    throw std::invalid_argument("fABBA input is too large for container v1");
  }
  const TransformResult transformed = transform(values, count, config);
  const std::size_t symbol_count = transformed.digitized.symbols.size();
  const std::size_t center_count = transformed.digitized.centers.size();
  const std::size_t total_size =
      kHeaderBytes + center_count * 16U + symbol_count * 2U + kChecksumBytes;
  std::vector<std::uint8_t> output;
  output.reserve(total_size);
  output.push_back(static_cast<std::uint8_t>('F'));
  output.push_back(static_cast<std::uint8_t>('A'));
  output.push_back(static_cast<std::uint8_t>('B'));
  output.push_back(static_cast<std::uint8_t>('B'));
  append_le<std::uint16_t>(output, kVersion);
  append_le<std::uint16_t>(output, kProfileFlags);
  append_le<std::uint64_t>(output, static_cast<std::uint64_t>(count));
  append_le<std::uint32_t>(output, static_cast<std::uint32_t>(symbol_count));
  append_le<std::uint32_t>(output, static_cast<std::uint32_t>(center_count));
  append_le<std::uint64_t>(output, double_bits(config.tolerance));
  append_le<std::uint64_t>(output, double_bits(config.alpha));
  append_le<std::uint64_t>(output, config.max_len);
  append_le<std::uint64_t>(output, double_bits(config.scl));
  append_le<std::uint64_t>(output, double_bits(values[0]));
  append_le<std::uint32_t>(output, kSortingStableNorm2);
  append_le<std::uint32_t>(output, kAlphabetSet);
  for (const Center& center : transformed.digitized.centers) {
    append_le<std::uint64_t>(output, double_bits(center.length));
    append_le<std::uint64_t>(output, double_bits(center.increment));
  }
  for (const std::uint16_t symbol : transformed.digitized.symbols) {
    append_le<std::uint16_t>(output, symbol);
  }
  append_le<std::uint32_t>(output, crc32(output.data(), output.size()));
  if (output.size() != total_size) {
    throw std::logic_error("fABBA container size mismatch after encoding");
  }
  const Accounting result = make_accounting(center_count, symbol_count, total_size);
  if (accounting != nullptr) {
    *accounting = result;
  }
  return output;
}

std::vector<double> decode(const std::uint8_t* encoded, const std::size_t size,
                           Accounting* accounting) {
  const ParsedContainer parsed = parse_container(encoded, size);
  std::vector<Center> expanded;
  expanded.reserve(parsed.symbols.size());
  for (const std::uint16_t symbol : parsed.symbols) {
    expanded.push_back(parsed.centers[symbol]);
  }
  const auto quantized = quantize(expanded);
  auto result = reconstruct(parsed.first_value, quantized, parsed.sample_count);
  if (accounting != nullptr) {
    *accounting = parsed.accounting;
  }
  return result;
}

Accounting inspect_accounting(const std::uint8_t* encoded, const std::size_t size) {
  return parse_container(encoded, size).accounting;
}

std::size_t max_encoded_size(const std::size_t sample_count) {
  if (sample_count < 2) {
    return 0;
  }
  const std::size_t pieces = sample_count - 1U;
  constexpr std::size_t fixed = kHeaderBytes + kChecksumBytes;
  if (pieces > (std::numeric_limits<std::size_t>::max() - fixed) / 18U) {
    return 0;
  }
  return fixed + pieces * 18U;
}

}  // namespace fabba
