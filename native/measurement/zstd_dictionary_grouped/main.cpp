// Group I/O for the r40 Zstd dictionary route; each frame still uses the locked
// feature worker's native stream helper, chunks, level and fresh context.
#include "feature_io.hpp"

#include <charconv>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string_view>

namespace {
using namespace lzbench_native;
using feature_io::check;
using clock_type = std::chrono::steady_clock;
namespace fs = std::filesystem;
constexpr size_t block = LN_MAX_BLOCK;
constexpr size_t wire_limit = block + 1024;
constexpr size_t holdout_limit = 512u << 20;
constexpr size_t in_chunk = 307, out_chunk = 521;
constexpr char magic[] = {'Z', 'D', 'G', '1'};

size_t positive(std::string_view s, size_t ceiling) {
    size_t n = 0;
    auto r = std::from_chars(s.data(), s.data() + s.size(), n);
    check(r.ec == std::errc{} && r.ptr == s.data() + s.size() && n && n <= ceiling, "invalid bounded size");
    return n;
}

std::ifstream input(const char* path) {
    std::ifstream f(path, std::ios::binary);
    check(bool(f), "open input");
    return f;
}

void read(std::istream& f, void* data, size_t n) {
    check(bool(f.read(static_cast<char*>(data), static_cast<std::streamsize>(n))), "short or unreadable input");
}

bytes read(std::istream& f, size_t n) {
    bytes b(n);
    read(f, b.data(), n);
    return b;
}

void end(std::istream& f) {
    check(f.peek() == std::char_traits<char>::eof() && f.eof() && !f.bad(), "trailing or unreadable input");
}

void write(std::ostream& f, const void* data, size_t n) {
    check(bool(f.write(static_cast<const char*>(data), static_cast<std::streamsize>(n))), "write output");
}

void word(std::ostream& f, uint32_t n) {
    unsigned char b[4];
    for (auto& v : b) { v = static_cast<unsigned char>(n); n >>= 8; }
    write(f, b, sizeof b);
}

uint32_t u32(const unsigned char* b) {
    uint32_t n = 0;
    for (int i = 0; i < 4; ++i) n |= uint32_t(b[i]) << (8 * i);
    return n;
}

uint32_t word(std::istream& f) {
    unsigned char b[4];
    read(f, b, sizeof b);
    return u32(b);
}

class Output {
    fs::path final_, partial_;
public:
    std::ofstream file;
    explicit Output(const char* name) : final_(name), partial_(final_.string() + ".partial") {
        check(!fs::exists(final_) && !fs::exists(partial_), "output exists");
        file.open(partial_, std::ios::binary);
        check(bool(file), "open output");
    }
    void publish() {
        file.close();
        check(bool(file), "close output");
        fs::rename(partial_, final_);
    }
    ~Output() {
        if (file.is_open()) file.close();
        std::error_code ignored;
        fs::remove(partial_, ignored);
    }
};

uint32_t dictionary_id(const bytes& d) {
    check(d.size() >= 8 && d.size() <= 2048 && u32(d.data()) == 0xec30a437 && u32(d.data() + 4) > 1,
          "trained dictionary identity differs");
    return u32(d.data() + 4);
}

bytes dictionary(const char* path) {
    const auto n = fs::file_size(path);
    check(n >= 8 && n <= 2048, "dictionary extent differs");
    auto f = input(path);
    auto d = read(f, n);
    end(f);
    return d;
}

struct Clocks {
    uint64_t wall = 0, cpu = 0;
    static uint64_t self_cpu() {
        timespec t{};
        check(clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &t) == 0, "read process CPU clock");
        return uint64_t(t.tv_sec) * 1000000000u + t.tv_nsec;
    }
    template<class Work> bytes measure(Work work) {
        const auto c = self_cpu();
        const auto a = clock_type::now();
        auto result = work();
        wall += std::chrono::duration_cast<std::chrono::nanoseconds>(clock_type::now() - a).count();
        cpu += self_cpu() - c;
        return result;
    }
    void emit() const { std::cout << ",\"call_wall_ns\":" << wall << ",\"call_cpu_ns\":" << cpu; }
};

void train(const char* source, const char* dest, size_t cap, size_t each, size_t count) {
    check(count >= 8 && ((cap == 256 && each == 32) || (cap == 2048 && each % 8 == 0 && count * each >= 8192)),
          "training tier, alignment or sample population differs");
    auto f = input(source);
    std::vector<bytes> samples;
    for (size_t i = 0; i < count; ++i) samples.push_back(read(f, each));
    end(f);
    Clocks times;
    auto d = times.measure([&] { return train_zstd_dictionary(samples, cap); });
    auto id = dictionary_id(d);
    check(d.size() <= cap, "dictionary capacity exceeded");
    Output out(dest);
    write(out.file, d.data(), d.size());
    out.publish();
    std::cout << "{\"operation\":\"train\",\"samples\":" << count << ",\"sample_bytes\":" << each
              << ",\"input_bytes\":" << each * count << ",\"dictionary_id\":" << id
              << ",\"dictionary_bytes\":" << d.size() << ",\"dictionary_capacity_bytes\":" << cap;
    times.emit();
    std::cout << "}\n";
}

void frames(bool encode, const char* source, const char* dest, const char* shared, size_t logical) {
    configuration config;
    config.codec = LN_ZSTD;
    config.mode = "frame";
    config.level = 3;
    config.dictionary = dictionary(shared);
    const auto id = dictionary_id(config.dictionary);
    const auto count = (logical + block - 1) / block;
    auto f = input(source);
    Output out(dest);
    if (encode) {
        write(out.file, magic, sizeof magic);
        word(out.file, static_cast<uint32_t>(count));
    } else {
        char head[sizeof magic];
        read(f, head, sizeof head);
        check(std::equal(std::begin(head), std::end(head), std::begin(magic)) && word(f) == count,
              "ZDG1 header or frame count differs");
    }
    Clocks times;
    size_t frame_bytes = 0;
    reset_worker_stats();
    for (size_t off = 0; off < logical; off += block) {
        const auto n = std::min(block, logical - off);
        auto size = n;
        if (!encode) {
            check(word(f) == n, "ZDG1 frame input extent differs");
            size = word(f);
            check(size && size <= wire_limit, "ZDG1 payload length out of bounds");
        }
        auto data = read(f, size);
        auto result = times.measure([&] {
            session s(config);
            check(s.streaming() && s.configured().level == 3, "native Zstd frame route differs");
            return encode ? feature_io::encode(s, data, in_chunk, out_chunk, block)
                          : feature_io::decode(s, data, in_chunk, out_chunk, n);
        });
        if (encode) {
            check(!result.empty() && result.size() <= wire_limit, "native Zstd frame exceeds harness bound");
            word(out.file, static_cast<uint32_t>(n));
            word(out.file, static_cast<uint32_t>(result.size()));
        }
        frame_bytes += encode ? result.size() : size;
        write(out.file, result.data(), result.size());
    }
    end(f);
    auto stats = get_worker_stats();
    check(stats.worker_threads == 0, "unexpected background Zstd workers");
    out.publish();
    std::cout << "{\"operation\":\"" << (encode ? "encode" : "decode") << "\",\"logical_bytes\":" << logical
              << ",\"native_frames\":" << count << ",\"native_frame_bytes\":" << frame_bytes
              << ",\"wrapper_bytes\":" << 8 + 8 * count << ",\"dictionary_id\":" << id
              << ",\"dictionary_bytes\":" << config.dictionary.size()
              << ",\"worker_threads\":" << stats.worker_threads << ",\"jobs\":" << stats.jobs;
    times.emit();
    std::cout << "}\n";
}
}

int main(int argc, char** argv) {
    try {
        const std::string_view op = argc > 1 ? argv[1] : "";
        if (op == "train" && argc == 7)
            train(argv[2], argv[3], positive(argv[4], 2048), positive(argv[5], 2048), positive(argv[6], 128));
        else if ((op == "encode" || op == "decode") && argc == 6)
            frames(op == "encode", argv[2], argv[3], argv[4], positive(argv[5], holdout_limit));
        else throw std::runtime_error("usage: train input output capacity sample_bytes samples | encode/decode input output dictionary logical_bytes");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
