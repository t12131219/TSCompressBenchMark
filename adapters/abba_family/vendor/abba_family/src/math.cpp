// SPDX-License-Identifier: MIT AND BSD-3-Clause
// Structured translation of the frozen ABBA/fABBA/QABBA mathematical stages.
// NumPy indirect quicksort: BSD-3-Clause; see LICENSES and dependency snapshot.
#include "internal.hpp"
#include <algorithm>
#include <future>
#include <limits>
#include <numeric>
#include <thread>
namespace abba_family {
V values(const Json &j, bool nan) {
  require(j.is_array() && j.size() <= MAX_SAMPLES, "invalid sample array");
  V x;
  x.reserve(j.size());
  for (auto &v : j) {
    require(v.is_number() || (nan && v.is_null()), "numeric sample required");
    double d = v.is_null() && nan ? std::numeric_limits<double>::quiet_NaN()
                                  : v.get<double>();
    require(std::isfinite(d) || (nan && std::isnan(d)), "nonfinite sample");
    x.push_back(d);
  }
  return x;
}
std::vector<V> collection(const Json &j, bool &single) {
  require(j.is_array() && !j.empty(), "empty collection");
  single = !j[0].is_array();
  std::vector<V> out;
  if (single)
    out.push_back(values(j, true));
  else {
    require(j.size() <= 4096, "too many series");
    for (auto &row : j)
      out.push_back(values(row, true));
  }
  std::size_t n = 0;
  for (auto &row : out) {
    require(row.size() >= 2, "series requires two samples");
    n += row.size();
  }
  require(n <= MAX_SAMPLES, "input sample limit");
  return out;
}
V fill(V x, const std::string &rawmode, bool strict) {
  if (strict && std::all_of(x.begin(), x.end(),
                            [](double v) { return std::isfinite(v); }))
    return x;
  std::string mode = rawmode;
  for (char &ch : mode)
    if (ch >= 'A' && ch <= 'Z')
      ch = char(ch - 'A' + 'a');
  require(!strict || mode == rawmode, "QABBA fill mode is case sensitive");
  require(mode == "ffill" || mode == "bfill" || mode == "zero" ||
              mode == "mean" || mode == "median",
          "invalid missing fill");
  V good;
  for (double z : x)
    if (std::isfinite(z))
      good.push_back(z);
  double v = 0;
  if (mode == "mean" || mode == "median") {
    require(!good.empty(), "all missing mean/median");
    v = mode == "mean" ? mean(good) : median(good);
  }
  if (mode == "bfill") {
    for (std::size_t i = x.size(); i-- > 0;)
      if (std::isnan(x[i]))
        x[i] = i + 1 < x.size() ? x[i + 1] : 0;
  } else
    for (std::size_t i = 0; i < x.size(); ++i)
      if (std::isnan(x[i]))
        x[i] = mode == "ffill" ? (i ? x[i - 1] : 0) : v;
  return x;
}
double sum(const V &a) {
  double s = 0;
  for (double x : a)
    s += x;
  return s;
}
double mean(const V &a) {
  require(!a.empty(), "empty mean");
  return sum(a) / double(a.size());
}
double stddev(const V &a) {
  double m = mean(a), v = 0;
  for (double x : a) {
    double d = x - m;
    v += d * d;
  }
  return std::sqrt(v / double(a.size()));
}
double median(V a) {
  require(!a.empty(), "empty median");
  std::sort(a.begin(), a.end());
  return a.size() % 2 ? a[a.size() / 2]
                      : (a[a.size() / 2 - 1] + a[a.size() / 2]) / 2;
}
Ids argsort(const V &v) {
  Ids a(v.size());
  std::iota(a.begin(), a.end(), 0);
  if (a.size() < 2)
    return a;
  using I = std::ptrdiff_t;
  struct Range {
    I l, r;
    int depth;
  };
  std::vector<Range> stack;
  I l = 0, r = I(a.size()) - 1;
  int depth = 0;
  for (auto n = a.size(); n > 1; n >>= 1)
    depth += 2;
  for (;;) {
    if (depth < 0) {
      // NumPy aheapsort, using an index accessor instead of its out-of-bounds
      // one-before-array pointer. Equal keys follow the reference's decisions.
      auto at = [&](I i) -> std::size_t & { return a[std::size_t(l + i - 1)]; };
      I n = r - l + 1;
      for (I root = n / 2; root > 0; --root) {
        auto tmp = at(root);
        I i = root, j = root * 2;
        for (; j <= n;) {
          if (j < n && v[at(j)] < v[at(j + 1)])
            ++j;
          if (v[tmp] < v[at(j)]) {
            at(i) = at(j);
            i = j;
            j *= 2;
          } else
            break;
        }
        at(i) = tmp;
      }
      for (; n > 1;) {
        auto tmp = at(n);
        at(n) = at(1);
        --n;
        I i = 1, j = 2;
        for (; j <= n;) {
          if (j < n && v[at(j)] < v[at(j + 1)])
            ++j;
          if (v[tmp] < v[at(j)]) {
            at(i) = at(j);
            i = j;
            j *= 2;
          } else
            break;
        }
        at(i) = tmp;
      }
    } else {
      while (r - l > 15) {
        I m = l + ((r - l) >> 1);
        if (v[a[m]] < v[a[l]])
          std::swap(a[m], a[l]);
        if (v[a[r]] < v[a[m]])
          std::swap(a[r], a[m]);
        if (v[a[m]] < v[a[l]])
          std::swap(a[m], a[l]);
        double pivot = v[a[m]];
        I i = l, j = r - 1;
        std::swap(a[m], a[j]);
        for (;;) {
          do {
            ++i;
          } while (v[a[i]] < pivot);
          do {
            --j;
          } while (pivot < v[a[j]]);
          if (i >= j)
            break;
          std::swap(a[i], a[j]);
        }
        std::swap(a[i], a[r - 1]);
        --depth;
        if (i - l < r - i) {
          stack.push_back({i + 1, r, depth});
          r = i - 1;
        } else {
          stack.push_back({l, i - 1, depth});
          l = i + 1;
        }
      }
      for (I i = l + 1; i <= r; ++i) {
        auto z = a[i];
        I j = i;
        while (j > l && v[z] < v[a[j - 1]]) {
          a[j] = a[j - 1];
          --j;
        }
        a[j] = z;
      }
    }
    if (stack.empty())
      break;
    auto z = stack.back();
    stack.pop_back();
    l = z.l;
    r = z.r;
    depth = z.depth;
  }
  return a;
}
void parallel(std::size_t n, std::size_t workers,
              const std::function<void(std::size_t)> &f) {
  require(workers >= 1 && workers <= 256, "worker limit");
  for (std::size_t start = 0; start < n; start += workers) {
    std::vector<std::future<void>> tasks;
    for (std::size_t i = start; i < std::min(n, start + workers); ++i) {
      if (workers == 1)
        f(i);
      else
        tasks.push_back(std::async(std::launch::async, [&, i] { f(i); }));
    }
    for (auto &t : tasks)
      t.get();
  }
}
Pieces segment(const V &x, double tol, std::size_t maxlen, int norm,
               bool abba) {
  require(x.size() >= 2, "series requires two samples");
  require(std::isfinite(tol) && tol >= 0 && maxlen >= 1 &&
              (norm == 1 || norm == 2),
          "segmentation config");
  for (double z : x)
    require(std::isfinite(z), "nonfinite segment input");
  double threshold = abba && norm == 2 ? tol * tol : tol;
  Pieces out;
  std::size_t s = 0, e = 1;
  double lastinc = 0, lasterr = 0;
  std::size_t work = 0;
  while (e < x.size()) {
    require(e - s + 1 <= 100000000 - work, "segmentation work limit");
    work += e - s + 1;
    double inc = x[e] - x[s], error = 0;
    require(std::isfinite(inc), "increment overflow");
    double slope = inc / double(e - s);
    for (std::size_t k = 0; k <= e - s; ++k) {
      double d = x[s] + slope * double(k) - x[s + k];
      error += norm == 1 ? std::abs(d) : d * d;
    }
    if (abba && norm == 2) {
      double z = std::sqrt(error);
      error = z * z;
    }
    require(std::isfinite(error), "segmentation error overflow");
    if (error <= threshold * double(e - s - 1) +
                     std::numeric_limits<double>::epsilon() &&
        e - s - 1 < maxlen) {
      lastinc = inc;
      lasterr = error;
      ++e;
    } else {
      require(e > s + 1, "unrepresentable initial segment");
      out.push_back({double(e - s - 1), lastinc, lasterr});
      s = e - 1;
    }
  }
  out.push_back({double(e - s - 1), lastinc, lasterr});
  return out;
}
Pieces compression(const V &x, const Json &c, const std::string &a) {
  double tol = c.contains("tol") && c["tol"].is_array()
                   ? c["tol"][0].get<double>()
                   : number(c, "tol", a == "qabba" ? .2 : .1);
  std::size_t m = MAX_SAMPLES;
  if (c.contains("max_len") && !c["max_len"].is_null()) {
    double z = c["max_len"].get<double>();
    if (a == "fabba")
      require(c["max_len"].is_number_integer() && (z == -1 || z >= 1),
              "fABBA integer max_len");
    else
      require(std::isfinite(z) && z > 0, "positive maximum length required");
    if (z != -1)
      m = std::size_t(std::ceil(std::min(z, double(MAX_SAMPLES))));
  }
  int norm = c.value("norm", 2);
  if (a == "abba")
    return segment(x, tol, m, norm, true);
  if (a == "qabba")
    return segment(x, tol, m, 2, false);
  std::size_t workers = job_count(c);
  std::size_t partitions = 1;
  if (c.contains("partition") && !c["partition"].is_null())
    partitions = integer(c, "partition", 1);
  else if (c.contains("partition_rate") && !c["partition_rate"].is_null()) {
    double rate = number(c, "partition_rate", 1);
    require(rate > 0, "invalid partition_rate");
    partitions =
        std::size_t(std::exp(std::min(1 / rate, std::log(double(x.size()))))) *
        workers;
  } else
    return segment(x, tol, m, 2, false);
  require(partitions > 0, "invalid partition");
  partitions = std::min(partitions, x.size() - 1);
  std::vector<Pieces> parts(partitions);
  parallel(partitions, workers, [&](std::size_t i) {
    auto begin =
        std::size_t(double(i) * double(x.size() - 1) / double(partitions));
    auto end = i + 1 == partitions
                   ? x.size() - 1
                   : std::size_t(double(i + 1) * double(x.size() - 1) /
                                 double(partitions));
    parts[i] = segment(V(x.begin() + std::ptrdiff_t(begin),
                         x.begin() + std::ptrdiff_t(end + 1)),
                       tol, m, 2, false);
  });
  Pieces out;
  for (auto &p : parts)
    out.insert(out.end(), p.begin(), p.end());
  return out;
}
Points points(const Json &j) {
  require(j.is_array() && !j.empty() && j.size() <= MAX_SAMPLES,
          "invalid points");
  Points out;
  for (auto &row : j) {
    require(row.is_array() && row.size() >= 2, "invalid point shape");
    P p{row[0].get<double>(), row[1].get<double>()};
    require(std::isfinite(p[0]) && std::isfinite(p[1]) && p[0] >= 1,
            "invalid piece");
    out.push_back(p);
  }
  return out;
}
Points first2(const Pieces &p) {
  Points out;
  for (auto z : p)
    out.push_back({z[0], z[1]});
  return out;
}
Points grid(const Points &p, const std::string &a) {
  Points out = p;
  if (a == "fabba") {
    double t = 0, prev = 0;
    for (auto &z : out) {
      t += z[0];
      double end = std::floor(t + .5);
      z[0] = end - prev;
      prev = end;
    }
  } else if (out.size() == 1)
    out[0][0] = round_even(out[0][0]);
  else if (!out.empty()) {
    for (std::size_t i = 0; i + 1 < out.size(); ++i) {
      double corr = round_even(out[i][0]) - out[i][0];
      out[i][0] = round_even(out[i][0] + corr);
      out[i + 1][0] -= corr;
      if (out[i][0] == 0) {
        out[i][0] = 1;
        out[i + 1][0] -= 1;
      }
    }
    out.back()[0] = round_even(out.back()[0]);
  }
  return out;
}
V reconstruct(const Points &p, double start, const std::string &a) {
  require(std::isfinite(start), "invalid start");
  std::size_t n = 1;
  for (auto z : p) {
    require(std::isfinite(z[0]) && std::isfinite(z[1]) &&
                (a != "fabba" || z[0] >= 1) && z[0] == std::floor(z[0]) &&
                z[0] <= double(MAX_OUTPUT - n),
            "invalid reconstruction length");
    if (z[0] > 0)
      n += std::size_t(z[0]);
  }
  V out;
  out.reserve(n);
  out.push_back(start);
  for (auto z : p) {
    if (z[0] <= 0)
      continue; // source arange produces no appended samples
    double endpoint = out.back();
    for (std::size_t k = 1; k <= std::size_t(z[0]); ++k) {
      double y = a == "fabba" ? endpoint + double(k) * (z[1] / z[0])
                              : endpoint + (double(k) / z[0]) * z[1];
      require(std::isfinite(y), "reconstruction overflow");
      out.push_back(y);
    }
  }
  return out;
}
} // namespace abba_family
