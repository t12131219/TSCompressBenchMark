// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
namespace cameo_family {
std::string numeric_backend();
using Values = std::vector<double>;
using Bytes = std::vector<std::uint8_t>;
enum class Algorithm : std::uint32_t {
    CAMEO = 1,
    VW,
    PIP,
    TP,
    SWAB,
    SimPiece,
    PMC,
    SWING,
    DFT,
    DWT_DCT_II
};
struct Config {
    Algorithm algorithm = Algorithm::CAMEO;
    double error_bound = .01, fraction = .5, window_fraction = .5;
    std::size_t nlags = 4, hops = 2, kappa = 1, threads = 1;
    bool parallel_lookahead = false, ratio_stopping = false, bottom_up = false,
         python_bottom_up = false, canonical_dct = false;
};
struct Stages {
    std::vector<std::uint8_t> mask;
    Values working, points_x, points_y, coefficients, imaginary, reconstructed, initial_impacts;
    Bytes source_bytes;
    std::string diagnostic;
};
constexpr std::size_t max_samples = 131072, max_frame = 64 * 1024 * 1024;
// Every call owns its state. Input is copied before the source-style in-place stages.
// Exceptions indicate invalid config/representation, resource or allocation failure.
Stages analyze(const Values &, const Config &);
Bytes encode(const Values &, const Config &);
Values decode(const std::uint8_t *, std::size_t);
Bytes compress_raw(const Values &, const Config &);
Values decompress_raw(const Bytes &); // TerseTS little-endian usize64 raw interchange
std::vector<std::size_t> numpy_argsort(const Values &);
Algorithm algorithm(const std::string &);
std::string name(Algorithm);
} // namespace cameo_family
