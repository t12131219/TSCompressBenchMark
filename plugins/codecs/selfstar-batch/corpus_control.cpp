// Corpus-sized BMKSEL controller. I/O is block-bounded; native state is not.
#include "selfstar.h"

#include <algorithm>
#include <array>
#include <cfenv>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

namespace {
constexpr size_t block = 512, prefix = 4, header = 32, workspace = 25000;
constexpr size_t max_rows = 64 * 1024 * 1024 / 8, schema_limit = 65536;
constexpr std::array<uint8_t, 8> magic{'B','M','K','S','E','L',1,0};
constexpr std::array<size_t, 5> adds{1, 7, 63, 121, block};
static_assert(sizeof(double) == 8);
using Context = std::unique_ptr<sf_c, decltype(&sf_c_destroy)>;
void need(bool ok, const char *msg) { if (!ok) throw std::runtime_error(msg); }
void native(sf_status status, const char *operation) {
    if (status != SF_OK) throw std::runtime_error(std::string(operation) + ": " + sf_status_string(status));
}
void read(std::istream &in, void *p, size_t n) {
    need(bool(in.read(static_cast<char *>(p), n)), "truncated input");
}
void write(std::ostream &out, const void *p, size_t n) {
    need(bool(out.write(static_cast<const char *>(p), n)), "write failed");
}
void put(uint8_t *p, size_t n, uint64_t value) {
    for (size_t i = 0; i < n; ++i) p[i] = static_cast<uint8_t>(value >> (8*i));
}
uint64_t get(const uint8_t *p, size_t n) {
    uint64_t v = 0;
    for (size_t i = 0; i < n; ++i) v |= uint64_t(p[i]) << (8*i);
    return v;
}
size_t limit(size_t n) { return (n + 1)*92 + 395; }
size_t bytes(size_t bits) { return (bits + 7)/8; }
size_t blocks(size_t n) { return (n + block - 1)/block; }
size_t extent(std::istream &in) {
    in.seekg(0, std::ios::end);
    const auto size = in.tellg();
    need(size >= 0, "cannot read extent");
    in.seekg(0);
    return static_cast<size_t>(size);
}
void progress(sf_c *ctx, size_t n, size_t minimum, int phase, size_t &bits) {
    sf_progress p{};
    native(sf_c_progress(ctx, &p), "progress");
    need(p.count == n && p.bits >= minimum && p.phase == phase && !p.deferred_values, "unexpected SElf* progress");
    bits = p.bits;
}
struct Counts {
    size_t rows{}, blocks{}, bits{}, data{}, calls{}, prefinish{};
    void print(const char *mode) const {
        std::cout << "{\"mode\":\"" << mode << "\",\"rows\":" << rows << ",\"blocks\":" << blocks
                  << ",\"native_bits\":" << bits << ",\"native_payload_bytes\":" << data
                  << ",\"add_calls\":" << calls << ",\"prefinish_bits\":" << prefinish << "}\n";
    }
};
void encode(std::istream &raw, std::istream &schema_in, std::ostream &out, sf_c *codec) {
    const auto raw_bytes = extent(raw), schema_size = extent(schema_in);
    need(raw_bytes && raw_bytes % sizeof(double) == 0 && raw_bytes/8 <= max_rows && schema_size <= schema_limit,
         "input extent outside contract");
    const auto rows = raw_bytes/8;
    std::string schema(schema_size, '\0');
    read(schema_in, schema.data(), schema.size());
    std::array<uint8_t,header> h{};
    std::copy(magic.begin(), magic.end(), h.begin());
    put(h.data()+8, 4, 10); put(h.data()+12, 8, rows); put(h.data()+20, 4, schema_size);
    write(out, h.data(), h.size()); write(out, schema.data(), schema.size());
    std::array<double,block> values{};
    std::array<uint8_t,workspace> wire{};
    Counts c{rows, blocks(rows)};
    for (size_t start = 0; start < rows; start += block) {
        const auto n = std::min(block, rows-start);
        read(raw, values.data(), n*8);
        wire.fill(0);
        native(sf_c_begin(codec, wire.data(), bytes(limit(n))), "begin");
        size_t last{};
        progress(codec, 0, 0, 1, last);
        need(last == 0, "nonempty begin progress");
        for (size_t i = 0, k = 0; i < n; ++k) {
            const auto take = std::min(adds.at(k), n-i);
            native(sf_c_add(codec, values.data()+i, take), "add");
            i += take; ++c.calls;
            progress(codec, i, last+1, 1, last);
        }
        c.prefinish += last;
        size_t bits{}, done{};
        native(sf_c_finish(codec, &bits), "finish");
        progress(codec, n, last+1, 0, done);
        need(bits == done && bits <= limit(n), "finished bits outside bounds");
        std::array<uint8_t,prefix> tag{};
        put(tag.data(), tag.size(), bits);
        write(out, tag.data(), tag.size()); write(out, wire.data(), bytes(bits));
        c.bits += bits; c.data += bytes(bits);
    }
    need(raw.peek() == EOF && !raw.bad(), "trailing raw input");
    put(h.data()+24, 8, c.data+c.blocks*prefix);
    out.seekp(0); write(out, h.data(), h.size()); out.flush();
    need(bool(out), "encode flush failed");
    c.print("live");
}
void decode(std::istream &input, std::ostream &out, std::ostream &schema, sf_c *codec) {
    const size_t total = extent(input);
    std::array<uint8_t,header> h{};
    read(input, h.data(), h.size());
    const auto rows = get(h.data()+12,8), schema_size = get(h.data()+20,4), payload = get(h.data()+24,8);
    need(std::equal(magic.begin(), magic.end(), h.begin()) && get(h.data()+8,4) == 10 && rows && rows <= max_rows &&
         schema_size <= schema_limit && schema_size <= total-header && payload == total-header-schema_size,
         "bad frame header");
    std::string metadata(schema_size, '\0');
    read(input, metadata.data(), metadata.size());
    write(schema, metadata.data(), metadata.size());
    std::array<double,block> values{};
    std::array<uint8_t,workspace> wire{};
    Counts c{static_cast<size_t>(rows), blocks(rows)};
    for (size_t start = 0; start < rows; start += block) {
        const auto n = std::min<uint64_t>(block, rows-start);
        std::array<uint8_t,prefix> tag{};
        read(input, tag.data(), tag.size());
        const auto bits = get(tag.data(), tag.size());
        need(bits && bits <= limit(n), "invalid block bit extent");
        read(input, wire.data(), bytes(bits));
        need(bits%8 == 0 || (wire[bytes(bits)-1] & ((1u << (8-bits%8))-1)) == 0, "nonzero pad bits");
        native(sf_c_read_begin(codec, wire.data(), bytes(bits), bits, n), "read_begin");
        int has = -1;
        for (size_t i = 0; i < n; ++i) {
            native(sf_c_next(codec, values.data()+i, &has), "next");
            need(has == 1, "short native block");
        }
        size_t before{}, after{};
        progress(codec, n, 0, 2, before);
        double ignored{};
        native(sf_c_next(codec, &ignored, &has), "drain");
        progress(codec, n, bits, 0, after);
        need(has == 0 && before < bits && after == bits, "bad sentinel drain");
        write(out, values.data(), n*8);
        c.bits += bits; c.data += bytes(bits);
    }
    need(c.data+c.blocks*prefix == payload && input.peek() == EOF && !input.bad(), "trailing frame bytes");
    out.flush(); schema.flush();
    need(bool(out) && bool(schema), "decode flush failed");
    c.print("read-finalized");
}
}
int main(int argc, char **argv) {
    try {
        need(argc == 5 && std::fegetround() == FE_TONEAREST, "expected live RAW SCHEMA FRAME or read-finalized FRAME RAW SCHEMA");
        const std::string op = argv[1];
        need(op == "live" || op == "read-finalized", "unknown corpus operation");
        Context codec(sf_c_create(SF_SELF_STAR, SF_F64), sf_c_destroy);
        need(bool(codec), "cannot create native context");
        std::ifstream input(argv[2], std::ios::binary);
        if (op == "live") {
            std::ifstream schema(argv[3], std::ios::binary);
            std::ofstream out(argv[4], std::ios::binary);
            encode(input, schema, out, codec.get());
        } else {
            std::ofstream out(argv[3], std::ios::binary), schema(argv[4], std::ios::binary);
            decode(input, out, schema, codec.get());
        }
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 2; }
}
