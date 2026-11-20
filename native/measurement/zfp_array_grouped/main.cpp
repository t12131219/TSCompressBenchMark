// Group frozen array windows in one worker without changing any ZFP array state
// or native bytes. Initial and updated archives are independently reopenable.
#include "zfp_native.h"

#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
using Array = std::unique_ptr<zn_array, decltype(&zn_array_destroy)>;
constexpr std::string_view raw_magic("ZAR1"), wire_magic("ZAG1"), value_magic("ZAV1");
constexpr uint32_t requested_rate = 18, effective_rate = 32;

void check(bool ok, const char* reason) { if (!ok) throw std::runtime_error(reason); }
void native(zn_status code) { if (code != ZN_OK) throw std::runtime_error(zn_error(code)); }
void read(std::istream& f, void* ptr, size_t n) {
    check(bool(f.read(static_cast<char*>(ptr), static_cast<std::streamsize>(n))), "truncated grouped array input");
}
void write(std::ostream& f, const void* ptr, size_t n) {
    check(bool(f.write(static_cast<const char*>(ptr), static_cast<std::streamsize>(n))), "grouped array output write failed");
}
uint32_t word(std::istream& f) {
    uint8_t buf[4];
    read(f, buf, sizeof buf);
    uint32_t n = 0;
    for (unsigned i = 0; i < 4; ++i) n |= uint32_t(buf[i]) << (8*i);
    return n;
}
void word(std::ostream& f, uint32_t n) {
    uint8_t buf[4];
    for (auto& v : buf) { v = static_cast<uint8_t>(n); n >>= 8; }
    write(f, buf, sizeof buf);
}

class Product {
    fs::path path_, scratch_;
    bool published_ = false, accepted_ = false;
public:
    std::ofstream file;
    explicit Product(const char* path) : path_(path), scratch_(path_.string()+".partial") {
        check(!fs::exists(path_) && !fs::exists(scratch_), "array output already exists");
        file.open(scratch_, std::ios::binary);
        check(bool(file), "array output open failed");
    }
    void publish() {
        file.close();
        check(bool(file), "array output close failed");
        fs::rename(scratch_, path_);
        published_ = true;
    }
    void accept() noexcept { accepted_ = true; }
    ~Product() {
        if (file.is_open()) file.close();
        std::error_code ignored;
        if (published_ && !accepted_) fs::remove(path_, ignored);
        if (!published_) fs::remove(scratch_, ignored);
    }
};

struct Extent { uint32_t windows, columns, rows; };
struct Window { uint32_t column, start, rows; };

Extent extent(std::istream& f, std::string_view kind) {
    char head[4];
    read(f, head, sizeof head);
    check(std::string_view(head, sizeof head) == kind, "grouped array input identity differs");
    Extent e{word(f), word(f), word(f)};
    check(e.windows && e.windows <= 25000 && e.columns && e.columns <= 4096 && e.rows >= 8 && e.rows <= 131072 &&
          uint64_t(e.columns)*e.rows*sizeof(double) <= (128u<<20), "grouped array input extent differs");
    if (kind == wire_magic)
        check(word(f) == requested_rate && word(f) == effective_rate, "grouped array wire rate differs");
    return e;
}
void header(std::ostream& f, std::string_view kind, Extent e) {
    write(f, kind.data(), kind.size());
    word(f, e.windows); word(f, e.columns); word(f, e.rows);
    if (kind == wire_magic) { word(f, requested_rate); word(f, effective_rate); }
}
void geometry(std::ostream& f, Window w) { word(f, w.column); word(f, w.start); word(f, w.rows); }
Window geometry(std::istream& f, Extent e, Window prior, uint32_t index) {
    Window w{word(f), word(f), word(f)};
    check(w.column < e.columns && w.rows >= 8 && w.rows <= 4096 && w.start < e.rows && w.rows <= e.rows-w.start &&
          (index == 0 || w.column > prior.column || (w.column == prior.column && w.start >= prior.start + prior.rows)),
          "grouped array window is out of range, overlaps, or is unordered");
    return w;
}

uint64_t cpu_ns() {
    timespec ts{};
    check(clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &ts) == 0, "cannot observe array CPU time");
    return uint64_t(ts.tv_sec)*1000000000u + ts.tv_nsec;
}
struct Span {
    uint64_t cpu_start = cpu_ns();
    Clock::time_point wall_start = Clock::now();
    uint64_t wall = 0, cpu = 0;
    void stop() {
        wall = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-wall_start).count();
        cpu = cpu_ns()-cpu_start;
    }
    void emit(const char* name) const {
        std::cout << ",\"" << name << "\":{\"wall_ns\":" << wall << ",\"process_cpu_ns\":" << cpu << '}';
    }
};
zn_config config(uint32_t rows) {
    auto c = zn_config_1d(ZN_F64, rows);
    c.mode = ZN_RATE;
    c.parameter = requested_rate;
    return c;
}
size_t wire_bytes(Window w) { return 16*((w.rows+3)/4); }
void identity(zn_array* a, Window w, size_t bytes) {
    check(zn_array_count(a) == w.rows && zn_array_rate(a) == effective_rate && zn_array_compressed_size(a) == bytes,
          "aligned native array rate or frame length differs");
}
std::vector<uint8_t> export_frame(zn_array* a, size_t bytes) {
    std::vector<uint8_t> out(bytes);
    size_t used = 0;
    native(zn_array_export(a, out.data(), out.size(), &used));
    check(used == bytes, "native array export length differs");
    return out;
}
double get(zn_array* a, size_t index) {
    double value{};
    native(zn_array_get(a, index, &value));
    return value;
}
void report(Window w, size_t bytes) {
    std::cout << "{\"column\":" << w.column << ",\"row_start\":" << w.start << ",\"rows\":" << w.rows
              << ",\"frame_bytes\":" << bytes << ",\"requested_rate\":" << requested_rate << ",\"effective_rate\":" << effective_rate;
}

void update(std::istream& input, Extent e, Product& initial, Product& changed) {
    header(initial.file, wire_magic, e);
    header(changed.file, wire_magic, e);
    Window prior{};
    for (uint32_t i = 0; i < e.windows; ++i) {
        const auto w = prior = geometry(input, e, prior, i);
        std::vector<double> values(w.rows);
        const auto bytes = wire_bytes(w), logical = values.size()*sizeof(double);
        read(input, values.data(), logical);
        const auto cfg = config(w.rows);
        zn_array* pointer = nullptr;
        Span create;
        const auto status = zn_array_create(&cfg, values.data(), logical, &pointer);
        create.stop();
        Array a(pointer, zn_array_destroy);
        native(status);
        identity(a.get(), w, bytes);
        Span before;
        const auto baseline = export_frame(a.get(), bytes);
        before.stop();
        Span mutate;
        native(zn_array_set(a.get(), 1, &values.back()));
        const auto cached = get(a.get(), 1);
        check(std::memcmp(&cached, &values.back(), sizeof(double)) == 0, "point write missing from cache");
        (void)get(a.get(), w.rows-1);
        native(zn_array_set_range(a.get(), 3, 4, values.data(), 4*sizeof(double)));
        native(zn_array_flush(a.get()));
        mutate.stop();
        Span after;
        const auto modified = export_frame(a.get(), bytes);
        after.stop();
        geometry(initial.file, w);
        write(initial.file, baseline.data(), baseline.size());
        geometry(changed.file, w);
        write(changed.file, modified.data(), modified.size());
        report(w, bytes);
        create.emit("create"); before.emit("initial_export"); mutate.emit("point_range_flush"); after.emit("updated_export");
        std::cout << "}\n";
    }
}
void reopen(std::istream& input, Extent e, Product& output) {
    header(output.file, value_magic, e);
    Window prior{};
    for (uint32_t i = 0; i < e.windows; ++i) {
        const auto w = prior = geometry(input, e, prior, i);
        const auto bytes = wire_bytes(w);
        std::vector<uint8_t> payload(bytes);
        read(input, payload.data(), payload.size());
        const auto cfg = config(w.rows);
        zn_array* pointer = nullptr;
        Span import;
        const auto status = zn_array_import(&cfg, payload.data(), payload.size(), &pointer);
        import.stop();
        Array a(pointer, zn_array_destroy);
        native(status);
        identity(a.get(), w, bytes);
        std::vector<double> values(w.rows);
        std::array<double, 4> sample{};
        const auto logical = values.size()*sizeof(double);
        Span ranges;
        native(zn_array_get_range(a.get(), 0, w.rows, values.data(), logical));
        native(zn_array_get_range(a.get(), 3, sample.size(), sample.data(), sizeof(sample)));
        ranges.stop();
        check(std::memcmp(sample.data(), values.data()+3, sizeof(sample)) == 0, "reopened range differs");
        geometry(output.file, w);
        write(output.file, values.data(), logical);
        report(w, bytes);
        import.emit("import"); ranges.emit("read_ranges");
        std::cout << "}\n";
    }
}
void eof(std::istream& input) {
    check(input.peek() == std::char_traits<char>::eof() && input.eof() && !input.bad(), "trailing or unreadable grouped array bytes");
    check(bool(std::cout), "array observations could not be written");
}
}

int main(int argc, char** argv) {
    try {
        std::string_view op = argc > 1 ? argv[1] : "";
        check((op == "update" && argc == 5) || (op == "reopen" && argc == 4), "usage: update input initial after | reopen archive output");
        std::ifstream input(argv[2], std::ios::binary);
        check(bool(input), "grouped array input open failed");
        if (op == "update") {
            const auto e = extent(input, raw_magic);
            Product before(argv[3]), after(argv[4]);
            update(input, e, before, after);
            eof(input);
            before.publish(); after.publish();
            before.accept(); after.accept();
        } else {
            const auto e = extent(input, wire_magic);
            Product out(argv[3]);
            reopen(input, e, out);
            eof(input);
            out.publish(); out.accept();
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 2;
    }
}
