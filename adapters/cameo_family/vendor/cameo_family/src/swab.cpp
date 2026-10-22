// SPDX-License-Identifier: Apache-2.0
#include "internal.hpp"
#include <queue>
#include <tuple>
namespace cameo_family {
double reference_lstsq_error(const Values &, I, I);
namespace {
double fit_error(const Values &y, I first, I last, bool python) {
    require(first >= 0 && last < I(y.size()) && last >= first, "SWAB interval");
    I len = last - first + 1;
    if (len <= 1)
        return 0;
    if (python)
        return reference_lstsq_error(y, first, last);
    double sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (I i = first; i <= last; ++i) {
        sx += double(i);
        sy += y[i];
        sxx += double(i * i);
        sxy += double(i) * y[i];
    }
    double n = double(len), var = sxx - sx * sx / n, mean = sy / n,
           slope = std::fabs(var) < 1e-14 ? 0 : (sxy - sx * sy / n) / var,
           intercept = mean - slope * (sx / n), sse = 0;
    for (I i = first; i <= last; ++i) {
        double d = y[i] - (slope * double(i) + intercept);
        sse += d * d;
    }
    return python ? (len <= 2 ? 0 : sse) : std::sqrt(std::max(sse, 0.));
}
struct S {
    double cost = inf;
    I id = 0, first = 0, last = 0, left = -1, right = -1;
};
struct H {
    std::vector<S> v;
    std::vector<I> where;
    I count = 0;
    void sw(I a, I b) {
        std::swap(v[a], v[b]);
        where[v[a].id] = a;
        where[v[b].id] = b;
    }
    I up(I i) {
        while (i > 0 && v[i].cost < v[(i - 1) / 2].cost) {
            sw(i, (i - 1) / 2);
            i = (i - 1) / 2;
        }
        return i;
    }
    void down(I i) {
        for (;;) {
            I q = i, l = 2 * i + 1, r = l + 1;
            if (l < count && v[l].cost < v[q].cost)
                q = l;
            if (r < count && v[r].cost < v[q].cost)
                q = r;
            if (i == q)
                break;
            sw(i, q);
            i = q;
        }
    }
    void init() {
        count = I(v.size());
        where.resize(v.size());
        for (I start = count / 2; start >= 0; --start) {
            I i = start, ch = 2 * i + 1;
            while (ch < count) {
                I r = ch + 1;
                if (r < count && v[ch].cost > v[r].cost)
                    ch = r;
                std::swap(v[ch], v[i]);
                i = ch;
                ch = 2 * i + 1;
            }
            while (i > start && v[i].cost < v[(i - 1) / 2].cost) {
                std::swap(v[i], v[(i - 1) / 2]);
                i = (i - 1) / 2;
            }
        }
        for (I i = 0; i < count; ++i)
            where[v[i].id] = i;
    }
    S pop() {
        require(count > 0, "empty SWAB heap");
        S q = v[0];
        --count;
        where[q.id] = -1;
        if (count) {
            v[0] = v[count];
            where[v[0].id] = 0;
            down(0);
        }
        return q;
    }
    S at(I id) {
        require(id >= 0 && id < I(where.size()) && where[id] >= 0, "SWAB neighbor");
        return v[where[id]];
    }
    void update(S q) {
        I i = where[q.id];
        v[i] = q;
        down(up(i));
    }
};
std::vector<std::pair<I, I>> bottom(const Values &y, I begin, I end, double limit, bool aux) {
    require(end > begin && end <= I(y.size()), "SWAB buffer domain");
    H h;
    I id = 0;
    for (I i = begin; i < end; i += 2) {
        I last = i + 1;
        if (last >= I(y.size()))
            last = I(y.size()) - 1;
        h.v.push_back({inf, id, i, last, id - 1, -1});
        if (id) {
            h.v[id - 1].right = id;
            h.v[id - 1].cost = fit_error(y, h.v[id - 1].first, last, false);
        }
        ++id;
    }
    h.init();
    while (h.count > 0 && h.v[0].cost < limit) {
        auto q = h.pop();
        S left = q;
        if (q.left >= 0)
            left = h.at(q.left);
        else
            left.id = -1;
        if (q.right < 0)
            break;
        S next = h.at(q.right);
        next.first = q.first;
        next.left = left.id;
        left.right = next.id;
        if (next.left >= 0) {
            left.cost = fit_error(y, left.first, next.last, false);
            h.update(left);
        }
        next.cost = next.right >= 0 ? fit_error(y, next.first, h.at(next.right).last, false) : inf;
        h.update(next);
    }
    std::vector<std::pair<I, I>> segments;
    for (I i = 0; i < h.count; ++i)
        segments.emplace_back(h.v[i].first, h.v[i].last);
    if (aux)
        std::sort(segments.begin(), segments.end());
    return segments;
}
std::vector<std::pair<I, I>> python_bottom(const Values &y, double eb) {
    struct PySeg {
        I first, last, left, right;
        bool alive;
    };
    using Entry = std::tuple<double, I, I>;
    std::vector<PySeg> v;
    std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> h;
    for (I i = 0; i < I(y.size()); i += 2) {
        I id = I(v.size());
        v.push_back({i, std::min<I>(i + 1, I(y.size()) - 1), id - 1, -1, true});
        if (id) {
            v[id - 1].right = id;
            h.emplace(fit_error(y, v[id - 1].first, v[id].last, true), id - 1, id);
        }
    }
    while (!h.empty() && std::get<0>(h.top()) < eb) {
        auto e = h.top();
        h.pop();
        auto l = std::get<1>(e), r = std::get<2>(e);
        if (!v[l].alive || !v[r].alive || v[l].right != r || v[r].left != l)
            continue;
        v[l].last = v[r].last;
        v[r].alive = false;
        v[l].right = v[r].right;
        if (v[r].right >= 0)
            v[v[r].right].left = l;
        I q = v[l].right;
        if (q >= 0)
            h.emplace(fit_error(y, v[l].first, v[q].last, true), l, q);
    }
    std::vector<std::pair<I, I>> out;
    for (auto q : v)
        if (q.alive)
            out.emplace_back(q.first, q.last);
    return out;
}
} // namespace
Stages swab_stages(const Values &y, const Config &c) {
    Stages s;
    s.working = y;
    s.mask.assign(y.size(), 0);
    I n = I(y.size());
    if (!n)
        return s;
    require(c.error_bound >= 0 && std::isfinite(c.error_bound), "SWAB error");
    require(static_cast<long double>(n) * n <= 1e8L, "SWAB work limit");
    auto mark = [&](std::pair<I, I> q) {
        require(q.first >= 0 && q.second < n, "SWAB retained point");
        s.mask[q.first] = s.mask[q.second] = 1;
    };
    if (c.python_bottom_up) {
        for (auto q : python_bottom(y, c.error_bound))
            mark(q);
    } else if (c.bottom_up) {
        for (auto q : bottom(y, 0, n, c.error_bound, false))
            mark(q);
    } else {
        require(c.window_fraction > 0 && c.window_fraction <= 1 && std::isfinite(c.window_fraction),
                "SWAB window");
        I window = I(double(n) * c.window_fraction), lower = window / 2, upper = 2 * window,
          end = window, i = 0;
        require(window >= 2, "SWAB buffer too small");
        while (i < n) {
            auto seg = bottom(y, i, end, c.error_bound, true);
            require(!seg.empty(), "empty SWAB result");
            auto first = seg[0];
            mark(first);
            I length = first.second - first.first + 1;
            if (end < n - 1) {
                I next = end + 1;
                double cost = 0;
                while (next < n - 1 && cost < c.error_bound) {
                    cost = fit_error(y, end, next, false);
                    ++next;
                }
                end = next;
            } else {
                for (std::size_t j = 2; j < seg.size(); ++j)
                    mark(seg[j]);
                break;
            }
            i += length;
            window = end - i;
            if (window <= lower)
                end = std::min(end + lower - 1, n);
            if (window - i >= upper)
                end -= (window - upper - 1);
            require(end > i, "nonprogressing SWAB buffer");
        }
        s.mask[n - 1] = 1;
    }
    return s;
}
} // namespace cameo_family
