// SPDX-License-Identifier: Apache-2.0
#include "internal.hpp"
extern "C" {
#include "pocketfft.h"
}
#include <memory>
namespace cameo_family {
// Orthonormal DCT-II/III through the FFT of the even extension. Retain the
// independent direct definition as a forced canonical path for verification.
Values dct_ii(const Values &x, bool inverse, bool canonical) {
    const std::size_t n = x.size();
    if (!n)
        return {};
    const double pi = std::acos(-1.);
    Values out(n);
    if (canonical) {
        require(static_cast<long double>(n) * n <= 1e8L, "canonical DCT work limit");
        for (std::size_t k = 0; k < n; ++k) {
            double sum = inverse ? x[0] / std::sqrt(double(n)) : 0;
            for (std::size_t j = inverse ? 1 : 0; j < n; ++j)
                sum += inverse ? std::sqrt(2. / double(n)) * x[j] *
                                     std::cos(pi * double(j) * (double(k) + .5) / double(n))
                               : x[j] * std::cos(pi * (double(j) + .5) * double(k) / double(n));
            out[k] = inverse ? sum : sum * std::sqrt((k ? 2. : 1.) / double(n));
        }
        return out;
    }
    std::unique_ptr<cfft_plan_i, decltype(&destroy_cfft_plan)> plan(make_cfft_plan(2 * n),
                                                                destroy_cfft_plan);
    if (!plan)
        throw std::bad_alloc();
    Values z(4 * n, 0);
    if (!inverse) {
        for (std::size_t j = 0; j < n; ++j)
            z[2 * j] = z[2 * (2 * n - 1 - j)] = x[j];
        require(cfft_forward(plan.get(), z.data(), 1) == 0, "DCT FFT failure");
        for (std::size_t k = 0; k < n; ++k) {
            const double angle = pi * double(k) / double(2 * n);
            out[k] = (z[2 * k] * std::cos(angle) + z[2 * k + 1] * std::sin(angle)) *
                     (k ? 1 / std::sqrt(2. * double(n)) : 1 / (2 * std::sqrt(double(n))));
        }
    } else {
        z[0] = x[0] * (2 * std::sqrt(double(n)));
        for (std::size_t k = 1; k < n; ++k) {
            const double angle = pi * double(k) / double(2 * n),
                         value = x[k] * std::sqrt(2. * double(n));
            z[2 * k] = z[2 * (2 * n - k)] = value * std::cos(angle);
            z[2 * k + 1] = value * std::sin(angle);
            z[2 * (2 * n - k) + 1] = -z[2 * k + 1];
        }
        require(cfft_backward(plan.get(), z.data(), 1 / double(2 * n)) == 0,
                "inverse DCT FFT failure");
        for (std::size_t j = 0; j < n; ++j)
            out[j] = z[2 * j];
    }
    return out;
}
Values inverse_fft(const Values &r, const Values &i) {
    std::size_t n = r.size();
    if (!n)
        return {};
    std::unique_ptr<cfft_plan_i, decltype(&destroy_cfft_plan)> plan(make_cfft_plan(n),
                                                                    destroy_cfft_plan);
    if (!plan)
        throw std::bad_alloc();
    Values z(2 * n);
    for (std::size_t k = 0; k < n; ++k) {
        z[2 * k] = r[k];
        z[2 * k + 1] = i[k];
    }
    require(cfft_backward(plan.get(), z.data(), 1 / double(n)) == 0, "inverse FFT");
    Values out(n);
    for (std::size_t k = 0; k < n; ++k)
        out[k] = z[2 * k];
    return out;
}
Stages frequency(const Values &y, const Config &c) {
    require(!y.empty(), "source transform empty input");
    require(std::isfinite(c.fraction) && std::fabs(c.fraction) <= 1e6, "fraction domain");
    Stages s;
    std::size_t n = y.size();
    I requested = I(double(n) * c.fraction);
    s.coefficients.resize(n);
    s.reconstructed.resize(n);
    if (c.algorithm == Algorithm::DFT) {
        std::unique_ptr<cfft_plan_i, decltype(&destroy_cfft_plan)> plan(make_cfft_plan(n),
                                                                        destroy_cfft_plan);
        if (!plan)
            throw std::bad_alloc();
        Values z(2 * n);
        for (std::size_t i = 0; i < n; ++i)
            z[2 * i] = y[i];
        require(cfft_forward(plan.get(), z.data(), 1) == 0, "FFT failure");
        Values magnitude(n);
        for (std::size_t i = 0; i < n; ++i)
            magnitude[i] = std::hypot(z[2 * i], z[2 * i + 1]);
        auto sorted = numpy_argsort(magnitude);
        I count = requested < 0 ? std::max<I>(0, I(n) + requested) : std::min<I>(I(n), requested);
        std::vector<std::uint8_t> keep(n, 0);
        for (I i = 0; i < count; ++i)
            keep[sorted[n - 1 - std::size_t(i)]] = 1;
        s.imaginary.resize(n);
        for (std::size_t i = 0; i < n; ++i) {
            if (!keep[i])
                z[2 * i] = z[2 * i + 1] = 0;
            s.coefficients[i] = z[2 * i];
            s.imaginary[i] = z[2 * i + 1];
        }
        require(cfft_backward(plan.get(), z.data(), 1 / double(n)) == 0, "inverse FFT failure");
        for (std::size_t i = 0; i < n; ++i)
            s.reconstructed[i] = z[2 * i];
    } else {
        s.coefficients = dct_ii(y, false, c.canonical_dct);
        I start;
        if (requested == 0)
            start = 0;
        else if (requested > 0)
            start = std::max<I>(0, I(n) - requested);
        else
            start = std::min<I>(I(n), -requested);
        for (I i = start; i < I(n); ++i)
            s.coefficients[i] = 0;
        s.reconstructed = dct_ii(s.coefficients, true, c.canonical_dct);
    }
    checked(s.coefficients);
    checked(s.imaginary);
    checked(s.reconstructed);
    return s;
}
} // namespace cameo_family
