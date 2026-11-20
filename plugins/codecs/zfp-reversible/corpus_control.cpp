// Real-corpus control for the frozen ZFP C11 API. Raw streams are trusted products.
#include "zfp_native.h"
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
constexpr size_t max_field_rows = (1u << 20) / sizeof(double);
constexpr size_t max_array_rows = 4096;
constexpr size_t max_wire_bytes = 4u << 20;
constexpr unsigned chunk_blocks = 64;
void check(bool ok, const char* text) { if (!ok) throw std::runtime_error(text); }
void native(zn_status status) { check(status == ZN_OK, zn_error(status)); }
using Field = std::unique_ptr<zn_context, decltype(&zn_destroy)>;
using Array = std::unique_ptr<zn_array, decltype(&zn_array_destroy)>;

template<class T> std::vector<T> read(const char* path, size_t limit) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    const auto end = file.tellg();
    check(end > 0 && size_t(end) <= limit && size_t(end) % sizeof(T) == 0, "invalid input extent");
    std::vector<T> out(size_t(end) / sizeof(T));
    file.seekg(0);
    check(bool(file.read(reinterpret_cast<char*>(out.data()), end)) && file.peek() == EOF, "input read failed");
    return out;
}
void write(const char* path, const void* data, size_t size) {
    check(data && size && size <= max_wire_bytes, "invalid output extent");
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    check(bool(file.write(static_cast<const char*>(data), size)), "output write failed");
    file.close();
    check(bool(file), "output close failed");
}
size_t rows(std::string_view text, size_t min, size_t max) {
    size_t n{};
    const auto end = text.data() + text.size();
    const auto result = std::from_chars(text.data(), end, n);
    check(result.ec == std::errc{} && result.ptr == end && min <= n && n <= max, "invalid row count");
    return n;
}
Field field(size_t n, std::string_view policy, zn_info& info) {
    const auto cfg = zn_config_1d(ZN_F64, n);
    auto opts = zn_defaults();
    if (policy != "serial") {
        check(policy == "omp1" || policy == "omp2", "invalid field policy");
        opts.execution = ZN_OPENMP;
        opts.threads = policy == "omp1" ? 1 : 2;
        opts.chunk_size = chunk_blocks;
    }
    zn_context* raw = nullptr;
    const auto status = zn_create_ex(&cfg, &opts, &raw);
    Field handle(raw, zn_destroy);
    native(status);
    native(zn_get_info(raw, &info));
    check(info.config.type == ZN_F64 && info.config.dims == 1 && info.config.mode == ZN_REVERSIBLE &&
          info.logical_bytes == n * sizeof(double) && info.options.execution == opts.execution &&
          info.options.threads == opts.threads && info.options.chunk_size == opts.chunk_size &&
          info.decode_execution == ZN_SERIAL, "unexpected active field configuration");
    if (opts.execution == ZN_OPENMP)
        check(info.openmp_built == 1 && !info.omp_dynamic && info.omp_thread_limit == 2, "OpenMP controls differ");
    return handle;
}
void field_io(bool encode, size_t n, const char* path, std::string_view policy) {
    zn_info info{};
    const auto context = field(n, policy, info);
    size_t frame_bytes = 0;
    if (encode) {
        const auto values = read<double>(path, n * sizeof(double));
        check(values.size() == n, "field input count differs");
        native(zn_encode_field(context.get(), values.data(), n * sizeof(double), 0, &frame_bytes));
        check(frame_bytes % 8 == 0, "unaligned field bitstream");
        write("frame", zn_data(context.get()), frame_bytes);
    } else {
        check(policy == "serial", "detached recovery uses serial field context");
        const auto frame = read<unsigned char>(path, max_wire_bytes);
        frame_bytes = frame.size();
        check(frame_bytes % 8 == 0, "unaligned field bitstream");
        std::vector<double> values(n);
        native(zn_decode_field(context.get(), frame.data(), frame_bytes, values.data(), n * sizeof(double), 0));
        write("values", values.data(), n * sizeof(double));
    }
    std::cout << "{\"rows\":" << n << ",\"frame_bytes\":" << frame_bytes << ",\"execution\":"
              << info.options.execution << ",\"configured_threads\":" << info.options.threads
              << ",\"chunk_blocks\":" << info.options.chunk_size << ",\"decode_execution\":" << info.decode_execution << "}\n";
}
zn_config array_config(size_t n) {
    auto cfg = zn_config_1d(ZN_F64, n);
    cfg.mode = ZN_RATE;
    cfg.parameter = 18;
    return cfg;
}
double get(zn_array* a, size_t index) {
    double value{};
    native(zn_array_get(a, index, &value));
    return value;
}
void export_array(zn_array* a, const char* path, size_t bytes) {
    std::vector<unsigned char> frame(bytes);
    size_t used{};
    native(zn_array_export(a, frame.data(), frame.size(), &used));
    check(used == bytes, "array export size differs");
    write(path, frame.data(), used);
}
void array_io(bool encode, size_t n, const char* path) {
    const auto cfg = array_config(n);
    const size_t bytes = ((n + 3) / 4) * 16;
    std::vector<double> values;
    std::vector<unsigned char> frame;
    zn_array* raw = nullptr;
    if (encode) {
        values = read<double>(path, n * sizeof(double));
        check(values.size() == n, "array input count differs");
    } else {
        frame = read<unsigned char>(path, bytes);
        check(frame.size() == bytes, "array bitstream extent differs");
    }
    const auto status = encode ? zn_array_create(&cfg, values.data(), n * sizeof(double), &raw)
                               : zn_array_import(&cfg, frame.data(), frame.size(), &raw);
    Array handle(raw, zn_array_destroy);
    native(status);
    check(zn_array_count(raw) == n && zn_array_rate(raw) == 32 && zn_array_compressed_size(raw) == bytes,
          "array aligned rate or extent differs");
    if (encode) {
        export_array(raw, "before", bytes);
        native(zn_array_set(raw, 1, &values.back()));
        const auto cached = get(raw, 1);
        check(std::memcmp(&cached, &values.back(), sizeof(double)) == 0, "point write missing from dirty cache");
        (void)get(raw, n - 1); // Exercise eviction before the cross-block range write.
        native(zn_array_set_range(raw, 3, 4, values.data(), 4 * sizeof(double)));
        native(zn_array_flush(raw));
        export_array(raw, "after", bytes);
    } else {
        values.resize(n);
        native(zn_array_get_range(raw, 0, n, values.data(), n * sizeof(double)));
        std::array<double,4> range{};
        native(zn_array_get_range(raw, 3, range.size(), range.data(), sizeof(range)));
        check(std::memcmp(range.data(), values.data() + 3, sizeof(range)) == 0, "reopened range differs");
        write("values", values.data(), n * sizeof(double));
    }
    std::cout << "{\"rows\":" << n << ",\"frame_bytes\":" << bytes << ",\"requested_rate\":18,\"effective_rate\":32}\n";
}
}
int main(int argc, char** argv) {
    try {
        check(argc >= 4, "expected operation, rows, and file");
        const std::string_view op = argv[1];
        if (op == "field-encode" || op == "field-restore") {
            const bool encode = op == "field-encode";
            check(argc == (encode ? 5 : 4), "invalid field arguments");
            field_io(encode, rows(argv[2], 1, max_field_rows), argv[3], encode ? argv[4] : "serial");
        } else {
            check(argc == 4 && (op == "array-update" || op == "array-reopen"), "invalid array arguments");
            array_io(op == "array-update", rows(argv[2], 8, max_array_rows), argv[3]);
        }
        return std::cout ? 0 : 2;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
