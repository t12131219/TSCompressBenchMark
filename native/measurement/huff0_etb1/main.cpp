// Separate observation runner; keep the historic ETB1 control and wire unchanged.
#include "entropy_port.hpp"

#include <charconv>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sched.h>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace {
namespace ep = entropy_port;
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
static_assert(Clock::is_steady);
constexpr size_t header = 9;

void check(bool condition, const char *reason) {
    if (!condition) throw std::runtime_error(reason);
}
uint64_t ns_since(Clock::time_point t) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-t).count();
}
uint32_t le(const uint8_t *p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
ep::Bytes read_short(const fs::path& path, size_t max_size) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    auto n = in.tellg();
    check(n > 0 && uint64_t(n) <= max_size, "invalid train/model extent");
    ep::Bytes out(static_cast<size_t>(n));
    in.seekg(0);
    check(bool(in.read(reinterpret_cast<char *>(out.data()), n)) && in.peek() == EOF && !in.bad(), "short train/model read");
    return out;
}
void write(std::ofstream &out, const ep::Bytes &data) {
    check(bool(out.write(reinterpret_cast<const char *>(data.data()), data.size())), "cannot write output");
}
void finish(std::ofstream &out) { out.close(); check(out.good(), "cannot close output"); }
std::string name(size_t i) {
    std::ostringstream text;
    text << 'g' << std::setfill('0') << std::setw(5) << i << ".bin";
    return text.str();
}
std::vector<size_t> parse_groups(std::string_view text) {
    std::vector<size_t> groups;
    while (!text.empty()) {
        const auto comma = text.find(',');
        const auto field = text.substr(0, comma);
        size_t n{};
        const auto r = std::from_chars(field.data(), field.data()+field.size(), n);
        check(r.ec == std::errc{} && r.ptr == field.data()+field.size() && n && n <= 256 && groups.size() < 10000,
              "invalid ETB1 group block count");
        groups.push_back(n);
        if (comma == std::string_view::npos) break;
        text.remove_prefix(comma+1);
        check(!text.empty(), "trailing ETB1 group delimiter");
    }
    check(!groups.empty(), "ETB1 has no groups");
    return groups;
}
void report(const ep::TableCodec &codec, size_t blocks, size_t raw, size_t wire,
            uint64_t setup, uint64_t calls, int cpu0) {
    std::cout << "{\"streams\":" << codec.huffman_streams() << ",\"effective_table_log\":" << codec.effective_table_log()
              << ",\"blocks\":" << blocks << ",\"raw_bytes\":" << raw << ",\"wire_bytes\":" << wire << ",\"context_count\":1"
              << ",\"table_wall_ns\":" << setup << ",\"block_calls_wall_ns\":" << calls
              << ",\"cpu_endpoints\":[" << cpu0 << ',' << sched_getcpu() << "]}\n";
    check(std::cout.good(), "ETB1 observation write failed");
}
void train(std::string_view lanes, const fs::path &source, const fs::path &dest) {
    check(lanes == "1" || lanes == "4", "unsupported ETB1 stream count");
    const auto raw = read_short(source, ep::block_size);
    const auto cpu = sched_getcpu();
    const auto t = Clock::now();
    const ep::TableCodec codec(ep::Algorithm::Huff, raw, 0, lanes == "1" ? 1 : 4);
    const auto setup = ns_since(t);
    std::ofstream out(dest, std::ios::binary);
    write(out, codec.model());
    finish(out);
    report(codec, 0, raw.size(), codec.model().size(), setup, 0, cpu);
}
void transfer(bool encode, const fs::path &model_path, const fs::path &src, const fs::path &dst,
              const std::vector<size_t> &groups) {
    const auto model = read_short(model_path, 1024);
    check(model.size() >= 8 && model[4] == unsigned(ep::Algorithm::Huff), "not a Huff0 model");
    const auto cpu = sched_getcpu();
    const auto started = Clock::now();
    const ep::TableCodec codec(model);
    const auto setup = ns_since(started);
    ep::Bytes block;
    size_t blocks = 0, raw = 0, wire = 0;
    uint64_t calls = 0;
    for (size_t g = 0; g < groups.size(); ++g) {
        std::ifstream in(src / name(g), std::ios::binary);
        std::ofstream out(dst / name(g), std::ios::binary);
        check(in && out, "ETB1 group open failed");
        for (size_t b = 0; b < groups[g]; ++b) {
            const bool tail = g+1 == groups.size() && b+1 == groups[g];
            if (encode) {
                block.resize(ep::block_size);
                in.read(reinterpret_cast<char *>(block.data()), block.size());
                const auto n = in.gcount();
                check(n > 0 && (tail || n == static_cast<std::streamsize>(ep::block_size)) && !in.bad(), "bad held-out block length");
                block.resize(static_cast<size_t>(n));
                const auto t = Clock::now();
                const auto encoded = codec.encode_block(block);
                calls += ns_since(t);
                check(encoded.size() >= header && encoded.size() <= n+header, "bad ETB1 wire length");
                write(out, encoded);
                raw += n; wire += encoded.size();
            } else {
                block.resize(header);
                check(bool(in.read(reinterpret_cast<char *>(block.data()), header)), "short ETB1 block header");
                const auto len = le(block.data()+1), n = le(block.data()+5);
                check(len > 0 && len <= ep::block_size && (tail || len == ep::block_size) && n > 0 && n <= len,
                      "bad ETB1 restored extent");
                block.resize(header+n);
                check(bool(in.read(reinterpret_cast<char *>(block.data()+header), n)), "short ETB1 block body");
                const auto t = Clock::now();
                const auto decoded = codec.decode_block(block);
                calls += ns_since(t);
                check(decoded.size() == len, "ETB1 decoded length differs");
                write(out, decoded);
                raw += len; wire += block.size();
            }
            ++blocks;
        }
        check(in.peek() == EOF && in.eof() && !in.bad(), "trailing ETB1 group bytes");
        finish(out);
    }
    report(codec, blocks, raw, wire, setup, calls, cpu);
}
}

int main(int argc, char **argv) {
    try {
        const std::string_view op = argc > 1 ? argv[1] : "";
        if (op == "train" && argc == 5) train(argv[2], argv[3], argv[4]);
        else if ((op == "encode" || op == "decode") && argc == 6)
            transfer(op == "encode", argv[2], argv[3], argv[4], parse_groups(argv[5]));
        else throw std::runtime_error("expected train STREAMS TRAIN MODEL or encode|decode MODEL INPUT OUTPUT BLOCK_COUNTS");
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "ETB1 timing: " << e.what() << '\n';
        return 1;
    }
}
