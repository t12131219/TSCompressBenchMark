#include "alp_native.h"
#include "lzbench_extended.hpp"
#include "tsbench/trace_api.h"
#ifdef TSBENCH_PROFILE_BUILD
#include "collector.hpp"
#endif
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace {
using Clock = std::chrono::steady_clock;
using lzbench_native::bytes;
using lzbench_native::session;
constexpr size_t file_cap = size_t{16} << 20;
void check(bool ok, const char *error) { if (!ok) throw std::runtime_error(error); }

struct Span {
#ifdef TSBENCH_PROFILE_BUILD
    uint64_t id;
    explicit Span(bmk_trace_stage name) : id(bmk_trace_begin(name)) {}
    ~Span() { bmk_trace_end(id); }
#else
    explicit Span(bmk_trace_stage) {}
#endif
    Span(const Span &) = delete;
};

struct Cycles {
    int fd{-1}, error{};
    uint64_t count{};
    bool wanted{};
    void open(bool enabled) {
        wanted = enabled;
        if (!wanted) return;
        perf_event_attr attr{};
        attr.size = sizeof(attr);
        attr.type = PERF_TYPE_HARDWARE;
        attr.config = PERF_COUNT_HW_CPU_CYCLES;
        attr.disabled = 1;
        attr.exclude_kernel = 1;
        attr.exclude_hv = 1;
        fd = static_cast<int>(::syscall(SYS_perf_event_open, &attr, 0, -1, -1, PERF_FLAG_FD_CLOEXEC));
        if (fd < 0) error = errno;
    }
    void begin() { if (fd >= 0 && ::ioctl(fd, PERF_EVENT_IOC_ENABLE, 0) < 0) error = errno; }
    void end() {
        if (fd < 0 || error) return;
        if (::ioctl(fd, PERF_EVENT_IOC_DISABLE, 0) < 0) { error = errno; return; }
        auto n = ::read(fd, &count, sizeof(count));
        if (n != sizeof(count)) error = n < 0 ? errno : EIO;
    }
    void dump() {
        std::cout << "{\"scope\":\"caller_thread_user_only\",\"status\":\""
                  << (!wanted ? "disabled" : error ? "unavailable" : "measured") << "\",\"value\":";
        if (!wanted || error) std::cout << "null"; else std::cout << count;
        std::cout << ",\"errno\":";
        if (error) std::cout << error; else std::cout << "null";
        std::cout << '}';
    }
    ~Cycles() { if (fd >= 0) ::close(fd); }
};

bytes read(const char *name) {
    std::ifstream in(name, std::ios::binary | std::ios::ate);
    const auto n = in.tellg();
    check(n > 0 && uint64_t(n) <= file_cap, "input outside file bound");
    bytes value(static_cast<size_t>(n));
    in.seekg(0);
    in.read(reinterpret_cast<char *>(value.data()), n);
    check(bool(in), "cannot read input file");
    return value;
}
// Same per-call spans and finish rule as the frozen corpus worker driver.
// Input is staged before L0; output is buffered and serialized separately.
size_t zstd_worker_spans(session &s, bool encode, const bytes &in, bytes &out) {
    const size_t in_span = encode ? 262139 : 1 << 20;
    const size_t out_span = encode ? 65521 : 131071;
    size_t at = 0, end = 0, used = 0, idle = 0;
    do {
        if (at == end && end < in.size()) end += std::min(in_span, in.size() - end);
        const size_t available = std::min(out_span, out.size() - used);
        const auto step = s.process(encode, in.data() + at, end - at, out.data() + used, available, end == in.size());
        check(step.consumed <= end - at && step.produced <= available, "native Zstd exceeded the span");
        at += step.consumed;
        used += step.produced;
        if (step.finished) {
            check(at == in.size() && used > 0, "native Zstd worker finished outside the frozen extent");
            return used;
        }
        idle = (step.consumed || step.produced) ? 0 : idle + 1;
        check(idle < 16384, "native Zstd worker stalled");
    } while (true);
}

void save(const char *name, const bytes &value, size_t used) {
    std::ofstream out(name, std::ios::binary | std::ios::trunc);
    out.write(reinterpret_cast<const char *>(value.data()), used);
    out.close();
    check(bool(out), "cannot publish output file");
}
size_t number(const char *text) {
    size_t pos = 0;
    const auto n = std::stoull(text, &pos);
    check(std::string_view(text).size() == pos && n <= file_cap, "invalid size");
    return static_cast<size_t>(n);
}
}

int main(int argc, char **argv) {
    try {
        check(argc == 8, "usage: DRIVER MODE ROUTE encode|decode ORIGINAL_BYTES INPUT OUTPUT TRACE_LIMIT");
        const std::string_view mode = argv[1], route = argv[2], op = argv[3];
        const bool encode = op == "encode", active = mode == "profiled";
        const bool alp = route == "alp-fused", corpus_mt = route == "zstd-mt-real";
        const bool zstd = route == "zstd-mt" || corpus_mt;
        check((encode || op == "decode") && (alp || zstd || route == "xz-opaque"), "unsupported route or direction");
#ifdef TSBENCH_PROFILE_BUILD
        check(active || mode == "trace_off", "wrong driver build for pass");
        if (active) tsbench::trace::start(number(argv[7]));
#else
        check(mode == "timing_only", "wrong driver build for pass");
#endif
        const size_t original = number(argv[4]);
        const auto input = read(argv[5]);
        check(!encode || original == input.size(), "unexpected original size");
        check((!alp || original % 8 == 0) && original && (!(!alp && !zstd) || original <= LN_MAX_BLOCK), "illegal original domain");
        size_t used = 0;
        alpn_decode_stats alp_stats{};
        lzbench_native::worker_stats native_stats{};
        Cycles cycles;
        cycles.open(active);
        if (zstd) lzbench_native::reset_worker_stats();
        cycles.begin();
        const auto start = Clock::now();
        {
            Span root(BMK_TRACE_OPERATION);
            bytes output;
            std::unique_ptr<session> stream;
            std::unique_ptr<ln_context, decltype(&ln_destroy)> xz(nullptr, ln_destroy);
            {
                Span stage(BMK_TRACE_PREPARE);
                size_t cap = original;
                if (alp) {
                    check(encode || alpn_backend_available(ALPN_FALP_AVX2, 64), "AVX2 runtime not supported");
                    if (encode) cap = alpn_compress_bound(original / 8, 64);
                } else if (zstd) {
                    lzbench_native::configuration config;
                    config.codec = LN_ZSTD;
                    config.level = 3;
                    if (corpus_mt) config.parameters = {{"workers", encode ? 2 : 0}, {"job_size", 524288}, {"checksum", 0}};
                    else config.parameters = {{"workers", 2}, {"job_size", 524288}, {"checksum", 1},
                                              {"pledged_size", static_cast<int64_t>(original)}};
                    stream = std::make_unique<session>(std::move(config));
                    if (corpus_mt) {
                        check(stream->streaming(), "corpus Zstd requires native sessions");
                        stream->reset(encode);
                        // Allocate one drain span past the bound so the native decoder can
                        // consume the final marker with a non-empty output span, as in the corpus driver.
                        cap = encode ? original + original / 10 + 65536 + 65521 : original + 131071;
                    } else cap = encode ? original + 65536 : original + 1;
                } else {
                    ln_context *context = nullptr;
                    check(ln_create(LN_XZ, 6, &context) == LN_OK, "cannot create opaque XZ context");
                    xz.reset(context);
                    if (encode) cap = ln_compress_bound(LN_XZ, original);
                }
                check(cap && cap <= file_cap, "output allocation exceeds bound");
                output.resize(cap);
            }
            {
                Span stage(BMK_TRACE_CODEC);
                if (alp) {
                    const size_t n = original / 8;
                    if (encode) check(alpn_compress(input.data(), n, 64, ALPN_AUTO, output.data(), output.size(), &used, nullptr) == ALPN_OK,
                                      "native ALP encode rejected");
                    else {
                        check(alpn_decompress_ex(input.data(), input.size(), n, output.data(), n, &used, ALPN_FALP_AVX2, &alp_stats) == ALPN_OK,
                              "native ALP decode rejected");
                        used *= 8;
                    }
                } else if (corpus_mt) {
                    used = zstd_worker_spans(*stream, encode, input, output);
                    check(encode ? used <= original + original / 10 + 65536 : used == original,
                          "corpus Zstd output budget or restoration extent differs");
                    stream.reset();
                } else if (zstd) {
                    size_t consumed = 0;
                    for (int i = 0; i < 2048; ++i) {
                        const auto step = stream->process(encode, input.data() + consumed, input.size() - consumed,
                                                          output.data() + used, output.size() - used, true);
                        consumed += step.consumed; used += step.produced;
                        if (step.finished) {
                            check(consumed == input.size(), "native Zstd did not finish complete input");
                            break;
                        }
                        check(i < 2047 && used < output.size(), "native Zstd did not finish within bounds");
                    }
                    stream.reset();  // joins worker pool before the root and trace snapshot close
                } else {
                    const auto s = encode ? ln_compress(xz.get(), input.data(), input.size(), output.data(), output.size(), &used)
                                          : ln_decompress(xz.get(), input.data(), input.size(), output.data(), output.size(), original, &used);
                    check(s == LN_OK, "native opaque XZ call rejected");
                    xz.reset();
                }
                check(used && used <= output.size() && (encode || used == original), "unacceptable output length");
            }
            {
                Span stage(BMK_TRACE_SERIALIZE);
                save(argv[6], output, used);
            }
        }
        const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
        cycles.end();
        if (zstd) native_stats = lzbench_native::get_worker_stats();
        std::cout << "{\"pid\":" << ::getpid() << ",\"pass_kind\":\"" << mode << "\",\"wall_ns\":" << ns
                  << ",\"input_bytes\":" << input.size() << ",\"output_bytes\":" << used
                  << ",\"alp_fused_vectors\":" << alp_stats.falp_avx2_vectors
                  << ",\"native_jobs\":" << native_stats.jobs << ",\"native_worker_threads\":" << native_stats.worker_threads
                  << ",\"native_caller_jobs\":" << native_stats.caller_jobs << ",\"cycles\":";
        cycles.dump();
        std::cout << ",\"trace\":";
#ifdef TSBENCH_PROFILE_BUILD
        if (active) { tsbench::trace::stop(); tsbench::trace::dump(std::cout); } else
#endif
        std::cout << "null";
        std::cout << "}\n";
        return std::cout ? 0 : 5;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 2; }
}
