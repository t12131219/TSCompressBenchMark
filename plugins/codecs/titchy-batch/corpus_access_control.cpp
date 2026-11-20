// Bounded driver for the two frozen real-corpus TCHY access routes.
#include "titchy.h"
#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <sys/resource.h>
#include <vector>

namespace {
constexpr size_t rows_cap = 65536;
constexpr titchy_config config{64, 4, 1000, 0, .25, UINT64_MAX};
using Bytes = std::vector<uint8_t>;
using Clock = std::chrono::steady_clock;
using Reader = std::unique_ptr<titchy_reader, decltype(&titchy_reader_free)>;

void need(bool ok, const char* msg) { if (!ok) throw std::runtime_error(msg); }
size_t number(std::string_view str) {
    size_t n = 0;
    const auto p = std::from_chars(str.data(), str.data()+str.size(), n);
    need(p.ec == std::errc{} && p.ptr == str.data()+str.size() && n && n <= rows_cap, "invalid rows");
    return n;
}
Bytes read(const char* path, size_t maximum) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    const auto n = f.tellg();
    need(n > 0 && static_cast<uint64_t>(n) <= maximum, "input extent outside limit");
    Bytes b(static_cast<size_t>(n));
    f.seekg(0);
    need(bool(f.read(reinterpret_cast<char*>(b.data()), n)), "read input failed");
    return b;
}
void write(const char *path, const Bytes& b) {
    std::ofstream f(path, std::ios::binary | std::ios::trunc);
    need(bool(f.write(reinterpret_cast<const char*>(b.data()), b.size())), "write output failed");
    f.close();
    need(bool(f), "close output failed");
}

template<class F> uint64_t measure(F fn, const char* error) {
    const auto t = Clock::now();
    const int rc = fn();
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-t).count();
    need(rc == TITCHY_OK, error);
    return static_cast<uint64_t>(ns);
}
void rss() {
    struct rusage u{};
    std::cout << ",\"process_peak_rss_bytes\":";
    if (getrusage(RUSAGE_SELF, &u) == 0) std::cout << static_cast<uint64_t>(u.ru_maxrss) * 1024;
    else std::cout << "null";
}

template<class T> void array(const T& data) {
    std::cout << '[';
    bool first = true;
    for (auto x : data) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << +x;
    }
    std::cout << ']';
}
void encode(const char* input, const char* artifact) {
    const auto raw = read(input, rows_cap*8);
    need(raw.size()%8 == 0, "misaligned u64 source");
    std::vector<uint64_t> values(raw.size()/8);
    for (size_t i = 0; i < values.size(); ++i)
        for (unsigned b = 0; b < 8; ++b) values[i] |= uint64_t(raw[8*i+b]) << (8*b);
    const size_t cap = titchy_bound(values.size(), &config);
    need(cap && cap <= titchy_bound(rows_cap, &config), "invalid TCHY bound");
    Bytes wire(cap);
    size_t written = 0;
    const auto ns = measure([&]{return titchy_c_encode(values.data(), values.size(), &config,
                                                      wire.data(), wire.size(), &written);}, "native encode");
    need(written >= 38 && written <= cap, "native TCHY length");
    wire.resize(written);
    write(artifact, wire);
    std::cout << "{\"entry\":\"titchy_c_encode\",\"rows\":" << values.size() << ",\"bytes\":" << written
              << ",\"wall_ns\":" << ns;
    rss(); std::cout << "}\n";
}

// Logical requests to immutable memory. This counter is not FILE or physical I/O.
struct ReadAt {
    const Bytes& wire;
    size_t calls = 0, bytes = 0;
    static int call(void* ptr, uint64_t offset, void* dst, size_t n) noexcept {
        auto& self = *static_cast<ReadAt*>(ptr);
        if (offset > self.wire.size() || n > self.wire.size()-offset) return 1;
        ++self.calls;
        self.bytes += n;
        if (n) std::memcpy(dst, self.wire.data()+offset, n);
        return 0;
    }
    void emit(uint64_t ns) {
        std::cout << "{\"wall_ns\":" << ns << ",\"calls\":" << calls << ",\"requested_bytes\":" << bytes << '}';
        calls = bytes = 0;
    }
};
struct Request {
    std::array<size_t, 3> points, bits;
    size_t start, count;
};
Request for_rows(size_t n) {
    const size_t mid = n/2, start = mid > 4 ? mid-4 : 0;
    return {{0, mid, n-1}, {0, mid*64+31, n*64-1}, start, std::min(n-start, size_t{9})};
}
void queries(titchy_reader* r, const Request& q, ReadAt* log) {
    std::array<uint64_t, 3> values{};
    std::array<uint8_t, 3> bits{};
    std::vector<uint64_t> range(q.count);
    auto emit = [&](uint64_t ns) {
        if (log) log->emit(ns);
        else std::cout << "{\"wall_ns\":" << ns << ",\"requested_bytes\":null}";
    };
    std::cout << "{\"point_observations\":[";
    for (size_t i = 0; i < q.points.size(); ++i) {
        if (i) std::cout << ',';
        emit(measure([&]{return titchy_reader_sample(r, q.points[i], &values[i]);}, "native point"));
    }
    std::cout << "],\"bit_observations\":[";
    for (size_t i = 0; i < q.bits.size(); ++i) {
        if (i) std::cout << ',';
        emit(measure([&]{return titchy_reader_bit(r, q.bits[i], &bits[i]);}, "native bit"));
    }
    std::cout << "],\"range_observation\":";
    emit(measure([&]{return titchy_reader_range(r, q.start, q.count, range.data(), range.size());}, "native indexed range"));
    std::cout << ",\"points\":"; array(values);
    std::cout << ",\"bits\":"; array(bits);
    std::cout << ",\"range\":"; array(range);
    std::cout << '}';
}
void restore(const Bytes& wire, size_t n, const char* output) {
    std::vector<uint64_t> values(n);
    size_t got = 0;
    const auto ns = measure([&]{return titchy_c_decode(wire.data(), wire.size(), values.data(), n, n, &got);},
                            "full TCHY recovery");
    need(got == n, "recovered count differs");
    Bytes raw(n*8);
    for (size_t i = 0; i < n; ++i)
        for (unsigned b = 0; b < 8; ++b) raw[i*8+b] = static_cast<uint8_t>(values[i] >> (8*b));
    write(output, raw);
    std::cout << ",\"restore\":{\"entry\":\"titchy_c_decode\",\"wall_ns\":" << ns << ",\"rows\":" << got << '}';
}
void access(std::string_view mode, const char* artifact, size_t n, const char* output) {
    const auto bound = titchy_bound(n, &config);
    const auto wire = read(artifact, bound);
    const auto q = for_rows(n);
    std::cout << "{\"range_start\":" << q.start << ",\"range_count\":" << q.count;
    if (mode == "batch-range") {
        std::vector<uint64_t> result(q.count);
        const auto ns = measure([&]{return titchy_c_range(wire.data(), wire.size(), q.start, q.count,
                                                         result.data(), result.size(), n);}, "native stateless range");
        std::cout << ",\"entry\":\"titchy_c_range\",\"whole_container_validated\":true,\"wall_ns\":" << ns
                  << ",\"requested_bytes\":null,\"range\":";
        array(result);
    } else if (mode == "loaded-file-access") {
        titchy_reader* p = nullptr;
        ReadAt log{wire};
        const auto mem_ns = measure([&]{return titchy_reader_open(ReadAt::call, &log, wire.size(), n, &p);},
                                    "native callback open");
        Reader reader(p, titchy_reader_free);
        need(reader && titchy_reader_count(reader.get()) == n, "callback row count differs");
        std::cout << ",\"point_indices\":"; array(q.points);
        std::cout << ",\"bit_indices\":"; array(q.bits);
        std::cout << ",\"callback_open\":"; log.emit(mem_ns);
        std::cout << ",\"callback_queries\":"; queries(reader.get(), q, &log);
        reader.reset();
        p = nullptr;
        const auto file_ns = measure([&]{return titchy_reader_open_file(artifact, n, &p);}, "native file open");
        reader.reset(p);
        need(reader && titchy_reader_count(reader.get()) == n, "file row count differs");
        std::cout << ",\"file_open\":{\"wall_ns\":" << file_ns << ",\"requested_bytes\":null},\"file_queries\":";
        queries(reader.get(), q, nullptr);
    } else {
        need(false, "unknown access mode");
    }
    restore(wire, n, output);
    rss(); std::cout << "}\n";
}
}

int main(int argc, char** argv) {
    try {
        if (argc == 4 && std::string_view(argv[1]) == "encode") encode(argv[2], argv[3]);
        else if (argc == 5) access(argv[1], argv[2], number(argv[3]), argv[4]);
        else need(false, "expected encode INPUT FRAME or ACCESS FRAME ROWS OUTPUT");
        return std::cout.good() ? 0 : 2;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
