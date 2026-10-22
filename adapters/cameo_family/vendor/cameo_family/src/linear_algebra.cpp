// SPDX-License-Identifier: Apache-2.0
// The public Python wrapper uses NumPy lstsq. Call its frozen native DGELSD
// dependency directly, retaining its QR/SVD arithmetic and residual decisions.
#include "internal.hpp"
#include <cstdint>
#ifndef CF_DGELSD
#define CF_DGELSD dgelsd_64_
#endif
extern "C" void CF_DGELSD(const std::int64_t *, const std::int64_t *, const std::int64_t *,
                           double *, const std::int64_t *, double *, const std::int64_t *, double *,
                           const double *, std::int64_t *, double *, const std::int64_t *,
                           std::int64_t *, std::int64_t *);
extern "C" const char *openblas_get_config();
extern "C" const char *openblas_get_corename();
namespace cameo_family {
std::string numeric_backend() {
    return std::string(openblas_get_config()) + "; actual_core=" + openblas_get_corename();
}
double reference_lstsq_error(const Values &y, I first, I last) {
    std::int64_t m = last - first + 1, n = 2, nrhs = 1, lda = m, ldb = m, rank = 0, info = 0,
                 lwork = -1;
    if (m <= 2)
        return 0;
    Values a(std::size_t(m) * 2, 1.), b(std::size_t(m), 0), singular(2);
    for (std::int64_t i = 0; i < m; ++i) {
        a[std::size_t(i)] = double(first + i);
        b[std::size_t(i)] = y[std::size_t(first + i)];
    }
    std::int64_t iwork[64]{};
    double query = 0, rcond = std::numeric_limits<double>::epsilon() * double(m);
    CF_DGELSD(&m, &n, &nrhs, a.data(), &lda, b.data(), &ldb, singular.data(), &rcond, &rank,
               &query, &lwork, iwork, &info);
    require(info == 0 && std::isfinite(query) && query > 0 && query <= 10000000.,
            "DGELSD workspace");
    lwork = std::int64_t(query);
    Values work(std::size_t(lwork), 0);
    CF_DGELSD(&m, &n, &nrhs, a.data(), &lda, b.data(), &ldb, singular.data(), &rcond, &rank,
               work.data(), &lwork, iwork, &info);
    require(info == 0, "DGELSD convergence");
    if (rank < n)
        return 0;
    double error = 0;
    for (std::int64_t i = n; i < m; ++i)
        error += b[std::size_t(i)] * b[std::size_t(i)];
    return error;
}
} // namespace cameo_family
