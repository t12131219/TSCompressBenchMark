// Native caller for the frozen edge fixtures and bounded real-corpus pages.
#include "pcodec_native_ext.h"
#include "pcodec_source.h"
#include <array>
#include <charconv>
#include <chrono>
#include <ctime>
#include <sys/resource.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <numeric>
#include <stdexcept>
#include <string_view>
#include <vector>

int run_intmult(int argc,char **argv);

namespace {
using Bytes = std::vector<uint8_t>;
constexpr size_t counts[2] = {513, 260};
constexpr size_t total = counts[0] + counts[1];
constexpr size_t capacity = 256;
constexpr size_t width = sizeof(uint64_t);
constexpr size_t max_meta = 65536;
constexpr size_t max_page(size_t i) { return max_meta + counts[i]*width; }

void check(bool b, const char *where) { if (!b) throw std::runtime_error(where); }
Bytes load(const char *path, size_t limit) {
    std::unique_ptr<std::FILE, decltype(&std::fclose)> file(std::fopen(path,"rb"), std::fclose);
    check(!!file,"open bounded input");
    Bytes data(limit);
    const size_t n = std::fread(data.data(),1,limit,file.get());
    check(std::fgetc(file.get()) == EOF && !std::ferror(file.get()),"input exceeds limit");
    data.resize(n);
    return data;
}
void save(const char *path, const Bytes &data) {
    auto *file = std::fopen(path,"wbx");
    check(file,"create output");
    const bool wrote = std::fwrite(data.data(),1,data.size(),file) == data.size();
    check(std::fclose(file) == 0 && wrote,"write output");
}

#define PAGE_API(NAME, PFX, NATIVE) \
    struct NAME { \
        using encoder = PFX##_encoder; using decoder = PFX##_decoder; using buf = PFX##_buffer; \
        static constexpr bool native = NATIVE; \
        static constexpr auto defaults = PFX##_default_config; \
        static constexpr auto chunk = PFX##_chunk_new; static constexpr auto free_encoder = PFX##_chunk_destroy; \
        static constexpr auto meta = PFX##_chunk_header_meta; static constexpr auto page = PFX##_chunk_page; \
        static constexpr auto geometry = PFX##_chunk_page_counts; static constexpr auto enc_state = PFX##_chunk_describe; \
        static constexpr auto open = PFX##_wrapped_open; static constexpr auto free_decoder = PFX##_decoder_destroy; \
        static constexpr auto start = PFX##_wrapped_start_page; static constexpr auto read = PFX##_read; \
        static constexpr auto dec_state = PFX##_decoder_describe; static constexpr auto free_bytes = PFX##_buffer_free; \
    }
PAGE_API(Source, pcs, false);
PAGE_API(Native, pcn, true);
#undef PAGE_API

template<class Api> struct Buffer {
    typename Api::buf out{};
    ~Buffer() { if (out.data) Api::free_bytes(out.data,out.size); }
    Bytes take(size_t cap) const {
        check(out.size <= cap && (!out.size || out.data), "native output extent");
        return out.size ? Bytes(out.data,out.data+out.size) : Bytes{};
    }
};

template<class Api, class Fn, class... Args>
Bytes extract(size_t cap, Fn fn, Args... args) {
    Buffer<Api> b;
    check(fn(args...,&b.out) == PC_OK,"native buffer output failed");
    return b.take(cap);
}

template<class Api>
auto open(const Bytes &meta) {
    typename Api::decoder *ptr = nullptr;
    const int rc = Api::open(meta.data(),meta.size(),PC_F64,&ptr);
    std::unique_ptr<typename Api::decoder,decltype(Api::free_decoder)> out(ptr,Api::free_decoder);
    check(rc == PC_OK && ptr,"wrapped decoder open failed");
    return out;
}

struct Step { Bytes data; size_t rows; int end, status; };
template<class Api>
Step step(typename Api::decoder *d, size_t cap, int expected = PC_OK, int alternative = -1) {
    Buffer<Api> b;
    size_t rows = 0;
    int done = 0;
    const int rc = Api::read(d,cap,&b.out,&rows,&done);
    if (rc != expected && rc != alternative) std::fprintf(stderr,"read status %d, expected %d or %d\n",rc,expected,alternative);
    check(rc == expected || rc == alternative,"read status differs");
    if (rc) check(!b.out.data && !b.out.size && !rows && !done,"failed read produced output");
    check(rows <= cap && b.out.size == rows*width && (done == 0 || done == 1),"native page buffer geometry");
    return {b.take(cap*width),rows,done,rc};
}

template<class Api>
Bytes drain(typename Api::decoder *d, size_t rows, std::vector<size_t> *spans = nullptr,
            size_t read_capacity = capacity) {
    Bytes out;
    while (rows) {
        const auto r = step<Api>(d,read_capacity);
        const size_t wanted = rows > read_capacity ? read_capacity : rows;
        check(r.rows == wanted && bool(r.end) == (rows == wanted),"wrong page progress or terminal flag");
        if (spans) spans->push_back(r.rows);
        out.insert(out.end(),r.data.begin(),r.data.end());
        rows -= r.rows;
    }
    return out;
}

void state_json(const Bytes &state) {
    check(state.size() >= 2 && state.front() == '{' && state.back() == '}' &&
          std::fwrite(state.data(),1,state.size(),stdout) == state.size(),"native state JSON missing");
}

template<class Api>
void encode(const char *path) {
    const auto input = load(path,total*width);
    check(input.size() == total*width,"raw page input extent");
    std::array<uint64_t,total> aligned;
    std::memcpy(aligned.data(),input.data(),input.size());
    typename Api::encoder *ptr = nullptr;
    const auto cfg = Api::defaults();
    check(cfg.level == 8 && cfg.mode == -1 && cfg.delta == -1 && cfg.max_page_n == 262144,"wrong Auto defaults");
    const int rc = Api::chunk(aligned.data(),total,PC_F64,&cfg,counts,2,&ptr);
    std::unique_ptr<typename Api::encoder,decltype(Api::free_encoder)> e(ptr,Api::free_encoder);
    check(rc == PC_OK && ptr,"chunk training failed");
    const auto geometry = extract<Api>(sizeof(counts),Api::geometry,ptr);
    check(geometry.size() == sizeof(counts) && std::memcmp(geometry.data(),counts,sizeof(counts)) == 0,
          "native page counts differ");
    const auto meta = extract<Api>(max_meta,Api::meta,ptr);
    const auto state = extract<Api>(4096,Api::enc_state,ptr);
    const auto p1 = extract<Api>(max_page(1),Api::page,ptr,1);
    const auto p0 = extract<Api>(max_page(0),Api::page,ptr,0);
    check(meta.size() >= 2 && !p0.empty() && !p1.empty(),"empty page data or missing metadata");
    save("meta",meta); save("page-0",p0); save("page-1",p1);
    std::printf("{\"counts\":[%zu,%zu],\"generation_order\":[1,0],\"dtype\":%d,\"level\":%d,\"requested_mode\":%d,"
                "\"requested_delta\":%d,\"meta_bytes\":%zu,\"page_bytes\":[%zu,%zu],\"state\":",counts[0],counts[1],PC_F64,
                cfg.level,cfg.mode,cfg.delta,meta.size(),p0.size(),p1.size());
    state_json(state);
    std::puts("}");
}

template<class Api>
void decode(size_t i, const char *m, const char *p) {
    const auto meta = load(m,max_meta), page = load(p,max_page(i));
    check(meta.size() >= 2 && !page.empty(),"missing retained inputs");
    auto d = open<Api>(meta);
    const auto state = extract<Api>(4096,Api::dec_state,d.get());
    const size_t n = counts[i];
    check(Api::start(d.get(),page.data(),page.size(),n,n) == PC_OK,"detached page failed to start");
    std::vector<size_t> spans;
    save("raw",drain<Api>(d.get(),n,&spans));
    std::printf("{\"index\":%zu,\"rows\":%zu,\"meta_bytes\":%zu,\"page_bytes\":%zu,\"spans\":[",i,n,meta.size(),page.size());
    for (size_t j=0;j<spans.size();++j) std::printf("%s%zu",j?",":"",spans[j]);
    std::printf("],\"finished\":true,\"state\":"); state_json(state); std::puts("}");
}

template<class Api>
void missing(const char *p) {
    const auto page = load(p,max_page(0));
    check(!page.empty(),"no detached page for missing metadata check");
    typename Api::decoder *ptr = nullptr;
    const uint8_t empty = 0;  // No metadata bytes, valid address for a length-zero native slice.
    const int rc = Api::open(&empty,0,PC_F64,&ptr);
    std::unique_ptr<typename Api::decoder,decltype(Api::free_decoder)> cleanup(ptr,Api::free_decoder);
    check(!ptr && rc == (Api::native ? PC_INVALID : PC_TRUNCATED),"missing metadata status differs");
    std::printf("{\"metadata_bytes\":0,\"available_page_bytes\":%zu,\"status\":%d,\"decoder_null\":true}\n",page.size(),rc);
}

template<class Api>
void diagnose(const char *m, const char *one, const char *two) {
    const auto meta = load(m,max_meta), p0 = load(one,max_page(0)), p1 = load(two,max_page(1));
    check(meta.size() >= 2 && p0.size() >= 2 && !p1.empty(),"short control assets");
    int small, next, second;
    {
        auto d = open<Api>(meta);
        small = Api::start(d.get(),p0.data(),p0.size(),counts[0],counts[0]-1);
        check(small == PC_LIMIT,"first page count limit not enforced");
        check(Api::start(d.get(),p0.data(),p0.size(),counts[0],total) == PC_OK,"control first page start");
        step<Api>(d.get(),capacity-1,PC_INVALID);
        auto head = step<Api>(d.get(),capacity);
        check(head.rows == capacity && !head.end,"first read completed page prematurely");
        next = Api::start(d.get(),p1.data(),p1.size(),counts[1],total);
        check(next == PC_INVALID,"start accepted before full drain");
        const auto tail = drain<Api>(d.get(),counts[0]-capacity);
        head.data.insert(head.data.end(),tail.begin(),tail.end());
        save("session-0",head.data);
        second = Api::start(d.get(),p1.data(),p1.size(),counts[1],counts[1]);
        check(second == (Api::native ? PC_LIMIT : PC_OK),"wrong page quota interpretation");
        if constexpr (Api::native)
            check(Api::start(d.get(),p1.data(),p1.size(),counts[1],total) == PC_OK,"cumulative budget retry failed");
        save("session-1",drain<Api>(d.get(),counts[1]));
    }
    {
        auto d = open<Api>(meta);
        auto trailing = p0; trailing.push_back(0);
        check(Api::start(d.get(),trailing.data(),trailing.size(),counts[0],total) == PC_OK,"trailing case did not start");
        for (unsigned i=0;i<2;++i) {
            const auto s = step<Api>(d.get(),capacity);
            check(s.rows == capacity && !s.end,"trailing case prematurely finished");
        }
        step<Api>(d.get(),capacity,PC_CORRUPT); step<Api>(d.get(),capacity,PC_INVALID);
    }
    size_t truncated_prefix = 0;
    {
        auto d = open<Api>(meta);
        check(Api::start(d.get(),p0.data(),p0.size()-1,counts[0],total) == PC_OK,"truncated case did not start");
        bool refused = false;
        for (unsigned i=0;i<3;++i) {
            const auto s = step<Api>(d.get(),capacity,PC_OK,PC_TRUNCATED);
            if (s.status == PC_TRUNCATED) {
                refused = true;
                break;
            }
            check(s.rows == capacity && !s.end,"truncated case prematurely finished");
            truncated_prefix += s.rows;
        }
        check(refused && truncated_prefix < counts[0],"truncated input did not fail before full page completion");
    }
    if constexpr (Api::native) {
        auto d = open<Api>(meta);
        auto caller = p0;
        check(Api::start(d.get(),caller.data(),caller.size(),counts[0],total) == PC_OK,"ownership page start");
        std::memset(caller.data(),0,caller.size());
        save("ownership",drain<Api>(d.get(),counts[0]));
    }
    std::printf("{\"first_page_small_quota\":%d,\"early_next_page\":%d,\"read_capacity_255\":1,"
                "\"after_first_with_second_quota\":%d,\"trailing_at_drain\":4,\"read_after_error\":1,"
                "\"truncated_page\":{\"stage\":\"drain\",\"status\":3,\"prefix_rows\":%zu},\"overwrote_caller_buffer\":%s}\n",
                small,next,second,truncated_prefix,Api::native?"true":"false");
}

// PM3PAGE1: magic, page count, metadata length, (rows, bytes) for each
// page, then metadata and page bodies in logical order. Integers are u32 LE.
constexpr size_t corpus_rows = 65536, corpus_pages = 16;
constexpr size_t corpus_page_rows = 4096, requested_read = 257;
constexpr size_t corpus_max_frame = 16 + 8 * corpus_pages + max_meta * (corpus_pages + 1) + corpus_rows * width;

void append_u32(Bytes &dst, size_t value) {
    check(value <= UINT32_MAX,"page envelope integer overflow");
    for (unsigned shift = 0; shift < 32; shift += 8) dst.push_back(static_cast<uint8_t>(value >> shift));
}

size_t read_u32(const Bytes &src, size_t &offset) {
    check(offset <= src.size() && src.size() - offset >= 4,"truncated page envelope");
    uint32_t value = 0;
    for (unsigned shift = 0; shift < 32; shift += 8) value |= uint32_t(src[offset++]) << shift;
    return value;
}

struct Timer {
    using Clock = std::chrono::steady_clock;
    Clock::time_point wall = Clock::now();
    std::clock_t cpu = std::clock();
    void print() const {
        const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - wall).count();
        const auto stop_cpu = std::clock();
        struct rusage usage{};
        check(cpu != -1 && stop_cpu >= cpu && getrusage(RUSAGE_SELF,&usage)==0,"process measurement unavailable");
        const auto ns = static_cast<long long>((stop_cpu - cpu) * (1e9 / CLOCKS_PER_SEC));
        std::printf("\"operation_wall_ns\":%lld,\"operation_cpu_ns\":%lld,\"process_peak_rss_bytes\":%llu",
                    static_cast<long long>(elapsed),ns,static_cast<unsigned long long>(usage.ru_maxrss)*1024);
    }
};

template<class Api>
void corpus_encode(const char *input, const char *output) {
    const auto raw = load(input,corpus_rows*width);
    check(!raw.empty() && raw.size()%width==0,"real corpus page input extent");
    std::vector<uint64_t> aligned(raw.size()/width);
    std::memcpy(aligned.data(),raw.data(),raw.size());
    std::vector<size_t> sizes;
    for (size_t left = aligned.size(); left;) {
        const size_t n = left < corpus_page_rows ? left : corpus_page_rows;
        sizes.push_back(n); left -= n;
    }
    auto cfg = Api::defaults();
    check(cfg.level == 8 && cfg.mode == -1 && cfg.delta == -1,"wrong Auto defaults");
    cfg.max_page_n = corpus_page_rows;
    typename Api::encoder *ptr = nullptr;
    const Timer timer;
    const int rc = Api::chunk(aligned.data(),aligned.size(),PC_F64,&cfg,sizes.data(),sizes.size(),&ptr);
    std::unique_ptr<typename Api::encoder,decltype(Api::free_encoder)> e(ptr,Api::free_encoder);
    check(rc == PC_OK && ptr,"real corpus chunk training failed");
    const auto meta = extract<Api>(max_meta,Api::meta,ptr);
    std::vector<Bytes> pages(sizes.size());
    for (size_t i = sizes.size(); i-- > 0;)
        pages[i] = extract<Api>(max_meta+sizes[i]*width,Api::page,ptr,i);
    std::putchar('{'); timer.print();
    const auto state = extract<Api>(4096,Api::enc_state,ptr);
    const auto geometry = extract<Api>(sizes.size()*sizeof(size_t),Api::geometry,ptr);
    check(geometry.size()==sizes.size()*sizeof(size_t) &&
          std::memcmp(geometry.data(),sizes.data(),geometry.size())==0,"native page geometry differs");
    check(meta.size()>=2,"empty page metadata");
    Bytes frame{'P','M','3','P','A','G','E','1'};
    append_u32(frame,sizes.size()); append_u32(frame,meta.size());
    size_t payload = 0, empty_pages = 0;
    for (size_t i=0; i<sizes.size(); ++i) {
        // A native page can use zero bits when its values follow from metadata.
        empty_pages += pages[i].empty();
        append_u32(frame,sizes[i]); append_u32(frame,pages[i].size());
        payload += pages[i].size();
    }
    frame.insert(frame.end(),meta.begin(),meta.end());
    for (const auto &page : pages) frame.insert(frame.end(),page.begin(),page.end());
    save(output,frame);
    std::printf(",\"rows\":%zu,\"pages\":%zu,\"meta_bytes\":%zu,\"payload_bytes\":%zu,\"container_bytes\":%zu,\"zero_payload_pages\":%zu,\"state\":",
                aligned.size(),pages.size(),meta.size(),payload,frame.size()-meta.size()-payload,empty_pages);
    state_json(state); std::puts("}");
}

template<class Api>
void corpus_decode(const char *input, const char *output) {
    const auto frame = load(input,corpus_max_frame);
    check(frame.size()>=16 && std::memcmp(frame.data(),"PM3PAGE1",8)==0,"invalid page envelope");
    size_t pos = 8;
    const size_t n = read_u32(frame,pos), meta_size = read_u32(frame,pos);
    check(n && n<=corpus_pages && meta_size>=2 && meta_size<=max_meta,"page envelope bounds");
    std::vector<size_t> sizes, lengths;
    for (size_t i=0; i<n; ++i) {
        const size_t rows=read_u32(frame,pos), bytes=read_u32(frame,pos);
        check(rows && rows<=corpus_page_rows && (i+1==n || rows==corpus_page_rows) &&
              bytes<=max_meta+rows*width,"invalid page geometry");
        sizes.push_back(rows); lengths.push_back(bytes);
    }
    check(meta_size<=frame.size()-pos,"truncated metadata");
    const Bytes meta(frame.begin()+pos,frame.begin()+pos+meta_size);
    pos += meta_size;
    // Exercise the frozen non-aligned request on a separate decoder. The
    // supported capacity below stays within the request without rounding up.
    {
        auto d = open<Api>(meta);
        check(lengths[0]<=frame.size()-pos,"truncated first page");
        check(Api::start(d.get(),lengths[0] ? frame.data()+pos : meta.data(),lengths[0],sizes[0],sizes[0])
              == PC_OK,"open first page");
        step<Api>(d.get(),requested_read,PC_INVALID);
    }
    Bytes raw;
    raw.reserve(corpus_rows*width);
    size_t read_calls = 0, empty_pages = 0;
    const size_t total_rows = std::accumulate(sizes.begin(),sizes.end(),size_t{0});
    const Timer timer;
    auto d = open<Api>(meta);
    for (size_t i=0; i<n; ++i) {
        check(lengths[i]<=frame.size()-pos,"truncated page");
        const size_t quota = Api::native ? total_rows : sizes[i];
        check(Api::start(d.get(),lengths[i] ? frame.data()+pos : meta.data(),lengths[i],sizes[i],quota)
              == PC_OK,"start real corpus page");
        empty_pages += lengths[i] == 0;
        std::vector<size_t> spans;
        const auto restored = drain<Api>(d.get(),sizes[i],&spans);
        raw.insert(raw.end(),restored.begin(),restored.end());
        read_calls += spans.size();
        pos += lengths[i];
    }
    std::putchar('{'); timer.print();
    check(pos==frame.size(),"trailing bytes in page envelope");
    save(output,raw);
    std::printf(",\"rows\":%zu,\"pages\":%zu,\"read_calls\":%zu,\"request_values\":%zu,"
                "\"unaligned_request_status\":%d,\"effective_read_capacity\":%zu,\"zero_payload_pages\":%zu}\n",
                raw.size()/width,n,read_calls,requested_read,PC_INVALID,capacity,empty_pages);
}

template<class Api> int run(std::string_view op, int argc, char **argv) {
    if (op == "corpus-encode" && argc == 5) corpus_encode<Api>(argv[3],argv[4]);
    else if (op == "corpus-decode" && argc == 5) corpus_decode<Api>(argv[3],argv[4]);
    else if (op == "encode" && argc == 4) encode<Api>(argv[3]);
    else if (op == "decode" && argc == 6 && (std::string_view(argv[3]) == "0" || std::string_view(argv[3]) == "1"))
        decode<Api>(size_t(argv[3][0]-'0'),argv[4],argv[5]);
    else if (op == "missing" && argc == 4) missing<Api>(argv[3]);
    else if (op == "diagnose" && argc == 6) diagnose<Api>(argv[3],argv[4],argv[5]);
    else return 2;
    return std::fflush(stdout) == 0 && !std::ferror(stdout) ? 0 : 3;
}
}

int main(int argc, char **argv) {
    if (argc < 2 || !pc_source_backend_available()) return 2;
    try {
        const std::string_view op(argv[1]);
        if (op=="intmult-encode" || op=="intmult-decode") return run_intmult(argc,argv);
        if (argc<3) return 2;
        const std::string_view lane(argv[2]);
        if (lane == "source") return run<Source>(op,argc,argv);
        if (lane == "native") return run<Native>(op,argc,argv);
    } catch (const std::exception &e) { std::fprintf(stderr,"pcodec wrapped page control: %s\n",e.what()); return 1; }
    return 2;
}
