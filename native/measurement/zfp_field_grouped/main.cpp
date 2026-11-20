// File grouping only: each whole f64 column is still a fresh r40 ZFP field.
#include "zfp_native.h"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <vector>

#ifdef TSBENCH_ZFP_GROUPED_OBSERVE
void zfp_clear_work_marks();
void zfp_print_work_marks();
#endif

namespace {
namespace fs = std::filesystem;
using clock_type = std::chrono::steady_clock;
using Field = std::unique_ptr<zn_context, decltype(&zn_destroy)>;
constexpr size_t max_field_rows = (1u << 20) / sizeof(double);
constexpr size_t max_field_frame = 4u << 20;
constexpr unsigned chunk_blocks = 64;
constexpr char magic[] = {'Z', 'F', 'G', '1'};

void check(bool ok, const char* reason) { if (!ok) throw std::runtime_error(reason); }
void native(zn_status rc) { if (rc != ZN_OK) throw std::runtime_error(zn_error(rc)); }

size_t count(std::string_view text, size_t max) {
    size_t n = 0;
    auto end = text.data() + text.size();
    auto r = std::from_chars(text.data(), end, n);
    check(r.ec == std::errc{} && r.ptr == end && n && n <= max, "invalid field geometry");
    return n;
}

void read(std::istream& f, void* p, size_t n) {
    check(bool(f.read(static_cast<char*>(p), static_cast<std::streamsize>(n))), "truncated field input");
}
void write(std::ostream& f, const void* p, size_t n) {
    check(bool(f.write(static_cast<const char*>(p), static_cast<std::streamsize>(n))), "failed writing field output");
}
uint32_t word(std::istream& f) {
    unsigned char b[4]; read(f, b, sizeof b);
    uint32_t n = 0;
    for (int i = 0; i < 4; ++i) n |= uint32_t(b[i]) << (8*i);
    return n;
}
void word(std::ostream& f, uint32_t n) {
    unsigned char b[4];
    for (auto& c : b) { c = static_cast<unsigned char>(n); n >>= 8; }
    write(f, b, sizeof b);
}

class Product {
    fs::path final_, partial_;
public:
    std::ofstream file;
    explicit Product(const char* path) : final_(path), partial_(final_.string() + ".partial") {
        check(!fs::exists(final_) && !fs::exists(partial_), "output already exists");
        file.open(partial_, std::ios::binary);
        check(bool(file), "cannot create field output");
    }
    void publish() {
        file.close();
        check(bool(file), "cannot close field output");
        fs::rename(partial_, final_);
    }
    ~Product() {
        if (file.is_open()) file.close();
        std::error_code ignored;
        fs::remove(partial_, ignored);
    }
};

#ifndef TSBENCH_ZFP_GROUPED_OBSERVE
uint64_t cpu_ns() {
    timespec t{};
    check(clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &t) == 0, "cannot read process CPU clock");
    return uint64_t(t.tv_sec)*1000000000u + t.tv_nsec;
}
#endif

Field context(size_t n, std::string_view profile, zn_info& actual) {
    const auto cfg = zn_config_1d(ZN_F64, n);
    auto opts = zn_defaults();
    if (profile != "serial") {
        opts.execution = ZN_OPENMP;
        opts.threads = profile == "omp1" ? 1 : 2;
        opts.chunk_size = chunk_blocks;
    }
    zn_context* raw = nullptr;
    auto status = zn_create_ex(&cfg, &opts, &raw);
    Field obj(raw, zn_destroy);
    native(status);
    native(zn_get_info(raw, &actual));
    check(actual.config.type == ZN_F64 && actual.config.dims == 1 && actual.config.mode == ZN_REVERSIBLE &&
          actual.logical_bytes == n*sizeof(double) && actual.options.execution == opts.execution &&
          actual.options.threads == opts.threads && actual.options.chunk_size == opts.chunk_size &&
          actual.decode_execution == ZN_SERIAL, "unexpected native ZFP field configuration");
    if (opts.execution == ZN_OPENMP)
        check(actual.openmp_built == 1 && !actual.omp_dynamic && actual.omp_thread_limit == 2, "OpenMP runtime policy differs");
    return obj;
}

void run(bool encode, std::string_view profile, size_t columns, size_t rows, const char* in, const char* out) {
    const size_t logical = rows*sizeof(double);
    check(columns*logical <= (128u << 20), "whole field input exceeds file ceiling");
    std::ifstream input(in, std::ios::binary);
    check(bool(input), "cannot open field input");
    Product product(out);
    if (encode) {
        write(product.file, magic, sizeof magic);
        word(product.file, static_cast<uint32_t>(columns));
        word(product.file, static_cast<uint32_t>(rows));
    } else {
        char header[sizeof magic]; read(input, header, sizeof header);
        check(std::equal(std::begin(header), std::end(header), std::begin(magic)) && word(input) == columns && word(input) == rows,
              "ZFG1 header geometry differs");
    }
    // Read values/frames before the native window; publish outside it. Per-field
    // configure and teardown are outside the encode/decode API clock as well.
    for (size_t c = 0; c < columns; ++c) {
        std::vector<double> values(rows);
        std::vector<unsigned char> frame;
        size_t used = 0;
        if (encode) {
            read(input, values.data(), logical);
        } else {
            used = word(input);
            check(used && used <= max_field_frame && used % 8 == 0, "invalid ZFG1 frame length");
            frame.resize(used);
            read(input, frame.data(), used);
        }
        zn_info actual{};
        const auto field = context(rows, profile, actual);
#ifdef TSBENCH_ZFP_GROUPED_OBSERVE
        zfp_clear_work_marks();
#else
        const auto cpu0 = cpu_ns();
        const auto wall0 = clock_type::now();
#endif
        const auto status = encode ? zn_encode_field(field.get(), values.data(), logical, 0, &used)
                                   : zn_decode_field(field.get(), frame.data(), used, values.data(), logical, 0);
#ifndef TSBENCH_ZFP_GROUPED_OBSERVE
        const auto wall = std::chrono::duration_cast<std::chrono::nanoseconds>(clock_type::now() - wall0).count();
        const auto cpu = cpu_ns() - cpu0;
#endif
        native(status);
        check(used && used <= max_field_frame && used % 8 == 0, "unexpected ZFP frame bytes");
        if (encode) {
            word(product.file, static_cast<uint32_t>(used));
            write(product.file, zn_data(field.get()), used);
        } else {
            write(product.file, values.data(), logical);
        }
        std::cout << "{\"column\":" << c << ",\"rows\":" << rows << ",\"frame_bytes\":" << used
                  << ",\"execution\":" << actual.options.execution << ",\"configured_threads\":" << actual.options.threads
                  << ",\"chunk_blocks\":" << actual.options.chunk_size << ",\"decode_execution\":" << actual.decode_execution;
#ifdef TSBENCH_ZFP_GROUPED_OBSERVE
        zfp_print_work_marks();
#else
        std::cout << ",\"call_wall_ns\":" << wall << ",\"call_cpu_ns\":" << cpu;
#endif
        std::cout << "}\n";
    }
    check(input.peek() == std::char_traits<char>::eof() && input.eof() && !input.bad(), "trailing or unreadable field input");
    product.publish();
}
}

int main(int argc, char** argv) {
    try {
        check(argc == 7, "usage: encode/decode serial/omp1/omp2 columns rows in out");
        const std::string_view op(argv[1]), profile(argv[2]);
        check((op == "encode" || op == "decode") && (profile == "serial" || profile == "omp1" || profile == "omp2") &&
              (op != "decode" || profile == "serial"), "invalid ZFP field operation or profile");
        run(op == "encode", profile, count(argv[3], 4096), count(argv[4], max_field_rows), argv[5], argv[6]);
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 2;
    }
}
