// Whole-file fixed-batch diagnostics. Group I/O is outside each native ABI span.
// Each call retains the frozen 65,536-row or 65,536-byte geometry and a fresh context.
#include "plugin_loader.hpp"

#include <charconv>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sched.h>
#include <sstream>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;
using Bytes = std::vector<uint8_t>;
using Count = uint64_t;
constexpr size_t cap = 8 << 20, schema_cap = 256, header = 32;
struct Route { std::string_view id; const char *magic; uint32_t dtype; size_t width; };
constexpr Route routes[] = {
    {"pcodec-source-auto", "BMKPCS\1\0", BMK_F64, 8},
    {"pcodec-c-native-auto", "BMKPCN\1\0", BMK_F64, 8},
    {"zstd", "BMKZST\1\0", BMK_U8, 1},
    {"xz-baseline", "BMKXZ\0\1\0", BMK_U8, 1},
};
static_assert(Clock::is_steady);

void need(bool ok, const char *why) {
    if (!ok) throw std::runtime_error(why);
}
Count since(Clock::time_point start) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
}
uint64_t read_le(const uint8_t *p, size_t bytes) {
    uint64_t v = 0;
    for (size_t i = 0; i < bytes; ++i) v |= uint64_t(p[i]) << (8*i);
    return v;
}
Bytes load(const std::filesystem::path &path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    const auto length = in.tellg();
    need(length > 0 && length <= static_cast<std::streamoff>(cap), "invalid group size");
    Bytes data(static_cast<size_t>(length));
    in.seekg(0);
    need(bool(in.read(reinterpret_cast<char *>(data.data()), length)) && in.peek() == EOF && !in.bad(), "unstable input group");
    return data;
}
void write(std::ofstream &out, const void *p, size_t n, size_t &budget) {
    need(p && n <= budget && bool(out.write(static_cast<const char *>(p), n)), "invalid or oversized group output");
    budget -= n;
}
std::string filename(size_t index) {
    std::ostringstream out;
    out << 'g' << std::setfill('0') << std::setw(5) << index << ".bin";
    return out.str();
}
struct Geometry { size_t raw, schema, frame; };
Geometry frame_geometry(const uint8_t *p, size_t remaining, const Route &route) {
    need(p && remaining >= header && std::memcmp(p, route.magic, 8) == 0 &&
         read_le(p+8, 4) == route.dtype, "wrong fixed batch envelope");
    const auto count = read_le(p+12, 8), schema = read_le(p+20, 4), payload = read_le(p+24, 8);
    need(count && count <= 65536 && schema && schema <= schema_cap && payload &&
         schema <= remaining-header && payload <= remaining-header-schema, "invalid fixed batch geometry");
    return {size_t(count*route.width), size_t(schema), size_t(header+schema+payload)};
}
const void *restored(const bmk_object_view &o, const Route &route, const uint8_t *schema, Geometry g) {
    need(o.column_count == 1 && o.columns && o.schema_json && o.schema_bytes == g.schema &&
         std::memcmp(o.schema_json, schema, g.schema) == 0, "restored schema differs");
    const auto &c = o.columns[0];
    need(c.struct_size >= sizeof(c) && c.dtype == route.dtype && c.rank == 1 && c.flags == 0 && !c.validity && !c.validity_bytes &&
         !c.validity_bit_offset && c.shape[0] == g.raw/route.width && c.strides_bytes[0] == static_cast<int64_t>(route.width) && c.storage &&
         c.origin_offset <= c.storage_bytes && g.raw <= c.storage_bytes - c.origin_offset && c.origin_offset <= SIZE_MAX - g.raw,
         "restored typed column differs");
    return static_cast<const uint8_t *>(c.storage) + c.origin_offset;
}

int run(std::string_view op, const char *library, std::string_view plugin, std::string_view options,
        const std::filesystem::path &input, const std::filesystem::path &output, size_t groups) {
    const bool encode = op == "encode";
    const Route *chosen = nullptr;
    for (const auto &route : routes) if (route.id == plugin) chosen = &route;
    need(chosen && (op == "decode" || encode) && options == "{}", "unbound operation, codec or options");
    const auto &route = *chosen;
    const auto module = tsbench::PluginModule::load(library, plugin);
    Count frames = 0, raw = 0, archive = 0, operation = 0, create = 0;
    std::map<std::string, size_t> observations;
    const int first_cpu = sched_getcpu();
    for (size_t i = 0; i < groups; ++i) {
        const auto data = load(input / filename(i));
        std::ofstream out(output / filename(i), std::ios::binary | std::ios::trunc);
        need(bool(out), "cannot write output group");
        size_t left_out = cap;
        for (size_t pos = 0; pos != data.size();) {
            const auto *p = data.data() + pos;
            const size_t left = data.size() - pos;
            const auto tick_create = Clock::now();
            tsbench::Context ctx(module, options);
            create += since(tick_create);
            Geometry g{};
            if (encode) {
                need(left >= 8, "truncated staging record");
                const size_t n = read_le(p, 4), s = read_le(p+4, 4);
                need(n && n <= 65536*route.width && n%route.width == 0 && s && s <= schema_cap && n+s <= left-8, "invalid staging geometry");
                // Group serialization is not required to align the typed column.
                std::vector<uint64_t> values((n+7)/8);
                std::memcpy(values.data(), p+8+s, n);
                bmk_array_view col{};
                col.struct_size = sizeof(col); col.dtype = route.dtype; col.rank = 1; col.shape[0] = n/route.width;
                col.strides_bytes[0] = route.width; col.storage = values.data(); col.storage_bytes = n;
                const bmk_object_view view{sizeof(view), 1, &col, p+8, s};
                const auto tick = Clock::now();
                const auto result = ctx.encode(view);
                operation += since(tick);
                const auto &f = result->get();
                need(f.size <= cap, "oversized returned frame");
                g = frame_geometry(f.data, f.size, route);
                need(g.frame == f.size && g.raw == n && g.schema == s && std::memcmp(f.data+header, p+8, s) == 0,
                     "encoded column layout differs");
                write(out, f.data, f.size, left_out);
                pos += 8+s+n;
            } else {
                g = frame_geometry(p, left, route);
                const auto tick = Clock::now();
                const auto result = ctx.decode(p, g.frame);
                operation += since(tick);
                const auto *bits = restored(result->get(), route, p+header, g);
                uint8_t lengths[8];
                for (size_t j = 0; j < 4; ++j) {
                    lengths[j] = uint8_t(g.raw >> (8*j));
                    lengths[j+4] = uint8_t(g.schema >> (8*j));
                }
                write(out, lengths, sizeof(lengths), left_out);
                write(out, p+header, g.schema, left_out);
                write(out, bits, g.raw, left_out);
                pos += g.frame;
            }
            const auto info = ctx.execution_info();
            const auto &b = info->get();
            need(b.data && b.size > 2 && b.size <= 1024 && b.data[0]=='{' && b.data[b.size-1]=='}', "invalid native execution info");
            ++observations[{reinterpret_cast<const char *>(b.data), size_t(b.size)}];
            ++frames; raw += g.raw; archive += g.frame;
        }
        out.close();
        need(out.good(), "cannot close output group");
    }
    std::cout << "{\"groups\":" << groups << ",\"frames\":" << frames << ",\"raw_bytes\":" << raw << ",\"archive_bytes\":" << archive
              << ",\"abi_wall_ns\":" << operation << ",\"context_create_wall_ns\":" << create << ",\"cpu_endpoints\":["
              << first_cpu << ',' << sched_getcpu() << "],\"execution_census\":[";
    const char *sep = "";
    for (const auto &[info, n] : observations) {
        std::cout << sep << "{\"count\":" << n << ",\"info\":" << info << '}';
        sep = ",";
    }
    std::cout << "]}\n";
    return std::cout ? 0 : 1;
}
}

int main(int argc, char **argv) {
    try {
        need(argc == 8, "expected OP LIB PLUGIN OPTIONS IN OUT GROUPS");
        std::string_view text(argv[7]);
        size_t groups = 0;
        const auto end = text.data()+text.size();
        const auto n = std::from_chars(text.data(), end, groups);
        need(n.ec == std::errc{} && n.ptr == end && groups > 0 && groups <= 50000, "invalid group count");
        return run(argv[1], argv[2], argv[3], argv[4], argv[5], argv[6], groups);
    } catch (const std::exception &err) {
        std::cerr << "fixed batch: " << err.what() << '\n';
        return 1;
    }
}
