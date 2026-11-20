// Use the historically frozen ordered begin/add/finish and finalized-reader
// schedule without duplicating or modifying its implementation. Only the
// surrounding streams change (already-loaded memory instead of filesystem).
#define main tsbench_untimed_selfstar_control_main
#include "../../../plugins/codecs/selfstar-batch/corpus_control.cpp"
#undef main

#include "plugin_loader.hpp"
#include <charconv>
#include <chrono>
#include <filesystem>
#include <iomanip>
#include <sched.h>
#include <sstream>

namespace {
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
static_assert(Clock::is_steady);
constexpr size_t cap = 8 << 20;

uint64_t ns_since(Clock::time_point t) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-t).count();
}
size_t count(std::string_view text) {
    size_t n{};
    auto r = std::from_chars(text.data(), text.data()+text.size(), n);
    need(r.ec == std::errc{} && r.ptr == text.data()+text.size() && n && n <= 10000, "invalid column count");
    return n;
}
std::string name(std::string_view kind, size_t i, const char *suffix) {
    std::ostringstream s;
    s << kind << '-' << std::setfill('0') << std::setw(4) << i << suffix;
    return s.str();
}
std::string slurp(const fs::path &path) {
    std::ifstream f(path, std::ios::binary);
    const auto n = extent(f);
    need(n && n <= cap, "column input exceeds cap");
    std::string out(n, '\0');
    read(f, out.data(), n);
    need(f.peek() == EOF && !f.bad(), "changed column input");
    return out;
}
void save(const fs::path &path, const void *data, size_t n) {
    need(n && n <= cap && data, "column output exceeds cap");
    std::ofstream f(path, std::ios::binary | std::ios::trunc);
    write(f, data, n);
    f.close();
    need(f.good(), "cannot close measured output");
}
struct Redirect {
    explicit Redirect(std::ostream &target) : old(std::cout.rdbuf(target.rdbuf())) {}
    ~Redirect() { std::cout.rdbuf(old); }
    std::streambuf *old;
};
struct Obs { uint64_t setup{}, operation{}; std::string profile; };
std::string info(tsbench::Context &ctx) {
    auto b = ctx.execution_info();
    const auto &view = b->get();
    need(view.data && view.size && view.size <= 1024, "invalid public ABI observation");
    return {reinterpret_cast<const char *>(view.data), static_cast<size_t>(view.size)};
}
Obs batch(const tsbench::Module &mod, bool enc, const fs::path &in, const fs::path &out, size_t i) {
    const auto raw_name = name("column", i, ".bin");
    const auto meta_name = name("schema", i, ".json");
    const auto wire_name = name("frame", i, ".bmk");
    const auto data = slurp(in / (enc ? raw_name : wire_name));
    const auto meta = enc ? slurp(in/meta_name) : std::string{};
    auto t = Clock::now();
    tsbench::Context ctx(mod,"{}");
    Obs obs{ns_since(t), 0, {}};
    if (enc) {
        need(data.size()%8 == 0, "unaligned f64 input");
        bmk_array_view col{};
        col.struct_size=sizeof(col); col.dtype=BMK_F64; col.rank=1;
        col.storage=data.data(); col.storage_bytes=data.size();
        col.shape[0]=data.size()/8; col.strides_bytes[0]=8;
        bmk_object_view object{sizeof(object),1,&col,reinterpret_cast<const uint8_t *>(meta.data()),meta.size()};
        t=Clock::now();
        auto frame=ctx.encode(object);
        obs.operation=ns_since(t);
        save(out/wire_name,frame->get().data,frame->get().size);
    } else {
        t=Clock::now();
        auto object=ctx.decode(reinterpret_cast<const uint8_t *>(data.data()),data.size());
        obs.operation=ns_since(t);
        const auto &v=object->get();
        need(v.column_count==1 && v.columns && v.schema_json && v.schema_bytes && v.schema_bytes<=65536,
             "invalid restored object schema");
        const auto &c=v.columns[0];
        need(c.struct_size>=sizeof(c) && c.rank==1 && c.dtype==BMK_F64 && !c.flags && !c.validity &&
             !c.validity_bytes && !c.validity_bit_offset && c.strides_bytes[0]==8 && c.shape[0]>0 &&
             c.shape[0]<=cap/8 && c.storage && c.origin_offset<=c.storage_bytes && c.origin_offset<=SIZE_MAX-c.shape[0]*8 &&
             c.shape[0]*8<=c.storage_bytes-c.origin_offset, "invalid restored column geometry");
        save(out/raw_name,static_cast<const uint8_t *>(c.storage)+c.origin_offset,c.shape[0]*8);
        save(out/meta_name,v.schema_json,v.schema_bytes);
    }
    obs.profile=info(ctx);
    return obs;
}
Obs incremental(bool enc, const fs::path &in, const fs::path &out, size_t i) {
    const auto raw_name = name("column", i, ".bin");
    const auto meta_name = name("schema", i, ".json");
    const auto wire_name = name("frame", i, ".bmk");
    std::istringstream data(slurp(in/(enc ? raw_name : wire_name)),std::ios::binary);
    std::istringstream schema_in(enc ? slurp(in/meta_name) : std::string{},std::ios::binary);
    std::ostringstream output(std::ios::binary), schema_out(std::ios::binary), log;
    auto t=Clock::now();
    Context native(sf_c_create(SF_SELF_STAR,SF_F64),sf_c_destroy);
    Obs obs{ns_since(t),0,{}};
    need(bool(native),"cannot initialize incremental context");
    {
        Redirect redirect(log);
        t=Clock::now();
        if (enc) encode(data,schema_in,output,native.get());
        else decode(data,output,schema_out,native.get());
        obs.operation=ns_since(t);
    }
    auto bytes=output.str();
    save(out/(enc ? wire_name : raw_name),bytes.data(),bytes.size());
    if (!enc) {
        auto meta=schema_out.str();
        save(out/meta_name,meta.data(),meta.size());
    }
    obs.profile=log.str();
    if (!obs.profile.empty() && obs.profile.back()=='\n') obs.profile.pop_back();
    return obs;
}
}

int main(int argc,char **argv) {
    try {
        const std::string_view op=argc>1 ? argv[1] : "";
        need(argc==9 && (op=="encode" || op=="decode") && std::string_view(argv[3])=="selfstar-batch" &&
             std::string_view(argv[4])=="{}" && std::fegetround()==FE_TONEAREST,
             "expected encode|decode LIB selfstar-batch {} batch|incremental INPUT OUTPUT COLS");
        const std::string_view route=argv[5];
        need(route=="batch" || route=="incremental","invalid SElf* direction route");
        const bool live=route=="incremental", enc=op=="encode";
        const auto mod=live ? tsbench::Module{} : tsbench::PluginModule::load(argv[2],argv[3]);
        const auto cols=count(argv[8]);
        const int cpu=sched_getcpu();
        std::cout << "{\"route\":\"" << route << "\",\"columns\":[";
        for (size_t c=0;c<cols;++c) {
            auto r=live ? incremental(enc,argv[6],argv[7],c) : batch(mod,enc,argv[6],argv[7],c);
            need(!r.profile.empty() && r.profile.front()=='{' && r.profile.back()=='}',"invalid profile JSON");
            std::cout << (c ? "," : "") << "{\"column\":" << c << ",\"context_create_wall_ns\":" << r.setup
                      << ",\"direction_call_wall_ns\":" << r.operation << ",\"execution\":" << r.profile << '}';
        }
        std::cout << "],\"cpu_endpoints\":[" << cpu << ',' << sched_getcpu() << "]}\n";
        return std::cout ? 0 : 1;
    } catch (const std::exception &e) {
        std::cerr << "SElf* timing: " << e.what() << '\n';
        return 1;
    }
}
