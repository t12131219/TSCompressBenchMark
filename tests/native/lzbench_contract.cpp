// Direct M0 probes, not benchmark methods or timed workloads.
#include "lzbench_extended.hpp"
#include "zstd.h"
#include "lzma.h"

#include <algorithm>
#include <iostream>
#include <fstream>
#include <iterator>
#include <vector>
#include <memory>
#include <stdexcept>
#include <string>

using namespace lzbench_native;

namespace {
void check(bool value, const char *message) {
    if (!value) throw std::logic_error(message);
}

template<class F> std::string rejects(F action, const char *message) {
    try { action(); }
    catch (const std::runtime_error &error) {
        if (std::string(error.what()).find(message) != std::string::npos) return error.what();
        throw;
    }
    throw std::logic_error(std::string("expected rejection: ") + message);
}

bytes sample(size_t n, unsigned salt) {
    bytes out(n);
    for (size_t i = 0; i < n; ++i) out[i] = static_cast<unsigned char>(i / 19 + (i % 29) * salt);
    return out;
}

void save(const std::string &name, const bytes &data) {
    std::ofstream out(name, std::ios::binary | std::ios::trunc);
    out.write(reinterpret_cast<const char *>(data.data()), data.size());
    out.close();
    check(bool(out), "cannot publish native diagnostic artifact");
}

constexpr size_t xz_worker_input_size = (size_t(2) << 20) + 297;
constexpr size_t xz_worker_frame_bound = xz_worker_input_size + 65536;
constexpr size_t xz_sync_block = 131072;
constexpr size_t xz_sync_inner_span = 16384;
constexpr uint32_t xz_sync_preset = 1;
constexpr uint64_t xz_sync_budget = 134217728;
constexpr lzma_check xz_sync_check = LZMA_CHECK_CRC64;

bytes read_bounded(const std::string &name, size_t limit) {
    std::ifstream in(name, std::ios::binary | std::ios::ate);
    check(bool(in), "cannot open XZ diagnostic input");
    const auto n = in.tellg();
    check(n > 0 && uint64_t(n) <= limit, "XZ diagnostic input outside bound");
    bytes data(static_cast<size_t>(n));
    in.seekg(0);
    in.read(reinterpret_cast<char *>(data.data()), n);
    check(bool(in), "incomplete XZ diagnostic read");
    return data;
}

void no_background_jobs() {
    const auto trace = get_worker_stats();
    check(trace.jobs == 0 && trace.worker_threads == 0 && trace.caller_jobs == 0,
          "synchronous reference entered MT worker hooks");
    std::cout << R"("mt_worker_hooks":{"jobs":)" << trace.jobs << ",\"worker_threads\":"
              << trace.worker_threads << ",\"caller_jobs\":" << trace.caller_jobs << '}';
}

// Use the same block coder, reservation and uncompressed fallback as the
// frozen MT worker, without copying its thread/queue implementation. The
// public one-shot block_buffer_encode uses a different fallback threshold.
bool xz_caller_block(lzma_block &block, const uint8_t *data, size_t size, uint8_t *output, size_t &written) {
    const size_t bound = lzma_block_buffer_bound(xz_sync_block);
    block.compressed_size = bound;
    block.uncompressed_size = xz_sync_block;
    check(lzma_block_header_size(&block) == LZMA_OK && block.header_size < bound,
          "cannot reserve XZ block header");
    lzma_stream stream = LZMA_STREAM_INIT;
    const auto end = [](lzma_stream *s) { lzma_end(s); };
    const std::unique_ptr<lzma_stream, decltype(end)> cleanup(&stream, end);
    check(lzma_block_encoder(&stream, &block) == LZMA_OK, "cannot initialize caller-thread XZ block coder");
    stream.next_in = data;
    stream.next_out = output + block.header_size;
    stream.avail_out = bound - block.header_size;
    size_t offered = 0;
    lzma_ret rc = LZMA_OK;
    do {
        if (stream.avail_in == 0 && offered < size) {
            stream.avail_in = std::min(xz_sync_inner_span, size-offered);
            offered += stream.avail_in;
        }
        rc = lzma_code(&stream, offered == size ? LZMA_FINISH : LZMA_RUN);
    } while (rc == LZMA_OK && stream.avail_out);
    if (rc == LZMA_STREAM_END) {
        check(stream.total_in == size && lzma_block_header_encode(&block, output) == LZMA_OK,
              "unexpected caller-thread XZ block boundary");
        written = block.header_size + stream.total_out;
        return false;
    }
    check(rc == LZMA_OK || rc == LZMA_BUF_ERROR, "unexpected XZ caller coder status");
    written = 0;
    check(lzma_block_uncomp_encode(&block, data, size, output, &written, bound) == LZMA_OK,
          "cannot write bounded XZ uncompressed Block");
    return true;
}

void xz_sync_encode(const std::string &path) {
    const auto data = read_bounded(path, xz_worker_input_size);
    check(data.size() == xz_worker_input_size, "synchronous comparison requires the matched worker workload");
    lzma_options_lzma options{};
    check(!lzma_lzma_preset(&options, xz_sync_preset), "invalid XZ synchronous preset");
    lzma_filter filters[] = {{LZMA_FILTER_LZMA2, &options}, {LZMA_VLI_UNKNOWN, nullptr}};
    const auto memory = lzma_raw_encoder_memusage(filters);
    check(memory != UINT64_MAX && memory <= xz_sync_budget, "XZ synchronous raw encoder exceeds memory ceiling");
    bytes frame(xz_worker_frame_bound);
    lzma_stream_flags flags{};
    flags.check = xz_sync_check;
    check(lzma_stream_header_encode(&flags, frame.data()) == LZMA_OK, "cannot write XZ stream header");
    const auto cleanup = [](lzma_index *i) { lzma_index_end(i, nullptr); };
    std::unique_ptr<lzma_index, decltype(cleanup)> index(lzma_index_init(nullptr), cleanup);
    check(bool(index), "cannot allocate XZ Index");
    size_t written = LZMA_STREAM_HEADER_SIZE;
    std::vector<size_t> input_blocks;
    size_t fallback_blocks = 0;
    bytes scratch(lzma_block_buffer_bound(xz_sync_block));
    reset_worker_stats();
    for (size_t at = 0; at < data.size(); at += xz_sync_block) {
        const auto n = std::min(xz_sync_block, data.size() - at);
        lzma_block block{};
        block.check = flags.check;
        block.filters = filters;
        size_t got = 0;
        fallback_blocks += xz_caller_block(block, data.data() + at, n, scratch.data(), got);
        check(block.uncompressed_size == n && got <= frame.size()-written, "caller-thread XZ Block exceeds bound");
        std::copy_n(scratch.data(), got, frame.data()+written);
        written += got;
        check(lzma_index_append(index.get(), nullptr, lzma_block_unpadded_size(&block), n) == LZMA_OK,
              "cannot append XZ Index record");
        input_blocks.push_back(n);
    }
    flags.backward_size = lzma_index_size(index.get());
    check(lzma_index_buffer_encode(index.get(), frame.data(), &written, frame.size()) == LZMA_OK &&
          written + LZMA_STREAM_HEADER_SIZE <= frame.size(), "cannot finish bounded XZ Index");
    check(lzma_stream_footer_encode(&flags, frame.data()+written) == LZMA_OK, "cannot write XZ stream footer");
    frame.resize(written + LZMA_STREAM_HEADER_SIZE);
    save("workers-sync.xz", frame);
    std::cout << R"({"entry":"lzma_block_encoder","input_bytes":)" << data.size() << ",\"frame_bytes\":"
              << frame.size() << ",\"raw_encoder_memory_bytes\":" << memory << ",\"fallback_blocks\":"
              << fallback_blocks << ",\"inner_input_span_bytes\":" << xz_sync_inner_span << ",\"block_input_bytes\":[";
    for (size_t i = 0; i < input_blocks.size(); ++i) std::cout << (i ? "," : "") << input_blocks[i];
    std::cout << "],\"parameters\":{\"block_size\":" << xz_sync_block << ",\"preset\":" << xz_sync_preset
              << ",\"check\":" << int(flags.check) << ",\"memory_limit\":" << xz_sync_budget << ",\"filter_id\":"
              << LZMA_FILTER_LZMA2 << ",\"dict_size\":" << options.dict_size << "},";
    no_background_jobs();
    std::cout << "}\n";
}

void xz_sync_decode(const std::string &name) {
    check(name == "workers-sync.xz" || name == "workers-2.xz" || name == "/inputs/frame", "unexpected synchronous XZ frame identity");
    const auto wire = read_bounded(name, xz_worker_frame_bound);
    auto stream = lzma_stream LZMA_STREAM_INIT;
    const auto end = [](lzma_stream *s) { lzma_end(s); };
    const std::unique_ptr<lzma_stream, decltype(end)> cleanup(&stream, end);
    reset_worker_stats();
    check(lzma_stream_decoder(&stream, xz_sync_budget, 0) == LZMA_OK, "caller-thread XZ decode initialization failed");
    bytes output(xz_worker_input_size+1);
    stream.next_in = wire.data();
    stream.avail_in = wire.size();
    stream.next_out = output.data();
    stream.avail_out = output.size();
    check(lzma_code(&stream, LZMA_FINISH) == LZMA_STREAM_END && !stream.avail_in &&
          stream.total_out == xz_worker_input_size, "caller-thread XZ decoder failed extent or checksum");
    output.resize(stream.total_out);
    save("sync.decoded", output);
    std::cout << R"({"entry":"lzma_stream_decoder","input_bytes":)" << stream.total_in
              << ",\"restored_bytes\":" << stream.total_out << ",\"memory_limit\":" << xz_sync_budget << ',';
    no_background_jobs();
    std::cout << "}\n";
}

void baseline(ln_codec codec) {
    ln_context *raw = nullptr;
    check(ln_create(codec, -1, &raw) == LN_INVALID && !raw, "negative baseline level accepted");
    check(ln_create(codec, codec == LN_ZSTD ? 3 : 6, &raw) == LN_OK && raw, "baseline create");
    const std::unique_ptr<ln_context, decltype(&ln_destroy)> ctx(raw, ln_destroy);
    std::vector<std::pair<ln_status, ln_status>> rejections;
    std::vector<worker_stats> xz_encode_jobs;
    for (const size_t n : {size_t(0), size_t(1), LN_MAX_BLOCK - 1, LN_MAX_BLOCK}) {
        auto input = sample(n, 7);
        const auto bound = ln_compress_bound(codec, n);
        check(bound > 0, "missing baseline bound");
        bytes frame(bound), decoded(n);
        size_t used = 99, got = 99;
        check(ln_compress(raw, input.data(), n, frame.data(), bound - 1, &used) == LN_CAPACITY && !used,
              "baseline compress capacity contract");
        if (codec == LN_XZ) reset_worker_stats();
        check(ln_compress(raw, input.data(), n, frame.data(), bound, &used) == LN_OK && used && used <= bound,
              "baseline encode");
        if (codec == LN_XZ) xz_encode_jobs.push_back(get_worker_stats());
        if (n) {
            check(ln_decompress(raw, frame.data(), used, decoded.data(), n - 1, n, &got) == LN_CAPACITY && !got,
                  "baseline decode capacity contract");
        }
        check(ln_decompress(raw, frame.data(), used, decoded.data(), n, n, &got) == LN_OK && got == n && decoded == input,
              "baseline exact length and bytes");
        {
            frame.resize(used);
            save((codec == LN_ZSTD ? "zstd-legacy-" : "xz-legacy-") + std::to_string(n) +
                 (codec == LN_ZSTD ? ".zst" : ".xz"), frame);
            bytes wide(n + 1);
            const auto wrong = ln_decompress(raw, frame.data(), used, wide.data(), wide.size(), n + 1, &got);
            // At the block cap, an impossible expected size is rejected earlier by ln_decompress.
            check(wrong == (n == LN_MAX_BLOCK ? LN_INVALID : LN_CODEC_ERROR) && !got, "wrong original length accepted");
            const auto truncated = ln_decompress(raw, frame.data(), used - 1, decoded.data(), n, n, &got);
            check(truncated == LN_CODEC_ERROR && !got, "truncated baseline frame accepted");
            rejections.emplace_back(wrong, truncated);
            if (codec == LN_ZSTD && n == LN_MAX_BLOCK) {
                bytes upstream(ZSTD_compressBound(n));
                const size_t size = ZSTD_compress(upstream.data(), upstream.size(), input.data(), n, 3);
                check(!ZSTD_isError(size) && size, "direct upstream encode failed");
                upstream.resize(size);
                std::fill(decoded.begin(), decoded.end(), 0);
                check(ln_decompress(raw, upstream.data(), upstream.size(), decoded.data(), n, n, &got) == LN_OK &&
                      got == n && decoded == input, "legacy decode of direct upstream product differs");
                save("zstd-upstream.zst", upstream);
            }
        }
    }
    auto input = sample(LN_MAX_BLOCK + 1, 7);
    bytes frame(ln_compress_bound(codec, LN_MAX_BLOCK));
    size_t used = 99;
    check(!ln_compress_bound(codec, input.size()), "oversize block has bound");
    check(ln_compress(raw, input.data(), input.size(), frame.data(), frame.size(), &used) == LN_INVALID && !used,
          "oversize baseline encode accepted");
    used = 99;
    check(ln_decompress(raw, frame.data(), frame.size(), input.data(), input.size(), input.size(), &used) == LN_INVALID && !used,
          "oversize baseline decode accepted");
    std::cout << R"({"roundtrip_sizes":[0,1,65535,65536],"oversize_and_short_capacity_rejected":true,"invalid_level_rejected":true)";
    std::cout << R"(,"wrong_length_and_truncated":[)";
    for (size_t i = 0; i < rejections.size(); ++i) {
        if (i) std::cout << ',';
        std::cout << '[' << rejections[i].first << ',' << rejections[i].second << ']';
    }
    std::cout << ']';
    if (codec == LN_ZSTD) std::cout << R"(,"legacy_decodes_upstream":true)";
    else {
        std::cout << R"(,"configured_preset":6,"encode_jobs":[)";
        for (size_t i = 0; i < xz_encode_jobs.size(); ++i) {
            if (i) std::cout << ',';
            const auto &job = xz_encode_jobs[i];
            std::cout << "{\"jobs\":" << job.jobs << ",\"worker_threads\":" << job.worker_threads
                      << ",\"caller_jobs\":" << job.caller_jobs << '}';
        }
        std::cout << ']';
    }
    std::cout << "}\n";
}

struct span_call { size_t offered, consumed, produced; bool finish, finished; };
struct transfer {
    bytes data;
    std::vector<span_call> calls;
    size_t finish_calls = 0;
};

void log_calls(const transfer &transfer) {
    std::cout << '[';
    for (size_t i = 0; i < transfer.calls.size(); ++i) {
        if (i) std::cout << ',';
        const auto &c = transfer.calls[i];
        std::cout << '[' << c.offered << ',' << c.consumed << ',' << c.produced << ',' << c.finish << ',' << c.finished << ']';
    }
    std::cout << ']';
}

transfer process(session &codec, bool encode, const bytes &src, size_t quota, size_t chunk, size_t out_chunk) {
    transfer result;
    bytes out(out_chunk);
    size_t offset = 0, end = std::min(chunk, src.size()), idle = 0;
    while (true) {
        const auto *data = src.empty() ? nullptr : src.data() + offset;
        const bool finish = end == src.size();
        const auto step = codec.process(encode, data, end - offset, out.data(), out.size(), finish);
        check(result.calls.size() < 50'000, "diagnostic step limit");
        result.calls.push_back({end - offset, step.consumed, step.produced, finish, step.finished});
        result.finish_calls += finish;
        check(step.consumed <= end - offset && step.produced <= out.size(), "native span bounds");
        check(step.produced <= quota - result.data.size(), "output quota");
        offset += step.consumed;
        result.data.insert(result.data.end(), out.begin(), out.begin() + step.produced);
        if (step.finished) {
            check(offset == src.size(), "unconsumed input after native finish");
            return result;
        }
        idle = (step.consumed || step.produced) ? 0 : idle + 1;
        check(idle < 10000, "stalled process loop");
        if (offset == end) end += std::min(chunk, src.size() - end);
    }
}

configuration xz_session_config() {
    configuration conf;
    conf.codec = LN_XZ;
    conf.level = 1;
    conf.parameters = {{"block_size", 32768}, {"check", 4}, {"filter0", 3}, {"filter0_distance", 4},
                       {"memory_limit", 64 << 20}, {"threads", 1}};
    return conf;
}

void xz_guards() {
    std::ifstream input("xz-dictionary-over-budget.xz",std::ios::binary);
    check(bool(input), "missing oversize dictionary frame");
    bytes frame((std::istreambuf_iterator<char>(input)), {});
    check(!frame.empty() && frame.size() < 256, "oversize dictionary control frame extent");
    ln_context *raw = nullptr;
    check(ln_create(LN_XZ, 6, &raw) == LN_OK && raw, "XZ baseline guard create");
    const std::unique_ptr<ln_context, decltype(&ln_destroy)> ctx(raw, ln_destroy);
    unsigned char byte = 0;
    size_t produced = 99;
    const auto legacy_status = ln_decompress(raw, frame.data(), frame.size(), &byte, 1, 1, &produced);
    check(legacy_status == LN_CODEC_ERROR && !produced, "XZ legacy decoder memory stop was not enforced");

    const auto conf = xz_session_config();
    session decoder(conf);
    const auto decode_limit = rejects([&] { process(decoder, false, frame, 1, 17, 7); }, "XZ code: 6");
    auto low = conf;
    low.parameters["memory_limit"] = 1;
    const auto encode_limit = rejects([&] { session s(low); }, "XZ encoder memory/configuration limit");
    auto unsupported = conf;
    unsupported.parameters["filter0"] = 127;
    const auto filter_reject = rejects([&] { session s(unsupported); }, "XZ BCJ filter id");
    std::cout << "{\"legacy_status\":" << legacy_status << ",\"legacy_produced\":" << produced
              << ",\"decoder_budget\":\"" << decode_limit << "\",\"encoder_budget\":\"" << encode_limit
              << "\",\"unsupported_filter\":\"" << filter_reject << "\"}\n";
}

void incremental(ln_codec codec) {
    configuration conf;
    conf.codec = codec;
    if (codec == LN_XZ) {
        // Exercise a real Delta prefilter before LZMA2. XZ native filter ID 3.
        conf = xz_session_config();
        auto dict = conf;
        dict.dictionary = {1};
        rejects([&] { session s(dict); }, "no external dictionary");
    } else {
        conf.level = -1; // Not accepted by legacy block ln_create.
        conf.parameters = {{"workers", 0}, {"checksum", 1}};
        auto bad = conf;
        bad.parameters["pledged_size"] = -2;
        session bad_pledge(bad);
        rejects([&] { bad_pledge.reset(true); }, "pledged size");
    }
    auto unknown = conf;
    unknown.parameters["tsbench_invalid"] = 1;
    rejects([&] { session s(unknown); }, "unsupported parameter: tsbench_invalid");

    session s(conf);
    check(s.streaming(), "not a native session");
    unsigned char b = 0;
    rejects([&] { s.process(true, &b, 1, &b, 1, false); }, "spans/capacity/overlap");
    rejects([&] { s.process(true, nullptr, 0, &b, 0, false); }, "spans/capacity/overlap");
    const auto block_reject = rejects([&] { s.compress_block(&b, 1); }, "use process for native stream/frame");
    const auto decode_block_reject = rejects([&] { s.decompress_block(&b, 1, 1); }, "use process for stream/frame");
    auto original = sample(136013, 9);
    auto independent = sample(7919, 13);
    s.reset(true);
    const auto a = process(s, true, original, original.size() + 65536, 4093, 7);
    check(a.finish_calls > 1, "finish backpressure not exercised");
    rejects([&] { s.process(true, nullptr, 0, &b, 1, true); }, "reset required after stream end");
    s.reset(true);
    const auto bframe = process(s, true, independent, independent.size() + 65536, 947, 11);

    // Start decoding the second frame first: no predecessor bytes or history required.
    session fresh(conf);
    const auto second_first = process(fresh, false, bframe.data, independent.size(), 17, 113);
    check(second_first.data == independent, "fresh decode after encode reset");
    const auto decoded = process(s, false, a.data, original.size(), 19, 127);
    check(decoded.data == original, "native split/partial session mismatch");
    s.reset(false);
    const auto reset = process(s, false, bframe.data, independent.size(), 13, 251);
    check(reset.data == independent, "decode reset");
    s.reset(false);
    auto truncated = bframe.data;
    truncated.pop_back();
    const auto truncation = rejects([&] { process(s, false, truncated, independent.size(), 17, 71); }, "truncated stream");
    const auto reset_required = rejects([&] { s.process(false, nullptr, 0, &b, 1, true); }, "reset required after failure");
    s.reset(false);
    const auto recovered = process(s, false, bframe.data, independent.size(), 17, 71);
    check(recovered.data == independent, "recovery after reset");
    for (const auto &entry : {std::make_pair("session-first", &a), std::make_pair("session-second", &bframe)}) {
        save(std::string(entry.first) + (codec == LN_ZSTD ? ".zst" : ".xz"), entry.second->data);
    }
    std::cout << "{\"input_bytes\":" << original.size() << ",\"frame_bytes\":" << a.data.size()
              << ",\"encode_finish_calls\":" << a.finish_calls
              << R"(,"independent_reset_decode":true,"truncation_and_reset_verified":true,"overlap_and_zero_capacity_rejected":true,"reject":[")"
              << block_reject << "\",\"" << decode_block_reject << "\",\"" << truncation << "\",\"" << reset_required
              << R"("],"calls":{)";
    bool comma = false;
    for (const auto &entry : {std::make_pair("encode-first", &a), std::make_pair("encode-second-after-reset", &bframe),
                             std::make_pair("decode-second-fresh", &second_first), std::make_pair("decode-first", &decoded),
                             std::make_pair("decode-second-after-reset", &reset), std::make_pair("decode-second-after-failure-and-reset", &recovered)}) {
        if (comma) std::cout << ',';
        comma = true;
        std::cout << '"' << entry.first << "\":";
        log_calls(*entry.second);
    }
    std::cout << "},\"configured_level\":" << conf.level << ",\"configured_parameters\":{";
    comma = false;
    for (const auto &[key, value] : conf.parameters) {
        if (comma) std::cout << ',';
        comma = true;
        std::cout << '"' << key << "\":" << value;
    }
    std::cout << "}}\n";
}
} // namespace

int main(int argc, char **argv) {
    try {
        if ((argc == 2 || argc == 3) && std::string(argv[1]) == "xz-sync-encode") {
            check(argc == 2 || std::string(argv[2]) == "/inputs/raw", "unexpected synchronous XZ input path");
            xz_sync_encode(argc == 2 ? "workers.bin" : argv[2]);
            return 0;
        }
        if (argc == 3 && std::string(argv[1]) == "xz-sync-decode") {
            xz_sync_decode(argv[2]);
            return 0;
        }
        check(argc == 3, "expected baseline|session zstd|xz");
        const std::string name = argv[2], operation = argv[1];
        check(name == "zstd" || name == "xz", "unknown codec");
        auto codec = name == "zstd" ? LN_ZSTD : LN_XZ;
        if (operation == "baseline") baseline(codec);
        else if (operation == "session") incremental(codec);
        else if (operation == "guards" && codec == LN_XZ) xz_guards();
        else check(false, "unknown operation");
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
