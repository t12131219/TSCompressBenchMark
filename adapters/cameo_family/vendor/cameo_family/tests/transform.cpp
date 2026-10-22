// SPDX-License-Identifier: Apache-2.0
#include "cameo_family.hpp"
#include "../tools/json.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace cameo_family;
using Clock = std::chrono::steady_clock;
double measure(const Values &x, Config c) {
    std::vector<double> times;
    for (int i = 0; i < 10; ++i) {
        auto start = Clock::now();
        auto s = analyze(x, c);
        double ns = std::chrono::duration<double, std::nano>(Clock::now() - start).count();
        if (s.reconstructed.size() != x.size())
            throw std::runtime_error("transform size");
        if (i >= 3)
            times.push_back(ns);
    }
    std::sort(times.begin(), times.end());
    return times[times.size()/2];
}
int main(int argc, char **) {
    nlohmann::json result;
    result["scope"] = "orthonormal DCT-II/III; forced canonical vs FFT; standalone analyze timing";
    double largest = 0;
    std::size_t count = 0;
    for (std::size_t n : {1,2,3,8,9,16,17,31,32,33,64,127,128,257,512,1024})
        for (int shape = 0; shape < 4; ++shape)
            for (double fraction : {-1.5,-.25,0.,.01,.25,.5,1.,1.5}) {
                Values x(n);
                for (std::size_t i = 0; i < n; ++i)
                    x[i] = shape == 0 ? 1.25 : shape == 1 ? double(i)*.01 :
                           shape == 2 ? double(i%2)*2-1 : 3+std::sin(double(i)*.49);
                Config fast, scalar;
                fast.algorithm = scalar.algorithm = Algorithm::DWT_DCT_II;
                fast.fraction = scalar.fraction = fraction;
                scalar.canonical_dct = true;
                auto a = analyze(x, fast), b = analyze(x, scalar);
                auto frame = encode(x, fast);
                auto restored = decode(frame.data(), frame.size());
                for (std::size_t i = 0; i < n; ++i) {
                    for (double diff : {std::abs(a.coefficients[i]-b.coefficients[i]),
                                        std::abs(a.reconstructed[i]-b.reconstructed[i]),
                                        std::abs(restored[i]-a.reconstructed[i])}) {
                        largest = std::max(largest, diff);
                        if (diff > 1e-10 + 1e-10 * std::abs(b.coefficients[i]))
                            throw std::runtime_error("canonical/FFT difference");
                    }
                }
                ++count;
            }
    result["cases"] = count;
    result["max_absolute_difference"] = largest;
    if (argc == 1) for (std::size_t n : {512,2048,8192}) {
        Values x(n);
        for (std::size_t i = 0; i < n; ++i)
            x[i] = 3+std::sin(double(i)*.49);
        Config fast;
        fast.algorithm = Algorithm::DWT_DCT_II;
        auto scalar = fast;
        scalar.canonical_dct = true;
        const double a = measure(x, fast), b = measure(x, scalar);
        result["timings"].push_back({{"n",n},{"fft_median_ns",a},{"canonical_median_ns",b},{"speedup",b/a}});
    }
    // Optimized path can handle the public maximum, which exceeds the scalar work limit.
    Values large(max_samples);
    for (std::size_t i = 0; i < large.size(); ++i)
        large[i] = std::sin(double(i)*.01);
    Config c;
    c.algorithm = Algorithm::DWT_DCT_II;
    auto bytes = encode(large,c);
    if (decode(bytes.data(),bytes.size()).size()!=large.size())
        throw std::runtime_error("maximum-size transform");
    result["maximum_n_roundtrip"] = max_samples;
    result["status"] = "PASS";
    std::cout << result.dump(2) << '\n';
}
