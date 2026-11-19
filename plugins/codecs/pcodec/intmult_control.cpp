// Direct calls into the frozen full pcodec library. No TSBench codec or wrapper frame.
#include "pcodec_source.h"
#include <array>
#include <charconv>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
constexpr size_t max_rows = 2048, frame_cap = 8192 + 65536, read_cap = 256;
using Bytes = std::vector<uint8_t>;
void check(bool ok, const char *what) { if (!ok) throw std::runtime_error(what); }
uint64_t number(std::string_view s) {
    uint64_t value = 0;
    auto result = std::from_chars(s.data(),s.data()+s.size(),value);
    check(result.ec==std::errc{} && result.ptr==s.data()+s.size(),"invalid unsigned argument");
    return value;
}
Bytes load(const char *name,size_t cap) {
    std::unique_ptr<FILE,decltype(&fclose)> in(fopen(name,"rb"),fclose);
    check(bool(in),"open input");
    Bytes bytes(cap);
    bytes.resize(fread(bytes.data(),1,cap,in.get()));
    check(fgetc(in.get())==EOF && !ferror(in.get()),"input exceeds bound or is unreadable");
    return bytes;
}
void save(const char *name,const uint8_t *data,size_t n) {
    FILE *out = fopen(name,"wbx");
    check(out,"create output");
    const bool ok = fwrite(data,1,n,out)==n;
    check(fclose(out)==0 && ok,"write output");
}
int encode(std::string_view type,uint64_t count,uint64_t base) {
    const int dtype = type=="u32"?PC_U32:type=="u64"?PC_U64:type=="f64"?PC_F64:0;
    const size_t width = pc_type_size(dtype);
    check(dtype && (width==4 || width==8) && count && count<=max_rows,"encode domain bound");
    auto data = load("/inputs/input",count*width);
    check(data.size()==count*width,"input extent");
    // pc_compress_intmult accepts aligned typed values. All frozen cases are LE.
    std::array<uint32_t,max_rows> u32;
    std::array<uint64_t,max_rows> u64;
    std::array<double,max_rows> f64;
    void *plain = dtype==PC_U32?static_cast<void *>(u32.data()):
                  dtype==PC_U64?static_cast<void *>(u64.data()):static_cast<void *>(f64.data());
    std::memcpy(plain,data.data(),data.size());
    uint8_t *ptr = nullptr;
    size_t n = 999;
    const int rc = pc_compress_intmult(plain,count,dtype,base,8,0,262144,&ptr,&n);
    std::unique_ptr<uint8_t,decltype(&pc_free)> out(ptr,pc_free);
    if (rc==PC_OK) {
        check(ptr && n>=15 && n<=data.size()+65536,"IntMult output extent");
        save("frame",ptr,n);
    } else {
        check(rc==PC_INVALID && !ptr && !n,"IntMult failed without clean PC_INVALID output");
    }
    std::printf("{\"native_status\":%d,\"output_bytes\":%zu,\"output_pointer_null\":%s}\n",rc,n,ptr?"false":"true");
    return rc==PC_OK?0:4;
}
struct Buffer {
    pcs_buffer b{};
    ~Buffer() { if (b.data) pcs_buffer_free(b.data,b.size); }
};
// pcs_file_open needs a numeric type; obtain it from the wrapped first chunk,
// not an external sidecar or input oracle. This is a frozen one-chunk fixture.
int type_of(const Bytes &frame) {
    check(frame.size()>=15 && std::memcmp(frame.data(),"pco!\3",5)==0,"standalone v3 signature");
    const size_t bits = (frame[6]&63)+1;
    const size_t wrapped = 6+(6+bits+7)/8;
    check(wrapped+2 < frame.size() && frame[wrapped]==4 && frame[wrapped+1]==1,"wrapped v4.1 header");
    const int dtype = frame[wrapped+2];
    check((dtype==PC_U32 || dtype==PC_U64) && (!frame[5] || frame[5]==dtype),"standalone u32/u64 type");
    return dtype;
}
void decode() {
    const auto frame = load("/inputs/frame",frame_cap);
    const int dtype = type_of(frame);
    const size_t width = pc_type_size(dtype);
    pcs_decoder *ptr = nullptr;
    int rc = pcs_file_open(frame.data(),frame.size(),dtype,max_rows,&ptr);
    std::unique_ptr<pcs_decoder,decltype(&pcs_decoder_destroy)> d(ptr,pcs_decoder_destroy);
    check(rc==PC_OK && d,"IntMult standalone open");
    Bytes restored;
    std::vector<size_t> spans;
    int done = 0;
    for (size_t i=0; !done && i<=max_rows/read_cap+1; ++i) {
        Buffer result;
        size_t rows = 0;
        rc = pcs_read(d.get(),read_cap,&result.b,&rows,&done);
        check(rc==PC_OK && rows<=read_cap && result.b.size==rows*width &&
              (done==0 || done==1) && (rows || done) && (!rows || result.b.data) &&
              restored.size()+result.b.size<=max_rows*width,"IntMult standalone drain extent");
        if (rows) restored.insert(restored.end(),result.b.data,result.b.data+result.b.size);
        spans.push_back(rows);
    }
    check(done && !spans.empty() && spans.back()==0 && !restored.empty(),"IntMult footer not consumed by zero-output terminal read");
    Buffer state;
    check(pcs_decoder_describe(d.get(),&state.b)==PC_OK && state.b.data && state.b.size>=2 && state.b.size<=4096 &&
          state.b.data[0]=='{' && state.b.data[state.b.size-1]=='}',"IntMult decoder describe");
    save("v",restored.data(),restored.size());
    std::printf("{\"spans\":[");
    for (size_t i=0;i<spans.size();++i) std::printf("%s%zu",i?",":"",spans[i]);
    std::printf("],\"state\":");
    check(fwrite(state.b.data,1,state.b.size,stdout)==state.b.size,"write decoder state");
    std::puts("}");
}
}

int run_intmult(int argc,char **argv) {
    const std::string_view op(argv[1]);
    int status;
    if (op=="intmult-encode" && argc==5) status=encode(argv[2],number(argv[3]),number(argv[4]));
    else if (op=="intmult-decode" && argc==2) { decode(); status=0; }
    else return 2;
    return fflush(stdout)==0 && !ferror(stdout)?status:3;
}
