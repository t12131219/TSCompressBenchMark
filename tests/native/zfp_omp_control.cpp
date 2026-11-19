// Test-only ELF interposition of native *block work*, not thread creation or
// an OpenMP runtime setting. This is not linked into the normal CPU worker.
#include "zfp_native.h"
#include "zfp.h"

#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string_view>
#include <sys/syscall.h>
#include <unistd.h>
#include <vector>

namespace {
std::mutex marks_lock;
std::map<long, size_t> encoded_blocks, decoded_blocks;
void mark(std::map<long, size_t> &counts) {
    static thread_local const long tid = syscall(SYS_gettid);
    const std::lock_guard<std::mutex> guard(marks_lock);
    ++counts[tid];
}
void verify(bool valid, const char *why) {
    if (!valid) throw std::runtime_error(why);
}
void counts(const std::map<long, size_t> &workers) {
    std::cout << '[';
    bool comma = false;
    for (auto [tid, blocks] : workers) {
        if (comma) std::cout << ',';
        comma = true;
        std::cout << "{\"tid\":" << tid << ",\"blocks\":" << blocks << '}';
    }
    std::cout << ']';
}
}
extern "C" size_t zfp_encode_block_double_1(zfp_stream *stream, const double *block) {
    static auto next = reinterpret_cast<decltype(&zfp_encode_block_double_1)>(dlsym(RTLD_NEXT, "zfp_encode_block_double_1"));
    if (!next) std::abort();
    mark(encoded_blocks);
    return next(stream, block);
}
extern "C" size_t zfp_decode_block_double_1(zfp_stream *stream, double *block) {
    static auto next = reinterpret_cast<decltype(&zfp_decode_block_double_1)>(dlsym(RTLD_NEXT, "zfp_decode_block_double_1"));
    if (!next) std::abort();
    mark(decoded_blocks);
    return next(stream, block);
}
int main(int argc, char **argv) {
    try {
        verify(argc == 6, "expected input count serial|1|2 chunk_blocks output");
        const size_t n = std::stoul(argv[2]);
        const std::string_view variant = argv[3];
        const unsigned threads = variant == "2" ? 2u : 1u;
        const unsigned chunk = static_cast<unsigned>(std::stoul(argv[4]));
        verify(n && n <= 1024*1024 && n % 4 == 0 && chunk && chunk < n/4/threads &&
               (variant == "serial" || variant == "1" || variant == "2"), "unexpected diagnostic domain");
        std::vector<double> input(n), output(n);
        const size_t bytes = n * sizeof(double);
        std::ifstream src(argv[1], std::ios::binary);
        verify(bool(src.read(reinterpret_cast<char *>(input.data()), bytes)) && src.peek() == EOF, "invalid test input length");
        auto config = zn_config_1d(ZN_F64, n);
        auto options = zn_defaults();
        if (variant != "serial") {
            options.execution = ZN_OPENMP;
            options.threads = threads;
            options.chunk_size = chunk;
        }
        zn_context *p = nullptr;
        verify(zn_create_ex(&config, &options, &p) == ZN_OK, "could not create native field context");
        const std::unique_ptr<zn_context, decltype(&zn_destroy)> handle(p, zn_destroy);
        zn_info active{};
        verify(zn_get_info(p, &active) == ZN_OK && active.openmp_built == 1 && active.omp_dynamic == 0 &&
               active.options.execution == options.execution && active.options.threads == threads &&
               active.options.chunk_size == options.chunk_size && active.decode_execution == ZN_SERIAL, "native field policy mismatch");
        size_t used{};
        verify(zn_encode_field(p, input.data(), bytes, 0, &used) == ZN_OK, "field encode failed");
        verify(used && decoded_blocks.empty() && encoded_blocks.size() == threads, "wrong observed encoding participants");
        size_t encoded = 0;
        for (auto [tid, blocks] : encoded_blocks) { verify(tid > 0 && blocks, "invalid encoding observation"); encoded += blocks; }
        verify(encoded == n/4, "did not intercept all encoding blocks");
        std::vector<unsigned char> payload(zn_data(p), zn_data(p) + used);
        verify(zn_decode_field(p, payload.data(), used, output.data(), bytes, 0) == ZN_OK, "field decode failed");
        verify(encoded == n/4 && decoded_blocks.size() == 1 && decoded_blocks.count(getpid()) == 1 &&
               decoded_blocks.begin()->second == n/4 && std::memcmp(input.data(), output.data(), bytes) == 0,
               "decode worker or output mismatch");
        zn_info restored{};
        verify(zn_get_info(p, &restored) == ZN_OK && restored.options.execution == options.execution, "encode policy not restored");
        std::ofstream out(argv[5], std::ios::binary);
        verify(bool(out.write(reinterpret_cast<const char *>(payload.data()), used)), "write failed");
        out.close();
        verify(bool(out), "close failed");
        std::cout << "{\"policy\":\"" << variant << "\",\"configured_threads\":" << threads
                  << ",\"caller_tid\":" << getpid() << ",\"chunk_blocks\":" << active.options.chunk_size << ",\"omp_dynamic\":" << active.omp_dynamic
                  << ",\"omp_thread_limit\":" << active.omp_thread_limit << ",\"encode_block_work\":";
        counts(encoded_blocks);
        std::cout << ",\"decode_block_work\":";
        counts(decoded_blocks);
        std::cout << ",\"serial_decode_reported\":true,\"reversible_bits_verified\":true}\n";
        return 0;
    } catch (const std::exception &err) {
        std::cerr << err.what() << '\n';
        return 1;
    }
}
