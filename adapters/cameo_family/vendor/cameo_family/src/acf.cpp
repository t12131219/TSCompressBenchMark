// SPDX-License-Identifier: Apache-2.0
// Structured translation of frozen CAMEO Cython LPC/HPC/FGC stages.
#include "internal.hpp"
#include <array>
#ifdef CF_DIAGNOSTIC_TRACE
#include <iostream>
#include <iomanip>
#endif
namespace cameo_family {
namespace {
template <class T> struct Node {
    T value = inf;
    I ts = 0, left = -1, right = -1;
};
template <class T> struct Heap {
    std::vector<Node<T>> v;
    std::vector<I> where;
    I count = 0;
    void swap(I a, I b) {
        std::swap(v[a], v[b]);
        where[v[a].ts] = a;
        where[v[b].ts] = b;
    }
    I up(I i) {
        while (i > 0 && v[i].value < v[(i - 1) / 2].value) {
            swap(i, (i - 1) / 2);
            i = (i - 1) / 2;
        }
        return i;
    }
    void down(I i) {
        for (;;) {
            I q = i, l = 2 * i + 1, r = l + 1;
            if (l < count && (v[l].value < v[q].value ||
                              (sizeof(T) > 8 && v[l].value == v[q].value && v[l].ts < v[q].ts)))
                q = l;
            if (r < count && (v[r].value < v[q].value ||
                              (sizeof(T) > 8 && v[r].value == v[q].value && v[r].ts < v[q].ts)))
                q = r;
            if (i == q)
                break;
            swap(i, q);
            i = q;
        }
    }
    void init(const std::vector<Node<T>> &nodes, I n) {
        v = nodes;
        count = I(v.size());
        where.assign(n, -1);
        for (I start = count / 2; start >= 0; --start) {
            I i = start, ch = 2 * i + 1;
            while (ch < count) {
                I r = ch + 1;
                if (r < count &&
                    (v[ch].value > v[r].value ||
                     (sizeof(T) > 8 && v[ch].value == v[r].value && v[ch].ts > v[r].ts)))
                    ch = r;
                std::swap(v[ch], v[i]);
                i = ch;
                ch = 2 * i + 1;
            }
            while (i > start && (v[i].value < v[(i - 1) / 2].value ||
                                 (sizeof(T) > 8 && v[i].value == v[(i - 1) / 2].value &&
                                  v[i].ts < v[(i - 1) / 2].ts))) {
                std::swap(v[i], v[(i - 1) / 2]);
                i = (i - 1) / 2;
            }
        }
        for (I i = 0; i < count; ++i)
            where[v[i].ts] = i;
    }
    Node<T> pop() {
        require(count > 2, "source heap endpoint guard");
        auto q = v[0];
        where[q.ts] = -1;
        --count;
        v[0] = v[count];
        v[count] = {T(inf), -1, -1, -1};
        where[v[0].ts] = 0;
        down(0);
        return q;
    }
    Node<T> &at(I ts) {
        require(ts >= 0 && ts < I(where.size()) && where[ts] >= 0, "invalid source neighbor");
        return v[where[ts]];
    }
    void links(const Node<T> &q) {
        if (q.left >= 0)
            at(q.left).right = q.right;
        if (q.right < I(where.size()))
            at(q.right).left = q.left;
    }
    void reheap(Node<T> q) {
        I i = where[q.ts];
        require(i >= 0, "missing heap node");
        if (v[i].value != q.value) {
            v[i] = q;
            down(up(i));
        }
    }
};
template <class T> struct ACF {
    I n = 0, L = 0, k = 1;
    std::vector<T> a, xs, ys, xss, yss, sxy, raw;
    ACF(Values &y, const Config &c)
        : n(I(y.size() / c.kappa)), L(I(c.nlags)), k(I(c.kappa)), a(n), xs(L), ys(L), xss(L),
          yss(L), sxy(L) {
        for (I j = 0; j < n; ++j) {
            T s = 0;
            for (I i = 0; i < k; ++i)
                s += T(y[j * k + i]);
            a[j] = s / k;
        }
        std::vector<T> s(n), ss(n);
        I chunk = n / 8;
        // Source uses exactly eight independent prefix-scan chunks.
        parallel_for(0, 8, c.threads, [&](I tid) {
            I start = tid * chunk, end = tid == 7 ? n : start + chunk;
            s[start] = a[start];
            ss[start] = a[start] * a[start];
            for (I i = start + 1; i < end; ++i) {
                s[i] = s[i - 1] + a[i];
                ss[i] = ss[i - 1] + a[i] * a[i];
            }
        });
        std::array<T, 8> ps{}, pss{};
        ps[0] = s[chunk - 1];
        pss[0] = ss[chunk - 1];
        for (I t = 1; t < 7; ++t) {
            ps[t] = ps[t - 1] + s[(t + 1) * chunk - 1];
            pss[t] = pss[t - 1] + ss[(t + 1) * chunk - 1];
        }
        for (I tid = 1; tid < 8; ++tid) {
            T sums = ps[tid - 1], sumsq = pss[tid - 1];
            I end = tid == 7 ? n : (tid + 1) * chunk;
            for (I i = tid * chunk; i < end; ++i) {
                s[i] += sums;
                ss[i] += sumsq;
            }
        }
        for (I lag = 0; lag < L; ++lag) {
            xs[lag] = s[n - lag - 2];
            ys[lag] = s[n - 1] - s[lag];
            xss[lag] = ss[n - lag - 2];
            yss[lag] = ss[n - 1] - ss[lag];
            T dot = 0;
            for (I i = 0; i < n - lag - 1; ++i)
                dot += a[i] * a[i + lag + 1];
            sxy[lag] = dot;
        }
        raw = acf();
    }
    T rho(I lag, I count, bool narrow = false) const {
        T den = (count * xss[lag] - xs[lag] * xs[lag]) * (count * yss[lag] - ys[lag] * ys[lag]);
        (void)narrow;
        T sq = std::sqrt(den);
        return (count * sxy[lag] - xs[lag] * ys[lag]) / sq;
    }
    std::vector<T> acf() const {
        std::vector<T> r(L);
        for (I lag = 0; lag < L; ++lag)
            r[lag] = rho(lag, n - lag - 1);
        return r;
    }
    T error(I count, bool narrow = false, bool cdouble = false) const {
        if (cdouble) {
            double sum = 0;
            for (I l = 0; l < L; ++l) {
                double v = double(rho(l, count - l - 1, narrow));
                sum = double(T(sum) + std::abs(raw[l] - T(v)));
            }
            return sum / double(L);
        }
        T sum = 0;
        for (I l = 0; l < L; ++l)
            sum += std::abs(raw[l] - rho(l, count - l - 1, narrow));
        return sum / L;
    }
    void one_delta(I j, T d, bool outside) {
        T ds = d * (2 * a[j] + d);
        for (I l = 0; l < L; ++l) {
            if (outside) {
                ys[l] += d;
                yss[l] += ds;
                xs[l] += d;
                xss[l] += ds;
                sxy[l] += d * (a[j + l + 1] + a[j - l - 1]);
            } else {
                if (j >= l + 1) {
                    ys[l] += d;
                    yss[l] += ds;
                    sxy[l] += d * a[j - l - 1];
                }
                if (j < n - 1 - l) {
                    xs[l] += d;
                    xss[l] += ds;
                    sxy[l] += d * a[j + l + 1];
                }
            }
        }
    }
    void single(Values &y, T val, I j) {
        I q = j / k;
        T d = (val - y[j]) / k;
        if (d != 0) {
            one_delta(q, d, q > L && q < n - L);
            y[j] = double(val);
            if (k == 1)
                a[q] = T(y[j]);
            else
                a[q] += d;
        }
    }
    void interpolate_update(Values &y, I start, I end) {
        require(start >= 0 && end < I(y.size()) && end > start, "source interval guard");
        if (start + 2 >= end) {
            T v = T((y[end] - y[start]) / double(end - start) + y[start]);
            single(y, v, start + 1);
            return;
        }
        T slope = T((y[end] - y[start]) / double(end - start));
        I first = (start + 1) / k, last = (end - 1) / k;
        std::vector<T> d(last - first + 1, 0);
        Values restored(end - start - 1);
        for (I j = start + 1; j < end; ++j) {
            T val = slope * (j - start) + y[start];
            d[j / k - first] += val - y[j];
            restored[j - start - 1] = double(val);
        }
        bool outside = first > L && last < n - L;
        for (I q = first; q <= last; ++q) {
            I i = q - first;
            d[i] /= k;
            T delta = d[i], ds = delta * (delta + 2 * a[q]);
            for (I l = 0; l < L; ++l) {
                if (outside) {
                    xs[l] += delta;
                    ys[l] += delta;
                    yss[l] += ds;
                    xss[l] += ds;
                    sxy[l] += delta * (a[q - l - 1] + a[q + l + 1]);
                } else {
                    if (q > l) {
                        ys[l] += delta;
                        yss[l] += ds;
                        sxy[l] += delta * a[q - l - 1];
                    }
                    if (q < n - 1 - l) {
                        xs[l] += delta;
                        xss[l] += ds;
                        sxy[l] += delta * a[q + l + 1];
                    }
                }
            }
        }
        for (I l = 0; l < std::min<I>(I(d.size()), L); ++l)
            for (I i = 0; i < I(d.size()) - l - 1; ++i)
                sxy[l] += d[i] * d[i + l + 1];
        for (I j = start + 1; j < end; ++j)
            y[j] = restored[j - start - 1];
        for (I q = first; q <= last; ++q) {
            if (k == 1)
                a[q] = T(y[q]);
            else
                a[q] += d[q - first];
        }
    }
    T initial_impact(const Values &y, I j) const {
        T d = T(((y[j - 1] + y[j + 1]) * .5 - y[j]) / double(k));
        I q = j / k;
        T ds = d * (2 * a[q] + d), err = 0;
        for (I l = 0; l < L; ++l) {
            T xx = xs[l], yy = ys[l], xxx = xss[l], yyy = yss[l], xy = sxy[l];
            I count = n - l - 1;
            if (L <= q && q < n - L) {
                yy += d;
                yyy += ds;
                xx += d;
                xxx += ds;
                xy += d * (k == 1 ? (a[q - l - 1] + a[q + l + 1]) : (a[q + l + 1] + a[q - l - 1]));
            } else if (q < L) {
                xx += d;
                xxx += ds;
                xy += d * a[q + l + 1];
                if (q >= l + 1) {
                    yy += d;
                    yyy += ds;
                    xy += d * a[q - l - 1];
                }
            } else {
                yy += d;
                yyy += ds;
                xy += d * a[q - l - 1];
                if (q < count) {
                    xx += d;
                    xxx += ds;
                    xy += d * a[q + l + 1];
                }
            }
            T den = (count * xxx - xx * xx) * (count * yyy - yy * yy);
            T corr = (count * xy - xx * yy) / std::sqrt(den);
            err += std::abs(raw[l] - corr);
        }
        return T(double(err / L));
    }
    T lookahead(const Values &y, I start, I end) const {
        ACF m = *this;
        if (start + 2 < end) {
            T slope = T((y[end] - y[start]) / double(end - start));
            I first = (start + 1) / k, last = (end - 1) / k;
            std::vector<T> d(last - first + 1, 0);
            for (I j = start + 1; j < end; ++j)
                d[j / k - first] += (slope * (j - start) + y[start] - y[j]);
            for (I q = first; q <= last; ++q) {
                T delta = (d[q - first] /= k), ds = delta * (delta + 2 * a[q]);
                for (I l = 0; l < L; ++l) {
                    if (q > l) {
                        m.ys[l] += delta;
                        m.yss[l] += ds;
                        m.sxy[l] += delta * a[q - l - 1];
                    }
                    if (q < n - 1 - l) {
                        m.xs[l] += delta;
                        m.xss[l] += ds;
                        m.sxy[l] += delta * a[q + l + 1];
                    }
                }
            }
            for (I l = 0; l < L; ++l)
                for (I i = 0; i < I(d.size()) - l - 1; ++i)
                    m.sxy[l] += d[i] * d[i + l + 1];
        } else {
            T val = T((y[end] - y[start]) / double(end - start) + y[start]),
              d = (val - y[start + 1]) / k;
            if (d == 0)
                return 0;
            I q = (start + 1) / k;
            T ds = d * (2 * a[q] + d);
            for (I l = 0; l < L; ++l) {
                if (q > l) {
                    m.ys[l] += d;
                    m.yss[l] += ds;
                    m.sxy[l] += d * a[q - l - 1];
                }
                if (q < n - 1 - (k > 1 ? 2 * l : l)) {
                    m.xs[l] += d;
                    m.xss[l] += ds;
                    m.sxy[l] += d * a[q + l + 1];
                }
            }
        }
        return m.error(n);
    }
};
struct PIP {
    struct P {
        I left = -1, right = -1, index = 0, order = 0;
        double value = 0, cache = inf;
    };
    std::vector<P> nodes;
    std::vector<I> v;
    I size = 0;
    explicit PIP(const Values &y) : nodes(y.size()), v(y.size()) {
        std::iota(v.begin(), v.end(), 0);
        for (I i = 0; i < I(y.size()); ++i)
            nodes[i].index = i;
        I tail = -1;
        for (I i = 0; i < I(y.size()); ++i) {
            I id = v[size++];
            auto &q = nodes[id];
            q.value = y[i];
            q.order = size;
            if (tail >= 0) {
                nodes[tail].right = id;
                cache(tail);
            }
            q.left = tail;
            cache(id);
            tail = id;
        }
    }
    bool less(I i, I j) const {
        if (i >= size)
            return false;
        if (j >= size)
            return true;
        auto &a = nodes[v[i]], &b = nodes[v[j]];
        return a.cache != b.cache ? a.cache < b.cache : a.order < b.order;
    }
    I swap(I a, I b) {
        nodes[v[a]].index = b;
        nodes[v[b]].index = a;
        std::swap(v[a], v[b]);
        return b;
    }
    I up(I i) {
        while (i != 0 && less(i, (i - 1) / 2))
            i = swap(i, (i - 1) / 2);
        return i;
    }
    I down(I i) {
        for (;;) {
            I j = less(2 * i + 1, 2 * i + 2) ? 2 * i + 1 : 2 * i + 2;
            I k = less(i, j) ? i : j;
            if (k == i || k >= size)
                return i;
            i = swap(i, k);
        }
    }
    void cache(I id) {
        auto &q = nodes[id];
        if (q.left >= 0 && q.right >= 0) {
            auto &a = nodes[q.left], &c = nodes[q.right];
            double ax = double(q.left), bx = double(id), cx = double(q.right);
            q.cache = std::abs(a.value + (c.value - a.value) * (bx - ax) / (cx - ax) - q.value);
        } else
            q.cache = inf;
        down(up(q.index));
    }
    I pop() {
        --size;
        swap(0, size);
        down(0);
        I id = v[size];
        auto q = nodes[id];
        if (q.left >= 0) {
            nodes[q.left].right = q.right;
            cache(q.left);
        }
        if (q.right >= 0) {
            nodes[q.right].left = q.left;
            cache(q.right);
        }
        return id;
    }
};
double area(const Values &y, I i, I l, I r) {
    return std::fabs(double(i) * (y[l] - y[r]) + double(l) * (y[r] - y[i]) +
                     double(r) * (y[i] - y[l])) /
           2.;
}
double importance(const Values &y, I l, I r) {
    double slope = (y[r] - y[l]) / double(r - l), intercept = y[l] - slope * double(l), sum = 0;
    for (I i = l; i < r; ++i)
        sum += std::fabs(slope * double(i) + intercept - y[i]);
    return sum / double(r - l);
}
template <class T> Stages simplify(Values y, const Config &c) {
    I n = I(y.size());
    ACF<T> m(y, c);
    Stages out;
    out.mask.assign(n, 1);
    Heap<T> h;
    std::vector<Node<T>> nodes;
    if (c.algorithm == Algorithm::PIP) {
        PIP p(y);
        while (p.size > 2) {
            I id = p.v[0];
            if (!(p.nodes[id].cache < inf))
                break;
            auto q = p.nodes[id];
            if (q.left < 0 || q.right < 0) {
                out.diagnostic = "source PIP endpoint dereference prevented";
                break;
            }
            p.pop();
            m.interpolate_update(y, q.left, q.right);
            double err = m.error(n, true, true);
            if (err >= c.error_bound)
                break;
            out.mask[id] = 0;
        }
    } else {
        if (c.algorithm == Algorithm::TP) {
            out.mask.assign(n, 0);
            Values orig = y;
            std::vector<I> selected{0};
            std::vector<double> values{inf};
            out.mask[0] = 1;
            for (I i = 1; i < n - 1; ++i) {
                bool line = y[i - 1] == y[i] && y[i] == y[i + 1],
                     turn = (y[i] >= y[i - 1] && y[i] >= y[i + 1]) ||
                            (y[i - 1] >= y[i] && y[i + 1] >= y[i]);
                if (!line && turn) {
                    I prev = selected.back();
                    double imp = 0;
                    if (prev + 1 < i) {
                        const bool first_span = selected.size() == 1;
                        if (first_span)
                            out.diagnostic = "tp-first-span-v1: first turning span repaired";
                        if (first_span || prev + 2 < i)
                            m.interpolate_update(y, prev, i);
                        else {
                            I l = selected[selected.size() - 2];
                            double xa = (y[prev] - y[l]) / double(prev - l) + y[l];
                            m.single(y, T(xa), l + 1);
                        }
                        double slope = (y[i] - y[prev]) / double(i - prev),
                               inter = y[prev] - slope * double(prev), sum = 0;
                        for (I j = prev; j <= i; ++j)
                            sum += std::fabs(slope * double(j) + inter - orig[j]);
                        imp = sum /
                              double(first_span ? i - prev : prev - selected[selected.size() - 2]);
                    }
                    selected.push_back(i);
                    values.push_back(imp);
                    out.mask[i] = 1;
                }
            }
            selected.push_back(n - 1);
            values.push_back(inf);
            out.mask[n - 1] = 1;
            if (m.error(n, false, true) >= c.error_bound) {
                out.mask.assign(n, 1);
                if (!out.diagnostic.empty())
                    out.diagnostic += "; ";
                out.diagnostic += "source TP uninitialized-free early exit safely handled";
                out.working = y;
                return out;
            }
            for (I i = 0; i < I(selected.size()); ++i)
                nodes.push_back({T(values[i]), selected[i], i ? selected[i - 1] : -1,
                                 i + 1 < I(selected.size()) ? selected[i + 1] : n});
            h.init(nodes, n);
        } else {
            out.initial_impacts.resize(n);
            out.initial_impacts[0] = out.initial_impacts[n - 1] = inf;
            if (c.algorithm == Algorithm::CAMEO)
                parallel_for(1, n - 1, c.threads,
                             [&](I i) { out.initial_impacts[i] = double(m.initial_impact(y, i)); });
            else
                for (I i = 1; i < n - 1; ++i)
                    out.initial_impacts[i] = std::fabs(double(i - 1) * (y[i] - y[i + 1]) +
                                                       double(i) * (y[i + 1] - y[i - 1]) +
                                                       double(i + 1) * (y[i - 1] - y[i])) *
                                             .5;
            for (I i = 0; i < n; ++i)
                nodes.push_back({T(out.initial_impacts[i]), i, i - 1, i + 1});
            h.init(nodes, n);
        }
        T ace = 0;
        I order = 0;
        while (h.count > 2 && h.v[0].value < T(inf)) {
            auto q = h.pop();
#ifdef CF_DIAGNOSTIC_TRACE
            std::cerr << "TRACE " << q.ts << " " << std::setprecision(17) << double(q.value)
                      << " [";
            for (std::size_t z = 0; z < y.size(); ++z)
                std::cerr << (z ? ", " : "") << y[z];
            std::cerr << "]\n";
#endif
            if (c.parallel_lookahead && c.kappa == 1)
                ace = 0;
            if (q.value != 0 || c.algorithm == Algorithm::TP) {
                m.interpolate_update(y, q.left, q.right);
                ace = m.error(c.algorithm == Algorithm::TP ? n : m.n, false,
                              c.algorithm == Algorithm::TP);
            }
            if (c.ratio_stopping) {
                if (n / (n - order) > I(c.error_bound))
                    break;
            } else if (ace >= c.error_bound)
                break;
            ++order;
            out.mask[q.ts] = 0;
            h.links(q);
            if (c.algorithm == Algorithm::VW) {
                for (I id : {q.right, q.left})
                    if (id > 0 && id < n - 1) {
                        auto v = h.at(id);
                        double x = area(y, v.ts, v.left, v.right);
                        v.value = T(x <= double(q.value) ? q.value : T(x));
                        h.reheap(v);
                    }
            } else if (c.algorithm == Algorithm::TP) {
                for (I id : {q.left, q.right})
                    if (id > 0 && id < n - 1) {
                        auto &v = h.at(id);
                        double x = importance(y, v.left, v.right);
                        if (x > double(v.value))
                            v.value = T(x); /* source changes same slot before reheap: equality
                                               prevents reheap */
                    }
            } else if (!c.parallel_lookahead && !c.ratio_stopping || ace != 0) {
                std::vector<Node<T>> nb;
                I left = q.left, right = q.right;
                for (I i = 0; i < I(c.hops); ++i) {
                    if (left > 0) {
                        auto v = h.at(left);
                        nb.push_back(v);
                        left = v.left;
                    }
                    if (right < n - 1) {
                        auto v = h.at(right);
                        nb.push_back(v);
                        right = v.right;
                    }
                }
                std::vector<T> impact(nb.size());
                parallel_for(0, I(nb.size()), c.parallel_lookahead ? c.threads : 1,
                             [&](I i) { impact[i] = m.lookahead(y, nb[i].left, nb[i].right); });
                for (std::size_t i = 0; i < nb.size(); ++i) {
                    nb[i].value = impact[i];
                    h.reheap(nb[i]);
                }
            }
        }
    }
    out.working = std::move(y);
    return out;
}
} // namespace
Stages lines(const Values &y, const Config &c) {
    require(c.kappa && y.size() % c.kappa == 0, "length must be multiple of kappa");
    std::size_t n = y.size() / c.kappa;
    require(n >= 8 && c.nlags > 0 && c.nlags < n / 2 && c.hops > 0 && c.hops <= max_samples,
            "ACF scan/lag/hops domain");
    long double planned =
        static_cast<long double>(y.size()) * y.size() * c.nlags * std::min(c.hops, std::size_t(16));
    require(planned <= 1e8L, "ACF work limit");
    return c.kappa > 1 ? simplify<long double>(y, c) : simplify<double>(y, c);
}
} // namespace cameo_family
