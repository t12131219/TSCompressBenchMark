// Detached, directional ABI calls. File groups bound I/O only: they do not
// change native frame geometry, context lifetimes or charged archive bytes.
#include "plugin_loader.hpp"

#include <algorithm>
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
using Bytes = std::vector<uint8_t>;
using Clock = std::chrono::steady_clock;
static_assert(Clock::is_steady);
constexpr size_t unit = 65536, schema_cap = 256, file_cap = 8 << 20, envelope = 32;
constexpr char sprintz_magic[] = "BMKSPR\1\0", huff0_magic[] = "BMKHUF\1\0";

void require(bool ok, const char *reason) {
    if (!ok) throw std::runtime_error(reason);
}
size_t count(std::string_view text) {
    size_t n{};
    auto r = std::from_chars(text.data(), text.data() + text.size(), n);
    require(r.ec == std::errc{} && r.ptr == text.data() + text.size() && n > 0 && n <= 50000, "invalid group count");
    return n;
}
uint64_t read_le(const uint8_t *p, size_t n) {
    uint64_t value = 0;
    for (size_t i = 0; i < n; ++i) value |= uint64_t(p[i]) << (8 * i);
    return value;
}
void write(std::ofstream &out, const void *p, size_t n) {
    require(p && bool(out.write(static_cast<const char *>(p), static_cast<std::streamsize>(n))), "cannot write result");
}
void write_lengths(std::ofstream &out, size_t raw, size_t schema) {
    uint8_t header[8];
    for (size_t i = 0; i < 4; ++i) {
        header[i] = (raw >> (8*i)) & 255;
        header[i+4] = (schema >> (8*i)) & 255;
    }
    write(out, header, sizeof(header));
}
std::string name(size_t group) {
    std::ostringstream text;
    text << 'g' << std::setfill('0') << std::setw(5) << group << ".bin";
    return text.str();
}
Bytes read_file(const std::filesystem::path &path) {
    std::ifstream in(path, std::ios::binary|std::ios::ate);
    auto n = in.tellg();
    require(n > 0 && n <= static_cast<std::streamoff>(file_cap), "invalid bounded group input size");
    Bytes buffer(static_cast<size_t>(n));
    in.seekg(0);
    require(bool(in.read(reinterpret_cast<char *>(buffer.data()), n)) && in.peek() == EOF && !in.bad(), "input changed or was truncated");
    return buffer;
}
uint64_t elapsed(Clock::time_point start) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
}
struct Geometry { size_t raw, schema, frame; };
Geometry shape(const uint8_t *p, size_t left, const char *magic, uint32_t dtype, size_t width) {
    require(left >= envelope && std::memcmp(p, magic, 8) == 0 && read_le(p + 8, 4) == static_cast<uint64_t>(dtype),
            "invalid ABI envelope kind");
    const uint64_t count = read_le(p + 12, 8), schema = read_le(p + 20, 4), payload = read_le(p + 24, 8);
    require(count && count <= unit / width && schema && schema <= schema_cap && payload && payload <= 4 * unit + 64 &&
            schema + payload <= left - envelope, "invalid ABI envelope geometry");
    return {static_cast<size_t>(count) * width, static_cast<size_t>(schema), static_cast<size_t>(envelope + schema + payload)};
}
const uint8_t *restored(const bmk_object_view &view, const uint8_t *schema, Geometry g, uint32_t dtype, size_t width) {
    require(view.column_count == 1 && view.columns && view.schema_json && view.schema_bytes == g.schema &&
            std::memcmp(view.schema_json, schema, g.schema) == 0, "restored ABI schema differs");
    const auto &c = view.columns[0];
    require(c.struct_size >= sizeof(c) && c.dtype == dtype && c.rank == 1 && !c.flags && !c.validity && !c.validity_bytes &&
            !c.validity_bit_offset && c.shape[0] == g.raw / width && c.strides_bytes[0] == static_cast<int64_t>(width) &&
            c.storage && c.origin_offset <= c.storage_bytes && g.raw <= c.storage_bytes - c.origin_offset &&
            c.origin_offset <= SIZE_MAX - g.raw, "invalid restored ABI column");
    return static_cast<const uint8_t *>(c.storage) + c.origin_offset;
}

int run(bool encode, std::string_view plugin, const char *library, const char *input, const char *output, size_t groups) {
    const bool sprintz = plugin == "sprintz-fire";
    require(sprintz || plugin == "huff0-reference", "unbound ABI codec");
    const auto dtype = sprintz ? BMK_U16 : BMK_U8;
    const size_t width = sprintz ? 2 : 1, alignment = sprintz ? 8 : 1;
    const char *magic = sprintz ? sprintz_magic : huff0_magic;
    auto module = tsbench::PluginModule::load(library, plugin);
    uint64_t context_ns = 0, operation_ns = 0;
    size_t frames = 0, raw_bytes = 0, archive_bytes = 0;
    const auto cpu_before = sched_getcpu();
    std::map<std::string, size_t> modes;
    for (size_t group = 0; group < groups; ++group) {
        const auto buffer = read_file(std::filesystem::path(input) / name(group));
        std::ofstream out(std::filesystem::path(output) / name(group), std::ios::binary | std::ios::trunc);
        require(bool(out), "cannot create output group");
        size_t pos = 0;
        while (pos < buffer.size()) {
            const auto *p = buffer.data() + pos;
            const size_t left = buffer.size() - pos;
            const auto started = Clock::now();
            tsbench::Context ctx(module, "{}");
            context_ns += elapsed(started);
            if (encode) {
                require(left >= 8, "truncated staging record");
                const size_t n = read_le(p, 4), s = read_le(p+4, 4);
                require(n && n <= unit && n % alignment == 0 && s && s <= schema_cap && n+s <= left-8,
                        "invalid staging geometry");
                bmk_array_view c{};
                c.struct_size = sizeof(c); c.dtype = dtype; c.rank = 1;
                c.storage = p+8+s; c.storage_bytes = n; c.shape[0] = n/width; c.strides_bytes[0] = width;
                const bmk_object_view v{sizeof(v), 1, &c, p+8, s};
                const auto tick = Clock::now();
                const auto result = ctx.encode(v);
                operation_ns += elapsed(tick);
                const auto &frame = result->get();
                require(frame.data && frame.size <= file_cap, "invalid returned frame");
                const auto g = shape(frame.data, frame.size, magic, dtype, width);
                require(g.frame == frame.size && g.raw == n && g.schema == s && std::memcmp(frame.data + envelope, p+8, s) == 0,
                        "emitted frame geometry or schema differs");
                write(out, frame.data, frame.size);
                pos += 8+s+n; raw_bytes += n; archive_bytes += frame.size;
            } else {
                const auto g = shape(p, left, magic, dtype, width);
                require(g.raw % alignment == 0, "invalid ABI value alignment");
                const auto tick = Clock::now();
                const auto result = ctx.decode(p, g.frame);
                operation_ns += elapsed(tick);
                const auto *data = restored(result->get(), p+envelope, g, dtype, width);
                write_lengths(out, g.raw, g.schema);
                write(out, p+envelope, g.schema);
                write(out, data, g.raw);
                pos += g.frame; raw_bytes += g.raw; archive_bytes += g.frame;
            }
            const auto info = ctx.execution_info();
            const auto &blob = info->get();
            require(blob.data && blob.size > 2 && blob.size <= 1024 && blob.data[0] == '{' && blob.data[blob.size-1] == '}',
                    "invalid ABI execution observation");
            ++modes[{reinterpret_cast<const char *>(blob.data), static_cast<size_t>(blob.size)}];
            ++frames;
        }
        out.close();
        require(out.good(), "cannot close bounded result group");
    }
    std::cout << "{\"groups\":" << groups << ",\"frames\":" << frames << ",\"raw_bytes\":" << raw_bytes
              << ",\"archive_bytes\":" << archive_bytes << ",\"abi_wall_ns\":" << operation_ns
              << ",\"context_create_wall_ns\":" << context_ns << ",\"cpu_endpoints\":[" << cpu_before << ',' << sched_getcpu()
              << "],\"execution_census\":[";
    bool first = true;
    for (auto &[key, n] : modes) {
        std::cout << (first ? "" : ",") << "{\"count\":" << n << ",\"info\":" << key << '}';
        first = false;
    }
    std::cout << "]}\n";
    return std::cout ? 0 : 1;
}
}

int main(int argc, char **argv) {
    try {
        const std::string_view op = argc > 1 ? argv[1] : "";
        require(argc == 8 && std::string_view(argv[4]) == "{}" && (op == "encode" || op == "decode"), "expected encode|decode LIB PLUGIN OPTIONS INPUT OUTPUT GROUPS");
        return run(op == "encode", argv[3], argv[2], argv[5], argv[6], count(argv[7]));
    } catch (const std::exception &e) {
        std::cerr << "ABI corpus: " << e.what() << '\n';
        return 1;
    }
}
