// Independent linear wire oracle against the actual shipped shared library.
#include "tscb_adapter_v1.h"
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <sys/mman.h>
#include <unistd.h>

extern "C" tscb_status_v1 tscb_get_telemetry_json(tscb_codec_handle_v1*,const char**,uint64_t*);
using Handle=tscb_codec_handle_v1;
using Status=tscb_status_v1;
static const char* names[]={"PACK32","TURBO","SC","BMI2","HORIZONTAL"};
static const char* isas[]={"SCALAR","SCALAR","SCALAR","AVX2_BMI2","SSE4_1"};
static uint64_t cases=0, malformed=0, guards=0;
static void need(bool ok,const char* message) {
    if (!ok) { std::fprintf(stderr,"%s (case=%llu)\n",message,static_cast<unsigned long long>(cases)); std::exit(2); }
}
static void ok(Status value) { need(value==TSCB_STATUS_OK_V1,"ABI call failed"); }
static tscb_buffer_v1 buffer(void* p,uint64_t capacity,uint64_t used,bool integer) {
    tscb_buffer_v1 b{}; b.data=p;b.capacity_bytes=capacity;b.used_bytes=used;
    b.dtype=integer?TSCB_DTYPE_U32_LE_V1:TSCB_DTYPE_BYTES_V1;b.rank=1;
    b.shape[0]=integer?(used?used:capacity)/4:capacity;b.strides_bytes[0]=integer?4:1;b.alignment_bytes=1;
    return b;
}
static Handle* create(unsigned kind,unsigned width,bool automatic) {
    char config[160],w[16];
    if(automatic)std::snprintf(w,sizeof(w),"\"AUTO\"");else std::snprintf(w,sizeof(w),"%u",width);
    int length=std::snprintf(config,sizeof(config),"{\"bit_width\":%s,\"codec\":\"%s\",\"isa\":\"%s\"}",w,names[kind],isas[kind]);
    Handle* h=nullptr;ok(tscb_create(config,length,&h));need(h,"null created handle");return h;
}
static uint32_t read32(const unsigned char* p) {
    uint32_t v=0;for(unsigned i=0;i<4;++i)v|=uint32_t(p[i])<<(8*i);return v;
}
static uint64_t read64(const unsigned char* p) {
    uint64_t v=0;for(unsigned i=0;i<8;++i)v|=uint64_t(p[i])<<(8*i);return v;
}
static void set32(unsigned char* p,uint32_t v) {
    for(unsigned i=0;i<4;++i)p[i]=static_cast<unsigned char>(v>>(8*i));
}
static void rehash(std::vector<unsigned char>& wire) {
    uint64_t value=UINT64_C(14695981039346656037);
    for(size_t i=0;i<wire.size()-8;++i)value=(value^wire[i])*UINT64_C(1099511628211);
    for(unsigned i=0;i<8;++i)wire[wire.size()-8+i]=static_cast<unsigned char>(value>>(8*i));
}
static unsigned minimum_width(const std::vector<uint32_t>& input) {
    uint32_t value=0;for(uint32_t v:input)value|=v;
    unsigned width=0;while(value){++width;value>>=1;}return width;
}
static std::vector<unsigned char> oracle(const std::vector<uint32_t>& input,unsigned width) {
    std::vector<unsigned char> result((input.size()*width+7)/8,0);
    for(size_t i=0;i<input.size();++i)for(unsigned k=0;k<width;++k){
        size_t bit=i*width+k;
        result[bit/8]|=static_cast<unsigned char>(((input[i]>>k)&1U)<<(bit%8));
    }
    return result;
}
static uint64_t json_integer(const char* json,const char* name) {
    std::string key=std::string("\"")+name+"\":";
    const char* position=std::strstr(json,key.c_str());need(position,"missing JSON field");
    return std::strtoull(position+key.size(),nullptr,10);
}
static tscb_native_timing_v1 timing(Handle* h) {
    tscb_native_timing_v1 value{sizeof(value),1,0,0};ok(tscb_get_native_timing(h,&value));return value;
}
static bool sentinel(const std::vector<unsigned char>& b,unsigned char v) {
    return std::all_of(b.begin(),b.end(),[v](unsigned char c){return c==v;});
}
static void case_check(unsigned kind,unsigned supplied,bool automatic,
                       const std::vector<uint32_t>& input,unsigned offset) {
    Handle* encoder=create(kind,supplied,automatic),*decoder=create(kind,32,false);
    tscb_native_timing_v1 disabled{sizeof(disabled),1,77,88};
    need(tscb_get_native_timing(encoder,&disabled)==TSCB_STATUS_UNSUPPORTED_V1
         && disabled.native_encode_wall_ns==77,"native handle must start disabled");
    ok(tscb_set_native_timing(encoder,1));ok(tscb_set_native_timing(decoder,1));
    const unsigned width=automatic?minimum_width(input):supplied;
    auto payload=oracle(input,width);
    const size_t n=input.size(),exact=40+payload.size();
    std::vector<unsigned char> raw(n*4+offset+16,0x5a),wire(exact+offset+16,0xa5);
    if(n)std::memcpy(raw.data()+offset,input.data(),n*4);
    const auto raw_before=raw;
    auto in=buffer(raw.data()+offset,n*4,n*4,true);
    uint64_t bound=777;ok(tscb_compress_bound(encoder,&in,&bound));need(bound==exact,"bound not exact");
    auto out=buffer(wire.data()+offset,exact-1,0,false);const auto saved=out;
    need(tscb_compress(encoder,&in,&out)==TSCB_STATUS_DST_TOO_SMALL_V1,"short encode admitted");
    need(std::memcmp(&saved,&out,sizeof(out))==0 && sentinel(wire,0xa5),"short encode not atomic");
    need(timing(encoder).native_encode_wall_ns==0,"short capacity called native kernel");
    out=buffer(wire.data()+offset,exact,0,false);ok(tscb_compress(encoder,&in,&out));
    const auto* p=wire.data()+offset;
    need(out.used_bytes==exact && raw==raw_before,"encode modified input/count");
    need(!std::memcmp(p,"TSCBLIP1",8) && read32(p+8)==n && read32(p+12)==kind
         && read32(p+16)==width && read32(p+20)==automatic && read64(p+24)==payload.size(),"frame metadata differs");
    need(std::equal(payload.begin(),payload.end(),p+32),"native payload differs from linear oracle");
    for(size_t i=0;i<offset;++i)need(wire[i]==0xa5,"encode front canary changed");
    for(size_t i=offset+exact;i<wire.size();++i)need(wire[i]==0xa5,"encode rear canary changed");
    auto final=buffer(nullptr,0,0,false);const char* json;uint64_t length;
    need(tscb_get_accounting_json(encoder,&json,&length)==TSCB_STATUS_FINALIZE_REQUIRED_V1,"accounting before finalize");
    ok(tscb_finalize(encoder,&final));
    need(tscb_finalize(encoder,&final)==TSCB_STATUS_CODEC_ERROR_V1,"duplicate finalize admitted");
    ok(tscb_get_accounting_json(encoder,&json,&length));
    uint64_t billed=0;
    for(const char* key:{"container_bits","metadata_bits","checksum_bits","value_bits","padding_bits"})
        billed+=json_integer(json,key);
    need(billed==exact*8 && json_integer(json,"final_bits")==exact*8
         && json_integer(json,"value_bits")==n*width
         && json_integer(json,"padding_bits")==payload.size()*8-n*width,"physical ledger differs");
    auto t1=timing(encoder),t2=timing(encoder);
    need(t1.native_encode_wall_ns==t2.native_encode_wall_ns && t1.native_decode_wall_ns==0,"timer query destructive");
    auto compressed=buffer(wire.data()+offset,exact,exact,false);
    std::vector<unsigned char> decoded(n*4+offset+16,0xcc);
    auto decoded_out=buffer(decoded.data()+offset,n*4,0,true);
    if(n){
        auto short_out=buffer(decoded.data()+offset,(n-1)*4,0,true);const auto before=short_out;
        need(tscb_decompress(decoder,&compressed,&short_out)==TSCB_STATUS_DST_TOO_SMALL_V1
             && sentinel(decoded,0xcc) && !std::memcmp(&before,&short_out,sizeof(before)),"short decode not atomic");
    }
    const auto compressed_before=wire;
    ok(tscb_decompress(decoder,&compressed,&decoded_out));
    need(decoded_out.used_bytes==n*4 && (!n || !std::memcmp(decoded_out.data,input.data(),n*4)),"roundtrip differs");
    need(wire==compressed_before,"decoder modified input");
    for(size_t i=0;i<offset;++i)need(decoded[i]==0xcc,"decode front canary changed");
    for(size_t i=offset+n*4;i<decoded.size();++i)need(decoded[i]==0xcc,"decode rear canary changed");
    t1=timing(decoder);decoded_out.used_bytes=0;ok(tscb_decompress(decoder,&compressed,&decoded_out));
    t2=timing(decoder);need(t2.native_decode_wall_ns>=t1.native_decode_wall_ns,"decode timer did not accumulate");
    ok(tscb_get_telemetry_json(decoder,&json,&length));
    need(json_integer(json,"native_raw_bytes")==n*4 && json_integer(json,"native_payload_bytes")==payload.size()
         && json_integer(json,"native_staging_allocation_count")==2
         && json_integer(json,"internal_input_padding_bytes")==528
         && json_integer(json,"internal_output_headroom_bytes")==512,"internal padding telemetry differs");
    ok(tscb_set_native_timing(encoder,0));ok(tscb_reset(encoder,0));
    std::vector<unsigned char> untimed(exact,0);auto untimed_out=buffer(untimed.data(),exact,0,false);
    ok(tscb_compress(encoder,&in,&untimed_out));
    need(std::equal(untimed.begin(),untimed.end(),p),"timer toggle changed wire");
    need(tscb_get_native_timing(encoder,&disabled)==TSCB_STATUS_UNSUPPORTED_V1,"reset enabled disabled timer");
    ok(tscb_reset(decoder,0));need(timing(decoder).native_decode_wall_ns==0,"reset did not clear timer");
    ok(tscb_destroy(encoder));ok(tscb_destroy(decoder));++cases;
}
struct Guard {
    unsigned char* mapping;
    size_t writable,size;
    unsigned char* data;
    explicit Guard(size_t n):size(n) {
        const size_t page=static_cast<size_t>(sysconf(_SC_PAGESIZE));
        writable=((n+page-1)/page+1)*page;
        mapping=static_cast<unsigned char*>(mmap(nullptr,writable+page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
        need(mapping!=MAP_FAILED,"guard mmap failed");
        need(!mprotect(mapping+writable,page,PROT_NONE),"guard protect failed");data=mapping+writable-n;
    }
    void readonly() { need(!mprotect(mapping,writable,PROT_READ),"read-only protect failed"); }
    ~Guard(){munmap(mapping,writable+static_cast<size_t>(sysconf(_SC_PAGESIZE)));}
};
static std::vector<unsigned char> encoded(unsigned kind,unsigned width,const std::vector<uint32_t>& values) {
    auto* h=create(kind,width,false);
    auto in=buffer(const_cast<uint32_t*>(values.data()),values.size()*4,values.size()*4,true);
    uint64_t count=0;ok(tscb_compress_bound(h,&in,&count));
    std::vector<unsigned char> result(count,0);auto out=buffer(result.data(),count,0,false);
    ok(tscb_compress(h,&in,&out));ok(tscb_destroy(h));return result;
}
static void reject(Handle* h,const std::vector<unsigned char>& wire,size_t n) {
    std::vector<unsigned char> recovered(n*4,0xa5);
    auto in=buffer(const_cast<unsigned char*>(wire.data()),wire.size(),wire.size(),false);
    auto out=buffer(recovered.data(),recovered.size(),0,true);const auto before=out;
    need(tscb_decompress(h,&in,&out)==TSCB_STATUS_CODEC_ERROR_V1,"malformed input accepted");
    need(sentinel(recovered,0xa5) && !std::memcmp(&before,&out,sizeof(out)),"malformed decode changed output");++malformed;
}
static void boundaries(unsigned kind,unsigned width) {
    const uint32_t mask=static_cast<uint32_t>((UINT64_C(1)<<width)-1);
    std::vector<uint32_t> values(129,mask);auto wire=encoded(kind,width,values);
    auto* h=create(kind,32,true);
    for(size_t n=0;n<wire.size();++n)reject(h,std::vector<unsigned char>(wire.begin(),wire.begin()+n),129);
    auto extra=wire;extra.push_back(0);reject(h,extra,129);
    for(unsigned field:{0U,8U,12U,16U,20U,24U,32U}){
        auto bad=wire;
        if(field==0)bad[0]^=1;
        if(field==8)set32(bad.data()+8,16777217);
        if(field==12)set32(bad.data()+12,(kind+1)%5);
        if(field==16)set32(bad.data()+16,33);
        if(field==20)set32(bad.data()+20,2);
        if(field==24)bad[24]^=1;
        if(field==32){bad[bad.size()-1]^=1;reject(h,bad,129);continue;}
        rehash(bad);reject(h,bad,129);
    }
    if(width%8){auto bad=wire;bad[32+(129*width+7)/8-1]|=0x80;rehash(bad);reject(h,bad,129);}
    if(width){
        auto bad=encoded(kind,width,std::vector<uint32_t>(129,0));set32(bad.data()+20,1);rehash(bad);reject(h,bad,129);
    }
    for(unsigned n:{0U,1U,2U,31U,32U,33U,127U,128U,129U}){
        Guard raw(n*4);if(n)std::memcpy(raw.data,values.data(),n*4);raw.readonly();
        auto* encoder=create(kind,width,false);
        auto in=buffer(raw.data,n*4,n*4,true);uint64_t length;ok(tscb_compress_bound(encoder,&in,&length));
        Guard packed(length);auto out=buffer(packed.data,length,0,false);ok(tscb_compress(encoder,&in,&out));
        packed.readonly();Guard destination(n*4);
        auto compressed=buffer(packed.data,length,length,false),decoded=buffer(destination.data,n*4,0,true);
        ok(tscb_decompress(h,&compressed,&decoded));need(!n || !std::memcmp(destination.data,raw.data,n*4),"exact guard/read-only roundtrip");
        ok(tscb_destroy(encoder));++guards;
    }
    ok(tscb_destroy(h));
}
static void descriptor_checks(unsigned kind) {
    auto* h=create(kind,0,false);
    uint32_t v=1;std::array<unsigned char,64> target;target.fill(0xa5);
    auto in=buffer(&v,4,4,true),out=buffer(target.data(),target.size(),0,false);const auto saved=out;
    need(tscb_compress(h,&in,&out)==TSCB_STATUS_UNSUPPORTED_V1
         && !std::memcmp(&out,&saved,sizeof(out)) && std::all_of(target.begin(),target.end(),[](unsigned char c){return c==0xa5;}),"width domain rejection");
    auto final=buffer(nullptr,0,0,false);
    need(tscb_finalize(h,&final)==TSCB_STATUS_FINALIZE_REQUIRED_V1,"finalize before update");
    v=0;out=buffer(&v,4,0,false);
    need(tscb_compress(h,&in,&out)==TSCB_STATUS_INVALID_ARGUMENT_V1,"overlap accepted");
    for(unsigned i=0;i<12;++i){
        auto bad=in;
        if(i==0)bad.reserved=1;
        if(i==1)bad.rank=2;
        if(i==2)bad.strides_bytes[0]=8;
        if(i==3)bad.shape[0]=2;
        if(i==4)bad.shape[1]=1;
        if(i==5)bad.alignment_bytes=3;
        if(i==6)bad.dtype=TSCB_DTYPE_F32_LE_V1;
        if(i==7)bad.used_bytes=8;
        if(i==8)bad.data=nullptr;
        if(i==9)bad.ownership=3;
        if(i==10)bad.strides_bytes[1]=1;
        if(i==11)bad.capacity_bytes=3;
        uint64_t bound=333;need(tscb_compress_bound(h,&bad,&bound)==TSCB_STATUS_INVALID_ARGUMENT_V1 && bound==333,"bad descriptor bound");
    }
    auto huge=in;huge.shape[0]=16777217;huge.capacity_bytes=huge.used_bytes=huge.shape[0]*4;
    uint64_t bound=333;need(tscb_compress_bound(h,&huge,&bound)==TSCB_STATUS_UNSUPPORTED_V1 && bound==333,"count limit");
    uint64_t used=333;need(tscb_query(h,nullptr,0,nullptr,0,&used)==TSCB_STATUS_UNSUPPORTED_V1 && used==333,"query unsupported");
    ok(tscb_destroy(h));
}
int main() {
    uint64_t state=UINT64_C(0x4b177af039264201);
    const unsigned lengths[]={0,1,2,7,15,16,17,31,32,33,63,64,65,127,128,129,255,256,257,511,512,513,8193};
    for(unsigned kind=0;kind<5;++kind){
        descriptor_checks(kind);
        for(unsigned width=0;width<=32;++width){
            const uint32_t mask=static_cast<uint32_t>((UINT64_C(1)<<width)-1);
            for(unsigned n:lengths)for(unsigned pattern=0;pattern<5;++pattern){
                std::vector<uint32_t> input(n,0);
                for(unsigned i=0;i<n;++i){
                    state^=state>>12;state^=state<<25;state^=state>>27;
                    uint32_t random=static_cast<uint32_t>((state*UINT64_C(2685821657736338717))>>32);
                    input[i]=pattern==0?0:pattern==1?mask:pattern==2?(i&mask):pattern==3?((i&1)?mask:0):(random&mask);
                }
                for(unsigned offset:{0U,1U,2U,3U})case_check(kind,width,false,input,offset);
                case_check(kind,width,true,input,1);
            }
            boundaries(kind,width);
        }
        std::fprintf(stderr,"ABI_VARIANT_DONE %s cases=%llu\n",names[kind],static_cast<unsigned long long>(cases));
    }
    std::printf("{\"status\":\"PASS\",\"cases\":%llu,\"variants\":5,\"widths\":33,\"input_alignments\":4,\"auto_width\":true,"
                "\"malformed_rejections\":%llu,\"guard_roundtrips\":%llu,\"atomic_failures\":true,\"exact_guard_pages\":true,"
                "\"readonly_input\":true,\"native_timer_toggle_and_accumulation\":true}\n",
                static_cast<unsigned long long>(cases),static_cast<unsigned long long>(malformed),static_cast<unsigned long long>(guards));
}
