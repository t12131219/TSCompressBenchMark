// Bounded real-corpus control for trusted native PBEP objects. A restore process
// receives only one declared layer per object, without the original input.
#include "tba.h"
#include <dlfcn.h>
#include <array>
#include <charconv>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;
constexpr size_t max_rows = 4096, max_frame = 131072, max_group = 32, layers = 3;
constexpr double eps[]{16, 4, 1};
struct TempFile { FILE* file{}; size_t offset{}, extent{}; };
struct Traffic {
    std::array<TempFile,64> files{};
    size_t created{}, closed{}, seeks{}, reads{}, writes{}, live{}, peak{};
};
Traffic* collecting = nullptr;

template<class Fn> Fn next(const char* name) {
    auto fn = reinterpret_cast<Fn>(dlsym(RTLD_NEXT, name));
    if (!fn) std::abort();
    return fn;
}
TempFile* tracked(FILE* f) {
    if (collecting && f) for (auto& x : collecting->files) if (x.file == f) return &x;
    return nullptr;
}
void check(bool ok, const char* text) { if (!ok) throw std::runtime_error(text); }
void call(int rc, const char* error) { check(rc == 0, *error ? error : "native PBEPLA call failed"); }
struct Buffer { tba_buffer v{}; ~Buffer() { tba_free(&v); } };
struct Source {
    const std::vector<double>& data;
    size_t pos{}, rewinds{}, rows{}, eof{};
};
struct Sink {
    const Source& source;
    std::array<unsigned char,max_frame> data{};
    size_t bytes{}, calls{}, first_pass{};
    Clock::time_point start{}, first{};
};
int start_pass(void* ctx) {
    auto& s = *static_cast<Source*>(ctx);
    ++s.rewinds;
    s.pos = 0;
    return 0;
}
int next_value(void* ctx,double* out) {
    auto& s = *static_cast<Source*>(ctx);
    if (s.pos == s.data.size()) { ++s.eof; return 0; }
    *out = s.data[s.pos++];
    ++s.rows;
    return 1;
}
int emit_bytes(void* ctx,const void* data,size_t n) {
    auto& s = *static_cast<Sink*>(ctx);
    if (n > s.data.size()-s.bytes) return -1;
    if (!s.calls++) { s.first = Clock::now(); s.first_pass = s.source.eof; }
    std::memcpy(s.data.data()+s.bytes,data,n);
    s.bytes += n;
    return 0;
}
struct Values { std::array<double,max_rows> data{}; size_t count{}, limit{}; };
int emit_value(void* ctx,double value) {
    auto& s = *static_cast<Values*>(ctx);
    if (s.count == s.limit) return -1;
    s.data[s.count++] = value;
    return 0;
}
template<class T> std::vector<T> read(const std::string& path,size_t cap) {
    std::ifstream file(path,std::ios::binary | std::ios::ate);
    const auto end = file.tellg();
    check(end > 0 && size_t(end) <= cap && size_t(end)%sizeof(T) == 0,"invalid bounded input extent");
    std::vector<T> data(size_t(end)/sizeof(T));
    file.seekg(0);
    check(bool(file.read(reinterpret_cast<char*>(data.data()),end)) && file.peek() == EOF,"bounded input read failed");
    return data;
}
void write(const std::string& path,const void* data,size_t bytes) {
    check(data && bytes && bytes <= max_frame,"invalid bounded output extent");
    std::ofstream file(path,std::ios::binary);
    check(bool(file.write(static_cast<const char*>(data),bytes)),"bounded output write failed");
    file.close();
    check(bool(file),"bounded output close failed");
}
void string_json(std::string_view s) {
    std::cout << '"';
    constexpr char hex[] = "0123456789abcdef";
    for (const unsigned char c : s) {
        if (c == '"' || c == '\\') std::cout << '\\' << c;
        else if (c < 32 || c >= 127) std::cout << "\\u00" << hex[c >> 4] << hex[c & 15];
        else std::cout << c;
    }
    std::cout << '"';
}
void encode(const std::string& index,bool replay) {
    auto raw = read<double>("input/"+index,8*max_rows);
    auto cfg = tba_pbepla_defaults(eps,layers); cfg.max_delay = 64;
    Buffer full;
    char err[256]{};
    Source source{raw}; Sink sink{source}; Traffic traffic; tba_stream_stats stats{};
    if (replay) {
        sink.start = Clock::now(); collecting = &traffic;
        const int rc = tba_pbepla_encode_stream(&source,start_pass,next_value,&sink,emit_bytes,&cfg,raw.size(),&stats,err,sizeof err);
        collecting = nullptr;
        check(traffic.created == traffic.closed && !traffic.live,"PBEPLA temporary file leak");
        call(rc,err);
    }
    // For a replay-only request, construct the same-field serial reference too.
    // Its work is a validation control, not a duration charged to native replay.
    tba_pbepla_info info{};
    call(tba_pbepla_encode_ex(raw.data(),raw.size(),&cfg,&info,&full.v,err,sizeof err),err);
    check(full.v.count == raw.size() && full.v.bytes <= max_frame && info.layer_present == layers,"wrong batch descriptor");
    if (replay) check(sink.bytes == full.v.bytes && !std::memcmp(sink.data.data(),full.v.data,sink.bytes),
                      "PBEPLA replay full bytes differ from same-field batch");
    const void* native = replay ? static_cast<const void*>(sink.data.data()) : full.v.data;
    std::array<Buffer,layers> prefixes;
    for (unsigned layer=1; layer<=layers; ++layer) {
        auto& p = prefixes[layer-1].v;
        call(tba_pbepla_prefix(native,full.v.bytes,layer,&p,err,sizeof err),err);
        check(p.count == raw.size() && p.bytes > 0 && p.bytes <= max_frame,"wrong prefix extent");
    }
    for (unsigned layer=1; layer<=layers; ++layer) {
        const auto& p = prefixes[layer-1].v;
        write("out/"+index+"-"+std::to_string(layer),p.data,p.bytes);
    }
    std::cout << "{\"index\":" << index << ",\"status\":\"encoded\",\"rows\":" << raw.size()
              << ",\"native_full_bytes\":" << full.v.bytes << ",\"replay\":";
    if (!replay) std::cout << "null";
    else std::cout << "{\"result\":0,\"rewind_calls\":" << source.rewinds << ",\"eof_passes\":" << source.eof
                   << ",\"source_bytes_read\":" << 8*source.rows << ",\"sink_bytes\":" << sink.bytes
                   << ",\"sink_calls\":" << sink.calls << ",\"first_sink_after_pass\":" << sink.first_pass
                   << ",\"first_sink_ns\":" << std::chrono::duration_cast<std::chrono::nanoseconds>(sink.first-sink.start).count()
                   << ",\"temp_files_created\":" << traffic.created << ",\"temp_files_closed\":" << traffic.closed
                   << ",\"temp_seeks\":" << traffic.seeks << ",\"temp_bytes_written\":" << traffic.writes
                   << ",\"temp_bytes_read\":" << traffic.reads << ",\"temp_peak_live_bytes\":" << traffic.peak
                   << ",\"native_passes\":" << stats.source_passes << ",\"native_buffer_slots\":" << stats.buffer_slots
                   << ",\"native_value_count\":" << stats.value_count << ",\"native_numerical_retries\":" << stats.numerical_retries
                   << ",\"same_bytes_as_batch\":true}";
    std::cout << "}\n";
}
void restore(const std::string& index,bool replay,unsigned layer) {
    {
        auto name = index+"-"+std::to_string(layer);
        auto wire = read<unsigned char>("input/"+name,max_frame);
        char err[256]{};
        tba_pbepla_info info{};
        call(tba_pbepla_inspect(wire.data(),wire.size(),&info,err,sizeof err),err);
        check(info.layer_present == layer && info.layer_count == layers && info.value_count && info.value_count <= max_rows,
              "detach requires the declared prefix, not a larger PBEP object");
        if (replay) {
            Values values; values.limit = info.value_count;
            call(tba_pbepla_decode_stream(wire.data(),wire.size(),layer,info.value_count,&values,emit_value,err,sizeof err),err);
            check(values.count == info.value_count,"bad callback emission count");
            write("out/"+name,values.data.data(),8*values.count);
        } else {
            Buffer values;
            call(tba_decode(TBA_PBEPLA_RR,wire.data(),wire.size(),layer,info.value_count,&values.v,err,sizeof err),err);
            check(values.v.count == info.value_count && values.v.bytes == 8*info.value_count,"bad batch prefix restoration extent");
            write("out/"+name,values.v.data,values.v.bytes);
        }
    }
    std::cout << "{\"index\":" << index << ",\"status\":\"restored\",\"layer\":" << layer << "}\n";
}
}

extern "C" FILE* tmpfile() {
    static const auto fn = next<decltype(&tmpfile)>("tmpfile");
    FILE* f = fn();
    if (f && collecting) {
        for (auto& x : collecting->files) if (!x.file) { x = {f,0,0}; ++collecting->created; return f; }
        std::abort();
    }
    return f;
}
extern "C" int fclose(FILE* f) {
    static const auto fn = next<decltype(&fclose)>("fclose");
    if (auto* x = tracked(f)) { collecting->live -= x->extent; *x = {}; ++collecting->closed; }
    return fn(f);
}
extern "C" int fputc(int c,FILE* f) {
    static const auto fn = next<decltype(&fputc)>("fputc");
    const int rc = fn(c,f);
    if (auto* x = tracked(f); x && rc != EOF) {
        ++collecting->writes;
        if (++x->offset > x->extent) {
            collecting->live += x->offset-x->extent;
            x->extent = x->offset;
            if (collecting->live > collecting->peak) collecting->peak = collecting->live;
        }
    }
    return rc;
}
extern "C" int fgetc(FILE* f) {
    static const auto fn = next<decltype(&fgetc)>("fgetc");
    const int rc = fn(f);
    if (auto* x = tracked(f); x && rc != EOF) { ++collecting->reads; ++x->offset; }
    return rc;
}
extern "C" size_t fread(void* p,size_t size,size_t n,FILE* f) {
    static const auto fn = next<decltype(&fread)>("fread");
    const size_t rc = fn(p,size,n,f);
    if (auto* x = tracked(f)) { collecting->reads += size*rc; x->offset += size*rc; }
    return rc;
}
extern "C" int fseek(FILE* f,long off,int whence) {
    static const auto fn = next<decltype(&fseek)>("fseek");
    const int rc = fn(f,off,whence);
    if (auto* x = tracked(f); x && rc == 0) {
        if (off || whence != SEEK_SET) std::abort();
        x->offset = 0; ++collecting->seeks;
    }
    return rc;
}

int main(int argc,char** argv) {
    try {
        check(argc >= 3,"expected operation and bounded unit indexes");
        const std::string_view op = argv[1];
        check(op == "progressive" || op == "replay" || op == "restore-batch" || op == "restore-callback","invalid operation");
        const bool dec = op == "restore-batch" || op == "restore-callback";
        const bool replay = op == "replay" || op == "restore-callback";
        const int first = dec ? 3 : 2;
        check(first < argc && size_t(argc-first) <= max_group,"invalid group size");
        const unsigned layer = dec && std::strlen(argv[2]) == 1 ? unsigned(argv[2][0]-'0') : 0;
        check(!dec || (layer > 0 && layer <= layers),"invalid detached prefix layer");
        uint64_t mask = 0;
        for (int i=first; i<argc; ++i) {
            std::string_view arg(argv[i]);
            size_t ix{};
            const auto end = arg.data()+arg.size();
            const auto parsed = std::from_chars(arg.data(),end,ix);
            check(parsed.ec == std::errc{} && parsed.ptr == end && ix < max_group && std::to_string(ix) == arg &&
                  !(mask & (uint64_t(1)<<ix)),"invalid or duplicate unit index");
            mask |= uint64_t(1)<<ix;
        }
        for (int i=first; i<argc; ++i) {
            try {
                if (dec) restore(argv[i],replay,layer);
                else encode(argv[i],replay);
            } catch (const std::exception& e) {
                std::cout << "{\"index\":" << argv[i] << ",\"status\":\"failed\",\"reason\":";
                string_json(e.what()); std::cout << "}\n";
            }
        }
        return std::cout ? 0 : 2;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n'; return 2;
    }
}
