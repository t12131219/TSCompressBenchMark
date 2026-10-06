// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0

#include "prometheus_xor2_chunk.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <vector>

namespace codec = prometheus_xor2;
using Clock = std::chrono::steady_clock;

namespace {

constexpr std::size_t kSamples = 8192;
constexpr std::size_t kWarmups = 3;
constexpr std::size_t kRepetitions = 10;

struct Observation {
    std::uint64_t elapsed_ns;
    std::uint64_t iterations;
    double throughput;
};

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

std::uint64_t next(std::uint64_t* state) {
    std::uint64_t value = *state;
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    *state = value;
    return value;
}

std::vector<codec::Sample> fixture() {
    std::vector<codec::Sample> result;
    result.reserve(kSamples);
    std::uint64_t state = UINT64_C(0x20260928a17f39d1);
    std::int64_t timestamp = 1700000000000;
    std::uint64_t value = UINT64_C(0x3ff0000000000000);
    for (std::size_t index = 0; index < kSamples; ++index) {
        timestamp += 1000 + static_cast<std::int64_t>(next(&state) % 7) - 3;
        if (index % 5 == 0) {
            value ^= next(&state) & UINT64_C(0xfffff);
        }
        const std::int64_t st = index < 64 ? 0 : timestamp - static_cast<std::int64_t>(index % 29);
        result.push_back({st, timestamp, index % 997 == 0 ? codec::kStaleNaN : value});
    }
    return result;
}

template <class Function>
Observation measure(double seconds, Function function) {
    const auto start = Clock::now();
    std::uint64_t iterations = 0;
    do {
        function();
        ++iterations;
    } while (std::chrono::duration<double>(Clock::now() - start).count() < seconds);
    const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start);
    const double mib = static_cast<double>(iterations * kSamples * sizeof(codec::Sample)) /
        (1024.0 * 1024.0);
    return {static_cast<std::uint64_t>(elapsed.count()), iterations,
            mib / (static_cast<double>(elapsed.count()) / 1e9)};
}

double percentile(std::vector<double> values, double fraction) {
    std::sort(values.begin(), values.end());
    const double position = fraction * static_cast<double>(values.size() - 1);
    const std::size_t lower = static_cast<std::size_t>(position);
    const std::size_t upper = std::min(lower + 1, values.size() - 1);
    return values[lower] + (values[upper] - values[lower]) *
        (position - static_cast<double>(lower));
}

void observations(std::ofstream& out, const std::vector<Observation>& values) {
    out << '[';
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index) out << ',';
        out << "{\"elapsed_ns\":" << values[index].elapsed_ns
            << ",\"iterations\":" << values[index].iterations
            << ",\"throughput_mib_s\":" << values[index].throughput << '}';
    }
    out << ']';
}

void summary(std::ofstream& out, const std::vector<Observation>& observations_list) {
    std::vector<double> values;
    for (const auto& item : observations_list) values.push_back(item.throughput);
    const double mean = std::accumulate(values.begin(), values.end(), 0.0) /
        static_cast<double>(values.size());
    double squares = 0;
    for (double value : values) squares += (value - mean) * (value - mean);
    const double sd = std::sqrt(squares / static_cast<double>(values.size() - 1));
    out << "{\"n\":10,\"median_mib_s\":" << percentile(values, .5)
        << ",\"p25_mib_s\":" << percentile(values, .25)
        << ",\"p75_mib_s\":" << percentile(values, .75)
        << ",\"mean_mib_s\":" << mean << ",\"sd_mib_s\":" << sd
        << ",\"cv\":" << sd / mean << '}';
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: benchmark OUTPUT_JSON\n";
        return 2;
    }
    const auto samples = fixture();
    std::size_t bound = 0;
    require(codec::max_compressed_size(samples.size(), &bound).ok(), "bound failed");
    std::vector<std::uint8_t> encoded(bound);
    std::size_t encoded_size = 0;
    require(codec::encode(samples.data(), samples.size(), encoded.data(), encoded.size(), &encoded_size).ok(),
            "fixture encode failed");
    std::vector<codec::Sample> decoded(samples.size());
    const auto encode = [&] {
        std::size_t written = 0;
        require(codec::encode(samples.data(), samples.size(), encoded.data(), encoded.size(), &written).ok() &&
                    written == encoded_size, "timed encode failed");
    };
    const auto decode = [&] {
        std::size_t written = 0;
        require(codec::decode(encoded.data(), encoded_size, decoded.data(), decoded.size(), &written).ok() &&
                    written == samples.size(), "timed decode failed");
    };
    for (std::size_t index = 0; index < kWarmups; ++index) {
        static_cast<void>(measure(.5, encode));
        static_cast<void>(measure(.5, decode));
    }
    std::vector<Observation> enc;
    std::vector<Observation> dec;
    for (std::size_t index = 0; index < kRepetitions; ++index) enc.push_back(measure(1.0, encode));
    for (std::size_t index = 0; index < kRepetitions; ++index) dec.push_back(measure(1.0, decode));
    decode();
    require(std::equal(samples.begin(), samples.end(), decoded.begin(), [](const auto& a, const auto& b) {
        return a.start_timestamp == b.start_timestamp && a.timestamp == b.timestamp &&
               a.value_bits == b.value_bits;
    }), "post-measurement correctness failed");

    std::ofstream out(argv[1], std::ios::binary | std::ios::trunc);
    require(out.good(), "result open failed");
    out << std::fixed << std::setprecision(6)
        << "{\n  \"schema_version\":\"tscb.rewrite-performance.v1\",\n"
        << "  \"algorithm_id\":\"prometheus-xor2-chunk\",\n"
        << "  \"implementation_id\":\"prometheus-xor2-chunk-canonical-cpp\",\n"
        << "  \"measurement_mode\":\"FORMAL\",\n  \"timing_scope\":\"CORE\",\n"
        << "  \"dataset_id\":\"deterministic-synthetic-8192-triples-v1\",\n"
        << "  \"shape\":[8192,3],\n  \"canonical_raw_bits\":" << kSamples * 192 << ",\n"
        << "  \"serialized_bits\":" << encoded_size * 8 << ",\n"
        << "  \"external_side_information_bits\":0,\n  \"final_bits\":" << encoded_size * 8 << ",\n"
        << "  \"warmup\":{\"count\":3,\"minimum_seconds_each\":0.5},\n"
        << "  \"minimum_repetition_seconds\":1.0,\n  \"encode_observations\":";
    observations(out, enc);
    out << ",\n  \"decode_observations\":";
    observations(out, dec);
    out << ",\n  \"encode_summary\":";
    summary(out, enc);
    out << ",\n  \"decode_summary\":";
    summary(out, dec);
    out << ",\n  \"threads_used\":1,\n  \"isa_used\":\"portable-scalar\",\n"
        << "  \"correctness\":true\n}\n";
    std::cout << "performance validation complete\n";
    return 0;
}
