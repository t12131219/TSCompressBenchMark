// Independent frozen ln_* call, with the vendored XZ job hook and decoder budget check.
#include "lzbench_extended.hpp"
#include "lzma.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <memory>

namespace {
constexpr size_t max_wire = 68000;

bool load(const char *path, void *data, size_t cap, size_t &n) {
    auto *f = std::fopen(path, "rb");
    if (!f) return false;
    n = std::fread(data, 1, cap, f);
    const bool full = std::fgetc(f) == EOF && !std::ferror(f);
    return std::fclose(f) == 0 && full;
}

lzma_ret budget_status(const uint8_t *payload, size_t n) {
    lzma_stream s = LZMA_STREAM_INIT;
    lzma_mt config{};
    config.threads = 1;
    config.flags = LZMA_CONCATENATED | LZMA_IGNORE_CHECK;
    config.memlimit_stop = UINT64_C(256) << 20;
    auto status = lzma_stream_decoder_mt(&s, &config);
    if (status == LZMA_OK) {
        std::array<uint8_t, 2> output;
        s.next_in = payload;
        s.avail_in = n;
        s.next_out = output.data();
        s.avail_out = output.size();
        status = lzma_code(&s, LZMA_FINISH);
    }
    lzma_end(&s);
    return status;
}
}

int main(int argc, char **argv) {
    if (argc != 3 && argc != 4) return 2;
    std::array<uint8_t, LN_MAX_BLOCK> input;
    std::array<uint8_t, LN_MAX_BLOCK + 1> recovered;
    std::array<uint8_t, max_wire> frame, expected;
    size_t n, want;
    if (!load(argv[1], input.data(), input.size(), n) || !load(argv[2], expected.data(), expected.size(), want)) return 3;
    ln_context *raw = nullptr;
    if (ln_create(LN_XZ, 6, &raw) != LN_OK || !raw) return 4;
    const std::unique_ptr<ln_context, decltype(&ln_destroy)> ctx(raw, ln_destroy);
    const size_t cap = ln_compress_bound(LN_XZ, n);
    if (!cap || cap > frame.size() || want < 32 || want > cap) return 5;
    size_t used = 99;
    if (ln_compress(raw, input.data(), n, frame.data(), cap-1, &used) != LN_CAPACITY || used) return 6;
    lzbench_native::reset_worker_stats();
    if (ln_compress(raw, input.data(), n, frame.data(), cap, &used) != LN_OK || used != want ||
        std::memcmp(frame.data(), expected.data(), used)) return 7;
    const auto jobs = lzbench_native::get_worker_stats();
    size_t got = 99;
    if (ln_decompress(raw, expected.data(), want, recovered.data(), n, n, &got) != LN_OK || got != n ||
        std::memcmp(recovered.data(), input.data(), n)) return 8;
    if (n && (ln_decompress(raw, frame.data(), used, recovered.data(), n-1, n, &got) != LN_CAPACITY || got)) return 9;
    const auto wrong = ln_decompress(raw, frame.data(), used, recovered.data(), n+1, n+1, &got);
    if (got || wrong != (n == LN_MAX_BLOCK ? LN_INVALID : LN_CODEC_ERROR)) return 10;
    if (ln_decompress(raw, frame.data(), used-1, recovered.data(), n, n, &got) != LN_CODEC_ERROR || got) return 11;
    if (argc == 4) {
        size_t bad;
        if (n != 1 || !load(argv[3], expected.data(), expected.size(), bad) || bad != used ||
            budget_status(expected.data(), bad) != LZMA_MEMLIMIT_ERROR ||
            ln_decompress(raw, expected.data(), bad, recovered.data(), n, n, &got) != LN_CODEC_ERROR || got) return 12;
    }
    return std::printf("{\"bytes\":%zu,\"encode_jobs\":%llu,\"background_workers\":%llu,\"caller_jobs\":%llu,"
                       "\"encode_short_capacity\":2,\"decode_short_capacity\":%s,\"wrong_length\":%d,"
                       "\"truncated\":4,\"lzma_budget_error\":%s}\n", n,
                       static_cast<unsigned long long>(jobs.jobs), static_cast<unsigned long long>(jobs.worker_threads),
                       static_cast<unsigned long long>(jobs.caller_jobs), n ? "2" : "null", static_cast<int>(wrong),
                       argc == 4 ? "6" : "null") < 0 ? 13 : 0;
}
