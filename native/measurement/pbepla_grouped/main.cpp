// Native call boundaries for the unchanged r40 PBEP controller. Applies only
// to calls made by this executable; it does not modify or instrument the DSO.
#include "tba.h"
#include <array>
#include <charconv>
#include <chrono>
#include <filesystem>
#include <iostream>
#include <sched.h>
#include <stdexcept>
#include <string_view>

int tsbench_pbepla_corpus_unit(int argc, char **argv);

namespace {
using Clock = std::chrono::steady_clock;
static_assert(Clock::is_steady);
struct Sample { const char *part; unsigned layer; int result; uint64_t ns; };
std::array<Sample,8> samples;
size_t used=0;
void need(bool ok,const char *reason) {
    if (!ok) throw std::runtime_error(reason);
}
template<class F> int profile(const char *part,unsigned layer,F fn) {
    need(used<samples.size(),"too many PBEPLA calls from frozen corpus controller");
    const auto start=Clock::now();
    const int rc=fn();
    const auto elapsed=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();
    samples[used++]={part,layer,rc,static_cast<uint64_t>(elapsed)};
    return rc;
}
void emit(size_t index) {
    std::cout<<"{\"index\":"<<index<<",\"native_calls\":[";
    for (size_t i=0;i<used;++i) {
        const auto &r=samples[i];
        std::cout<<(i ? "," : "")<<"{\"part\":\""<<r.part<<"\",\"layer\":"<<r.layer
                 <<",\"result\":"<<r.result<<",\"wall_ns\":"<<r.ns<<'}';
    }
    std::cout<<"]}\n";
}
}

extern "C" {
decltype(tba_pbepla_encode_ex) __real_tba_pbepla_encode_ex;
decltype(tba_pbepla_encode_stream) __real_tba_pbepla_encode_stream;
decltype(tba_pbepla_prefix) __real_tba_pbepla_prefix;
decltype(tba_pbepla_inspect) __real_tba_pbepla_inspect;
decltype(tba_decode) __real_tba_decode;
decltype(tba_pbepla_decode_stream) __real_tba_pbepla_decode_stream;

int __wrap_tba_pbepla_encode_ex(const double *p,size_t n,const tba_pbepla_options *o,tba_pbepla_info *info,
                              tba_buffer *b,char *e,size_t cap) {
    return profile("batch_encode",0,[&]{return __real_tba_pbepla_encode_ex(p,n,o,info,b,e,cap);});
}
int __wrap_tba_pbepla_encode_stream(void *src,tba_rewind_fn rewind,tba_next_fn next,void *sink,tba_write_fn writer,
                                  const tba_pbepla_options *o,size_t n,tba_stream_stats *stats,char *e,size_t cap) {
    return profile("replay_encode",0,[&]{return __real_tba_pbepla_encode_stream(src,rewind,next,sink,writer,o,n,stats,e,cap);});
}
int __wrap_tba_pbepla_prefix(const void *p,size_t n,unsigned layer,tba_buffer *b,char *e,size_t cap) {
    return profile("prefix_materialize",layer,[&]{return __real_tba_pbepla_prefix(p,n,layer,b,e,cap);});
}
int __wrap_tba_pbepla_inspect(const void *p,size_t n,tba_pbepla_info *i,char *e,size_t cap) {
    return profile("detached_prefix_inspect",0,[&]{return __real_tba_pbepla_inspect(p,n,i,e,cap);});
}
int __wrap_tba_decode(int32_t kind,const void *p,size_t n,unsigned layer,size_t max,tba_buffer *b,char *e,size_t cap) {
    return profile("batch_restore",layer,[&]{return __real_tba_decode(kind,p,n,layer,max,b,e,cap);});
}
int __wrap_tba_pbepla_decode_stream(const void *p,size_t n,unsigned layer,size_t max,void *sink,tba_emit_fn fn,char *e,size_t cap) {
    return profile("callback_restore",layer,[&]{return __real_tba_pbepla_decode_stream(p,n,layer,max,sink,fn,e,cap);});
}
}

int main(int argc,char **argv) {
    try {
        need(argc>=3,"expected bounded progressive/replay group or detached prefix group");
        const std::string_view op=argv[1];
        const bool dec=op=="restore-batch" || op=="restore-callback";
        need(dec || op=="progressive" || op=="replay","unknown PBEPLA operation");
        const int first=dec ? 3 : 2;
        need(first<argc && argc-first<=32,"PBEPLA group must have 1--32 units");
        need(!dec || (std::string_view(argv[2]).size()==1 && argv[2][0]>='1' && argv[2][0]<='3'),"invalid layer");
        std::array<size_t,32> ids{};
        uint64_t mask=0;
        for (int i=first;i<argc;++i) {
            const std::string_view s=argv[i];
            const auto r=std::from_chars(s.data(),s.data()+s.size(),ids[i-first]);
            const size_t ix=ids[i-first];
            need(r.ec==std::errc{} && r.ptr==s.data()+s.size() && ix<32 && !(mask&(uint64_t(1)<<ix)),"invalid PBEPLA unit");
            mask|=uint64_t(1)<<ix;
        }
        namespace fs=std::filesystem;
        const fs::path work="/tmp/tsbench-pbepla-group";
        need(fs::create_directory(work),"group working directory already exists");
        fs::create_directory_symlink("/inputs",work/"input");
        fs::create_directory_symlink("/out",work/"out");
        fs::current_path(work);
        const int before=sched_getcpu();
        for (int i=first;i<argc;++i) {
            used=0;
            char *args[]{argv[0],argv[1],dec ? argv[2] : argv[i],dec ? argv[i] : nullptr,nullptr};
            need(tsbench_pbepla_corpus_unit(first+1,args)==0,"PBEPLA call group failed");
            emit(ids[i-first]);
        }
        std::cout<<"{\"units\":"<<argc-first<<",\"cpu_endpoints\":["<<before<<','<<sched_getcpu()<<"]}\n";
        return std::cout.good() ? 0 : 2;
    } catch (const std::exception &error) {
        std::cerr<<"PBEPLA group: "<<error.what()<<'\n';
        return 2;
    }
}
