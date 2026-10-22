// SPDX-License-Identifier: Apache-2.0
#include "cameo_family.hpp"
#include "json.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
using namespace cameo_family;
using J = nlohmann::json;
Config config(const J &q) {
    Config c;
    c.algorithm = algorithm(q.at("algorithm").get<std::string>());
    auto j = q.value("config", J::object());
    c.error_bound = j.value("error_bound", .01);
    c.fraction = j.value("fraction", .5);
    c.window_fraction = j.value("window_fraction", .5);
    c.nlags = j.value("nlags", 4u);
    c.hops = j.value("hops", 2u);
    c.kappa = j.value("kappa", 1u);
    c.threads = j.value("threads", 1u);
    c.parallel_lookahead = j.value("backend", std::string("lpc")) == "fgc";
    c.ratio_stopping = j.value("criterion", std::string("error")) == "cr";
    c.bottom_up = j.value("mode", std::string("sliding")) == "bottom-up";
    c.python_bottom_up = j.value("mode", std::string("sliding")) == "python-bottom-up";
    c.canonical_dct = j.value("transform", std::string("fft")) == "scalar";
    return c;
}
J request(const J &q) {
    std::string op = q.value("operation", std::string("analyze"));
    if (op == "numeric-info")
        return J{{"backend",numeric_backend()},{"long_double_digits",std::numeric_limits<long double>::digits}};
    if (op == "decode") {
        auto b = q.at("frame").get<Bytes>();
        J out = J::object();
        out["reconstructed"] = decode(b.data(), b.size());
        return out;
    }
    if (op == "raw-decode") {
        J out = J::object();
        out["reconstructed"] = decompress_raw(q.at("source_bytes").get<Bytes>());
        return out;
    }
    if (op == "argsort") {
        J out = J::object();
        out["indices"] = numpy_argsort(q.at("values").get<Values>());
        return out;
    }
    auto c = config(q);
    auto y = q.at("values").get<Values>();
    J out = J::object();
    if (op == "encode") {
        auto b = encode(y, c);
        out["frame"] = b;
        out["final_bits"] = b.size() * 8;
        out["reconstructed"] = decode(b.data(), b.size());
        return out;
    }
    auto s = analyze(y, c);
    out["reconstructed"] = s.reconstructed;
    if (!s.mask.empty()) {
        out["mask"] = s.mask;
        out["working"] = s.working;
        J points = J::array();
        for (std::size_t i = 0; i < s.points_x.size(); ++i) {
            J row = J::array();
            row.push_back(s.points_x[i]);
            row.push_back(s.points_y[i]);
            points.push_back(std::move(row));
        }
        out["points"] = std::move(points);
    }
    if (!s.coefficients.empty()) {
        if (s.imaginary.empty())
            out["coefficients"] = s.coefficients;
        else {
            J co = J::array();
            for (std::size_t i = 0; i < s.coefficients.size(); ++i) {
                J row = J::array();
                row.push_back(s.coefficients[i]);
                row.push_back(s.imaginary[i]);
                co.push_back(std::move(row));
            }
            out["coefficients"] = std::move(co);
        }
    }
    if (!s.source_bytes.empty())
        out["source_bytes"] = s.source_bytes;
    if (!s.initial_impacts.empty()) {
        J co = J::array();
        for (auto x : s.initial_impacts)
            co.push_back(std::isfinite(x) ? J(x) : J());
        out["initial_impacts"] = std::move(co);
    }
    if (!s.diagnostic.empty())
        out["diagnostic"] = s.diagnostic;
    return out;
}

namespace {
constexpr std::size_t json_limit = 16 * 1024 * 1024;
J parse_json(const std::string &s) {
    return J::parse(s, [](int depth, J::parse_event_t, J &) {
        if (depth > 64)
            throw std::invalid_argument("JSON depth limit");
        return true;
    });
}
std::string file_text(const char *path, std::size_t limit) {
    std::ifstream f(path, std::ios::binary);
    if (!f)
        throw std::invalid_argument("cannot open input file");
    std::string s;
    char chunk[4096];
    while (f) {
        f.read(chunk, sizeof(chunk));
        auto n = std::size_t(f.gcount());
        if (n > limit - s.size())
            throw std::invalid_argument("input file limit");
        s.append(chunk, n);
    }
    if (!f.eof())
        throw std::runtime_error("input file read failed");
    return s;
}
bool line(std::istream &in, std::string &s, bool &oversized) {
    s.clear();
    oversized = false;
    char c;
    bool read = false;
    while (in.get(c)) {
        read = true;
        if (c == '\n')
            break;
        if (s.size() < json_limit)
            s.push_back(c);
        else
            oversized = true;
    }
    return read;
}
} // namespace
int main(int argc, char **argv) {
    try {
        if (argc == 4 && std::string(argv[1]) == "decode-file") {
            auto data = file_text(argv[2], max_frame);
            auto y = decode(reinterpret_cast<const std::uint8_t *>(data.data()), data.size());
            std::ofstream o(argv[3]);
            if (!o)
                throw std::runtime_error("cannot open output file");
            o << J(y).dump() << '\n';
            if (!o)
                throw std::runtime_error("output write failed");
            return 0;
        }
        if (argc == 4 && std::string(argv[1]) == "encode-file") {
            auto q = parse_json(file_text(argv[2], json_limit));
            auto b = encode(q.at("values").get<Values>(), config(q));
            std::ofstream o(argv[3], std::ios::binary);
            if (!o)
                throw std::runtime_error("cannot open output file");
            o.write(reinterpret_cast<const char *>(b.data()), std::streamsize(b.size()));
            if (!o)
                throw std::runtime_error("output write failed");
            return 0;
        }
        if (argc != 1)
            throw std::invalid_argument("usage: cameo_cli [encode-file request.json output.cf | "
                                        "decode-file input.cf values.json]");
        std::string s;
        bool oversized;
        while (line(std::cin, s, oversized)) {
            try {
                if (oversized)
                    throw std::invalid_argument("JSON request limit");
                std::cout << request(parse_json(s)).dump() << '\n';
            } catch (const std::exception &e) {
                J err = J::object();
                err["error"] = e.what();
                std::cout << err.dump() << '\n';
            }
        }
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
    return 0;
}
