#include "alp_port.h"
#include <chrono>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>
int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "info") { std::cout << alp_port_profile() << '\n'; return 0; }
        if (argc != 7) throw std::runtime_error("usage: alp_cli encode|decode f32|f64 alp|alp-rd input output repeats(1..100)");
        const std::string op = argv[1], type = argv[2], mode = argv[3];
        if ((op != "encode" && op != "decode") || (type != "f32" && type != "f64") || (mode != "alp" && mode != "alp-rd")) throw std::runtime_error("unsupported argument");
        const uint8_t d = type == "f32" ? 4 : 8, m = mode == "alp" ? 0 : 1;
        const int repeats = std::stoi(argv[6]); if (repeats < 1 || repeats > 100) throw std::runtime_error("repeats limit");
        std::ifstream f(argv[4], std::ios::binary | std::ios::ate); if (!f) throw std::runtime_error("input open");
        const auto bytes = f.tellg(); if (bytes < 0 || bytes > 600000000) throw std::runtime_error("input size limit");
        std::vector<uint8_t> in(static_cast<size_t>(bytes)); f.seekg(0); if (!in.empty() && !f.read(reinterpret_cast<char*>(in.data()), in.size())) throw std::runtime_error("input read");
        size_t bound = 0;
        if (op == "encode") {
            if (in.size() % d || alp_port_bound(in.size() / d, d, m, &bound)) throw std::runtime_error("raw size or resource limit");
        } else {
            if (in.size() < 32) throw std::runtime_error("short frame");
            uint64_t n = 0; for (int i = 0; i < 8; ++i) n |= uint64_t(in[12 + i]) << (i * 8);
            if (n > ALP_PORT_MAX_VALUES) throw std::runtime_error("count resource limit");
            bound = n * d;
        }
        std::vector<uint8_t> out(bound ? bound : 1); size_t used = 0, consumed = 0; uint64_t count = 0; uint8_t od = 0, om = 0;
        const auto start = std::chrono::steady_clock::now();
        for (int i = 0; i < repeats; ++i) {
            const int s = op == "encode" ? alp_port_encode(in.data(), in.size() / d, d, m, out.data(), out.size(), &used) : alp_port_decode(in.data(), in.size(), out.data(), bound, &used, &consumed, &count, &od, &om);
            if (s) throw std::runtime_error(alp_port_status_string(s));
            if (op == "decode" && (od != d || om != m || consumed != in.size())) throw std::runtime_error("decode descriptor mismatch");
        }
        const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - start).count();
        std::ofstream g(argv[5], std::ios::binary); if (!g || !g.write(reinterpret_cast<const char*>(out.data()), used)) throw std::runtime_error("output write");
        std::cout << "{\"profile\":\"" << alp_port_profile() << "\",\"operation\":\"" << op << "\",\"input_bytes\":" << in.size() << ",\"output_bytes\":" << used << ",\"repeats\":" << repeats << ",\"total_ns\":" << ns << "}\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
