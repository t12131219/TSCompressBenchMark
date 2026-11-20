// An equivalent public-ABI operation, with and without the production Context wrapper.
#include "plugin_loader.hpp"

#include <charconv>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <new>
#include <optional>
#include <sched.h>
#include <string>
#include <vector>

namespace {
struct Calls { size_t new_calls{}, new_bytes{}, memcpy_calls{}, memcpy_bytes{}; };
#ifdef TSBENCH_COUNT_ABI_CALLSITE
thread_local Calls *observed = nullptr;
#endif
}
#ifdef TSBENCH_COUNT_ABI_CALLSITE
extern "C" void *__real__Znwm(size_t);
extern "C" void *__wrap__Znwm(size_t n) {
    auto *p = __real__Znwm(n);
    if (observed) { ++observed->new_calls; observed->new_bytes += n; }
    return p;
}
extern "C" void *__real_memcpy(void *, const void *, size_t);
extern "C" void *__wrap_memcpy(void *dst, const void *src, size_t n) {
    auto *p = __real_memcpy(dst, src, n);
    if (observed) { ++observed->memcpy_calls; observed->memcpy_bytes += n; }
    return p;
}
#endif

namespace {
using Clock = std::chrono::steady_clock;
using Bytes = std::vector<uint8_t>;
constexpr size_t cap = 64 * 1024 * 1024 + 65536;
struct Span { int64_t ns = 0; Calls counts; };

template<class F> Span observe(F &&do_work) {
    Span span;
    const auto start = Clock::now();
#ifdef TSBENCH_COUNT_ABI_CALLSITE
    struct Guard {
        explicit Guard(Calls &row) { observed = &row; }
        ~Guard() { observed = nullptr; }
    } guard(span.counts);
#endif
    do_work();
    span.ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
    return span;
}
void require(bool value, const char *reason) { if (!value) throw std::runtime_error(reason); }
size_t number(std::string_view s) {
    size_t n{};
    const auto r = std::from_chars(s.data(), s.data() + s.size(), n);
    require(r.ec == std::errc{} && r.ptr == s.data() + s.size() && n > 0 && n <= cap, "invalid array extent");
    return n;
}
Bytes read(const char *path, size_t limit) {
    std::ifstream in(path, std::ios::ate | std::ios::binary);
    const auto n = in.tellg();
    require(n > 0 && static_cast<uint64_t>(n) <= limit, "invalid input file extent");
    Bytes out(static_cast<size_t>(n));
    in.seekg(0);
    require(bool(in.read(reinterpret_cast<char *>(out.data()), n)) && in.peek() == EOF && !in.bad(), "short or changed input file");
    return out;
}
void output(const char *path, const void *p, size_t n) {
    require(p && n && n <= cap, "invalid bounded output extent");
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out.write(static_cast<const char *>(p), static_cast<std::streamsize>(n));
    out.close();
    require(bool(out), "cannot write result");
}
void check_blob(const bmk_blob &b) {
    require(b.struct_size >= sizeof(b) && b.release && b.size <= b.capacity && (b.data || !b.size), "bad ABI frame ownership");
}
void check_object(const bmk_owned_object &o) {
    require(o.struct_size >= sizeof(o) && o.release && o.view.struct_size >= sizeof(o.view) &&
            (!o.view.column_count || o.view.columns) && (!o.view.schema_bytes || o.view.schema_json), "bad ABI restored object ownership");
}
struct Direct {
    const bmk_plugin_v1 &api;
    bmk_host_v1 host{sizeof(host), BMK_ABI_V1, nullptr, nullptr, nullptr, nullptr};
    bmk_context *ctx = nullptr;
    Direct(const bmk_plugin_v1 &api_, std::string_view opt) : api(api_) {
        const auto status = api.create(&host, reinterpret_cast<const uint8_t *>(opt.data()), opt.size(), &ctx);
        if (status != BMK_OK || !ctx) {
            if (ctx) api.destroy(ctx);
            throw std::runtime_error("ABI create failed");
        }
    }
    ~Direct() { api.destroy(ctx); }
    Direct(const Direct &) = delete;
};
struct Owners {
    bmk_blob frame{};
    bmk_owned_object values{};
    std::unique_ptr<tsbench::Blob> abi_frame;
    std::unique_ptr<tsbench::Object> abi_values;
    Owners() { frame.struct_size = sizeof(frame); values.struct_size = sizeof(values); }
    ~Owners() { release(); }
    void release() noexcept {
        if (frame.release) { frame.release(&frame); frame.release = nullptr; }
        if (values.release) { values.release(&values); values.release = nullptr; }
        abi_frame.reset(); abi_values.reset();
    }
    const bmk_blob &blob() const { return abi_frame ? abi_frame->get() : frame; }
    const bmk_object_view &view() const { return abi_values ? abi_values->get() : values.view; }
};
const uint8_t *restored(const bmk_object_view &o, const Bytes &schema, const bmk_array_view &wanted) {
    require(o.column_count == 1 && o.columns && o.schema_bytes == schema.size() && o.schema_json &&
            std::memcmp(o.schema_json, schema.data(), schema.size()) == 0, "different restored schema");
    const auto &c = o.columns[0];
    require(c.struct_size >= sizeof(c) && c.dtype == wanted.dtype && c.rank == 1 && !c.flags && !c.validity &&
            !c.validity_bytes && !c.validity_bit_offset && c.shape[0] == wanted.shape[0] && c.strides_bytes[0] == wanted.strides_bytes[0] &&
            c.storage && c.origin_offset <= c.storage_bytes && wanted.storage_bytes <= c.storage_bytes - c.origin_offset,
            "different restored typed view");
    return static_cast<const uint8_t *>(c.storage) + c.origin_offset;
}
void print(const char *name, const Span &s) {
    std::cout << ",\"" << name << "\":{";
#ifdef TSBENCH_COUNT_ABI_CALLSITE
    const auto &c = s.counts;
    std::cout << "\"wall_ns\":null,\"counts\":{\"new_calls\":" << c.new_calls << ",\"new_bytes\":" << c.new_bytes
              << ",\"memcpy_calls\":" << c.memcpy_calls << ",\"memcpy_bytes\":" << c.memcpy_bytes << "}}";
#else
    std::cout << "\"wall_ns\":" << s.ns << ",\"counts\":null}";
#endif
}

int run(char **argv) {
    const std::string_view arm(argv[1]), life(argv[2]), op(argv[3]), plugin(argv[4]), opt(argv[6]);
    const bool direct = arm == "direct", steady = life == "steady_reset", enc = op == "encode";
    require((direct || arm == "framework") && (steady || life == "cold") && (enc || op == "decode") &&
            (plugin == "raw-store" || plugin == "zstd" || plugin == "alp-auto" || plugin == "xz-baseline"), "invalid paired ABI lane");
    require(opt == "{}" || (plugin == "alp-auto" && opt == "{\"decode_backend\":\"falp-auto\"}"), "unbound options");
    const auto n = number(argv[9]);
    const auto dtype = number(argv[10]);
    require(dtype == BMK_F64 || dtype == BMK_U8, "unsupported paired dtype");
    const size_t width = dtype == BMK_F64 ? 8 : 1;
    require(n <= (64 * 1024 * 1024) / width, "paired logical extent exceeds limit");
    const auto source = read(argv[7], cap);
    const auto schema = read(argv[8], 65536);
    require(!enc || source.size() == n * width, "typed original extent differs");
    bmk_array_view col{};
    col.struct_size = sizeof(col); col.dtype = dtype; col.rank = 1;
    col.storage = enc ? source.data() : nullptr; col.storage_bytes = n * width;
    col.shape[0] = n; col.strides_bytes[0] = static_cast<int64_t>(width);
    const bmk_object_view input{sizeof(input), 1, &col, schema.data(), schema.size()};
    const auto module = tsbench::PluginModule::load(argv[5], plugin);
    std::optional<Direct> plain;
    std::optional<tsbench::Context> framework;
    const auto create = [&] { if (direct) plain.emplace(module->api(), opt); else framework.emplace(module, opt); };
    const auto reset = [&] {
        if (direct) require(plain->api.reset(plain->ctx, 0) == BMK_OK, "ABI reset failed");
        else framework->reset(0);
    };
    const auto step = [&](Owners &out) {
        if (direct) {
            if (enc) { require(plain->api.encode(plain->ctx, &input, &out.frame) == BMK_OK, "direct ABI encode failed"); check_blob(out.frame); }
            else { require(plain->api.decode(plain->ctx, source.data(), source.size(), &out.values) == BMK_OK, "direct ABI decode failed"); check_object(out.values); }
        } else if (enc) { out.abi_frame = framework->encode(input); }
        else { out.abi_values = framework->decode(source.data(), source.size()); }
    };
    if (steady) {
        create();
        Owners warm;
        step(warm);
        if (!enc) (void) restored(warm.view(), schema, col);
    }
    Owners measured;
    const int start_cpu = sched_getcpu();
    const auto prepare = observe([&] { if (steady) reset(); else create(); });
    const auto codec = observe([&] { step(measured); });
    const int end_cpu = sched_getcpu();
    // Result-ready ends before verification/serialization. Both operations
    // publish the actual measured product for external SHA/byte checks.
    const size_t result_bytes = enc ? measured.blob().size : col.storage_bytes;
    const auto *p = enc ? measured.blob().data : restored(measured.view(), schema, col);
    const size_t capacity = enc ? measured.blob().capacity : measured.view().columns[0].storage_bytes;
    output(argv[11], p, result_bytes);
    const auto free_result = observe([&] { measured.release(); });
    Owners info;
    if (direct) {
        require(plain->api.execution_info(plain->ctx, &info.frame) == BMK_OK, "ABI execution info missing");
        check_blob(info.frame);
    } else { info.abi_frame = framework->execution_info(); }
    const auto &meta = info.blob();
    require(meta.size && meta.size < 65536, "invalid ABI execution info extent");
    const std::string details(reinterpret_cast<const char *>(meta.data), meta.size);
    info.release();
    const auto destroy = observe([&] { plain.reset(); framework.reset(); });
    std::cout << "{\"arm\":\"" << arm << "\",\"lifecycle\":\"" << life << "\",\"direction\":\"" << op
              << "\",\"cpu_endpoints\":[" << start_cpu << ',' << end_cpu << "],\"logical_bytes\":" << col.storage_bytes
              << ",\"input_bytes\":" << source.size() << ",\"output_bytes\":" << result_bytes << ",\"capacity_bytes\":" << capacity
              << ",\"protocol\":{\"create\":1,\"reset\":" << (steady ? 1 : 0) << ",\"warmup\":" << (steady ? 1 : 0)
              << ",\"operation\":1,\"measured_output_release\":1,\"info\":1,\"destroy\":1},\"execution_info\":" << details;
    print("prepare", prepare); print("result_ready", codec); print("release", free_result); print("destroy", destroy);
    std::cout << "}\n";
    return std::cout ? 0 : 1;
}
}
int main(int argc, char **argv) {
    try { require(argc == 12, "usage: arm lifecycle direction plugin library options input schema rows dtype output"); return run(argv); }
    catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
