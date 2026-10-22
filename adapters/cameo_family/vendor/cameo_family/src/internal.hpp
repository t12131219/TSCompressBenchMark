// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "cameo_family.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <numeric>
#include <future>
#include <exception>
#include <mutex>
#include <atomic>
#include <omp.h>
namespace cameo_family {
inline void require(bool v, const char *why) {
    if (!v)
        throw std::invalid_argument(why);
}
using I = std::ptrdiff_t;
constexpr double inf = std::numeric_limits<double>::infinity();
inline void checked(const Values &v) {
    require(v.size() <= max_samples, "sample limit");
    for (double x : v)
        require(std::isfinite(x), "finite input required");
}
template <class F> void parallel_for(I a, I b, std::size_t workers, F f) {
    require(workers > 0 && workers <= 64, "worker limit");
    std::exception_ptr error;
    std::mutex lock;
    std::atomic<bool> published{false};
    std::atomic<I> completed{0};
    published.store(true, std::memory_order_release);
#pragma omp parallel for num_threads(workers) schedule(static)
    for (I i = a; i < b; ++i) {
        (void)published.load(std::memory_order_acquire);
        try {
            f(i);
        } catch (...) {
            std::lock_guard<std::mutex> guard(lock);
            if (!error)
                error = std::current_exception();
        }
        completed.fetch_add(1, std::memory_order_acq_rel);
    }
    require(completed.load(std::memory_order_acquire) == b - a, "parallel completion");
    if (error)
        std::rethrow_exception(error);
}
Stages lines(const Values &, const Config &);
Stages swab_stages(const Values &, const Config &);
Stages frequency(const Values &, const Config &);
Values dct_ii(const Values &, bool inverse, bool canonical = false);
inline void u64(Bytes &b, std::uint64_t x) {
    for (int i = 0; i < 8; ++i)
        b.push_back(std::uint8_t(x >> (i * 8)));
}
inline void f64(Bytes &b, double x) {
    std::uint64_t n;
    std::memcpy(&n, &x, 8);
    u64(b, n);
}
struct Reader {
    const std::uint8_t *p;
    std::size_t n, pos = 0;
    std::uint64_t u() {
        require(n - pos >= 8, "truncated integer");
        std::uint64_t x = 0;
        for (int i = 0; i < 8; ++i)
            x |= std::uint64_t(p[pos++]) << (8 * i);
        return x;
    }
    double f() {
        auto b = u();
        double d;
        std::memcpy(&d, &b, 8);
        require(std::isfinite(d), "nonfinite payload");
        return d;
    }
};
inline Values interpolate(const Values &xs, const Values &ys, std::size_t n) {
    require(xs.size() == ys.size() && !xs.empty(), "empty points");
    Values out(n);
    std::size_t j = 0;
    for (std::size_t i = 0; i < n; ++i) {
        while (j + 1 < xs.size() && xs[j + 1] < double(i))
            ++j;
        if (i <= xs.front())
            out[i] = ys.front();
        else if (j + 1 == xs.size())
            out[i] = ys.back();
        else {
            double slope = (ys[j + 1] - ys[j]) / (xs[j + 1] - xs[j]);
            out[i] = slope * (double(i) - xs[j]) + ys[j];
        }
    }
    checked(out);
    return out;
}
} // namespace cameo_family
