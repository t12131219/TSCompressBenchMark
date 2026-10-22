// SPDX-License-Identifier: Apache-2.0
#include "cameo_family.hpp"
#include <cstddef>
#include <cstdint>
#include <exception>
#include <algorithm>
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t *p, std::size_t n) {
    try {
        cameo_family::decode(p, n);
    } catch (const std::exception &) {
    }
    if (n >= 68 && n <= 65536) {
        cameo_family::Bytes b(p, p + n);
        std::uint32_t crc = ~0u;
        for (std::size_t i = 0; i < n - 8; ++i) {
            crc ^= b[i];
            for (int k = 0; k < 8; ++k)
                crc = (crc >> 1) ^ (0xedb88320u & std::uint32_t(-std::int32_t(crc & 1)));
        }
        crc = ~crc;
        for (int k = 0; k < 8; ++k)
            b[n - 8 + k] = k < 4 ? std::uint8_t(crc >> (8 * k)) : 0;
        try {
            cameo_family::decode(b.data(), b.size());
        } catch (const std::exception &) {
        }
    }
    try {
        cameo_family::decompress_raw(cameo_family::Bytes(p, p + n));
    } catch (const std::exception &) {
    }
    if (n >= 16) {
        cameo_family::Config c;
        c.algorithm = cameo_family::Algorithm(1 + p[0] % 10);
        c.python_bottom_up = (p[1] & 1) != 0;
        c.bottom_up = (p[1] & 2) != 0;
        c.canonical_dct = (p[1] & 4) != 0;
        c.nlags = 2;
        c.error_bound = .1;
        c.threads = 1;
        c.fraction = double(p[1]) / 255.;
        std::size_t count = std::min<std::size_t>(64, n - 2);
        cameo_family::Values y(count);
        for (std::size_t i = 0; i < count; ++i)
            y[i] = (int(p[i + 2]) - 128) / 16.;
        try {
            auto frame = cameo_family::encode(y, c);
            auto restored = cameo_family::decode(frame.data(), frame.size());
            if (restored.size() > count)
                __builtin_trap();
        } catch (const std::exception &) {
        }
    }
    return 0;
}
