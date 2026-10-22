// SPDX-License-Identifier: Apache-2.0
#include "cameo_family.hpp"
#include <cmath>
#include <iostream>
int main() {
    using namespace cameo_family;
    Values y(64);
    for (std::size_t i = 0; i < y.size(); ++i)
        y[i] = 3 + std::sin(i * .49) + (i % 2 ? -1. : 1.);
    for (unsigned id = 1; id <= 10; ++id) {
        Config c;
        c.algorithm = Algorithm(id);
        if (id == 4)
            c.error_bound = 0;
        auto b = encode(y, c);
        if (decode(b.data(), b.size()).size() != y.size())
            return 1;
    }
    std::cout << "C++17 installed static consumer PASS: 10 algorithms\n";
}
