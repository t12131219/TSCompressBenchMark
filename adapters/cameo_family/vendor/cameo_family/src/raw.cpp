// SPDX-License-Identifier: Apache-2.0
// Translation of TerseTS PMC-Mean, connected SwingFilter and SimPiece.
#include "internal.hpp"
#include <map>
namespace cameo_family {
namespace {
struct Segment {
    std::size_t start;
    double intercept, lo, hi;
};
using Group = std::map<double, std::map<double, std::vector<std::size_t>>>;
float error_bound(const Config &c) {
    require(std::isfinite(c.error_bound) && c.error_bound >= 0 &&
                c.error_bound <= std::numeric_limits<float>::max(),
            "invalid absolute error");
    return float(c.error_bound);
}
Bytes pmc(const Values &y, float e) {
    Bytes b;
    std::size_t index = 0;
    if (e == 0) {
        double current = y[0];
        for (std::size_t i = 1; i < y.size(); ++i) {
            if (y[i] != current) {
                f64(b, current);
                u64(b, i);
                current = y[i];
            }
        }
        f64(b, current);
        u64(b, y.size());
        return b;
    }
    double lo = std::numeric_limits<double>::quiet_NaN(), hi = lo, length = 0;
    long double mean = 0;
    for (double v : y) {
        double l = std::fmin(v, lo), h = std::fmax(v, hi), len = length + 1;
        long double av = (mean * length + v) / len;
        if (h - av > e || av - l > e) {
            f64(b, double(mean));
            u64(b, index);
            lo = hi = v;
            length = 1;
            mean = v;
        } else {
            lo = l;
            hi = h;
            length = len;
            mean = av;
        }
        ++index;
    }
    f64(b, double(mean));
    u64(b, index);
    return b;
}
struct Line {
    double slope, intercept;
    double at(std::size_t i) const { return slope * double(i) + intercept; }
};
Line line(std::size_t start, double a, std::size_t end, double b, float error) {
    double s = (b + error - a) / double(end - start);
    return {s, a - s * double(start)};
}
Bytes swing(const Values &y, float e) {
    float adjusted = e > 0 ? float(e - 1e-7f) : e;
    Bytes b;
    std::size_t start = 0, end = 1;
    double a = y[0], z = y[1], derivative = z - a;
    Line upper = line(start, a, end, z, adjusted), lower = line(start, a, end, z, -adjusted);
    f64(b, a);
    auto record = [&](std::size_t i) {
        std::size_t count = i - start - 1;
        double value = z;
        if (count > 1) {
            double sums = double(count * (count + 1) * (2 * count + 1) / 6);
            double slope = std::fmax(std::fmin(derivative / sums, upper.slope), lower.slope);
            value = slope * double(i - 1) + (a - slope * double(start));
        }
        f64(b, value);
        u64(b, i);
        return value;
    };
    for (std::size_t i = 2; i < y.size(); ++i) {
        double ul = upper.at(i), ll = lower.at(i);
        if (!std::isfinite(ul + ll + y[i]) || ul < y[i] - adjusted || ll > y[i] + adjusted) {
            double value = record(i);
            start = i - 1;
            a = value;
            end = i;
            z = y[i];
            upper = line(start, a, end, z, adjusted);
            lower = line(start, a, end, z, -adjusted);
            derivative = (z - a) * double(end - start);
        } else {
            end = i;
            z = y[i];
            auto u = line(start, a, end, z, adjusted), l = line(start, a, end, z, -adjusted);
            if (ul > u.at(i))
                upper = u;
            if (ll < l.at(i))
                lower = l;
            derivative += (z - a) * double(end - start);
        }
    }
    record(y.size());
    return b;
}
Bytes simpiece(const Values &y, float e) {
    require(e != 0, "SimPiece zero error unsupported");
    require(std::fabs(y[0]) <= 1e15, "SimPiece first-value domain");
    float adjusted = e - 1e-7f;
    std::vector<Segment> meta;
    double lo = -std::numeric_limits<double>::max(), hi = std::numeric_limits<double>::max();
    std::size_t start = 0;
    double inter = std::floor(y[0] / e) * e + 1e-7f;
    for (std::size_t i = 1; i < y.size(); ++i) {
        require(y[i] <= 1e15, "SimPiece value domain");
        double duration = double(i - start), ul = hi * duration + inter, ll = lo * duration + inter;
        if (ul < y[i] - adjusted || ll > y[i] + adjusted) {
            meta.push_back({start, inter, lo, hi});
            start = i;
            inter = std::floor(y[i] / e) * e + 1e-7f;
            hi = std::numeric_limits<double>::max();
            lo = -hi;
        } else {
            double uh = (y[i] + adjusted - inter) / duration,
                   lh = (y[i] - adjusted - inter) / duration;
            if (y[i] + adjusted < ul)
                hi = std::fmax(uh, lo);
            if (y[i] - adjusted > ll)
                lo = std::fmin(lh, hi);
        }
    }
    if (y.size() - start == 1)
        hi = lo = 0;
    meta.push_back({start, inter, lo, hi});
    std::map<double, std::vector<Segment>> byinter;
    for (auto q : meta)
        byinter[q.intercept].push_back(q);
    std::vector<Segment> merged;
    for (auto &entry : byinter) {
        auto &v = entry.second;
        std::stable_sort(v.begin(), v.end(), [](auto a, auto b) { return a.lo < b.lo; });
        Segment current = v[0];
        std::vector<std::size_t> ids{current.start};
        auto emit = [&]() {
            for (auto i : ids)
                merged.push_back({i, current.intercept, current.lo, current.hi});
        };
        for (std::size_t i = 1; i < v.size(); ++i) {
            auto q = v[i];
            if (q.lo <= current.hi && q.hi >= current.lo) {
                ids.push_back(q.start);
                current.lo = std::fmax(current.lo, q.lo);
                current.hi = std::fmin(current.hi, q.hi);
            } else {
                emit();
                current = q;
                ids.assign(1, q.start);
            }
        }
        emit();
    }
    std::sort(merged.begin(), merged.end(), [](auto a, auto b) { return a.start < b.start; });
    Group groups;
    for (auto q : merged)
        groups[q.intercept][(q.lo + q.hi) / 2].push_back(q.start);
    Bytes b;
    for (auto &intercepts : groups) {
        f64(b, intercepts.first);
        u64(b, intercepts.second.size());
        for (auto &slopes : intercepts.second) {
            f64(b, slopes.first);
            u64(b, slopes.second.size());
            std::size_t prev = 0;
            for (auto i : slopes.second) {
                u64(b, i - prev);
                prev = i;
            }
        }
    }
    u64(b, y.size());
    return b;
}
} // namespace
Bytes compress_raw(const Values &y, const Config &c) {
    checked(y);
    require(c.algorithm == Algorithm::SimPiece || c.algorithm == Algorithm::PMC ||
                c.algorithm == Algorithm::SWING,
            "raw method required");
    Bytes b;
    if (y.empty())
        return b;
    if (y.size() == 1) {
        f64(b, y[0]);
        b.push_back(0);
        return b;
    }
    float e = error_bound(c);
    if (c.algorithm == Algorithm::PMC)
        b = pmc(y, e);
    else if (c.algorithm == Algorithm::SWING)
        b = swing(y, e);
    else
        b = simpiece(y, e);
    b.push_back(c.algorithm == Algorithm::PMC ? 2 : c.algorithm == Algorithm::SWING ? 3 : 6);
    require(b.size() <= max_frame, "raw frame limit");
    return b;
}
Values decompress_raw(const Bytes &b) {
    if (b.empty())
        return {};
    require(b.size() <= max_frame, "raw frame limit");
    auto method = b.back();
    Reader r{b.data(), b.size() - 1};
    Values out;
    if (method == 0) {
        require(r.n % 8 == 0, "raw length");
        while (r.pos < r.n) {
            require(out.size() < max_samples, "output limit");
            out.push_back(r.f());
        }
    } else if (method == 2) {
        require(r.n % 16 == 0, "PMC tuple size");
        while (r.pos < r.n) {
            double v = r.f();
            auto end = r.u();
            require(end >= out.size() && end <= max_samples, "PMC index");
            out.resize(end, v);
        }
    } else if (method == 3) {
        require(r.n >= 24 && (r.n - 8) % 16 == 0, "Swing tuple size");
        double start = r.f();
        out.push_back(start);
        std::size_t index = 0;
        while (r.pos < r.n) {
            double endvalue = r.f();
            auto count = r.u();
            require(count >= 2 && count <= max_samples && count - 1 > index, "Swing index");
            std::size_t end = count - 1;
            auto l = line(index, start, end, endvalue, 0);
            for (std::size_t i = index + 1; i < end; ++i)
                out.push_back(l.at(i));
            out.push_back(endvalue);
            index = end;
            start = endvalue;
        }
    } else if (method == 6) {
        require(r.n >= 8 && r.n % 8 == 0, "SimPiece alignment");
        std::vector<Segment> segments;
        while (r.pos < r.n - 8) {
            double inter = r.f();
            auto slopes = r.u();
            require(slopes > 0 && slopes <= (r.n - r.pos) / 24, "SimPiece slopes");
            for (std::uint64_t i = 0; i < slopes; ++i) {
                double slope = r.f();
                auto count = r.u();
                require(count > 0 && count <= (r.n - r.pos) / 8 &&
                            count <= max_samples - segments.size(),
                        "SimPiece count");
                std::uint64_t index = 0;
                for (std::uint64_t j = 0; j < count; ++j) {
                    auto delta = r.u();
                    require(delta <= max_samples - index, "SimPiece delta");
                    index += delta;
                    segments.push_back({std::size_t(index), inter, slope, slope});
                }
            }
        }
        auto n = r.u();
        require(n <= max_samples && !segments.empty(), "SimPiece restored count");
        std::sort(segments.begin(), segments.end(),
                  [](auto a, auto b) { return a.start < b.start; });
        require(segments.front().start == 0, "SimPiece first index");
        for (std::size_t j = 0; j < segments.size(); ++j) {
            auto q = segments[j];
            std::size_t end = j + 1 < segments.size() ? segments[j + 1].start : std::size_t(n);
            require(end > q.start && end <= n, "SimPiece segment order");
            for (auto i = q.start; i < end; ++i)
                out.push_back(q.hi * double(i - q.start) + q.intercept);
        }
    } else
        throw std::invalid_argument("unsupported raw method");
    require(r.pos == r.n, "raw trailing bytes");
    checked(out);
    return out;
}
} // namespace cameo_family
