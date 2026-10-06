// SPDX-License-Identifier: NOASSERTION
#pragma once
#include "tristan.hpp"
namespace corad {
using Code=tristan::Code;using Error=tristan::Error;using Solver=tristan::Solver;
using Limits=tristan::Limits;
struct Config:tristan::Config {double threshold=.8;};
struct Selection {std::vector<double> correlations;std::vector<std::uint32_t> order;std::vector<std::int32_t> references;};
struct Trace:tristan::Trace {Selection selection;};
struct Accounting {
    std::uint64_t header_bytes=104,normalization_bytes=0,dictionary_bytes=0,
        tag_bytes=0,index_bytes=0,coefficient_bytes=0,reference_bytes=0;
    std::uint64_t physical_bytes()const;std::uint64_t final_bits()const;
};
struct Decoded {Config config;std::uint64_t original_rows=0,windows=0;std::uint32_t channels=0;
    std::vector<double> values,means,scales;Accounting accounting;};
std::uint64_t workspace_bound(std::uint64_t rows,std::uint32_t channels,const Config&);
std::uint64_t compress_bound(std::uint64_t rows,std::uint32_t channels,const Config&,const Limits& = {});
Selection correlate(const double* normalized,std::uint64_t rows,std::uint32_t channels,
                    std::uint32_t length,double threshold,const Limits& = {});
std::vector<std::uint8_t> encode(const double*,std::uint64_t rows,std::uint32_t channels,
                               const Config& = {},const Limits& = {},Trace* =nullptr);
std::size_t compress(const double*,std::uint64_t rows,std::uint32_t channels,const Config&,
                     std::uint8_t* output,std::size_t capacity,const Limits& = {});
Decoded decode(const std::uint8_t*,std::size_t,const Limits& = {});
}
