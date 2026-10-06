#include "abba.hpp"

#include "ckmeans/Ckmeans.1d.dp.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

namespace abba {
namespace {

constexpr std::size_t kHeaderBytes = 64;
constexpr std::size_t kChecksumBytes = 4;
constexpr std::uint16_t kVersion = 1;
constexpr std::uint16_t kProfileFlags = 1;

void validate_config(const Config& config) {
  if (!std::isfinite(config.compression_tolerance) ||
      !std::isfinite(config.digitization_tolerance) ||
      config.compression_tolerance < 0.0 ||
      config.digitization_tolerance < 0.0 || config.min_k == 0 ||
      config.min_k > config.max_k || config.max_k > 65535U ||
      config.max_len == 0 || config.scl < 0.0 ||
      (config.scl != std::numeric_limits<double>::infinity() &&
       !std::isfinite(config.scl)) ||
      (config.norm != 1U && config.norm != 2U)) {
    throw std::invalid_argument("invalid ABBA configuration");
  }
}

void validate_values(const double* values, const std::size_t count) {
  if (values == nullptr || count < 2) {
    throw std::invalid_argument("ABBA requires at least two samples");
  }
  for (std::size_t i = 0; i < count; ++i) {
    if (!std::isfinite(values[i])) {
      throw std::invalid_argument("ABBA input must be finite");
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
  const double parity = std::fmod(std::fabs(lower), 2.0);
  return parity == 0.0 ? lower : lower + 1.0;
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
    throw std::invalid_argument("truncated ABBA container");
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
          result.checksum_bits !=
      result.final_bits) {
    throw std::logic_error("ABBA accounting does not close");
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

struct Point2 {
  double x;
  double y;
};

double squared_distance(const Point2& left, const Point2& right) {
  const double dx = left.x - right.x;
  const double dy = left.y - right.y;
  return dx * dx + dy * dy;
}

double numpy_random_sample(std::mt19937& generator) {
  const std::uint64_t high = static_cast<std::uint64_t>(generator() >> 5U);
  const std::uint64_t low = static_cast<std::uint64_t>(generator() >> 6U);
  return static_cast<double>(high * 67108864ULL + low) / 9007199254740992.0;
}

std::pair<std::vector<int>, std::vector<Point2>> sklearn_style_kmeans(
    const std::vector<Point2>& input, const std::size_t cluster_count) {
  std::vector<Point2> points = input;
  Point2 mean{0.0, 0.0};
  for (const Point2& point : points) { mean.x += point.x; mean.y += point.y; }
  mean.x /= static_cast<double>(points.size());
  mean.y /= static_cast<double>(points.size());
  double variance = 0.0;
  for (Point2& point : points) {
    point.x -= mean.x;
    point.y -= mean.y;
    variance += point.x * point.x + point.y * point.y;
  }
  const double tolerance = variance / static_cast<double>(points.size()) * 1e-4;
  std::mt19937 generator(0U);
  double best_inertia = std::numeric_limits<double>::infinity();
  std::vector<int> best_labels;
  std::vector<Point2> best_centers;
  for (int restart = 0; restart < 10; ++restart) {
    std::vector<Point2> centers;
    const std::size_t first = std::min<std::size_t>(
        static_cast<std::size_t>(numpy_random_sample(generator) * static_cast<double>(points.size())),
        points.size() - 1U);
    centers.push_back(points[first]);
    std::vector<double> closest(points.size());
    for (std::size_t i = 0; i < points.size(); ++i) closest[i] = squared_distance(points[i], centers.front());
    double potential = std::accumulate(closest.begin(), closest.end(), 0.0);
    const std::size_t local_trials = 2U + static_cast<std::size_t>(std::log(static_cast<double>(cluster_count)));
    while (centers.size() < cluster_count) {
      Point2 best_candidate = points.front();
      std::vector<double> best_closest;
      double best_potential = std::numeric_limits<double>::infinity();
      for (std::size_t trial = 0; trial < local_trials; ++trial) {
        const double target = numpy_random_sample(generator) * potential;
        double cumulative = 0.0;
        std::size_t candidate = points.size() - 1U;
        for (std::size_t i = 0; i < points.size(); ++i) {
          cumulative += closest[i];
          if (cumulative >= target) { candidate = i; break; }
        }
        std::vector<double> candidate_closest(points.size());
        double candidate_potential = 0.0;
        for (std::size_t i = 0; i < points.size(); ++i) {
          candidate_closest[i] = std::min(closest[i], squared_distance(points[i], points[candidate]));
          candidate_potential += candidate_closest[i];
        }
        if (candidate_potential < best_potential) {
          best_potential = candidate_potential;
          best_candidate = points[candidate];
          best_closest = std::move(candidate_closest);
        }
      }
      centers.push_back(best_candidate);
      closest = std::move(best_closest);
      potential = best_potential;
    }
    std::vector<int> labels(points.size(), -1);
    for (int iteration = 0; iteration < 300; ++iteration) {
      std::vector<Point2> sums(cluster_count, {0.0, 0.0});
      std::vector<std::size_t> counts(cluster_count, 0U);
      std::vector<int> next_labels(points.size(), 0);
      for (std::size_t i = 0; i < points.size(); ++i) {
        std::size_t best = 0U;
        double distance = squared_distance(points[i], centers.front());
        for (std::size_t c = 1; c < cluster_count; ++c) {
          const double candidate = squared_distance(points[i], centers[c]);
          if (candidate < distance) { distance = candidate; best = c; }
        }
        next_labels[i] = static_cast<int>(best);
        sums[best].x += points[i].x;
        sums[best].y += points[i].y;
        ++counts[best];
      }
      std::vector<Point2> next_centers = centers;
      for (std::size_t c = 0; c < cluster_count; ++c) {
        if (counts[c] != 0U) {
          const double count = static_cast<double>(counts[c]);
          next_centers[c] = {sums[c].x / count, sums[c].y / count};
        }
      }
      double shift = 0.0;
      for (std::size_t c = 0; c < cluster_count; ++c) shift += squared_distance(centers[c], next_centers[c]);
      const bool strict_convergence = next_labels == labels;
      labels = std::move(next_labels);
      centers = std::move(next_centers);
      if (strict_convergence || shift <= tolerance) break;
    }
    double inertia = 0.0;
    for (std::size_t i = 0; i < points.size(); ++i) inertia += squared_distance(points[i], centers[static_cast<std::size_t>(labels[i])]);
    if (inertia < best_inertia) {
      best_inertia = inertia;
      best_labels = labels;
      best_centers = centers;
    }
  }
  for (Point2& center : best_centers) { center.x += mean.x; center.y += mean.y; }
  return {best_labels, best_centers};
}

ParsedContainer parse_container(const std::uint8_t* data, const std::size_t size) {
  if (data == nullptr || size < kHeaderBytes + kChecksumBytes) {
    throw std::invalid_argument("truncated ABBA container");
  }
  if (std::memcmp(data, "ABBA", 4) != 0) {
    throw std::invalid_argument("invalid ABBA magic");
  }

  std::size_t offset = 4;
  const auto version = read_le<std::uint16_t>(data, size, offset);
  const auto flags = read_le<std::uint16_t>(data, size, offset);
  const auto sample_count_u64 = read_le<std::uint64_t>(data, size, offset);
  const auto symbol_count = read_le<std::uint32_t>(data, size, offset);
  const auto center_count = read_le<std::uint32_t>(data, size, offset);
  Config config;
  config.compression_tolerance =
      bits_double(read_le<std::uint64_t>(data, size, offset));
  config.digitization_tolerance =
      bits_double(read_le<std::uint64_t>(data, size, offset));
  config.max_len = read_le<std::uint64_t>(data, size, offset);
  config.min_k = read_le<std::uint32_t>(data, size, offset);
  config.max_k = read_le<std::uint32_t>(data, size, offset);
  const double first_value =
      bits_double(read_le<std::uint64_t>(data, size, offset));

  if (version != kVersion || flags != kProfileFlags) {
    throw std::invalid_argument("unsupported ABBA container profile");
  }
  validate_config(config);
  if (sample_count_u64 < 2 ||
      sample_count_u64 > static_cast<std::uint64_t>(
                             std::numeric_limits<std::size_t>::max()) ||
      symbol_count == 0 || center_count == 0 || center_count > 65535U ||
      center_count > symbol_count || !std::isfinite(first_value)) {
    throw std::invalid_argument("invalid ABBA container counts");
  }
  const std::uint64_t expected_u64 =
      static_cast<std::uint64_t>(kHeaderBytes + kChecksumBytes) +
      static_cast<std::uint64_t>(center_count) * 16U +
      static_cast<std::uint64_t>(symbol_count) * 2U;
  if (expected_u64 != size) {
    throw std::invalid_argument("ABBA container size mismatch");
  }
  const std::uint32_t stored_crc =
      static_cast<std::uint32_t>(data[size - 4]) |
      (static_cast<std::uint32_t>(data[size - 3]) << 8U) |
      (static_cast<std::uint32_t>(data[size - 2]) << 16U) |
      (static_cast<std::uint32_t>(data[size - 1]) << 24U);
  if (crc32(data, size - kChecksumBytes) != stored_crc) {
    throw std::invalid_argument("ABBA container checksum mismatch");
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
      throw std::invalid_argument("invalid ABBA codebook center");
    }
    parsed.centers.push_back({length, increment});
  }
  parsed.symbols.reserve(symbol_count);
  for (std::uint32_t i = 0; i < symbol_count; ++i) {
    const auto symbol = read_le<std::uint16_t>(data, size, offset);
    if (symbol >= center_count) {
      throw std::invalid_argument("ABBA symbol outside codebook");
    }
    parsed.symbols.push_back(symbol);
  }
  if (offset != size - kChecksumBytes) {
    throw std::logic_error("ABBA parser offset mismatch");
  }
  parsed.accounting = make_accounting(center_count, symbol_count, size);
  return parsed;
}

}  // namespace

std::vector<Piece> compress(const double* values, const std::size_t count,
                            const Config& config) {
  validate_config(config);
  validate_values(values, count);
  const double tolerance = config.norm == 2U
                               ? config.compression_tolerance * config.compression_tolerance
                               : config.compression_tolerance;
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
      const double position = static_cast<double>(index - start);
      const double expected = values[start] + (increment / width) * position;
      const double residual = expected - values[index];
      error += config.norm == 2U ? residual * residual : std::fabs(residual);
    }
    const std::size_t interior = end - start - 1;
    if (error <= tolerance * static_cast<double>(interior) + epsilon &&
        static_cast<std::uint64_t>(interior) < config.max_len) {
      last_increment = increment;
      last_error = error;
      ++end;
    } else {
      pieces.push_back({static_cast<double>(interior), last_increment, last_error});
      start = end - 1;
    }
  }
  pieces.push_back(
      {static_cast<double>(end - start - 1), last_increment, last_error});
  for (const Piece& piece : pieces) {
    if (piece.length < 1.0) {
      throw std::runtime_error("ABBA segmentation produced a zero-length piece");
    }
  }
  return pieces;
}

Digitized digitize(const std::vector<Piece>& pieces,
                   const std::size_t original_sample_count,
                   const Config& config) {
  validate_config(config);
  if (pieces.empty() || pieces.size() < config.min_k ||
      original_sample_count < 2) {
    throw std::invalid_argument("invalid pieces for ABBA digitization");
  }
  double length_sum = 0.0;
  std::vector<double> increments;
  increments.reserve(pieces.size());
  for (const Piece& piece : pieces) {
    if (!std::isfinite(piece.length) || !std::isfinite(piece.increment) ||
        piece.length < 1.0) {
      throw std::invalid_argument("invalid ABBA piece");
    }
    length_sum += piece.length;
    increments.push_back(piece.increment);
  }
  if (length_sum + 1.0 != static_cast<double>(original_sample_count)) {
    throw std::invalid_argument("ABBA piece lengths do not match sample count");
  }

  const double mean =
      std::accumulate(increments.begin(), increments.end(), 0.0) /
      static_cast<double>(increments.size());
  double variance = 0.0;
  for (const double value : increments) {
    const double delta = value - mean;
    variance += delta * delta;
  }
  variance /= static_cast<double>(increments.size());
  double increment_std = std::sqrt(variance);
  if (increment_std <= std::numeric_limits<double>::epsilon()) {
    increment_std = 1.0;
  }
  std::vector<double> normalized;
  normalized.reserve(increments.size());
  for (const double value : increments) {
    normalized.push_back(value / increment_std);
  }
  std::vector<double> unique = normalized;
  std::sort(unique.begin(), unique.end());
  unique.erase(std::unique(unique.begin(), unique.end()), unique.end());
  if (unique.size() < config.min_k) {
    throw std::invalid_argument("canonical profile forbids sklearn fallback");
  }

  auto finish = [&](const std::vector<int>& labels,
                    const std::vector<Center>& raw_centers,
                    const double bound) {
    Digitized result;
    result.variance_bound = bound;
    result.raw_labels = labels;
    result.raw_centers = raw_centers;
    std::vector<std::size_t> counts(raw_centers.size(), 0U);
    for (const int label : labels) {
      if (label < 0 || static_cast<std::size_t>(label) >= counts.size()) {
        throw std::logic_error("ABBA clustering returned an invalid label");
      }
      ++counts[static_cast<std::size_t>(label)];
    }
    std::vector<std::size_t> first_order;
    for (const int label : labels) {
      const auto cluster = static_cast<std::size_t>(label);
      if (std::find(first_order.begin(), first_order.end(), cluster) ==
          first_order.end()) {
        first_order.push_back(cluster);
      }
    }
    std::stable_sort(first_order.begin(), first_order.end(),
                     [&counts](const std::size_t left, const std::size_t right) {
                       return counts[left] > counts[right];
                     });
    std::vector<std::uint16_t> old_to_new(raw_centers.size(), 0U);
    for (std::size_t index = 0; index < first_order.size(); ++index) {
      old_to_new[first_order[index]] = static_cast<std::uint16_t>(index);
      result.centers.push_back(raw_centers[first_order[index]]);
    }
    result.symbols.reserve(labels.size());
    for (const int label : labels) {
      result.symbols.push_back(old_to_new[static_cast<std::size_t>(label)]);
    }
    return result;
  };

  if (config.clustering == Config::ClusteringMethod::Incremental) {
    std::vector<std::size_t> order(pieces.size());
    std::iota(order.begin(), order.end(), 0U);
    std::stable_sort(order.begin(), order.end(), [&](std::size_t left, std::size_t right) {
      const double l = config.symmetric ? std::fabs(increments[left]) : increments[left];
      const double r = config.symmetric ? std::fabs(increments[right]) : increments[right];
      return l < r || (l == r && left < right);
    });
    std::vector<int> labels(pieces.size(), -1);
    std::vector<Center> centers;
    std::size_t begin = 0U;
    std::size_t end = 0U;
    double center = increments[order.front()];
    const auto weighted_median = [](std::vector<double> values,
                                    const std::vector<double>& weights) {
      std::vector<std::size_t> indices(values.size());
      std::iota(indices.begin(), indices.end(), 0U);
      std::stable_sort(indices.begin(), indices.end(), [&](std::size_t left, std::size_t right) {
        return values[left] < values[right];
      });
      double total = std::accumulate(weights.begin(), weights.end(), 0.0);
      double cumulative = 0.0;
      for (std::size_t p = 0; p < indices.size(); ++p) {
        cumulative += weights[indices[p]];
        if (cumulative > total / 2.0) return values[indices[p]];
        if (cumulative == total / 2.0 && p + 1U < indices.size()) {
          return (values[indices[p]] + values[indices[p + 1U]]) / 2.0;
        }
      }
      return values[indices.back()];
    };
    bool sign_change = false;
    bool sign_sorted = false;
    double last_sign = std::copysign(1.0, center);
    while (end < order.size()) {
      const double old_center = center;
      double error = std::numeric_limits<double>::infinity();
      std::size_t cluster_size = end - begin + 1U;
      if (end + 1U < order.size()) {
        if (std::copysign(1.0, increments[order[end + 1U]]) != last_sign) sign_change = true;
        ++cluster_size;
        std::vector<std::size_t> members(order.begin() + static_cast<std::ptrdiff_t>(begin),
                                         order.begin() + static_cast<std::ptrdiff_t>(end + 2U));
        std::sort(members.begin(), members.end());
        std::vector<double> values;
        for (const std::size_t index : members) values.push_back(increments[index]);
        if (!config.weighted) {
          if (config.norm == 1U) {
            auto sorted = values;
            std::sort(sorted.begin(), sorted.end());
            const std::size_t mid = sorted.size() / 2U;
            center = sorted.size() % 2U ? sorted[mid] : (sorted[mid - 1U] + sorted[mid]) / 2.0;
          } else {
            center = std::accumulate(values.begin(), values.end(), 0.0) /
                     static_cast<double>(values.size());
          }
        } else if (config.norm == 1U) {
          std::vector<double> cumulative_means;
          std::vector<double> weights;
          double sum = 0.0;
          for (std::size_t p = 0; p < values.size(); ++p) {
            sum += values[p];
            const double weight = static_cast<double>(p + 1U);
            cumulative_means.push_back(sum / weight);
            weights.push_back(weight);
          }
          center = weighted_median(cumulative_means, weights);
        } else {
          double numerator = 0.0;
          double denominator = 0.0;
          for (std::size_t p = 0; p < values.size(); ++p) {
            const double weight = static_cast<double>((values.size() + 1U) * values.size() / 2U) -
                                  static_cast<double>(p * (p + 1U) / 2U);
            numerator += values[p] * weight;
          }
          const double n_values = static_cast<double>(values.size());
          denominator = n_values * (n_values + 1.0) * (2.0 * n_values + 1.0) / 6.0;
          center = numerator / denominator;
        }
        double cumulative = 0.0;
        error = 0.0;
        for (std::size_t p = 0; p < values.size(); ++p) {
          cumulative += values[p];
          const double residual = config.weighted
              ? cumulative - static_cast<double>(p + 1U) * center
              : values[p] - center;
          if (config.norm == 1U && !config.weighted) {
            error = std::max(error, std::fabs(residual));
          } else {
            error += config.norm == 1U ? std::fabs(residual) : residual * residual;
          }
        }
      }
      if (error < static_cast<double>(cluster_size) * config.digitization_tolerance &&
          end + 1U < order.size()) {
        ++end;
        continue;
      }
      const int label = static_cast<int>(centers.size());
      double cluster_length_sum = 0.0;
      for (std::size_t p = begin; p <= end; ++p) {
        labels[order[p]] = label;
        cluster_length_sum += pieces[order[p]].length;
      }
      centers.push_back({cluster_length_sum / static_cast<double>(end - begin + 1U), old_center});
      if (config.symmetric && !sign_sorted && sign_change && end + 1U < order.size()) {
        std::stable_sort(order.begin() + static_cast<std::ptrdiff_t>(end + 1U), order.end(),
                         [&](std::size_t left, std::size_t right) {
          const double ls = increments[left] < 0.0 ? -1.0 : (increments[left] > 0.0 ? 1.0 : 0.0);
          const double rs = increments[right] < 0.0 ? -1.0 : (increments[right] > 0.0 ? 1.0 : 0.0);
          if (ls != rs) return ls < rs;
          const double la = std::fabs(increments[left]);
          const double ra = std::fabs(increments[right]);
          return la < ra || (la == ra && left < right);
        });
        sign_sorted = true;
      }
      begin = end + 1U;
      end = begin;
      if (begin < order.size()) {
        center = increments[order[begin]];
        last_sign = std::copysign(1.0, center);
      }
    }
    return finish(labels, centers, config.digitization_tolerance);
  }

  if (config.scl > 0.0 && config.scl != std::numeric_limits<double>::infinity()) {
    std::vector<double> lengths;
    lengths.reserve(pieces.size());
    for (const Piece& piece : pieces) lengths.push_back(piece.length);
    auto population_std_local = [](const std::vector<double>& values) {
      const double mean_local = std::accumulate(values.begin(), values.end(), 0.0) /
                                static_cast<double>(values.size());
      double sum = 0.0;
      for (const double value : values) { const double delta = value - mean_local; sum += delta * delta; }
      const double stddev = std::sqrt(sum / static_cast<double>(values.size()));
      return stddev <= std::numeric_limits<double>::epsilon() ? 1.0 : stddev;
    };
    const double length_std = population_std_local(lengths);
    const double n = static_cast<double>(original_sample_count);
    const double m = static_cast<double>(pieces.size());
    const double bound = (6.0 * (n - m) / (n * m)) *
                         ((config.digitization_tolerance * config.digitization_tolerance) / 0.04);
    std::vector<int> selected_labels;
    std::vector<Center> selected_centers;
    const std::size_t maximum_k = std::min<std::size_t>(config.max_k, pieces.size());
    for (std::size_t k = config.min_k; k <= maximum_k; ++k) {
      std::vector<Point2> normalized_points;
      for (const Piece& piece : pieces) {
        normalized_points.push_back({piece.length * config.scl / length_std,
                                     piece.increment / increment_std});
      }
      auto clustered = sklearn_style_kmeans(normalized_points, k);
      std::vector<int> labels = std::move(clustered.first);
      std::vector<Center> raw_centers(k, Center{});
      std::vector<std::size_t> counts(k, 0U);
      for (std::size_t i = 0; i < pieces.size(); ++i) {
        const auto cluster = static_cast<std::size_t>(labels[i]);
        raw_centers[cluster].length += pieces[i].length;
        raw_centers[cluster].increment += pieces[i].increment;
        ++counts[cluster];
      }
      double maximum_variance = 0.0;
      for (std::size_t c = 0; c < k; ++c) {
        if (counts[c] == 0U) continue;
        const double count = static_cast<double>(counts[c]);
        raw_centers[c].length /= count;
        raw_centers[c].increment /= count;
        double length_variance = 0.0;
        double increment_variance = 0.0;
        for (std::size_t i = 0; i < pieces.size(); ++i) if (labels[i] == static_cast<int>(c)) {
          const double dl = pieces[i].length / length_std - raw_centers[c].length / length_std;
          const double di = pieces[i].increment / increment_std - raw_centers[c].increment / increment_std;
          length_variance += dl * dl;
          increment_variance += di * di;
        }
        maximum_variance = std::max(maximum_variance,
            std::max(length_variance / count, increment_variance / count));
      }
      selected_labels = std::move(labels);
      selected_centers = std::move(raw_centers);
      if (config.digitization_tolerance != 0.0 && maximum_variance <= bound) break;
    }
    return finish(selected_labels, selected_centers, bound);
  }

  if (config.scl == std::numeric_limits<double>::infinity()) {
    std::vector<double> lengths;
    lengths.reserve(pieces.size());
    for (const Piece& piece : pieces) lengths.push_back(piece.length);
    const double mean_length = std::accumulate(lengths.begin(), lengths.end(), 0.0) /
                               static_cast<double>(lengths.size());
    double variance_length = 0.0;
    for (const double value : lengths) {
      const double delta = value - mean_length;
      variance_length += delta * delta;
    }
    double length_std = std::sqrt(variance_length / static_cast<double>(lengths.size()));
    if (length_std <= std::numeric_limits<double>::epsilon()) length_std = 1.0;
    std::vector<double> normalized_lengths;
    normalized_lengths.reserve(lengths.size());
    for (const double value : lengths) normalized_lengths.push_back(value / length_std);
    std::vector<double> unique_lengths = normalized_lengths;
    std::sort(unique_lengths.begin(), unique_lengths.end());
    unique_lengths.erase(std::unique(unique_lengths.begin(), unique_lengths.end()), unique_lengths.end());
    if (unique_lengths.size() < config.min_k) throw std::invalid_argument("not enough unique ABBA lengths");
    const double n = static_cast<double>(original_sample_count);
    const double m = static_cast<double>(pieces.size());
    const double bound = (6.0 * (n - m) / (n * m)) *
        ((config.digitization_tolerance * config.digitization_tolerance) / 0.04);
    const Output output = kmeans_1d_dp(normalized_lengths, config.min_k, config.max_k, bound, "linear");
    std::vector<Center> centers(output.Kopt);
    std::vector<std::size_t> counts(output.Kopt, 0U);
    for (std::size_t i = 0; i < pieces.size(); ++i) {
      const auto cluster = static_cast<std::size_t>(output.cluster[i]);
      centers[cluster].length += pieces[i].length;
      centers[cluster].increment += pieces[i].increment;
      ++counts[cluster];
    }
    for (std::size_t c = 0; c < centers.size(); ++c) {
      const double count = static_cast<double>(counts[c]);
      centers[c].length /= count;
      centers[c].increment /= count;
    }
    return finish(output.cluster, centers, bound);
  }

  const double n = static_cast<double>(original_sample_count);
  const double m = static_cast<double>(pieces.size());
  const double bound =
      (6.0 * (n - m) / (n * m)) *
      ((config.digitization_tolerance * config.digitization_tolerance) / 0.04);
  const Output output = kmeans_1d_dp(normalized, config.min_k, config.max_k,
                                     bound, "linear");

  std::vector<Center> raw_centers(output.Kopt);
  std::vector<std::size_t> counts(output.Kopt, 0);
  for (std::size_t cluster = 0; cluster < output.Kopt; ++cluster) {
    raw_centers[cluster].increment =
        output.centres[cluster] * increment_std;
  }
  for (std::size_t index = 0; index < pieces.size(); ++index) {
    const auto cluster = static_cast<std::size_t>(output.cluster[index]);
    if (cluster >= output.Kopt) {
      throw std::logic_error("CKmeans returned an invalid label");
    }
    raw_centers[cluster].length += pieces[index].length;
    ++counts[cluster];
  }
  for (std::size_t cluster = 0; cluster < output.Kopt; ++cluster) {
    raw_centers[cluster].length /= static_cast<double>(counts[cluster]);
  }

  return finish(output.cluster, raw_centers, bound);
}

std::vector<Center> quantize(const std::vector<Center>& pieces) {
  if (pieces.empty()) {
    throw std::invalid_argument("cannot quantize an empty ABBA stream");
  }
  std::vector<Center> result = pieces;
  if (result.size() == 1) {
    result[0].length = round_ties_even(result[0].length);
  } else {
    for (std::size_t index = 0; index + 1 < result.size(); ++index) {
      const double correction =
          round_ties_even(result[index].length) - result[index].length;
      result[index].length =
          round_ties_even(result[index].length + correction);
      result[index + 1].length -= correction;
      if (result[index].length == 0.0) {
        result[index].length = 1.0;
        result[index + 1].length -= 1.0;
      }
    }
    result.back().length = round_ties_even(result.back().length);
  }
  for (const Center& piece : result) {
    if (!std::isfinite(piece.length) || !std::isfinite(piece.increment) ||
        piece.length < 1.0 || piece.length != std::floor(piece.length)) {
      throw std::invalid_argument("invalid quantized ABBA piece");
    }
  }
  return result;
}

std::vector<double> reconstruct(const double first_value,
                                const std::vector<Center>& pieces,
                                const std::size_t original_sample_count) {
  if (!std::isfinite(first_value) || original_sample_count < 2) {
    throw std::invalid_argument("invalid ABBA reconstruction request");
  }
  std::vector<double> result;
  result.reserve(original_sample_count);
  result.push_back(first_value);
  for (const Center& piece : pieces) {
    if (!std::isfinite(piece.length) || !std::isfinite(piece.increment) ||
        piece.length < 1.0 || piece.length != std::floor(piece.length) ||
        piece.length > static_cast<double>(
                           std::numeric_limits<std::size_t>::max())) {
      throw std::invalid_argument("invalid ABBA reconstruction piece");
    }
    const auto length = static_cast<std::size_t>(piece.length);
    const double start = result.back();
    for (std::size_t position = 1; position <= length; ++position) {
      const double value =
          start + (static_cast<double>(position) / piece.length) * piece.increment;
      if (!std::isfinite(value)) {
        throw std::invalid_argument("non-finite ABBA reconstruction");
      }
      result.push_back(value);
    }
    if (result.size() > original_sample_count) {
      throw std::invalid_argument("ABBA reconstruction exceeds declared length");
    }
  }
  if (result.size() != original_sample_count) {
    throw std::invalid_argument("ABBA reconstruction length mismatch");
  }
  return result;
}

TransformResult transform(const double* values, const std::size_t count,
                          const Config& config) {
  TransformResult result;
  result.pieces = compress(values, count, config);
  result.digitized = digitize(result.pieces, count, config);
  std::vector<Center> expanded;
  expanded.reserve(result.digitized.symbols.size());
  for (const std::uint16_t symbol : result.digitized.symbols) {
    expanded.push_back(result.digitized.centers[symbol]);
  }
  result.quantized_pieces = quantize(expanded);
  result.reconstructed =
      reconstruct(values[0], result.quantized_pieces, count);
  return result;
}

std::vector<std::uint8_t> encode(const double* values, const std::size_t count,
                                 const Config& config,
                                 Accounting* accounting) {
  if (count > static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max()) +
                  1ULL) {
    throw std::invalid_argument("ABBA input is too large for container v1");
  }
  const TransformResult transformed = transform(values, count, config);
  const std::size_t symbol_count = transformed.digitized.symbols.size();
  const std::size_t center_count = transformed.digitized.centers.size();
  const std::size_t total_size =
      kHeaderBytes + center_count * 16U + symbol_count * 2U + kChecksumBytes;
  std::vector<std::uint8_t> output;
  output.reserve(total_size);
  output.push_back(static_cast<std::uint8_t>('A'));
  output.push_back(static_cast<std::uint8_t>('B'));
  output.push_back(static_cast<std::uint8_t>('B'));
  output.push_back(static_cast<std::uint8_t>('A'));
  append_le<std::uint16_t>(output, kVersion);
  append_le<std::uint16_t>(output, kProfileFlags);
  append_le<std::uint64_t>(output, static_cast<std::uint64_t>(count));
  append_le<std::uint32_t>(output, static_cast<std::uint32_t>(symbol_count));
  append_le<std::uint32_t>(output, static_cast<std::uint32_t>(center_count));
  append_le<std::uint64_t>(output, double_bits(config.compression_tolerance));
  append_le<std::uint64_t>(output, double_bits(config.digitization_tolerance));
  append_le<std::uint64_t>(output, config.max_len);
  append_le<std::uint32_t>(output, config.min_k);
  append_le<std::uint32_t>(output, config.max_k);
  append_le<std::uint64_t>(output, double_bits(values[0]));
  for (const Center& center : transformed.digitized.centers) {
    append_le<std::uint64_t>(output, double_bits(center.length));
    append_le<std::uint64_t>(output, double_bits(center.increment));
  }
  for (const std::uint16_t symbol : transformed.digitized.symbols) {
    append_le<std::uint16_t>(output, symbol);
  }
  append_le<std::uint32_t>(output, crc32(output.data(), output.size()));
  if (output.size() != total_size) {
    throw std::logic_error("ABBA container size mismatch after encoding");
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

Accounting inspect_accounting(const std::uint8_t* encoded,
                              const std::size_t size) {
  return parse_container(encoded, size).accounting;
}

std::size_t max_encoded_size(const std::size_t sample_count) {
  if (sample_count < 2) {
    return 0;
  }
  const std::size_t pieces = sample_count - 1;
  if (pieces > (std::numeric_limits<std::size_t>::max() -
                kHeaderBytes - kChecksumBytes) /
                   18U) {
    return 0;
  }
  return kHeaderBytes + pieces * 18U + kChecksumBytes;
}

}  // namespace abba
