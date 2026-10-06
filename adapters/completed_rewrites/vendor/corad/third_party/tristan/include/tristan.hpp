// SPDX-License-Identifier: NOASSERTION
// Local TRISTAN rewrite; upstream CORAD attribution in README and contract.
#pragma once
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace tristan {
enum class Code { InvalidArgument, OutputTooSmall, CorruptStream, ResourceLimit,
                  NumericalFailure, Unsupported };
struct Error : std::runtime_error {
    Code code;
    Error(Code c, const std::string& message) : std::runtime_error(message), code(c) {}
};
enum class Solver : std::uint32_t { Omp, Lars, LassoLars, LassoCd, Threshold };
struct Config {
    std::uint32_t length=40, atoms=200, nonzeros=4, seed=0, requested_n_iter=150;
    double alpha=1.;
    Solver solver=Solver::Omp;
};
struct Limits {
    std::uint64_t input_bytes=256ULL<<20, output_bytes=256ULL<<20,
                  workspace_bytes=1ULL<<30;
};
struct Trace {
    std::vector<double> normalized, dictionary, coefficients, means, scales, costs;
    std::vector<std::vector<double>> learning_snapshots;
    std::uint64_t rows=0, windows=0;
    std::uint32_t channels=0;
};
struct Accounting {
    std::uint64_t header_bytes=96, normalization_bytes=0, dictionary_bytes=0,
                  count_bytes=0, index_bytes=0, coefficient_bytes=0;
    std::uint64_t physical_bytes() const;
    std::uint64_t final_bits() const;
};
struct Decoded {
    Config config;
    std::uint64_t original_rows=0, windows=0;
    std::uint32_t channels=0;
    // Channel/window/position ordered standardized reconstruction.
    std::vector<double> values, means, scales;
    Accounting accounting;
};
std::uint64_t compress_bound(std::uint64_t rows, std::uint32_t channels,
                             const Config&, const Limits& = {});
std::uint64_t workspace_bound(std::uint64_t rows, std::uint32_t channels,
                              const Config&);
std::vector<std::uint8_t> encode(const double* values, std::uint64_t rows,
                                std::uint32_t channels, const Config& = {},
                                const Limits& = {}, Trace* trace=nullptr);
std::size_t compress(const double* values, std::uint64_t rows, std::uint32_t channels,
                     const Config&, std::uint8_t* output, std::size_t capacity,
                     const Limits& = {});
Decoded decode(const std::uint8_t* frame, std::size_t size, const Limits& = {});
// Numerical stage API: row-major matrices; dictionary [atoms,length].
std::vector<double> train(const std::vector<double>& data, std::size_t samples,
                          const Config&, std::vector<double>* costs=nullptr,
                          std::vector<std::vector<double>>* snapshots=nullptr);
std::vector<double> sparse(const std::vector<double>& data, std::size_t samples,
                           const std::vector<double>& dictionary, const Config&);
std::vector<double> rng_trace(std::uint32_t seed);
std::string backend_info();
// Diagnostic-only numerical trace; no frame or production state dependency.
std::vector<double> debug_lars(const std::vector<double>& gram,
                               const std::vector<double>& covariance,
                               std::uint32_t length,
                               std::vector<std::vector<double>>& records);
} // namespace tristan
