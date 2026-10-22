// SPDX-License-Identifier: Apache-2.0
#include "internal.hpp"
#include "cameo_family_c.h"
#include <array>
namespace cameo_family {
Values inverse_fft(const Values &, const Values &);
Algorithm algorithm(const std::string &s) {
    if (s == "cameo" || s == "sip")
        return Algorithm::CAMEO;
    if (s == "vw")
        return Algorithm::VW;
    if (s == "pip")
        return Algorithm::PIP;
    if (s == "tp")
        return Algorithm::TP;
    if (s == "swab")
        return Algorithm::SWAB;
    if (s == "sim-piece")
        return Algorithm::SimPiece;
    if (s == "pmc")
        return Algorithm::PMC;
    if (s == "swing")
        return Algorithm::SWING;
    if (s == "dft")
        return Algorithm::DFT;
    if (s == "dwt-dct-ii" || s == "DWT(DCT-II)")
        return Algorithm::DWT_DCT_II;
    throw std::invalid_argument("unknown algorithm");
}
std::string name(Algorithm a) {
    switch (a) {
    case Algorithm::CAMEO:
        return "CAMEO / SIP";
    case Algorithm::VW:
        return "VW";
    case Algorithm::PIP:
        return "PIP";
    case Algorithm::TP:
        return "TP";
    case Algorithm::SWAB:
        return "SWAB";
    case Algorithm::SimPiece:
        return "Sim-Piece";
    case Algorithm::PMC:
        return "PMC-Mean";
    case Algorithm::SWING:
        return "SWING";
    case Algorithm::DFT:
        return "DFT";
    case Algorithm::DWT_DCT_II:
        return "DWT(DCT-II)";
    }
    throw std::invalid_argument("invalid algorithm id");
}
Stages analyze(const Values &y, const Config &c) {
    checked(y);
    name(c.algorithm);
    require(c.threads >= 1 && c.threads <= 64, "workers");
    require(std::isfinite(c.error_bound) && c.error_bound >= 0, "invalid threshold");
    if (c.ratio_stopping)
        require(c.algorithm == Algorithm::CAMEO && c.error_bound >= 1 &&
                    c.error_bound <= max_samples && c.error_bound == std::floor(c.error_bound),
                "ratio criterion");
    require(!c.ratio_stopping || c.kappa == 1, "aggregate CR absent in source");
    if (c.algorithm == Algorithm::DFT || c.algorithm == Algorithm::DWT_DCT_II)
        return frequency(y, c);
    Stages s;
    if (c.algorithm == Algorithm::SimPiece || c.algorithm == Algorithm::PMC ||
        c.algorithm == Algorithm::SWING) {
        s.source_bytes = compress_raw(y, c);
        s.reconstructed = decompress_raw(s.source_bytes);
        return s;
    }
    if (y.empty())
        return s;
    if (y.size() < 3) {
        s.working = y;
        s.mask.assign(y.size(), 1);
        s.diagnostic = "native short-object extension; unsafe upstream scan not called";
    } else
        s = c.algorithm == Algorithm::SWAB ? swab_stages(y, c) : lines(y, c);
    for (std::size_t i = 0; i < s.mask.size(); ++i)
        if (s.mask[i]) {
            s.points_x.push_back(double(i));
            s.points_y.push_back(s.working[i]);
        }
    require(!s.points_x.empty(), "no retained points");
    s.reconstructed = interpolate(s.points_x, s.points_y, std::size_t(s.points_x.back()) + 1);
    return s;
}
namespace {
std::uint32_t crc(const std::uint8_t *p, std::size_t n) {
    std::uint32_t c = ~0u;
    for (std::size_t i = 0; i < n; ++i) {
        c ^= p[i];
        for (int j = 0; j < 8; ++j)
            c = (c >> 1) ^ (0xedb88320u & std::uint32_t(-std::int32_t(c & 1)));
    }
    return ~c;
}
Values inverse_frequency(const Values &real, const Values &imag,
                         Algorithm alg) { // direct inverse, no transform/refit
    std::size_t n = real.size();
    Values out(n);
    if (!n)
        return out;
    if (alg == Algorithm::DFT) {
        require(imag.size() == n,
                "Fourier imaginary count"); // use the same bundled inverse transform
        // frequency() cannot be used: coefficients must be interpreted directly.

        return inverse_fft(real, imag);
    }
    return dct_ii(real, true);
}
} // namespace
Bytes encode(const Values &y, const Config &c) {
    auto s = analyze(y, c);
    Bytes payload;
    std::uint64_t count = 0, kind = 1;
    if (c.algorithm == Algorithm::SimPiece || c.algorithm == Algorithm::PMC ||
        c.algorithm == Algorithm::SWING) {
        payload = s.source_bytes;
        kind = 3;
        count = payload.size();
    } else if (c.algorithm == Algorithm::DFT || c.algorithm == Algorithm::DWT_DCT_II) {
        kind = 2;
        for (std::size_t i = 0; i < s.coefficients.size(); ++i)
            if (s.coefficients[i] != 0 || (c.algorithm == Algorithm::DFT && s.imaginary[i] != 0)) {
                u64(payload, i);
                f64(payload, s.coefficients[i]);
                if (c.algorithm == Algorithm::DFT)
                    f64(payload, s.imaginary[i]);
                ++count;
            }
    } else
        for (std::size_t i = 0; i < s.points_x.size(); ++i) {
            u64(payload, std::uint64_t(s.points_x[i]));
            f64(payload, s.points_y[i]);
            ++count;
        }
    Bytes out{'C', 'F', '0', '1'};
    u64(out, 1);
    u64(out, std::uint64_t(c.algorithm));
    u64(out, kind);
    u64(out, y.size());
    u64(out, s.reconstructed.size());
    u64(out, count);
    u64(out, payload.size());
    out.insert(out.end(), payload.begin(), payload.end());
    u64(out, crc(out.data(), out.size()));
    require(out.size() <= max_frame, "frame limit");
    return out;
}
Values decode(const std::uint8_t *p, std::size_t n) {
    require(p && n >= 68 && n <= max_frame, "frame size");
    require(std::memcmp(p, "CF01", 4) == 0, "frame magic");
    Reader check{p + n - 8, 8};
    auto checksum = check.u();
    require(checksum <= 0xffffffffu && std::uint32_t(checksum) == crc(p, n - 8), "checksum");
    Reader r{p, n - 8, 4};
    require(r.u() == 1, "frame version");
    auto id = r.u();
    require(id >= 1 && id <= 10, "frame algorithm");
    Algorithm a = Algorithm(id);
    auto kind = r.u(), input = r.u(), restored = r.u(), count = r.u(), bytes = r.u();
    require(input <= max_samples && restored <= max_samples && bytes == r.n - r.pos,
            "frame dimensions");
    Values out;
    if (kind == 3) {
        require(a == Algorithm::PMC || a == Algorithm::SWING || a == Algorithm::SimPiece,
                "raw algorithm");
        require(count == bytes, "raw accounting");
        Bytes b(p + r.pos, p + r.n);
        if (!b.empty())
            require(b.back() == 0 || (a == Algorithm::PMC && b.back() == 2) ||
                        (a == Algorithm::SWING && b.back() == 3) ||
                        (a == Algorithm::SimPiece && b.back() == 6),
                    "raw method mismatch");
        out = decompress_raw(b);
        r.pos = r.n;
        require(restored == input, "raw original size");
    } else if (kind == 2) {
        require(a == Algorithm::DFT || a == Algorithm::DWT_DCT_II, "frequency kind");
        std::size_t stride = a == Algorithm::DFT ? 24 : 16;
        require(restored == input && count <= input && bytes == count * stride,
                "frequency accounting");
        Values real(input, 0), imag(a == Algorithm::DFT ? input : 0, 0);
        std::uint64_t prev = 0;
        for (std::uint64_t i = 0; i < count; ++i) {
            auto index = r.u();
            require(index < input && (!i || index > prev), "coefficient index");
            real[index] = r.f();
            if (a == Algorithm::DFT)
                imag[index] = r.f();
            prev = index;
        }
        out = inverse_frequency(real, imag, a);
    } else if (kind == 1) {
        require(id <= 5 && count <= input && bytes == count * 16, "points accounting");
        Values xs, ys;
        xs.reserve(count);
        ys.reserve(count);
        std::uint64_t prev = 0;
        for (std::uint64_t i = 0; i < count; ++i) {
            auto index = r.u();
            require(index < input && (!i ? index == 0 : index > prev), "point order");
            xs.push_back(double(index));
            ys.push_back(r.f());
            prev = index;
        }
        if (count) {
            require(prev + 1 == restored, "point duration");
            out = interpolate(xs, ys, std::size_t(restored));
        } else
            require(input == 0 && restored == 0, "empty point object");
    } else
        throw std::invalid_argument("frame representation kind");
    require(r.pos == r.n && out.size() == restored, "frame consumption");
    checked(out);
    return out;
}
} // namespace cameo_family
namespace {
cameo_family::Config from_c(const cf_config_v1 &v) {
    using namespace cameo_family;
    require(v.version == 1 && v.reserved == 0 && (v.flags & ~31u) == 0, "C ABI version/flags");
    Config c;
    c.algorithm = Algorithm(v.algorithm);
    c.error_bound = v.error_bound;
    c.fraction = v.fraction;
    c.window_fraction = v.window_fraction;
    c.nlags = v.nlags;
    c.hops = v.hops;
    c.kappa = v.kappa;
    c.threads = v.threads;
    c.parallel_lookahead = v.flags & 1;
    c.ratio_stopping = v.flags & 2;
    c.bottom_up = v.flags & 4;
    c.python_bottom_up = v.flags & 8;
    c.canonical_dct = v.flags & 16;
    return c;
}
bool range(const void *p, size_t n) {
    auto a = reinterpret_cast<uintptr_t>(p);
    return (!n || p) && n <= UINTPTR_MAX - a;
}
bool overlap(const void *a, size_t an, const void *b, size_t bn) {
    if (!an || !bn)
        return false;
    auto x = reinterpret_cast<uintptr_t>(a), y = reinterpret_cast<uintptr_t>(b);
    return x < y + bn && y < x + an;
}
bool counters(size_t *used, size_t *need, const void *in, size_t inbytes, const void *out,
              size_t outbytes, const void *config = nullptr, size_t configbytes = 0) {
    if (!used || !need || reinterpret_cast<uintptr_t>(used) % alignof(size_t) ||
        reinterpret_cast<uintptr_t>(need) % alignof(size_t))
        return false;
    if (!range(used, sizeof(size_t)) || !range(need, sizeof(size_t)) ||
        overlap(used, sizeof(size_t), need, sizeof(size_t)))
        return false;
    if (!range(in, inbytes) || !range(out, outbytes) || !range(config, configbytes))
        return false;
    for (auto p : {used, need})
        if (overlap(p, sizeof(size_t), in, inbytes) || overlap(p, sizeof(size_t), out, outbytes) ||
            overlap(p, sizeof(size_t), config, configbytes))
            return false;
    return true;
}
template <class F> int protect(size_t *produced, size_t *required, F f) {
    *produced = 0;
    *required = 0;
    try {
        return f();
    } catch (const std::bad_alloc &) {
        return CF_NOMEM;
    } catch (const std::invalid_argument &) {
        return CF_INVALID;
    } catch (...) {
        return CF_INTERNAL;
    }
}
} // namespace
extern "C" uint32_t cf_api_version_v1() { return 1; }
extern "C" int cf_encode_v1(const double *p, size_t n, const cf_config_v1 *c, uint8_t *out,
                            size_t cap, size_t *used, size_t *need) {
    if (n > cameo_family::max_samples || cap > cameo_family::max_frame ||
        !counters(used, need, p, n * sizeof(double), out, cap, c, c ? sizeof(*c) : 0))
        return CF_INVALID;
    return protect(used, need, [&]() {
        using namespace cameo_family;
        require(c && (p || !n) && (out || !cap), "encode pointers");
        cf_config_v1 saved;
        std::memcpy(&saved, c, sizeof(saved));
        Values values;
        if (n) {
            values.resize(n);
            std::memcpy(values.data(), p, n * sizeof(double));
        }
        auto b = encode(values, from_c(saved));
        *need = b.size();
        if (cap < b.size() || !out)
            return int(CF_CAPACITY);
        std::memcpy(out, b.data(), b.size());
        *used = b.size();
        return int(CF_OK);
    });
}
extern "C" int cf_decode_v1(const uint8_t *p, size_t n, double *out, size_t cap, size_t *used,
                            size_t *need) {
    if (n > cameo_family::max_frame || cap > cameo_family::max_samples ||
        !counters(used, need, p, n, out, cap * sizeof(double)))
        return CF_INVALID;
    return protect(used, need, [&]() {
        using namespace cameo_family;
        require(p && (out || !cap), "decode pointers");
        auto v = decode(p, n);
        *need = v.size();
        if (cap < v.size() || (!out && !v.empty()))
            return int(CF_CAPACITY);
        if (!v.empty())
            std::memcpy(out, v.data(), v.size() * sizeof(double));
        *used = v.size();
        return int(CF_OK);
    });
}
