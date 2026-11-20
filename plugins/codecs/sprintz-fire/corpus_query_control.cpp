// Real-corpus direct Sprintz control. Each independent SFB1 frame is one (column, row span).
#include "native_profile.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace {
namespace fs = std::filesystem;
using namespace tsbench::sprintz_fire;
using Clock = std::chrono::steady_clock;
constexpr size_t header = 32, value_bytes = 8, rows_per_unit = max_bytes / value_bytes;

void check(bool b, const char* reason) { if (!b) throw std::runtime_error(reason); }
size_t number(std::string_view arg) {
    size_t n = 0;
    const auto result = std::from_chars(arg.begin(), arg.end(), n);
    check(result.ec == std::errc{} && result.ptr == arg.end() && n > 0 && n <= 1000000, "invalid geometry");
    return n;
}
fs::path column(std::string_view path, size_t i) {
    std::ostringstream name;
    name << "column-" << std::setfill('0') << std::setw(4) << i << ".bin";
    return fs::path(path) / name.str();
}
void read(std::istream& in, uint8_t* buf, size_t n) {
    check(bool(in.read(reinterpret_cast<char*>(buf), n)), "truncated input");
}
void write(std::ostream& out, const sf::Bytes& b) {
    check(bool(out.write(reinterpret_cast<const char*>(b.data()), b.size())), "write failed");
}
void end(std::istream& in) { check(in.peek() == std::char_traits<char>::eof() && in.eof() && !in.bad(), "trailing input"); }
void close(std::ofstream& out) { out.close(); check(out.good(), "close output failed"); }
uint32_t u32(const uint8_t* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
uint64_t ns(Clock::time_point t) { return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - t).count(); }
template<typename T> void vector_json(const std::vector<T>& v) {
    std::cout << '[';
    for (size_t i = 0; i < v.size(); ++i) std::cout << (i ? "," : "") << v[i];
    std::cout << ']';
}
void emit_query(const sf::QueryResult& q) {
    std::cout << "{\"backend\":\"" << (q.backend == sf::QueryBackend::UpstreamSimd ? "upstream_simd" : "scalar")
              << "\",\"count\":";
    vector_json(q.count); std::cout << ",\"sum\":"; vector_json(q.sum);
    std::cout << ",\"max\":"; vector_json(q.max); std::cout << '}';
}

// A group is only a file extent. The codec, column traversal and native unit
// geometry stay identical to the single-file protocol.
std::vector<size_t> group_ends(std::string_view text, size_t cols) {
    std::vector<size_t> ends;
    size_t previous = 0;
    while (!text.empty()) {
        const auto comma = text.find(',');
        const auto n = number(text.substr(0, comma));
        check(n > previous && n <= cols && ends.size() < 10000, "invalid archive group boundary");
        ends.push_back(n);
        previous = n;
        if (comma == std::string_view::npos) break;
        text.remove_prefix(comma + 1);
        check(!text.empty(), "trailing archive group separator");
    }
    check(previous == cols, "archive groups do not cover all columns");
    return ends;
}
fs::path archive_path(std::string_view base, bool grouped, size_t ordinal) {
    if (!grouped) return fs::path(base);
    std::ostringstream path;
    path << "archive-" << std::setfill('0') << std::setw(4) << ordinal << ".sfb1";
    return fs::path(base) / path.str();
}
void run(std::string_view op, std::string_view input, size_t cols, size_t rows, std::string_view output,
         const std::vector<size_t>& ends, bool grouped) {
    sf::Codec codec(profile, max_bytes);
    std::ifstream archive_in;
    std::ofstream archive_out;
    size_t group = 0;
    const auto close_archive = [&] {
        if (op == "encode") close(archive_out);
        else { end(archive_in); archive_in.close(); }
    };
    std::cout << "{\"backend\":\"" << sf::backend() << "\",\"workspace_bytes\":" << codec.workspace_capacity()
              << ",\"units\":[";
    for (size_t c = 0; c < cols; ++c) {
        if (!c || c == ends[group]) {
            if (c) { close_archive(); ++group; }
            if (op == "encode") archive_out.open(archive_path(output, grouped, group), std::ios::binary | std::ios::trunc);
            else archive_in.open(archive_path(input, grouped, group), std::ios::binary);
            check(op == "encode" ? archive_out.good() : archive_in.good(), "open archive failed");
        }
        std::ifstream orig;
        std::ofstream restored;
        if (op == "encode") { orig.open(column(input, c), std::ios::binary); check(orig.good(), "open source column failed"); }
        if (op == "decode") {
            restored.open(column(output, c), std::ios::binary | std::ios::trunc);
            check(restored.good(), "open recovered column failed");
        }
        for (size_t start = 0; start < rows; start += rows_per_unit) {
            const size_t n = std::min(rows - start, rows_per_unit) * value_bytes;
            if (c || start) std::cout << ',';
            std::cout << "{\"column\":" << c << ",\"row_start\":" << start << ",\"raw_bytes\":" << n;
            if (op == "encode") {
                sf::Bytes raw(n);
                read(orig, raw.data(), n);
                const auto t = Clock::now();
                const auto payload = codec.encode(raw.data(), n);
                const auto elapsed = ns(t);
                const auto frame = sf::frame(profile, raw.data(), n, payload);
                write(archive_out, frame);
                std::cout << ",\"encode_wall_ns\":" << elapsed << ",\"frame_bytes\":" << frame.size();
            } else {
                sf::Bytes frame(header);
                read(archive_in, frame.data(), header);
                const size_t z = u32(frame.data()+16);
                check(!std::memcmp(frame.data(), "SFB1", 4) && u32(frame.data()+12) == n && z >= 8 && z <= 4 * max_bytes,
                      "invalid SFB1 geometry");
                frame.resize(header + z);
                read(archive_in, frame.data() + header, z);
                size_t raw_bytes = 0;
                uint32_t crc = 0;
                const auto payload = sf::unframe(profile, frame.data(), frame.size(), raw_bytes, crc, max_bytes);
                std::cout << ",\"frame_bytes\":" << frame.size();
                if (op == "query") {
                    const auto t0 = Clock::now();
                    const auto a = codec.query(payload.data(), payload.size(), raw_bytes);
                    const auto auto_ns = ns(t0);
                    const auto t1 = Clock::now();
                    const auto s = codec.query(payload.data(), payload.size(), raw_bytes, sf::QueryMode::Scalar);
                    const auto scalar_ns = ns(t1);
                    std::cout << ",\"auto_wall_ns\":" << auto_ns << ",\"scalar_wall_ns\":" << scalar_ns << ",\"auto\":";
                    emit_query(a); std::cout << ",\"scalar\":"; emit_query(s);
                } else {
                    const auto t = Clock::now();
                    const auto decoded = codec.decode(payload.data(), payload.size(), raw_bytes);
                    const auto elapsed = ns(t);
                    check(decoded.size() == n && sf::crc32(decoded.data(), decoded.size()) == crc, "restored CRC or size differs");
                    write(restored, decoded);
                    std::cout << ",\"decode_wall_ns\":" << elapsed;
                }
            }
            std::cout << '}';
        }
        if (op == "encode") end(orig);
        if (op == "decode") close(restored);
    }
    close_archive();
    std::cout << "]}\n";
}
}

int main(int argc, char** argv) {
    if (!supported_host()) { std::cerr << "Sprintz requires AVX2/BMI/BMI2/LZCNT/POPCNT\n"; return 77; }
    try {
        check(argc == 6 || argc == 7, "expected encode|query|decode INPUT COLUMNS ROWS OUTPUT [GROUP_ENDS]");
        std::string_view op = argv[1];
        check(op == "encode" || op == "decode" || (op == "query" && std::string_view(argv[5]) == "-"), "unknown operation");
        const size_t cols = number(argv[3]);
        const auto ends = argc == 7 ? group_ends(argv[6], cols) : std::vector<size_t>{cols};
        run(op, argv[2], cols, number(argv[4]), argv[5], ends, argc == 7);
        return std::cout.good() ? 0 : 1;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
