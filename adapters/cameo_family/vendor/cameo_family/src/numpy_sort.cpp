// SPDX-License-Identifier: MIT AND BSD-3-Clause
// Reused standalone NumPy1.24.3 indirect-sort translation from ABBA-family.
#include "internal.hpp"
namespace cameo_family {
std::vector<std::size_t> numpy_argsort(const Values &v) {
    std::vector<std::size_t> a(v.size());
    std::iota(a.begin(), a.end(), 0);
    if (a.size() < 2)
        return a;
    using I = std::ptrdiff_t;
    struct Range {
        I l, r;
        int depth;
    };
    std::vector<Range> stack;
    I l = 0, r = I(a.size()) - 1;
    int depth = 0;
    for (auto n = a.size(); n > 1; n >>= 1)
        depth += 2;
    for (;;) {
        if (depth < 0) {
            // NumPy aheapsort, using an index accessor instead of its out-of-bounds
            // one-before-array pointer. Equal keys follow the reference's decisions.
            auto at = [&](I i) -> std::size_t & { return a[std::size_t(l + i - 1)]; };
            I n = r - l + 1;
            for (I root = n / 2; root > 0; --root) {
                auto tmp = at(root);
                I i = root, j = root * 2;
                for (; j <= n;) {
                    if (j < n && v[at(j)] < v[at(j + 1)])
                        ++j;
                    if (v[tmp] < v[at(j)]) {
                        at(i) = at(j);
                        i = j;
                        j *= 2;
                    } else
                        break;
                }
                at(i) = tmp;
            }
            for (; n > 1;) {
                auto tmp = at(n);
                at(n) = at(1);
                --n;
                I i = 1, j = 2;
                for (; j <= n;) {
                    if (j < n && v[at(j)] < v[at(j + 1)])
                        ++j;
                    if (v[tmp] < v[at(j)]) {
                        at(i) = at(j);
                        i = j;
                        j *= 2;
                    } else
                        break;
                }
                at(i) = tmp;
            }
        } else {
            while (r - l > 15) {
                I m = l + ((r - l) >> 1);
                if (v[a[m]] < v[a[l]])
                    std::swap(a[m], a[l]);
                if (v[a[r]] < v[a[m]])
                    std::swap(a[r], a[m]);
                if (v[a[m]] < v[a[l]])
                    std::swap(a[m], a[l]);
                double pivot = v[a[m]];
                I i = l, j = r - 1;
                std::swap(a[m], a[j]);
                for (;;) {
                    do {
                        ++i;
                    } while (v[a[i]] < pivot);
                    do {
                        --j;
                    } while (pivot < v[a[j]]);
                    if (i >= j)
                        break;
                    std::swap(a[i], a[j]);
                }
                std::swap(a[i], a[r - 1]);
                --depth;
                if (i - l < r - i) {
                    stack.push_back({i + 1, r, depth});
                    r = i - 1;
                } else {
                    stack.push_back({l, i - 1, depth});
                    l = i + 1;
                }
            }
            for (I i = l + 1; i <= r; ++i) {
                auto z = a[i];
                I j = i;
                while (j > l && v[z] < v[a[j - 1]]) {
                    a[j] = a[j - 1];
                    --j;
                }
                a[j] = z;
            }
        }
        if (stack.empty())
            break;
        auto z = stack.back();
        stack.pop_back();
        l = z.l;
        r = z.r;
        depth = z.depth;
    }
    return a;
}
} // namespace cameo_family
