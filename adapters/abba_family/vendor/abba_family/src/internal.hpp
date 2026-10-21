// SPDX-License-Identifier: MIT AND BSD-3-Clause
#pragma once
#include "abba_family.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <functional>
#include <random>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
namespace abba_family {
// Avoid nested initializer-list temporaries: GCC 11 loses their ownership
// when a later element throws. Sequential pushes have normal RAII cleanup.
template <class... T> Json make_array(T &&...items) {
  Json out = Json::array();
  (out.push_back(std::forward<T>(items)), ...);
  return out;
}
using V = std::vector<double>;
using P = std::array<double, 2>;
using Points = std::vector<P>;
using Pieces = std::vector<std::array<double, 3>>;
using Ids = std::vector<std::size_t>;
constexpr std::size_t MAX_SAMPLES = 1048576, MAX_OUTPUT = 4194304,
                      MAX_FRAME = 268435456, MAX_CENTERS = 65535;
inline void require(bool b, const char *msg) {
  if (!b)
    throw std::invalid_argument(msg);
}
inline double number(const Json &j, const char *k, double d) {
  if (j.contains(k))
    require(j[k].is_number(), "numeric parameter required");
  double x = j.value(k, d);
  require(std::isfinite(x), "nonfinite configuration");
  return x;
}
inline std::size_t integer(const Json &j, const char *k, std::size_t d,
                           std::size_t hi = MAX_SAMPLES) {
  if (!j.contains(k))
    return d;
  require(j[k].is_number_integer(), "integer parameter required");
  auto n = j[k].get<std::int64_t>();
  require(n >= 0 && std::uint64_t(n) <= hi, "integer parameter out of range");
  return std::size_t(n);
}
inline std::size_t job_count(const Json &c) {
  if (!c.contains("n_jobs"))
    return 1;
  require(c["n_jobs"].is_number_integer(), "integer jobs required");
  auto n = c["n_jobs"].get<std::int64_t>();
  require(n == -1 || (n > 0 && n <= 256), "worker limit");
  return n == -1
             ? std::min(256U, std::max(1U, std::thread::hardware_concurrency()))
             : std::size_t(n);
}
inline double round_even(double x) {
  require(std::isfinite(x), "nonfinite rounding");
  double a = std::floor(x), d = x - a;
  return d < .5
             ? a
             : (d > .5 ? a + 1 : (std::fmod(std::abs(a), 2) == 0 ? a : a + 1));
}
inline double dist(P a, P b) {
  double x = a[0] - b[0], y = a[1] - b[1];
  return x * x + y * y;
}
V values(const Json &, bool allow_nan = false);
std::vector<V> collection(const Json &, bool &single);
V fill(V, const std::string &, bool = false);
Ids argsort(const V &);
double sum(const V &);
double mean(const V &);
double stddev(const V &);
double median(V);
Pieces segment(const V &, double, std::size_t, int, bool);
Pieces compression(const V &, const Json &, const std::string &);
Points points(const Json &);
Points first2(const Pieces &);
struct Cluster {
  Ids labels;
  Points centers;
  Json splist = Json::array();
};
Cluster aggregate(const Points &, const std::string &, double, bool,
                  bool = false);
Cluster kmeans(const Points &, std::size_t, unsigned, unsigned, double, int);
Cluster abba_digitize(const Points &, const Json &);
Cluster fabba_digitize(const Points &, const Json &);
Cluster qabba_digitize(const Points &, const Json &);
Json quantizer(const V &, int);
V dequantize(const Json &);
Json alphabet(std::size_t, const Json &, const std::string &);
Json symbolic(const Ids &, const Json &);
Ids symbol_ids(const Json &, const Json &);
Points grid(const Points &, const std::string &);
V reconstruct(const Points &, double, const std::string &);
Json image_fit(const Json &);
Json image_restore(const Json &, const Json &);
Json fit(const Json &);
Json inverse(const Json &, const Json &, const Json &);
Json model_transform(const Json &, const Json &);
Json symbol_stats(const Json &, const Json &, const std::string &, bool);
std::vector<std::uint8_t> symbol_pack(const Ids &, std::size_t,
                                      const std::string &, Json &);
Ids symbol_unpack(const std::vector<std::uint8_t> &, std::size_t, std::size_t,
                  const std::string &, const Json &);
std::vector<std::uint8_t> bytes_compress(const std::vector<std::uint8_t> &,
                                         const std::string &);
std::vector<std::uint8_t> bytes_decompress(const std::vector<std::uint8_t> &,
                                           const std::string &, std::size_t);
std::string hex(const std::vector<std::uint8_t> &);
std::vector<std::uint8_t> unhex(const std::string &);
void parallel(std::size_t, std::size_t,
              const std::function<void(std::size_t)> &);
} // namespace abba_family
