// SPDX-License-Identifier: MIT
#include "abba_family.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <sched.h>
#include <sys/resource.h>
using namespace abba_family;
int main(int argc, char **argv) {
  if (argc != 2)
    return 2;
  try {
    std::ifstream input(argv[1]);
    Json rows;
    input >> rows;
    Json results = Json::array();
    for (auto a : {"abba", "fabba", "qabba"})
      for (std::size_t row = 0; row < rows.size(); ++row) {
        Json r{{"algorithm", a},
               {"values", rows[row]},
               {"config", Json::object()}};
        if (std::string(a) == "abba")
          r["config"]["min_k"] = 1;
        std::vector<double> enc, dec;
        std::vector<uint8_t> frame;
        Json restored;
        for (int i = -2; i < 15; ++i) {
          auto begin = std::chrono::steady_clock::now();
          frame = encode(r);
          auto mid = std::chrono::steady_clock::now();
          restored = decode(frame.data(), frame.size());
          auto end = std::chrono::steady_clock::now();
          if (i >= 0) {
            enc.push_back(std::chrono::duration<double>(mid - begin).count());
            dec.push_back(std::chrono::duration<double>(end - mid).count());
          }
        }
        std::sort(enc.begin(), enc.end());
        std::sort(dec.begin(), dec.end());
        struct rusage usage {};
        getrusage(RUSAGE_SELF, &usage);
        results.push_back(Json{
            {"algorithm", a},
            {"row", row},
            {"samples", rows[row].size()},
            {"bytes", frame.size()},
            {"encoder_median_seconds", enc[7]},
            {"decoder_median_seconds", dec[7]},
            {"encoder_p95_seconds", enc[14]},
            {"decoder_p95_seconds", dec[14]},
            {"encode_samples_per_second", double(rows[row].size()) / enc[7]},
            {"decode_samples_per_second",
             double(restored["reconstructed"].size()) / dec[7]},
            {"process_peak_rss_kib", usage.ru_maxrss},
            {"cpu", sched_getcpu()}});
      }
    std::cout << Json{{"status", "PASS"},
                      {"timing_boundary",
                       "Native encode includes fitting, allocations, "
                       "serialization and CRC; decode includes parsing, "
                       "allocations, symbol decoding and reconstruction"},
                      {"warmup", 2},
                      {"repetitions", 15},
                      {"ranking_claim", false},
                      {"results", results}}
                     .dump(2)
              << '\n';
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
