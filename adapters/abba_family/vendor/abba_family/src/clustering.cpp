// SPDX-License-Identifier: MIT AND BSD-3-Clause
// Translated from frozen upstream classes. CKmeans itself is retained native
// code.
#include "Ckmeans.1d.dp.h"
#include "internal.hpp"
#include <algorithm>
#include <limits>
#include <numeric>
#include <set>
namespace abba_family {
namespace {
double uniform(std::mt19937 &g) {
  auto a = g() >> 5, b = g() >> 6;
  return (double(a) * 67108864. + double(b)) / 9007199254740992.;
}
std::size_t bounded(std::mt19937 &g, std::size_t max) {
  std::uint32_t mask = std::uint32_t(max);
  mask |= mask >> 1;
  mask |= mask >> 2;
  mask |= mask >> 4;
  mask |= mask >> 8;
  mask |= mask >> 16;
  std::uint32_t x;
  do {
    x = g() & mask;
  } while (x > max);
  return x;
}
Points centers_means(const Points &p, const Ids &labels, std::size_t k) {
  Points z(k, {0, 0});
  Ids counts(k);
  for (std::size_t i = 0; i < p.size(); ++i) {
    require(labels[i] < k, "invalid label");
    z[labels[i]][0] += p[i][0];
    z[labels[i]][1] += p[i][1];
    ++counts[labels[i]];
  }
  for (std::size_t c = 0; c < k; ++c) {
    require(counts[c] > 0, "empty learned cluster");
    z[c][0] /= double(counts[c]);
    z[c][1] /= double(counts[c]);
  }
  return z;
}
Cluster ck(const Points &p, std::size_t min, std::size_t max, double bound,
           int col) {
  V data;
  for (auto z : p)
    data.push_back(z[col]);
  auto o = kmeans_1d_dp(data, min, max, bound, "linear");
  Cluster out;
  for (auto label : o.cluster) {
    require(label >= 0 && std::size_t(label) < o.Kopt, "CKmeans label");
    out.labels.push_back(std::size_t(label));
  }
  out.centers = centers_means(p, out.labels, o.Kopt);
  for (std::size_t i = 0; i < o.Kopt; ++i)
    out.centers[i][col] = o.centres[i];
  return out;
}
double maxvar(const Points &p, const Cluster &cl) {
  double out = 0;
  for (std::size_t c = 0; c < cl.centers.size(); ++c)
    for (int d = 0; d < 2; ++d) {
      V a;
      for (std::size_t i = 0; i < p.size(); ++i)
        if (cl.labels[i] == c)
          a.push_back(p[i][d] - cl.centers[c][d]);
      if (a.size() > 1) {
        double v = stddev(a);
        out = std::max(out, v * v);
      }
    }
  return out;
}
Cluster incremental(const Points &p, const Json &c) {
  bool symmetric = c.value("symmetric", true),
       weighted = c.value("weighted", false);
  int norm = c.value("norm", 2);
  double tolerance = .1;
  if (c.contains("tol"))
    tolerance = c["tol"].is_array() ? c["tol"].back().get<double>()
                                    : c["tol"].get<double>();
  V keys;
  for (auto z : p)
    keys.push_back(symmetric ? std::abs(z[1]) : z[1]);
  Ids order = argsort(keys);
  Cluster out;
  out.labels.resize(p.size());
  std::size_t start = 0, end = 0;
  double m = p[order[0]][1];
  int lastsign = (m > 0) - (m < 0);
  bool signchange = false, signsorted = false;
  while (end < p.size()) {
    double old = m, error = std::numeric_limits<double>::infinity();
    std::size_t ell = end - start + 2;
    if (end + 1 < p.size()) {
      Ids idx(order.begin() + std::ptrdiff_t(start),
              order.begin() + std::ptrdiff_t(end + 2));
      std::sort(idx.begin(), idx.end());
      V v;
      for (auto i : idx)
        v.push_back(p[i][1]);
      double next = p[order[end + 1]][1];
      if ((next > 0) - (next < 0) != lastsign)
        signchange = true;
      if (!weighted) {
        m = norm == 1 ? median(v) : mean(v);
      } else if (norm == 2) {
        double num = 0,
               den = double(ell) * double(ell + 1) * double(2 * ell + 1) / 6;
        for (std::size_t i = 0; i < ell; ++i)
          num += v[i] *
                 (double(ell + 1) * double(ell) / 2 - double(i * (i + 1)) / 2);
        m = num / den;
      } else {
        V cum(ell);
        double acc = 0;
        for (std::size_t i = 0; i < ell; ++i) {
          acc += v[i];
          cum[i] = acc / double(i + 1);
        }
        Ids q = argsort(cum);
        double midpoint = double(ell * (ell + 1)) / 4;
        double maxw = double(ell);
        if (maxw > midpoint)
          m = cum.back();
        else {
          double w = 0;
          m = cum[q.back()];
          for (std::size_t j = 0; j < q.size(); ++j) {
            w += double(q[j] + 1);
            if (w >= midpoint) {
              m = w == midpoint && j + 1 < q.size()
                      ? (cum[q[j]] + cum[q[j + 1]]) / 2
                      : cum[q[j]];
              break;
            }
          }
        }
      }
      error = 0;
      double acc = 0;
      for (std::size_t i = 0; i < ell; ++i) {
        acc += v[i];
        double e = weighted ? acc - double(i + 1) * m : v[i] - m;
        if (norm == 1) {
          if (weighted)
            error += std::abs(e);
          else
            error = std::max(error, std::abs(e));
        } else
          error += e * e;
      }
    }
    if (error < double(ell) * tolerance && end + 1 < p.size())
      ++end;
    else {
      P center{0, old};
      for (std::size_t j = start; j <= end; ++j) {
        center[0] += p[order[j]][0];
        out.labels[order[j]] = out.centers.size();
      }
      center[0] /= double(end - start + 1);
      out.centers.push_back(center);
      if (symmetric && !signsorted && signchange) {
        std::stable_sort(order.begin() + std::ptrdiff_t(end + 1), order.end(),
                         [&](auto a, auto b) {
                           double x = p[a][1], y = p[b][1];
                           int sx = (x > 0) - (x < 0), sy = (y > 0) - (y < 0);
                           return sx == sy ? std::abs(x) < std::abs(y)
                                           : sx < sy;
                         });
        signsorted = true;
      }
      start = end + 1;
      end = start;
      if (start < p.size())
        m = p[order[start]][1];
    }
  }
  return out;
}
} // namespace
Cluster kmeans(const Points &in, std::size_t k, unsigned seed, unsigned maxiter,
               double tol, int restarts) {
  require(!in.empty() && k >= 1 && k <= in.size() && k <= MAX_CENTERS &&
              maxiter > 0 && maxiter <= 10000,
          "kmeans limits");
  require(k <= 100000000 / in.size() / maxiter / std::size_t(restarts),
          "kmeans work limit");
  Points p = in;
  P avg{0, 0};
  for (auto z : p) {
    avg[0] += z[0];
    avg[1] += z[1];
  }
  for (auto &z : avg)
    z /= double(p.size());
  double variance = 0;
  for (auto &z : p) {
    z[0] -= avg[0];
    z[1] -= avg[1];
    variance += z[0] * z[0] + z[1] * z[1];
  }
  double threshold = variance / double(p.size()) / 2 * tol;
  std::mt19937 rng(seed);
  Cluster best;
  double bestinertia = std::numeric_limits<double>::infinity();
  for (int restart = 0; restart < restarts; ++restart) {
    Cluster cur;
    std::size_t first =
        std::min(std::size_t(uniform(rng) * double(p.size())), p.size() - 1);
    cur.centers.push_back(p[first]);
    V closest;
    for (auto z : p)
      closest.push_back(dist(z, p[first]));
    double pot = sum(closest);
    std::size_t trials = 2 + std::size_t(std::log(double(k)));
    while (cur.centers.size() < k) {
      double bestpot = std::numeric_limits<double>::infinity();
      V bestd;
      P chosen = p[0];
      for (std::size_t t = 0; t < trials; ++t) {
        double target = uniform(rng) * pot, acc = 0;
        std::size_t index = p.size() - 1;
        for (std::size_t i = 0; i < p.size(); ++i) {
          acc += closest[i];
          if (acc >= target) {
            index = i;
            break;
          }
        }
        V nd;
        for (std::size_t i = 0; i < p.size(); ++i)
          nd.push_back(std::min(closest[i], dist(p[i], p[index])));
        double np = sum(nd);
        if (np < bestpot) {
          bestpot = np;
          bestd = std::move(nd);
          chosen = p[index];
        }
      }
      cur.centers.push_back(chosen);
      closest = std::move(bestd);
      pot = bestpot;
    }
    cur.labels.assign(p.size(), std::size_t(-1));
    bool strict = false;
    auto assign = [&]() {
      Ids lab;
      for (auto z : p) {
        std::size_t b = 0;
        double d = dist(z, cur.centers[0]);
        for (std::size_t c = 1; c < k; ++c) {
          double v = dist(z, cur.centers[c]);
          if (v < d) {
            d = v;
            b = c;
          }
        }
        lab.push_back(b);
      }
      return lab;
    };
    for (unsigned it = 0; it < maxiter; ++it) {
      Ids next = assign(), counts(k);
      Points centers(k, {0, 0});
      for (std::size_t i = 0; i < p.size(); ++i) {
        ++counts[next[i]];
        centers[next[i]][0] += p[i][0];
        centers[next[i]][1] += p[i][1];
      }
      V distances;
      for (std::size_t i = 0; i < p.size(); ++i)
        distances.push_back(dist(p[i], cur.centers[next[i]]));
      if (*std::max_element(distances.begin(), distances.end()) > 0) {
        Ids far = argsort(distances);
        std::size_t offset = 0;
        for (std::size_t c = 0; c < k; ++c)
          if (!counts[c]) {
            auto i = far[far.size() - 1 - offset++];
            auto old = next[i];
            centers[old][0] -= p[i][0];
            centers[old][1] -= p[i][1];
            --counts[old];
            centers[c] = p[i];
            counts[c] = 1;
          }
      }
      std::size_t largest = std::size_t(
          std::max_element(counts.begin(), counts.end()) - counts.begin());
      for (std::size_t c = 0; c < k; ++c)
        if (counts[c]) {
          centers[c][0] /= double(counts[c]);
          centers[c][1] /= double(counts[c]);
        }
      for (std::size_t c = 0; c < k; ++c)
        if (!counts[c])
          centers[c] = centers[largest];
      double shift = 0;
      for (std::size_t c = 0; c < k; ++c)
        shift += dist(cur.centers[c], centers[c]);
      strict = next == cur.labels;
      cur.labels = std::move(next);
      cur.centers = std::move(centers);
      if (strict || shift <= threshold)
        break;
    }
    if (!strict)
      cur.labels = assign();
    double inertia = 0;
    for (std::size_t i = 0; i < p.size(); ++i)
      inertia += dist(p[i], cur.centers[cur.labels[i]]);
    bool same = false;
    if (!best.labels.empty()) {
      std::vector<std::size_t> map(k, std::size_t(-1));
      same = true;
      for (std::size_t i = 0; i < p.size(); ++i) {
        auto x = cur.labels[i], y = best.labels[i];
        if (map[x] == std::size_t(-1))
          map[x] = y;
        else if (map[x] != y) {
          same = false;
          break;
        }
      }
    }
    if (inertia < bestinertia && !same) {
      bestinertia = inertia;
      best = std::move(cur);
    }
  }
  for (auto &z : best.centers) {
    z[0] += avg[0];
    z[1] += avg[1];
  }
  return best;
}
Cluster aggregate(const Points &data, const std::string &sorting, double alpha,
                  bool fabba, bool compiled) {
  require(!data.empty() && std::isfinite(alpha) && alpha >= 0,
          "invalid aggregate config");
  Points p = data;
  V key(p.size());
  bool pca = sorting == "pca", lex = sorting == "lexi",
       one = sorting == "1-norm";
  require(pca || lex || one || sorting == "2-norm" || sorting == "norm",
          "unknown sorting");
  if (pca) {
    P m{0, 0};
    for (auto z : p) {
      m[0] += z[0];
      m[1] += z[1];
    }
    m[0] /= double(p.size());
    m[1] /= double(p.size());
    double a = 0, b = 0, d = 0;
    for (auto &z : p) {
      z[0] -= m[0];
      z[1] -= m[1];
      a += z[0] * z[0];
      b += z[0] * z[1];
      d += z[1] * z[1];
    }
    if (p.size() < 2 || a + d == 0 ||
        (fabba && std::all_of(data.begin(), data.end(),
                              [&](P z) { return z == data[0]; }))) {
      require(fabba, "undefined QABBA PCA");
      p = data;
      pca = false;
    } else {
      double theta = .5 * std::atan2(2 * b, a - d);
      P eig{std::cos(theta), std::sin(theta)};
      for (std::size_t i = 0; i < p.size(); ++i)
        key[i] = p[i][0] * eig[0] + p[i][1] * eig[1];
      double sign = key[0] > 0 ? -1 : (key[0] < 0 ? 1 : 0);
      for (auto &z : key)
        z *= sign;
    }
  }
  if (!pca)
    for (std::size_t i = 0; i < p.size(); ++i)
      key[i] = one ? std::abs(p[i][0]) + std::abs(p[i][1])
                   : std::sqrt(p[i][0] * p[i][0] + p[i][1] * p[i][1]);
  Ids order;
  if (lex) {
    order.resize(p.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(),
                     [&](auto a, auto b) { return p[a] < p[b]; });
  } else
    order = argsort(key);
  std::size_t work = 0;
  Cluster out;
  out.labels.assign(p.size(), std::size_t(-1));
  for (std::size_t pos = 0; pos < order.size(); ++pos) {
    auto sp = order[pos];
    if (out.labels[sp] != std::size_t(-1))
      continue;
    auto label = out.centers.size();
    out.labels[sp] = label;
    std::size_t count = 1;
    for (std::size_t j = pos; j < order.size(); ++j) {
      require(++work <= 100000000, "aggregation work limit");
      auto idx = order[j];
      if (out.labels[idx] != std::size_t(-1))
        continue;
      bool pre = !fabba || sorting == "norm" || sorting == "pca";
      if (pre && key[idx] - key[sp] > alpha)
        break;
      double d = dist(p[idx], p[sp]);
      if (d <= alpha * alpha) {
        out.labels[idx] = label;
        ++count;
      } else if (!pre) {
        if (lex) {
          double dx = p[idx][0] - p[sp][0];
          if (dx > alpha || (dx == alpha && p[idx][1] > p[sp][1]))
            break;
        } else if (key[idx] - key[sp] > alpha)
          break;
      }
    }
    out.centers.push_back(data[sp]);
    out.splist.push_back(
        make_array(double(sp), double(label),
                   fabba && !compiled && (sorting == "2-norm" || one || lex)
                       ? 1.
                       : double(count),
                   (fabba && compiled && pca ? p[sp][0] : data[sp][0]),
                   (fabba && compiled && pca ? p[sp][1] : data[sp][1])));
  }
  require(out.centers.size() <= MAX_CENTERS, "codebook limit");
  return out;
}
Cluster abba_digitize(const Points &p, const Json &c) {
  auto min = integer(c, "min_k", 2, MAX_CENTERS),
       max = integer(c, "max_k", 100, MAX_CENTERS);
  require(min >= 1 && min <= max && p.size() >= min, "ABBA k bounds");
  double tol = .1;
  if (c.contains("tol"))
    tol = c["tol"].is_array() ? c["tol"].back().get<double>()
                              : c["tol"].get<double>();
  require(std::isfinite(tol) && tol >= 0, "ABBA tolerance");
  std::string method = c.value("c_method", "kmeans");
  require(method == "kmeans" || method == "incremental", "ABBA method");
  Cluster out;
  if (method == "incremental")
    out = incremental(p, c);
  else {
    double scl = c.contains("scl") && c["scl"].is_string()
                     ? std::numeric_limits<double>::infinity()
                     : number(c, "scl", 0);
    require(scl >= 0, "ABBA scl");
    bool one = scl == 0 || std::isinf(scl);
    int col = scl == 0 ? 1 : 0;
    V x, y;
    for (auto z : p) {
      x.push_back(z[0]);
      y.push_back(z[1]);
    }
    double sx = stddev(x), sy = stddev(y);
    if (sx <= std::numeric_limits<double>::epsilon())
      sx = 1;
    if (sy <= std::numeric_limits<double>::epsilon())
      sy = 1;
    Points z;
    for (auto v : p)
      z.push_back(one ? P{col == 0 ? v[0] / sx : 0, col == 1 ? v[1] / sy : 0}
                      : P{v[0] / sx * scl, v[1] / sy});
    double n = sum(x) + 1, m = double(p.size());
    double bound = (6 * (n - m) / (n * m)) * ((tol * tol) / (.2 * .2));
    std::set<double> unique;
    for (auto v : z)
      unique.insert(v[col]);
    if (one && unique.size() >= min) {
      out = ck(z, min, max, bound, col);
    } else {
      std::size_t k = tol == 0 ? std::min(max, p.size()) : min;
      for (;;) {
        out = kmeans(z, k, c.value("seed", true) ? 0 : std::random_device{}(),
                     300, 0, 10);
        if (tol == 0 || k >= max || maxvar(z, out) <= bound)
          break;
        ++k;
      }
    }
    if (one) {
      Points means = centers_means(p, out.labels, out.centers.size());
      for (std::size_t i = 0; i < means.size(); ++i)
        means[i][col] = out.centers[i][col] * (col == 0 ? sx : sy);
      out.centers = std::move(means);
    } else
      for (auto &center : out.centers) {
        center[0] = center[0] * sx / scl;
        center[1] *= sy;
      }
  }
  Ids counts(out.centers.size()), first(out.centers.size(), p.size());
  for (std::size_t i = 0; i < out.labels.size(); ++i) {
    ++counts[out.labels[i]];
    first[out.labels[i]] = std::min(first[out.labels[i]], i);
  }
  Ids order(counts.size());
  std::iota(order.begin(), order.end(), 0);
  std::sort(order.begin(), order.end(), [&](auto a, auto b) {
    return counts[a] == counts[b] ? first[a] < first[b] : counts[a] > counts[b];
  });
  Ids map(order.size());
  Points centers;
  for (std::size_t i = 0; i < order.size(); ++i) {
    map[order[i]] = i;
    centers.push_back(out.centers[order[i]]);
  }
  for (auto &x : out.labels)
    x = map[x];
  out.centers = std::move(centers);
  return out;
}
Cluster fabba_digitize(const Points &p, const Json &c) {
  V x, y;
  for (auto z : p) {
    x.push_back(z[0]);
    y.push_back(z[1]);
  }
  double sx = stddev(x), sy = stddev(y);
  if (sx == 0)
    sx = 1;
  if (sy == 0)
    sy = 1;
  double scl = number(c, "scl", 1);
  require(scl >= 0, "fABBA scl");
  Points z;
  for (auto v : p)
    z.push_back({v[0] * scl / sx, v[1] / sy});
  auto out = aggregate(z, c.value("sorting", "2-norm"), number(c, "alpha", .5),
                       true, c.value("source_backend", "python") == "cython");
  out.centers = centers_means(p, out.labels, out.centers.size());
  return out;
}
Cluster qabba_digitize(const Points &p, const Json &c) {
  V x, y;
  for (auto z : p) {
    x.push_back(z[0]);
    y.push_back(z[1]);
  }
  double sx = stddev(x), sy = stddev(y);
  if (sx == 0)
    sx = 1;
  if (sy == 0)
    sy = 1;
  double scl = number(c, "scale_length", 1);
  require(scl >= 0, "QABBA scale_length");
  if (scl == 0)
    scl = 1;
  const double length_scale = scl / sx, increment_scale = 1. / sy;
  Points z;
  for (auto v : p)
    z.push_back({v[0] * length_scale, v[1] * increment_scale});
  std::string mode = c.value("digitizer", "agg");
  Cluster out;
  if (mode == "agg")
    out = aggregate(z, c.value("sorting", "norm"),
                    c.contains("alpha") && c["alpha"].is_null()
                        ? .5
                        : number(c, "alpha", .5),
                    false);
  else {
    require(mode == "kmeans" || mode == "f-kmeans", "QABBA digitizer");
    std::set<P> unique(z.begin(), z.end());
    std::size_t k =
        std::min(integer(c, "n_symbols", 2, MAX_CENTERS), unique.size());
    unsigned seed = unsigned(integer(c, "random_state", 42, 4294967295ULL));
    unsigned iterations = unsigned(integer(c, "max_iter", 100, 10000));
    if (mode == "kmeans")
      out = kmeans(z, k, seed, iterations, 1e-4, 1);
    else {
      double r = number(c, "sample_rate", .5);
      require(r > 0 && r <= 1, "sample rate");
      std::size_t n = std::max(k, std::size_t(r * double(z.size())));
      Ids perm(z.size());
      std::iota(perm.begin(), perm.end(), 0);
      std::mt19937 rng(seed);
      for (std::size_t i = perm.size(); i > 1; --i)
        std::swap(perm[i - 1], perm[bounded(rng, i - 1)]);
      perm.resize(n);
      std::sort(perm.begin(), perm.end());
      Points sample;
      for (auto i : perm)
        sample.push_back(z[i]);
      out = kmeans(sample, k, seed, iterations, 1e-4, 1);
      Ids labels(z.size());
      for (std::size_t i = 0; i < z.size(); ++i) {
        std::size_t b = 0;
        double d = dist(z[i], out.centers[0]);
        for (std::size_t j = 1; j < k; ++j) {
          double t = dist(z[i], out.centers[j]);
          if (t < d) {
            d = t;
            b = j;
          }
        }
        labels[i] = b;
      }
      for (std::size_t j = 0; j < perm.size(); ++j)
        labels[perm[j]] = out.labels[j];
      out.labels = std::move(labels);
      out.centers = centers_means(z, out.labels, k);
    }
  }
  for (auto &v : out.centers) {
    v[0] /= length_scale;
    v[1] /= increment_scale;
  }
  return out;
}
Json quantizer(const V &x, int bits) {
  require(bits >= 1 && bits <= 64 && !x.empty(), "quantizer bits");
  double lo = *std::min_element(x.begin(), x.end()),
         hi = *std::max_element(x.begin(), x.end());
  double qmin = -std::ldexp(1., bits - 1), qmax = std::ldexp(1., bits - 1) - 1;
  if (hi == lo)
    hi = lo + 1e-12;
  double scale = (hi - lo) / (qmax - qmin),
         zero = (lo * qmax - hi * qmin) / (qmax - qmin);
  require(std::isfinite(scale) && scale > 0 && std::isfinite(zero),
          "unrepresentable quantizer scale");
  V q;
  for (double v : x) {
    double rounded = std::clamp(round_even((v - zero) / scale), qmin, qmax);
    if (bits == 64 && rounded >= std::ldexp(1., 63))
      rounded = -std::ldexp(1., 63);
    q.push_back(rounded);
  }
  return [&]() {
    Json result_object = Json::object();
    result_object["bits"] = bits;
    result_object["scale"] = scale;
    result_object["zero"] = zero;
    result_object["values"] = q;
    return result_object;
  }();
}
V dequantize(const Json &q) {
  double s = q.at("scale"), z = q.at("zero");
  require(std::isfinite(s) && s > 0 && std::isfinite(z), "invalid quantizer");
  V out;
  int b = int(integer(q, "bits", 0, 64));
  require(b >= 1 && b <= 64, "invalid quantizer bits");
  require(q.at("values").is_array() && q.at("values").size() <= MAX_CENTERS,
          "quantizer count");
  for (double v : q.at("values").get<V>()) {
    require(v >= -std::ldexp(1., b - 1) && v <= std::ldexp(1., b - 1) - 1 &&
                v == std::floor(v),
            "invalid quantized value");
    double x = s * v + z;
    require(std::isfinite(x), "quantizer overflow");
    out.push_back(x);
  }
  return out;
}
} // namespace abba_family
