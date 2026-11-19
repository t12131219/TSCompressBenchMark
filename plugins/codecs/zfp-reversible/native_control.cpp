// Direct control over the frozen native ABI. Only accept bounded fixtures and trusted frames.
#include "zfp_native.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
constexpr size_t limit = 1 << 20;
void require(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }
void ok(zn_status status) { require(status == ZN_OK, zn_error(status)); }
using Context = std::unique_ptr<zn_context, decltype(&zn_destroy)>;
using Array = std::unique_ptr<zn_array, decltype(&zn_array_destroy)>;
template<class T> std::vector<T> read(const char* path) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    const auto n = f.tellg();
    require(n > 0 && size_t(n) <= limit && size_t(n) % sizeof(T) == 0, "unexpected fixture size");
    std::vector<T> data(size_t(n) / sizeof(T));
    f.seekg(0);
    require(bool(f.read(reinterpret_cast<char*>(data.data()), n)) && f.peek() == EOF, "could not read fixture");
    return data;
}
void save(const char* path, const void* data, size_t bytes) {
    require(data && bytes && bytes <= limit, "unexpected output size");
    std::ofstream f(path, std::ios::binary);
    require(bool(f.write(static_cast<const char*>(data), bytes)), "could not write output");
    f.close();
    require(bool(f), "could not close output");
}
struct Field {
    zn_config cfg{};
    zn_options options = zn_defaults();
    size_t origin{}, span{};
};
Field field_spec(const char* path) {
    auto text = read<char>(path);
    require(text.size() <= 256, "field metadata too large");
    std::ifstream s(path);
    std::string magic;
    unsigned type{}, mode{};
    Field f;
    s >> magic >> type >> f.cfg.dims >> mode >> f.cfg.parameter;
    require(bool(s) && magic == "ZNFIELD1" && type >= 1 && type <= 4 && mode <= 3 &&
            f.cfg.dims >= 1 && f.cfg.dims <= 4, "invalid field metadata");
    f.cfg.type = static_cast<zn_type>(type);
    f.cfg.mode = static_cast<zn_mode>(mode);
    for (size_t& n : f.cfg.size) { s >> n; require(n && n <= 8192, "invalid field axis"); }
    for (auto& stride : f.options.stride) { s >> stride; require(stride >= -8192 && stride <= 8192, "invalid field stride"); }
    s >> f.origin >> f.span;
    require(bool(s) && f.span <= limit / 8 && f.origin < f.span && !(s >> magic), "invalid field span metadata");
    return f;
}
int reject_field(zn_config cfg, zn_options opts) {
    zn_context* p = nullptr;
    const auto st = zn_create_ex(&cfg, &opts, &p);
    Context handle(p, zn_destroy);
    require(!p && st == ZN_INVALID, "invalid field config reached allocation or was accepted");
    return st;
}
void field_controls() {
    auto cfg = zn_config_1d(ZN_I32, 5);
    auto opts = zn_defaults();
    cfg.mode = ZN_ACCURACY;
    cfg.parameter = .1;
    const auto accuracy = reject_field(cfg, opts);
    cfg = zn_config_1d(ZN_F32, 5);
    cfg.mode = ZN_PRECISION;
    cfg.parameter = 33;
    const auto precision = reject_field(cfg, opts);
    cfg = zn_config_1d(ZN_F64, 5);
    cfg.dims = 2;
    cfg.size[1] = 5;
    opts.stride[0] = opts.stride[1] = 1;
    const auto overlap = reject_field(cfg, opts);
    cfg = zn_config_1d(ZN_F64, 5);
    cfg.mode = ZN_RATE;
    cfg.parameter = 16;
    opts = zn_defaults();
    opts.execution = ZN_CUDA;
    const auto cuda = reject_field(cfg, opts);
    std::cout << ",\"invalid_configs\":{\"integer_accuracy\":" << accuracy << ",\"precision_above_width\":" << precision
              << ",\"overlap\":" << overlap << ",\"cuda_cpu_build\":" << cuda << "},\"cuda_built\":" << zn_cuda_built();
}
template<class T> void field(const Field& f, const char* path, bool encode, bool controls) {
    zn_context* p = nullptr;
    ok(zn_create_ex(&f.cfg, &f.options, &p));
    Context handle(p, zn_destroy);
    zn_info info{};
    ok(zn_get_info(p, &info));
    require(info.logical_bytes <= f.span * sizeof(T), "field logical extent exceeds span");
    std::cout << "{\"mode\":" << info.config.mode << ",\"rank\":" << info.config.dims
              << ",\"type\":" << info.config.type << ",\"requested\":" << info.config.parameter
              << ",\"effective\":" << info.effective_parameter << ",\"logical_bytes\":" << info.logical_bytes
              << ",\"strides\":[";
    for (unsigned i = 0; i < info.config.dims; ++i) std::cout << (i ? "," : "") << info.options.stride[i];
    std::cout << "],\"offset_bounds\":[" << info.min_offset << ',' << info.max_offset << ']'
              << ",\"decode_execution\":" << info.decode_execution;
    if (encode) {
        auto data = read<T>(path);
        require(data.size() == f.span, "wrong input span count");
        size_t used = std::numeric_limits<size_t>::max();
        const auto bad = zn_encode_field(p, data.data(), data.size()*sizeof(T), info.min_offset < 0 ? 0 : f.span, &used);
        require(bad == ZN_INVALID && used == 0, "invalid origin was accepted");
        ok(zn_encode_field(p, data.data(), data.size()*sizeof(T), f.origin, &used));
        require(used && used <= zn_capacity(p) && used % 8 == 0, "unexpected ZFP encoded size");
        save("frame", zn_data(p), used);
        std::cout << ",\"bad_origin_status\":" << bad << ",\"written\":" << used;
        if (controls) field_controls();
    } else {
        auto wire = read<unsigned char>(path);
        require(wire.size() % 8 == 0 && wire.size() <= zn_capacity(p), "unexpected ZFP trusted frame extent");
        auto dst = std::vector<T>(f.span, T(8191));
        ok(zn_decode_field(p, wire.data(), wire.size(), dst.data(), dst.size()*sizeof(T), f.origin));
        save("span", dst.data(), dst.size()*sizeof(T));
        std::cout << ",\"status\":0";
    }
    std::cout << "}\n";
}
struct ArraySpec {
    zn_config cfg;
    double effective;
};
ArraySpec array_spec(const char* path) {
    require(read<char>(path).size() <= 128, "array metadata too large");
    std::ifstream s(path);
    std::string magic;
    size_t n = 0;
    double requested = 0, effective = 0;
    s >> magic >> n >> requested >> effective;
    require(bool(s) && magic == "ZNARRAY1" && n == 13 && requested == 18 && effective == 32 && !(s >> magic),
            "unexpected array metadata");
    auto cfg = zn_config_1d(ZN_F64, n);
    cfg.mode = ZN_RATE;
    cfg.parameter = requested;
    return {cfg,effective};
}
std::vector<unsigned char> export_array(zn_array* p) {
    auto n = zn_array_compressed_size(p);
    require(n == 64, "unexpected aligned array extent");
    auto bytes = std::vector<unsigned char>(n);
    size_t used = 0;
    ok(zn_array_export(p, bytes.data(), n, &used));
    require(used == n, "array export count differs");
    return bytes;
}
double get(zn_array* p,size_t i) { double v; ok(zn_array_get(p,i,&v)); return v; }
void array_update(ArraySpec s,const char* initial,const char* patch) {
    auto data = read<double>(initial), changes = read<double>(patch);
    require(data.size()==s.cfg.size[0] && changes.size()==5,"unexpected update fixture");
    zn_array* p = nullptr;
    ok(zn_array_create(&s.cfg,data.data(),data.size()*8,&p));
    Array handle(p,zn_array_destroy);
    require(zn_array_count(p)==data.size() && zn_array_rate(p)==s.effective && zn_array_cache_size(p)==0,
            "unexpected initial array configuration");
    auto before = export_array(p);
    ok(zn_array_set(p,1,changes.data()));
    const auto cached = get(p,1);
    const auto populated = zn_array_cache_size(p);
    (void)get(p,data.size()-1); // Touch a different block to evict the first dirty block.
    const auto evicted = get(p,1);
    ok(zn_array_set_range(p,3,4,changes.data()+1,32));
    const auto range_tail = get(p,6);
    ok(zn_array_set_cache_size(p,16384));
    const auto resized = zn_array_cache_size(p);
    (void)get(p,3);
    const auto repopulated = zn_array_cache_size(p);
    ok(zn_array_flush_cache(p));
    const auto flushed = zn_array_cache_size(p);
    double value;
    const double nan = std::numeric_limits<double>::quiet_NaN();
    std::array<double,2> scratch{};
    const auto point_oob = zn_array_get(p,data.size(),&value);
    const auto nonfinite = zn_array_set(p,1,&nan);
    const auto range_oob = zn_array_get_range(p,data.size()-1,2,scratch.data(),sizeof scratch);
    ok(zn_array_flush(p));
    size_t used = std::numeric_limits<size_t>::max();
    std::array<unsigned char,64> small{};
    const auto capacity = zn_array_export(p,small.data(),small.size()-1,&used);
    require(capacity == ZN_INVALID && used == 0,"array capacity error wrote a result");
    auto after = export_array(p);
    save("before",before.data(),before.size());
    save("after",after.data(),after.size());
    std::cout << "{\"rate\":" << zn_array_rate(p) << ",\"cached_point\":" << cached << ",\"evicted_point\":" << evicted
              << ",\"range_tail\":" << range_tail << ",\"cache_size_request\":16384,\"cache_populated\":" << populated
              << ",\"cache_after_set_size\":" << resized << ",\"cache_repopulated\":" << repopulated
              << ",\"cache_after_flush\":" << flushed << ",\"rejected\":{\"point_oob\":" << point_oob
              << ",\"nonfinite_write\":" << nonfinite << ",\"range_oob\":" << range_oob
              << ",\"export_capacity\":" << capacity << "}}\n";
}
int reject_import(zn_config cfg,const void* wire,size_t size) {
    zn_array* p = nullptr;
    const auto st = zn_array_import(&cfg,wire,size,&p);
    Array handle(p,zn_array_destroy);
    require(!p && st == ZN_INVALID,"invalid array import accepted");
    return st;
}
void array_decode(ArraySpec s,const char* path,bool controls) {
    const auto wire = read<unsigned char>(path);
    require(wire.size()==64,"unexpected trusted array extent");
    zn_array* p = nullptr;
    ok(zn_array_import(&s.cfg,wire.data(),wire.size(),&p));
    Array handle(p,zn_array_destroy);
    require(zn_array_rate(p)==s.effective && zn_array_count(p)==s.cfg.size[0],"array restore config differs");
    auto data = std::vector<double>(s.cfg.size[0]);
    ok(zn_array_get_range(p,0,data.size(),data.data(),data.size()*8));
    // A separate cross-block read after reopening, not a slice of the full read.
    std::array<double,4> range{};
    ok(zn_array_get_range(p,3,4,range.data(),sizeof range));
    require(std::equal(range.begin(),range.end(),data.begin()+3),"reopened cross-block read differs");
    save("span",data.data(),data.size()*8);
    std::cout << "{\"rate\":" << zn_array_rate(p) << ",\"count\":" << data.size() << ",\"cross_block_read\":true";
    if (controls) {
        const auto truncated = reject_import(s.cfg,wire.data(),wire.size()-1);
        auto bad = s.cfg;
        bad.size[0] = 8;
        const auto wrong_size = reject_import(bad,wire.data(),wire.size());
        bad = zn_config_1d(ZN_F64,s.cfg.size[0]);
        const auto wrong_mode = reject_import(bad,wire.data(),wire.size());
        std::cout << ",\"rejected\":{\"truncated_raw\":" << truncated << ",\"wrong_derived_size\":" << wrong_size
                  << ",\"wrong_mode\":" << wrong_mode << '}';
    }
    std::cout << "}\n";
}
}
int main(int argc,char** argv) {
    try {
        require(argc >= 4 && argc <= 5,"expected operation, metadata, and data");
        std::cout << std::setprecision(17);
        const std::string_view op = argv[1];
        if (op == "field-encode" || op == "field-encode-controls" || op == "field-decode") {
            require(argc==4,"invalid field arguments");
            const auto f = field_spec(argv[2]);
            const auto encode = op != "field-decode", controls = op == "field-encode-controls";
            switch (f.cfg.type) {
                case ZN_I32: field<int32_t>(f,argv[3],encode,controls); break;
                case ZN_I64: field<int64_t>(f,argv[3],encode,controls); break;
                case ZN_F32: field<float>(f,argv[3],encode,controls); break;
                case ZN_F64: field<double>(f,argv[3],encode,controls); break;
            }
        } else if (op == "array-update") {
            require(argc==5,"invalid array update arguments");
            array_update(array_spec(argv[2]),argv[3],argv[4]);
        } else if (op == "array-decode" || op == "array-decode-controls") {
            require(argc==4,"invalid array decode arguments");
            array_decode(array_spec(argv[2]),argv[3],op == "array-decode-controls");
        } else require(false,"unknown operation");
        return std::cout ? 0 : 2;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
