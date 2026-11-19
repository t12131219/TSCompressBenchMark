#include "tba.h"

#include <dlfcn.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <iomanip>
#include <memory>
#include <string_view>

namespace {
struct FileTrace { FILE *stream{}; size_t offset{}, extent{}; };
std::array<FileTrace,16> tracked{};
bool recording{};
size_t files{}, closed{}, seeks{}, reads{}, writes{}, live_bytes{}, peak_bytes{};

template<class Fn> Fn next(const char *name) {
    auto fn = reinterpret_cast<Fn>(dlsym(RTLD_NEXT,name));
    if (!fn) std::abort();
    return fn;
}
FileTrace *trace(FILE *f) {
    if (recording && f) for (auto &x : tracked) if (x.stream == f) return &x;
    return nullptr;
}
struct Source {
    FILE *stream;
    std::string_view mode;
    size_t passes{}, eof{}, rows{}, rows_this_pass{};
};
struct Sink { FILE *stream; Source *source; size_t calls{}, size{}, first_after_pass{}; };
int rewind_source(void *ptr) {
    auto &s = *static_cast<Source *>(ptr);
    if (++s.passes > 1 && s.mode == "no-rewind") return -1;
    s.rows_this_pass = 0;
    return std::fseek(s.stream,0,SEEK_SET) == 0 ? 0 : -1;
}
int read_source(void *ptr,double *out) {
    auto &s = *static_cast<Source *>(ptr);
    if (std::fread(out,sizeof(*out),1,s.stream) == 1) {
        if (s.mode == "changed" && s.passes == 2 && s.rows_this_pass == 0) *out += 0.125;
        ++s.rows; ++s.rows_this_pass;
        return 1;
    }
    if (std::ferror(s.stream)) return -1;
    ++s.eof;
    return 0;
}
int write_sink(void *ptr,const void *data,size_t n) {
    auto &s = *static_cast<Sink *>(ptr);
    if (!s.calls++) s.first_after_pass = s.source->eof;
    else if (s.source->mode == "sink-fail") return -1;
    const auto wrote = std::fwrite(data,1,n,s.stream);
    s.size += wrote;
    return wrote == n ? 0 : -1;
}
}

extern "C" FILE *tmpfile() {
    static const auto fn = next<decltype(&tmpfile)>("tmpfile");
    FILE *f = fn();
    if (f && recording) {
        for (auto &x : tracked) if (!x.stream) { x = {f,0,0}; ++files; return f; }
        std::abort();
    }
    return f;
}
extern "C" int fputc(int c,FILE *f) {
    static const auto fn = next<decltype(&fputc)>("fputc");
    const int rc = fn(c,f);
    if (auto *x = trace(f); x && rc != EOF) {
        ++writes;
        if (++x->offset > x->extent) {
            live_bytes += x->offset-x->extent; x->extent = x->offset;
            if (live_bytes > peak_bytes) peak_bytes = live_bytes;
        }
    }
    return rc;
}
extern "C" int fgetc(FILE *f) {
    static const auto fn = next<decltype(&fgetc)>("fgetc");
    const int rc = fn(f);
    if (auto *x = trace(f); x && rc!=EOF) { ++reads; ++x->offset; }
    return rc;
}
extern "C" size_t fread(void *p,size_t size,size_t n,FILE *f) {
    static const auto fn = next<decltype(&fread)>("fread");
    const size_t rc = fn(p,size,n,f);
    if (auto *x = trace(f)) { reads += size*rc; x->offset += size*rc; }
    return rc;
}
extern "C" int fseek(FILE *f,long off,int whence) {
    static const auto fn = next<decltype(&fseek)>("fseek");
    const int rc = fn(f,off,whence);
    if (auto *x = trace(f); x && rc == 0) {
        if (off || whence != SEEK_SET) std::abort();
        x->offset = 0; ++seeks;
    }
    return rc;
}
extern "C" int fclose(FILE *f) {
    static const auto fn = next<decltype(&fclose)>("fclose");
    if (auto *x = trace(f)) { live_bytes -= x->extent; *x = {}; ++closed; }
    return fn(f);
}

int main(int argc,char **argv) {
    if (argc<7 || argc>22) return 2;
    const std::string_view mode = argv[1];
    if (mode!="normal" && mode!="changed" && mode!="no-rewind" && mode!="sink-fail") return 2;
    const std::unique_ptr<FILE,decltype(&fclose)> src(std::fopen(argv[2],"rb"),fclose);
    const std::unique_ptr<FILE,decltype(&fclose)> dst(std::fopen(argv[3],"wb"),fclose);
    if (!src || !dst) return 2;
    char *end = nullptr;
    const auto limit = std::strtoull(argv[4],&end,10);
    if (*end || limit>16000000) return 2;
    const auto delay = std::strtoull(argv[5],&end,10);
    if (*end || !delay || delay>65536) return 2;
    std::array<double,16> eps{};
    const size_t k = argc-6;
    for (size_t i=0;i<k;++i) { eps[i] = std::strtod(argv[i+6],&end); if (*end) return 2; }
    auto options = tba_pbepla_defaults(eps.data(),k);
    options.max_delay = delay;
    Source source{src.get(),mode};
    Sink sink{dst.get(),&source};
    tba_stream_stats stats{};
    char error[256]{};
    recording = true;
    const int rc = tba_pbepla_encode_stream(&source,rewind_source,read_source,&sink,write_sink,&options,limit,&stats,error,sizeof error);
    recording = false;
    if (std::fflush(dst.get()) || files != closed || live_bytes) return 2;
    if (rc) std::cerr << error << '\n';
    std::cout << "{\"result\":" << rc << ",\"rewind_calls\":" << source.passes << ",\"eof_passes\":" << source.eof
              << ",\"source_bytes_read\":" << source.rows*sizeof(double) << ",\"sink_bytes\":" << sink.size
              << ",\"sink_calls\":" << sink.calls << ",\"first_sink_after_pass\":" << sink.first_after_pass
              << ",\"temp_files_created\":" << files << ",\"temp_files_closed\":" << closed << ",\"temp_seeks\":" << seeks
              << ",\"temp_bytes_written\":" << writes << ",\"temp_bytes_read\":" << reads << ",\"temp_peak_live_bytes\":" << peak_bytes
              << ",\"native_passes\":" << stats.source_passes << ",\"native_buffer_slots\":" << stats.buffer_slots
              << ",\"native_value_count\":" << stats.value_count << ",\"native_numerical_retries\":" << stats.numerical_retries << "}\n";
    return 0;
}
