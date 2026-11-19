// Bounded diagnostics over the frozen native C ABI; inputs are frozen fixtures or their own PBEP frames.
#include "tba.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
constexpr size_t limit = 2 << 20;
void require(bool ok,const char* what) { if (!ok) throw std::runtime_error(what); }
struct Buffer { tba_buffer value{}; ~Buffer() { tba_free(&value); } };
template<class T> std::vector<T> read(const char* path) {
    std::ifstream f(path,std::ios::binary | std::ios::ate);
    const auto end = f.tellg();
    require(end >= 0 && size_t(end)<=limit && size_t(end)%sizeof(T)==0,"invalid fixture extent");
    auto data = std::vector<T>(size_t(end)/sizeof(T));
    f.seekg(0);
    if (end) require(bool(f.read(reinterpret_cast<char*>(data.data()),end)),"fixture read failed");
    require(f.peek()==EOF,"unexpected fixture tail");
    return data;
}
void write(const std::string& name,const void* data,size_t bytes) {
    require(bytes<=limit && (!bytes || data),"invalid output extent");
    std::ofstream f(name,std::ios::binary);
    if (bytes) require(bool(f.write(static_cast<const char*>(data),bytes)),"output write failed");
    f.close(); require(bool(f),"output close failed");
}
size_t integer(const char* arg,size_t max) {
    char* end = nullptr; const auto v = std::strtoull(arg,&end,10);
    require(end != arg && !*end && v<=max,"invalid integer argument"); return v;
}
double number(const char* arg) {
    char* end = nullptr; const auto v = std::strtod(arg,&end);
    require(end != arg && !*end && std::isfinite(v),"invalid floating argument"); return v;
}
void encode(int argc,char** argv) {
    require(argc>=10,"missing encode options");
    auto src = read<double>(argv[2]);
    const auto k = integer(argv[3],16);
    require(k && size_t(argc)==10+2*k,"invalid encode option extent");
    std::array<double,16> eps{};
    std::array<unsigned,16> res{};
    for (size_t i=0;i<k;++i) { eps[i]=number(argv[10+i]); res[i]=integer(argv[10+k+i],64); }
    auto cfg = tba_pbepla_defaults(eps.data(),k);
    cfg.max_delay=integer(argv[4],65536); cfg.connected=integer(argv[5],1); cfg.symmetric_band=integer(argv[6],1);
    cfg.has_source_range=integer(argv[7],1); cfg.source_min=number(argv[8]); cfg.source_max=number(argv[9]);
    cfg.resolutions=res.front() ? res.data() : nullptr;
    char err[256]{}; Buffer out; tba_pbepla_info info{}, inspect{};
    require(tba_pbepla_encode_ex(src.data(),src.size(),&cfg,&info,&out.value,err,sizeof err)==0,err);
    require(tba_pbepla_inspect(out.value.data,out.value.bytes,&inspect,err,sizeof err)==0,err);
    require(out.value.count==src.size() && inspect.value_count==src.size() && inspect.layer_present==k &&
            inspect.layer_count==k && inspect.max_delay==cfg.max_delay && inspect.connected==cfg.connected &&
            inspect.symmetric_band==cfg.symmetric_band && info.header_bytes==inspect.header_bytes && info.payload_bytes==inspect.payload_bytes,
            "native descriptor differs");
    write("full",out.value.data,out.value.bytes);
    std::cout << "{\"count\":"<<out.value.count<<",\"layers\":"<<k<<",\"header\":"<<inspect.header_bytes
              <<",\"payload\":"<<inspect.payload_bytes<<"}\n";
}
void assert_reject(const std::vector<unsigned char>& bytes,unsigned layer,size_t n,const char* message) {
    char err[256]{}; Buffer out;
    require(tba_decode(TBA_PBEPLA_RR,bytes.data(),bytes.size(),layer,n,&out.value,err,sizeof err)==-1 &&
            !out.value.data && !out.value.bytes && !out.value.count && std::string_view(err)==message,"native rejection differs");
}
void prefixes(const std::vector<unsigned char>& bytes,bool controls) {
    tba_pbepla_info info{}; char err[256]{};
    require(tba_pbepla_inspect(bytes.data(),bytes.size(),&info,err,sizeof err)==0,err);
    const auto n=info.value_count; const auto k=info.layer_present;
    require(n<=limit/8 && k && k<=16 && k==info.layer_count,"prefix profile differs");
    std::vector<std::vector<unsigned char>> decoded;
    for (unsigned layer=1;layer<=k;++layer) {
        Buffer prefix;
        require(tba_pbepla_prefix(bytes.data(),bytes.size(),layer,&prefix.value,err,sizeof err)==0,err);
        require(prefix.value.count==n,"native prefix count differs");
        write("L"+std::to_string(layer),prefix.value.data,prefix.value.bytes);
        if (!controls) continue;
        Buffer from_full, from_prefix;
        require(tba_decode(TBA_PBEPLA_RR,bytes.data(),bytes.size(),layer,n,&from_full.value,err,sizeof err)==0,err);
        require(tba_decode(TBA_PBEPLA_RR,prefix.value.data,prefix.value.bytes,layer,n,&from_prefix.value,err,sizeof err)==0,err);
        const auto& a=from_full.value; const auto& b=from_prefix.value;
        require(a.count==n && b.count==n && a.bytes==8*n && b.bytes==8*n && (!n || std::memcmp(a.data,b.data,a.bytes)==0),
                "full versus detached native value differs");
        decoded.emplace_back(a.bytes);
        if (a.bytes) std::memcpy(decoded.back().data(),a.data,a.bytes);
    }
    std::cout << "{\"count\":"<<n<<",\"layers\":"<<k;
    if (controls) {
        constexpr auto bad="pbepla_rr: requested layers exceed the stored layers";
        assert_reject(bytes,0,n,bad); assert_reject(bytes,k+1,n,bad);
        std::cout << ",\"native_rejects\":{\"zero_layers\":\""<<bad<<"\",\"absent_layer\":\""<<bad<<'"';
        if (n) {
            constexpr auto budget="pbepla_rr: value count exceeds the decode limit";
            assert_reject(bytes,1,n-1,budget); std::cout<<",\"value_budget\":\""<<budget<<'"';
        }
        if (info.payload_bytes) {
            constexpr auto crc="pbepla_rr: payload checksum mismatch";
            auto bad_bytes=bytes; bad_bytes.back()^=1;
            assert_reject(bad_bytes,1,n,crc); std::cout<<",\"later_crc_even_for_layer1\":\""<<crc<<'"';
        }
        std::cout<<"},\"targets\":[";
        for (unsigned i=0;i<=k;++i) {
            const auto target=i<k ? info.effective_eps[i] : info.effective_eps[k-1]/2;
            unsigned used=0; int met=0; Buffer out;
            require(tba_pbepla_approximate(bytes.data(),bytes.size(),target,n,&used,&met,&out.value,err,sizeof err)==0,err);
            require(used>0 && used<=k && out.value.bytes==8*n && out.value.count==n &&
                    (!n || !std::memcmp(out.value.data,decoded[used-1].data(),8*n)),"target recovery differs");
            std::cout<<(i ? "," : "")<<"{\"requested\":"<<target<<",\"layers_used\":"<<used
                     <<",\"bound_met\":"<<(met ? "true":"false")<<'}';
        }
        std::cout<<']';
    }
    std::cout<<"}\n";
}
struct Sink { std::vector<double> values; size_t cap; bool abort; };
int emit(void* ptr,double value) {
    auto& sink=*static_cast<Sink*>(ptr);
    if (sink.values.size()>=sink.cap) return -1;
    sink.values.push_back(value);
    return sink.abort ? -1 : 0;
}
void decode_stream(const std::vector<unsigned char>& bytes,unsigned layers,size_t n) {
    char err[256]{}; Sink sink{{},n,false}; sink.values.reserve(n);
    require(tba_pbepla_decode_stream(bytes.data(),bytes.size(),layers,n,&sink,emit,err,sizeof err)==0,err);
    require(sink.values.size()==n,"emission count differs");
    if (n) {
        Sink aborted{{},1,true}; aborted.values.reserve(1);
        require(tba_pbepla_decode_stream(bytes.data(),bytes.size(),layers,n,&aborted,emit,err,sizeof err)==-1 &&
                aborted.values.size()==1 && std::string_view(err).find("emit failed")!=std::string_view::npos,"emit rejection differs");
    }
    write("out",sink.values.data(),n*8);
    std::cout<<"{\"emitted\":"<<n<<",\"abort_after\":"<<(n ? 1 : 0)<<"}\n";
}
}
int main(int argc,char** argv) {
    try {
        require(argc>=3,"invalid invocation");
        std::cout<<std::setprecision(17);
        const std::string_view op=argv[1];
        if (op=="encode") encode(argc,argv);
        else if ((op=="prefixes" || op=="prefixes-controls") && argc==3)
            prefixes(read<unsigned char>(argv[2]),op=="prefixes-controls");
        else if (op=="stream-decode" && argc==5)
            decode_stream(read<unsigned char>(argv[2]),integer(argv[3],16),integer(argv[4],limit/8));
        else if (op=="partial-reject" && argc==4) {
            constexpr auto message="pbepla_rr: payload length does not match the header";
            assert_reject(read<unsigned char>(argv[2]),1,integer(argv[3],limit/8),message);
            std::cout<<"{\"diagnostic\":\""<<message<<"\"}\n";
        } else require(false,"unknown operation");
        return std::cout ? 0 : 1;
    } catch (const std::exception& err) { std::cerr<<err.what()<<'\n';return 2; }
}
