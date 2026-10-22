// SPDX-License-Identifier: Apache-2.0
#include "cameo_family.hpp"
#include "json.hpp"
#include <chrono>
#include <algorithm>
#include <cmath>
#include <iostream>
using namespace cameo_family;
using Clock = std::chrono::steady_clock;
int main() {
    nlohmann::json rows = nlohmann::json::array();
    Values y(512);
    for (std::size_t i = 0; i < y.size(); ++i)
        y[i] = 3 + std::sin(i * .49) + (i % 2 ? -.7 : .7);
    for (unsigned id = 1; id <= 10; ++id) {
        Config c;
        c.algorithm = Algorithm(id);
        c.error_bound = id == 4 ? 0 : .01;
        auto frame = encode(y, c);
        Values output;
        Bytes compressed;
        for (int i = 0; i < 3; ++i) {
            compressed = encode(y, c);
            output = decode(frame.data(), frame.size());
        }
        std::vector<double> enc, dec;
        for (int r = 0; r < 15; ++r) {
            auto a = Clock::now();
            compressed = encode(y, c);
            auto b = Clock::now();
            output = decode(frame.data(), frame.size());
            auto z = Clock::now();
            enc.push_back(std::chrono::duration<double, std::nano>(b - a).count());
            dec.push_back(std::chrono::duration<double, std::nano>(z - b).count());
        }
        std::sort(enc.begin(), enc.end());
        std::sort(dec.begin(), dec.end());
        rows.push_back({{"algorithm", name(c.algorithm)},
                        {"n", y.size()},
                        {"final_bits", frame.size() * 8},
                        {"encode_median_ns", enc[7]},
                        {"decode_median_ns", dec[7]},
                        {"encode_mib_s", y.size() * 8. / enc[7] * 1e9 / 1048576.},
                        {"decode_mib_s", y.size() * 8. / dec[7] * 1e9 / 1048576.}});
    }
    nlohmann::json result = {
        {"scope", "standalone PIPELINE encode=analyze+representation+CF01 framing; decode=whole "
                  "CF01 validation+inverse; warm 3, 15 samples, steady_clock, one worker; no "
                  "source comparison or Bench FORMAL claim"},
        {"cases", rows}};
    std::cout << result.dump(2) << '\n';
}
