// SPDX-License-Identifier: MIT AND BSD-3-Clause
#include "internal.hpp"
#include <algorithm>
namespace abba_family {
namespace {
double np_sum(const double *a, std::size_t n) {
  if (n < 8) {
    double x = -0.;
    for (std::size_t i = 0; i < n; ++i)
      x += a[i];
    return x;
  }
  if (n <= 128) {
    double r[8];
    for (unsigned i = 0; i < 8; ++i)
      r[i] = a[i];
    std::size_t i = 8;
    for (; i + 8 <= n; i += 8)
      for (unsigned j = 0; j < 8; ++j)
        r[j] += a[i + j];
    double s =
        ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
    for (; i < n; ++i)
      s += a[i];
    return s;
  }
  std::size_t m = n / 2;
  m -= m % 8;
  return np_sum(a, m) + np_sum(a + m, n - m);
}
void flatten_image(const Json &j, Ids &shape, V &values, std::size_t depth) {
  if (j.is_array()) {
    require(depth < 32 && !j.empty(), "image dimension");
    if (shape.size() == depth)
      shape.push_back(j.size());
    require(shape[depth] == j.size(), "ragged image");
    for (auto &row : j)
      flatten_image(row, shape, values, depth + 1);
  } else {
    require(depth == shape.size(), "image shape");
    double x = j.get<double>();
    require(std::isfinite(x) && values.size() < MAX_SAMPLES,
            "image sample limit");
    values.push_back(x);
  }
}
Json nest(const V &data, const Ids &shape, std::size_t depth, std::size_t &at) {
  if (depth == shape.size()) {
    require(at < data.size(), "image count");
    return data[at++];
  }
  Json out = Json::array();
  for (std::size_t i = 0; i < shape[depth]; ++i)
    out.push_back(nest(data, shape, depth + 1, at));
  return out;
}
} // namespace
Json image_restore(const Json &model, const Json &reconstructed) {
  auto spec = model.at("image");
  auto shape = spec.at("shape").get<Ids>();
  require(!shape.empty() && shape.size() <= 32, "image shape depth");
  std::size_t n = 1;
  for (auto x : shape) {
    require(x > 0 && x <= MAX_SAMPLES / n, "image shape product");
    n *= x;
  }
  auto v = values(reconstructed);
  require(v.size() == n, "image reconstruction shape");
  double mean = spec.at("mean"), std = spec.at("std");
  require(std::isfinite(mean) && std::isfinite(std) && std > 0,
          "image normalization");
  for (auto &x : v) {
    double p = round_even(x * std + mean);
    p = std::fmod(p, 256);
    if (p < 0)
      p += 256;
    x = p;
  }
  std::size_t at = 0;
  return nest(v, shape, 0, at);
}
Json image_fit(const Json &request) {
  require(request.value("algorithm", std::string("fabba")) == "fabba",
          "image algorithm");
  Ids shape;
  V data;
  flatten_image(request.at("values"), shape, data, 0);
  require(data.size() >= 2, "image requires two values");
  double mean = 0, std = 1;
  if (request.value("adjust", true)) {
    mean = np_sum(data.data(), data.size()) / double(data.size());
    V centered;
    for (double x : data)
      centered.push_back((x - mean) * (x - mean));
    std = std::sqrt(np_sum(centered.data(), centered.size()) /
                    double(data.size()));
    if (std == 0)
      std = 1;
    for (double &x : data)
      x = (x - mean) / std;
  }
  Json r = request;
  r["algorithm"] = "fabba";
  r["values"] = data;
  auto result = fit(r);
  result["model"]["image"] = [&]() {
    Json result_object = Json::object();
    result_object["shape"] = shape;
    result_object["mean"] = mean;
    result_object["std"] = std;
    return result_object;
  }();
  result["image"] =
      image_restore(result.at("model"), result.at("reconstructed"));
  return result;
}
} // namespace abba_family
