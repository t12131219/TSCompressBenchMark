// Separate diagnostic build: actual full/tail calls to the r40 native field
// primitives. Never use this interposed executable as a timing sample.
#include "zfp.h"

#include <cstdlib>
#include <dlfcn.h>
#include <iostream>
#include <map>
#include <mutex>
#include <sys/syscall.h>
#include <unistd.h>

namespace {
struct Work { size_t full = 0, tail = 0; };
std::mutex mutex;
std::map<long, Work> workers;
thread_local unsigned depth = 0;

class Mark {
public:
    explicit Mark(bool tail) {
        if (depth++ == 0) {
            static thread_local const long tid = syscall(SYS_gettid);
            const std::lock_guard<std::mutex> lock(mutex);
            auto& w = workers[tid];
            if (tail) ++w.tail;
            else ++w.full;
        }
    }
    ~Mark() { --depth; }
};

template<class F> F symbol(const char* name) {
    auto fn = reinterpret_cast<F>(dlsym(RTLD_NEXT, name));
    if (!fn) std::abort();
    return fn;
}
}

void zfp_clear_work_marks() {
    const std::lock_guard<std::mutex> lock(mutex);
    workers.clear();
}

void zfp_print_work_marks() {
    const std::lock_guard<std::mutex> lock(mutex);
    std::cout << ",\"caller_tid\":" << syscall(SYS_gettid) << ",\"block_workers\":[";
    bool comma = false;
    for (const auto& [tid, w] : workers) {
        if (comma) std::cout << ',';
        comma = true;
        std::cout << "{\"tid\":" << tid << ",\"full\":" << w.full << ",\"tail\":" << w.tail << '}';
    }
    std::cout << ']';
}

extern "C" size_t zfp_encode_block_double_1(zfp_stream* stream, const double* values) {
    static const auto next = symbol<decltype(&zfp_encode_block_double_1)>("zfp_encode_block_double_1");
    const Mark mark(false);
    return next(stream, values);
}
extern "C" size_t zfp_decode_block_double_1(zfp_stream* stream, double* out) {
    static const auto next = symbol<decltype(&zfp_decode_block_double_1)>("zfp_decode_block_double_1");
    const Mark mark(false);
    return next(stream, out);
}
extern "C" size_t zfp_encode_partial_block_strided_double_1(zfp_stream* stream, const double* values, size_t n, ptrdiff_t stride) {
    static const auto next = symbol<decltype(&zfp_encode_partial_block_strided_double_1)>("zfp_encode_partial_block_strided_double_1");
    const Mark mark(true);
    return next(stream, values, n, stride);
}
extern "C" size_t zfp_decode_partial_block_strided_double_1(zfp_stream* stream, double* out, size_t n, ptrdiff_t stride) {
    static const auto next = symbol<decltype(&zfp_decode_partial_block_strided_double_1)>("zfp_decode_partial_block_strided_double_1");
    const Mark mark(true);
    return next(stream, out, n, stride);
}
