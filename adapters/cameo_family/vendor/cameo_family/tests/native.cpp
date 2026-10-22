// SPDX-License-Identifier: Apache-2.0
#include "cameo_family.hpp"
#include "cameo_family_c.h"
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <future>
#include <iostream>
#include <new>
#include <stdexcept>
#include <sys/mman.h>
#include <unistd.h>
using namespace cameo_family;
thread_local long fail_after = -1;
#ifndef CF_NO_ALLOC_INJECTION
void *operator new(std::size_t n) {
    if (fail_after == 0)
        throw std::bad_alloc();
    if (fail_after > 0)
        --fail_after;
    if (void *p = std::malloc(n ? n : 1))
        return p;
    throw std::bad_alloc();
}
void *operator new[](std::size_t n) { return ::operator new(n); }
void *operator new(std::size_t n, const std::nothrow_t &) noexcept {
    try {
        return ::operator new(n);
    } catch (...) {
        return nullptr;
    }
}
void *operator new[](std::size_t n, const std::nothrow_t &) noexcept {
    return ::operator new(n, std::nothrow);
}
void operator delete(void *p, const std::nothrow_t &) noexcept { std::free(p); }
void operator delete[](void *p, const std::nothrow_t &) noexcept { std::free(p); }
void operator delete(void *p) noexcept { std::free(p); }
void operator delete[](void *p) noexcept { std::free(p); }
void operator delete(void *p, std::size_t) noexcept { std::free(p); }
void operator delete[](void *p, std::size_t) noexcept { std::free(p); }
#endif
void check(bool q, const char *s) {
    if (!q)
        throw std::runtime_error(s);
}
cf_config_v1 cfg(unsigned id) {
    cf_config_v1 c{};
    c.version = 1;
    c.algorithm = id;
    c.error_bound = .01;
    c.fraction = .5;
    c.window_fraction = .5;
    c.nlags = 4;
    c.hops = 2;
    c.kappa = 1;
    c.threads = 1;
    return c;
}
void put(Bytes &b, std::size_t at, std::uint64_t x) {
    for (int i = 0; i < 8; ++i)
        b.at(at + i) = std::uint8_t(x >> (8 * i));
}
void checksum(Bytes &b) {
    std::uint32_t c = ~0u;
    for (std::size_t i = 0; i < b.size() - 8; ++i) {
        c ^= b[i];
        for (int j = 0; j < 8; ++j)
            c = (c >> 1) ^ (0xedb88320u & std::uint32_t(-std::int32_t(c & 1)));
    }
    put(b, b.size() - 8, ~c);
}
void reject(const Bytes &b) {
    double out[132];
    std::fill(std::begin(out), std::end(out), 123456.);
    size_t used = 99, need = 99;
    int r = cf_decode_v1(b.data(), b.size(), out, 132, &used, &need);
    check(r == CF_INVALID && used == 0, "malformed rejection");
    for (double v : out)
        check(v == 123456., "failure changed output");
}
int main() {
    try {
        Values y(64);
        for (std::size_t i = 0; i < y.size(); ++i)
            y[i] = 3 + (i % 2 ? -.3 : .3) + std::sin(double(i) * .49);
        auto original = y;
        std::size_t checks = 0;
        // Regression: a first turning point at 2 or 4 has no earlier predecessor.
        // Check an independently calculated first-span interpolation, not only roundtrip.
        for (std::size_t gap : {std::size_t(2), std::size_t(4)})
            for (std::size_t kappa : {std::size_t(1), std::size_t(2)}) {
                Values signal(32);
                for (std::size_t i = 0; i <= gap; ++i)
                    signal[i] = double(i * (i + 1)) / 2;
                for (std::size_t i = gap + 1; i < signal.size(); ++i)
                    signal[i] = signal[gap] + .01 * double(i - gap) - double((i - gap) % 2);
                const auto saved_signal = signal;
                Config tp;
                tp.algorithm = Algorithm::TP;
                tp.nlags = 2;
                tp.kappa = kappa;
                tp.error_bound = 0;
                auto stage = analyze(signal, tp);
                for (std::size_t i = 1; i < gap; ++i) {
                    check(stage.working[i] == signal[gap] * double(i) / double(gap),
                          "TP first-span interpolation");
                    ++checks;
                }
                check(stage.diagnostic.find("tp-first-span-v1") != std::string::npos,
                      "TP repaired variant diagnostic");
                check(signal == saved_signal, "TP repair changed caller input");
                auto frame = encode(signal, tp);
                auto restored = decode(frame.data(), frame.size());
                check(restored.size() == signal.size() && restored.front() == signal.front() &&
                          restored.back() == signal.back(),
                      "TP repaired independent inverse");
                checks += 3;
            }
        for (unsigned id = 1; id <= 10; ++id) {
            auto c = cfg(id);
            if (id == 4)
                c.error_bound = 0.;
            size_t used = 42, need = 42;
            check(cf_encode_v1(y.data(), y.size(), &c, nullptr, 0, &used, &need) == CF_CAPACITY &&
                      used == 0 && need >= 68,
                  "encode capacity query");
            Bytes b(need + 32, 0xa5);
            size_t exact = need;
            check(cf_encode_v1(y.data(), y.size(), &c, b.data() + 16, exact - 1, &used, &need) ==
                          CF_CAPACITY &&
                      used == 0 && need == exact,
                  "short capacity");
            check(std::all_of(b.begin(), b.end(), [](auto v) { return v == 0xa5; }),
                  "short output changed");
            check(cf_encode_v1(y.data(), y.size(), &c, b.data() + 16, exact, &used, &need) ==
                          CF_OK &&
                      used == exact,
                  "encode");
            for (int i = 0; i < 16; ++i)
                check(b[i] == 0xa5 && b[16 + exact + i] == 0xa5, "encode canary");
            Bytes frame(b.begin() + 16, b.begin() + 16 + exact);
            check(cf_decode_v1(frame.data(), frame.size(), nullptr, 0, &used, &need) ==
                          CF_CAPACITY &&
                      used == 0 && need == y.size(),
                  "decode query");
            Values out(y.size() + 2, 999.);
            check(cf_decode_v1(frame.data(), frame.size(), out.data() + 1, y.size() - 1, &used,
                               &need) == CF_CAPACITY &&
                      used == 0,
                  "decode short");
            check(std::all_of(out.begin(), out.end(), [](auto x) { return x == 999.; }),
                  "decode short atomic");
            check(cf_decode_v1(frame.data(), frame.size(), out.data() + 1, y.size(), &used,
                               &need) == CF_OK &&
                      used == y.size(),
                  "decode");
            check(out.front() == 999. && out.back() == 999., "decode canary");
            check(y == original, "immutable input");
            Bytes repeat(exact);
            check(cf_encode_v1(y.data(), y.size(), &c, repeat.data(), repeat.size(), &used,
                               &need) == CF_OK &&
                      repeat == frame,
                  "repeat independence");
            Bytes overlap_buffer(std::max(exact, y.size() * 8) + 32);
            std::memcpy(overlap_buffer.data(), y.data(), y.size() * 8);
            check(cf_encode_v1(reinterpret_cast<double *>(overlap_buffer.data()), y.size(), &c,
                               overlap_buffer.data(), exact, &used, &need) == CF_OK,
                  "encode overlap");
            check(std::equal(frame.begin(), frame.end(), overlap_buffer.begin()), "overlap frame");
            check(cf_decode_v1(overlap_buffer.data(), exact,
                               reinterpret_cast<double *>(overlap_buffer.data()), y.size(), &used,
                               &need) == CF_OK,
                  "decode overlap");
            check(std::memcmp(overlap_buffer.data(), out.data() + 1, y.size() * 8) == 0,
                  "overlap values");
            for (std::size_t n = 0; n < frame.size(); ++n) {
                Bytes shortb(frame.begin(), frame.begin() + n);
                if (n == 0)
                    shortb.reserve(1);
                reject(shortb);
                ++checks;
            }
            for (std::size_t i = 0; i < frame.size(); ++i) {
                auto changed = frame;
                changed[i] ^= 0x80;
                reject(changed);
                ++checks;
            }
            for (auto change :
                 std::vector<std::pair<std::size_t, std::uint64_t>>{{4, 2},
                                                                    {12, 11},
                                                                    {20, 5},
                                                                    {28, max_samples + 1},
                                                                    {36, max_samples + 1},
                                                                    {44, UINT64_MAX},
                                                                    {52, UINT64_MAX}}) {
                auto changed = frame;
                put(changed, change.first, change.second);
                checksum(changed);
                reject(changed);
                ++checks;
            }
            // Persistent allocation failure at every C++ allocation prefix, including exception
            // handling.
            bool reached = false;
            for (long i = 0; i < 10000; ++i) {
                Bytes target(exact, 0x7b);
                used = 123;
                need = 123;
                fail_after = i;
                int r = cf_encode_v1(y.data(), y.size(), &c, target.data(), target.size(), &used,
                                     &need);
                fail_after = -1;
                if (r == CF_OK) {
                    check(target == frame, "OOM recovery frame");
                    reached = true;
                    break;
                }
                check(r == CF_NOMEM && used == 0, "OOM encode status");
                check(std::all_of(target.begin(), target.end(), [](auto v) { return v == 0x7b; }),
                      "OOM encode atomic");
                ++checks;
            }
            check(reached, "OOM encode ceiling");
            reached = false;
            for (long i = 0; i < 10000; ++i) {
                Values target(y.size(), 123456.);
                fail_after = i;
                int r = cf_decode_v1(frame.data(), frame.size(), target.data(), target.size(),
                                     &used, &need);
                fail_after = -1;
                if (r == CF_OK) {
                    reached = true;
                    break;
                }
                check(r == CF_NOMEM && used == 0, "OOM decode status");
                check(
                    std::all_of(target.begin(), target.end(), [](auto v) { return v == 123456.; }),
                    "OOM decode atomic");
                ++checks;
            }
            check(reached, "OOM decode ceiling");
        }
        for (unsigned id = 1; id <= 10; ++id)
            for (std::size_t n = 0; n < 3; ++n) {
                Config c;
                c.algorithm = Algorithm(id);
                Values small(n, 1.);
                if (id >= 9 && n == 0) {
                    bool threw = false;
                    try {
                        encode(small, c);
                    } catch (const std::invalid_argument &) {
                        threw = true;
                    }
                    check(threw, "empty transform refusal");
                } else {
                    auto b = encode(small, c);
                    check(decode(b.data(), b.size()).size() == n, "short roundtrip");
                }
                ++checks;
            }
        auto c = cfg(7);
        size_t used = 1, need = 1;
        Bytes target(4096, 0x42);
        auto saved = target;
        check(cf_encode_v1(y.data(), y.size(), &c, target.data(), target.size(), &used, &used) ==
                  CF_INVALID,
              "counter alias");
        check(target == saved, "alias output unchanged");
        check(cf_encode_v1(y.data(), y.size(), &c, target.data(), target.size(),
                           reinterpret_cast<size_t *>(target.data()), &need) == CF_INVALID,
              "counter in output");
        check(target == saved, "counter alias atomic");
        check(cf_encode_v1(y.data(), y.size(), &c, target.data(), target.size(),
                           reinterpret_cast<size_t *>(y.data()), &need) == CF_INVALID &&
                  y == original,
              "counter in input");
        auto nonfinite = y;
        nonfinite[5] = INFINITY;
        check(cf_encode_v1(nonfinite.data(), nonfinite.size(), &c, target.data(), target.size(),
                           &used, &need) == CF_INVALID &&
                  used == 0 && target == saved,
              "nonfinite failure");
        long page = sysconf(_SC_PAGESIZE);
        auto *mem = static_cast<unsigned char *>(
            mmap(nullptr, size_t(page) * 3, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
        check(mem != MAP_FAILED, "mmap");
        check(mprotect(mem + page, size_t(page), PROT_READ | PROT_WRITE) == 0, "mprotect");
        double *edge = reinterpret_cast<double *>(mem + 2 * page - y.size() * 8);
        std::memcpy(edge, y.data(), y.size() * 8);
        check(cf_encode_v1(edge, y.size(), &c, target.data(), target.size(), &used, &need) == CF_OK,
              "input guardpage");
        check(mprotect(mem + page, size_t(page), PROT_READ) == 0, "readonly input");
        check(cf_encode_v1(edge, y.size(), &c, target.data(), target.size(), &used, &need) == CF_OK,
              "readonly input encode");
        munmap(mem, size_t(page) * 3);
        std::vector<std::future<void>> jobs;
        for (int t = 0; t < 4; ++t)
            jobs.push_back(std::async(std::launch::async, [&, t]() {
                for (int i = 0; i < 20; ++i) {
                    Config co;
                    co.algorithm = i % 2 ? Algorithm::CAMEO : Algorithm::SWING;
                    co.parallel_lookahead = true;
                    co.threads = 2;
                    auto b = encode(y, co);
                    check(decode(b.data(), b.size()).size() == y.size(),
                          "parallel independent calls");
                }
            }));
        for (auto &job : jobs)
            job.get();
#ifdef CF_NO_ALLOC_INJECTION
        std::cout << "Clang TSan: allocator injection disabled (strong sanitizer interceptors); "
                     "verified separately by GCC ASan.\n";
#endif
        std::cout << "PASS native safety: " << checks
                  << " malformed/allocation/boundary checks, 10 codecs, 80 concurrent calls\n";
        return 0;
    } catch (const std::exception &e) {
        fail_after = -1;
        std::cerr << "FAIL: " << e.what() << '\n';
        return 1;
    }
}
