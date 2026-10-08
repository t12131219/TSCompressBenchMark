// Reuse the independent source-probe oracle, never the shim's grammar scanner.
#define main original_probe_main
#include "source_guard.cpp"
#undef main
#include "tscb_adapter_v1.h"

extern "C" tscb_status_v1 tscb_get_telemetry_json(tscb_codec_handle_v1*, const char**, uint64_t*);
using Handle = tscb_codec_handle_v1;
using Status = tscb_status_v1;

static tscb_buffer_v1 buffer(void* pointer, uint64_t capacity, uint64_t used, bool integer) {
    tscb_buffer_v1 b{};
    b.data = pointer; b.capacity_bytes = capacity; b.used_bytes = used;
    b.dtype = integer ? TSCB_DTYPE_U32_LE_V1 : TSCB_DTYPE_BYTES_V1;
    b.rank = 1; b.shape[0] = integer ? (used ? used : capacity)/4 : capacity;
    b.strides_bytes[0] = integer ? 4 : 1; b.alignment_bytes = 1;
    return b;
}
static void ok(Status status) { need(status == TSCB_STATUS_OK_V1,"ABI operation failed"); }
static Handle* create(unsigned kind, bool marked) {
    const char* names[] = {"SIMPLE9","SIMPLE9HACKED","SIMPLE16"};
    std::string config = std::string("{\"codec\":\"") + names[kind] +
        "\",\"isa\":\"SCALAR\",\"mark_length\":" + (marked ? "true}" : "false}");
    Handle* h = nullptr; ok(tscb_create(config.data(),config.size(),&h));
    need(h != nullptr,"create produced null handle"); return h;
}
static uint32_t le32(const unsigned char* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
static void set32(unsigned char* p, uint32_t value) {
    for (unsigned i=0;i<4;++i) p[i]=static_cast<unsigned char>(value >> (8*i));
}
static void rehash(std::vector<unsigned char>& bytes) {
    uint64_t value=UINT64_C(14695981039346656037);
    for(size_t i=0;i<bytes.size()-8;++i) value=(value^bytes[i])*UINT64_C(1099511628211);
    for(unsigned i=0;i<8;++i) bytes[bytes.size()-8+i]=static_cast<unsigned char>(value>>(8*i));
}
static uint64_t json_integer(const char* json, const char* key) {
    const std::string needle=std::string("\"")+key+"\":";
    const char* p=std::strstr(json,needle.c_str()); need(p,"missing accounting key");
    return std::strtoull(p+needle.size(),nullptr,10);
}
static tscb_native_timing_v1 timing(Handle* h) {
    tscb_native_timing_v1 value{sizeof(value),1,0,0}; ok(tscb_get_native_timing(h,&value)); return value;
}
static void reject(Handle* h, std::vector<unsigned char> stream, unsigned n) {
    std::vector<uint32_t> output(n,0xaced1357U);
    auto in=buffer(stream.data(),stream.size(),stream.size(),false);
    auto out=buffer(output.data(),output.size()*4,0,true);
    auto before=output; auto descriptor=out;
    need(tscb_decompress(h,&in,&out)==TSCB_STATUS_CODEC_ERROR_V1,"malformed stream admitted");
    need(output==before && std::memcmp(&out,&descriptor,sizeof(out))==0,"decode failure published output");
}

static void case_check(unsigned kind, bool marked, const std::vector<uint32_t>& values,
                       unsigned offset, std::array<uint64_t,16>& selector_counts) {
    Handle* encoder=create(kind,marked);
    Handle* decoder=create(kind,!marked);
    const size_t n=values.size();
    std::vector<unsigned char> raw(n*4+offset+16,0x5a);
    if(n) std::memcpy(raw.data()+offset,values.data(),n*4);
    const auto raw_before=raw;
    auto in=buffer(raw.data()+offset,n*4,n*4,true);
    uint64_t bound=123;
    ok(tscb_compress_bound(encoder,&in,&bound));
    need(bound==40+n*4+(marked?4:0),"ABI bound differs");
    const auto words=oracle(values,kind==2,marked,kind==1);
    const size_t exact=40+words.size()*4;
    need(exact<=bound,"source wire exceeds bound");
    std::vector<unsigned char> storage(exact+offset+16,0xa5);
    auto out=buffer(storage.data()+offset,exact-1,0,false);
    const auto out_before=out;
    need(tscb_compress(encoder,&in,&out)==TSCB_STATUS_DST_TOO_SMALL_V1,"short output not rejected");
    need(std::memcmp(&out,&out_before,sizeof(out))==0 &&
         std::all_of(storage.begin(),storage.end(),[](unsigned char b){return b==0xa5;}),
         "encode failure changed output");
    ok(tscb_reset(encoder,0));
    out=buffer(storage.data()+offset,exact,0,false);
    ok(tscb_compress(encoder,&in,&out));
    need(out.used_bytes==exact && raw==raw_before,"encode count/input differs");
    const auto* wire=storage.data()+offset;
    need(std::memcmp(wire,"TSCBSPF1",8)==0 && le32(wire+8)==n && le32(wire+12)==kind
         && le32(wire+16)==marked && le32(wire+20)==words.size(),"ABI frame differs");
    for(size_t i=0;i<words.size();++i) need(le32(wire+32+i*4)==words[i],"ABI bypassed original wire");
    for(size_t i=marked?1:0;i<words.size();++i) ++selector_counts[words[i]>>28];
    for(size_t i=0;i<offset;++i) need(storage[i]==0xa5,"encode front canary changed");
    for(size_t i=offset+exact;i<storage.size();++i) need(storage[i]==0xa5,"encode back canary changed");
    auto final=buffer(nullptr,0,0,false); ok(tscb_finalize(encoder,&final));
    need(tscb_finalize(encoder,&final)==TSCB_STATUS_CODEC_ERROR_V1,"duplicate finalize accepted");
    const char* accounting;uint64_t length;ok(tscb_get_accounting_json(encoder,&accounting,&length));
    uint64_t billed=0;
    for(const char* key:{"value_bits","padding_bits","metadata_bits","container_bits","checksum_bits"})
        billed+=json_integer(accounting,key);
    need(billed==exact*8 && json_integer(accounting,"final_bits")==exact*8,"ABI accounting does not close");
    // Inspect physical field widths independently; all spare payload bits charged.
    const auto table=selectors(kind==2);
    uint64_t logical=0, value_bits=0, padding_bits=0;
    for(size_t i=marked?1:0;i<words.size();++i){
        const auto selector=words[i]>>28;
        bool zero=kind==1 && selector==9;
        const auto& widths=table[zero?0:selector];
        size_t count=std::min<uint64_t>(widths.size(),n-logical);
        unsigned bits=0;if(!zero) for(size_t j=0;j<count;++j) bits+=widths[j];
        value_bits+=bits;padding_bits+=28-bits;logical+=count;
    }
    need(json_integer(accounting,"value_bits")==value_bits &&
         json_integer(accounting,"padding_bits")==padding_bits,"ABI component ledger differs");
    const auto first=timing(encoder),second=timing(encoder);
    need(first.native_encode_wall_ns==second.native_encode_wall_ns,"timer query cleared totals");
    need(first.native_decode_wall_ns==0,"encode reported decoder work");
    auto compressed=buffer(storage.data()+offset,exact,exact,false);
    std::vector<unsigned char> recovered(n*4+offset+16,0xcc);
    auto decoded=buffer(recovered.data()+offset,n*4,0,true);
    if(n){
        auto short_decoded=buffer(recovered.data()+offset,(n-1)*4,0,true);
        const auto saved=short_decoded;
        need(tscb_decompress(decoder,&compressed,&short_decoded)==TSCB_STATUS_DST_TOO_SMALL_V1,
             "short decode not rejected");
        need(std::memcmp(&saved,&short_decoded,sizeof(saved))==0 &&
             std::all_of(recovered.begin(),recovered.end(),[](unsigned char b){return b==0xcc;}),
             "short decode changed output");
    }
    const auto compressed_before=storage;
    ok(tscb_decompress(decoder,&compressed,&decoded));
    need(decoded.used_bytes==n*4 && (!n || std::memcmp(decoded.data,values.data(),n*4)==0),"roundtrip differs");
    need(storage==compressed_before,"decoder changed compressed input");
    for(size_t i=0;i<offset;++i) need(recovered[i]==0xcc,"decode front canary changed");
    for(size_t i=offset+n*4;i<recovered.size();++i) need(recovered[i]==0xcc,"decode back canary changed");
    const auto decoder_first=timing(decoder);
    decoded.used_bytes=0;ok(tscb_decompress(decoder,&compressed,&decoded));
    need(timing(decoder).native_decode_wall_ns>=decoder_first.native_decode_wall_ns,"decode totals did not accumulate");
    ok(tscb_set_native_timing(encoder,0));ok(tscb_reset(encoder,0));
    auto disabled=timing(decoder);(void)disabled;
    std::vector<unsigned char> untimed(exact,0);
    auto untimed_out=buffer(untimed.data(),exact,0,false);ok(tscb_compress(encoder,&in,&untimed_out));
    need(std::equal(untimed.begin(),untimed.end(),wire),"timer toggle changed stream");
    tscb_native_timing_v1 unavailable{sizeof(unavailable),1,99,99};
    need(tscb_get_native_timing(encoder,&unavailable)==TSCB_STATUS_UNSUPPORTED_V1
         && unavailable.native_encode_wall_ns==99,"disabled native timing falsely published");
    const char* telemetry; ok(tscb_get_telemetry_json(decoder,&telemetry,&length));
    need(json_integer(telemetry,"native_raw_bytes")==n*4 &&
         json_integer(telemetry,"native_payload_bytes")==words.size()*4,"API telemetry differs");
    ok(tscb_destroy(encoder));ok(tscb_destroy(decoder));
}

static void boundaries(unsigned kind, bool marked) {
    Handle* h=create(kind,marked);
    uint32_t value=uint32_t(1)<<28;
    std::array<unsigned char,256> target;target.fill(0xa5);
    auto in=buffer(&value,4,4,true),out=buffer(target.data(),target.size(),0,false);
    const auto saved=out;const auto before=timing(h);
    need(tscb_compress(h,&in,&out)==TSCB_STATUS_UNSUPPORTED_V1,"source-domain failure accepted");
    need(std::memcmp(&out,&saved,sizeof(saved))==0 && value==(uint32_t(1)<<28)
         && std::all_of(target.begin(),target.end(),[](unsigned char c){return c==0xa5;}),
         "source-domain rejection not atomic");
    need(timing(h).native_encode_wall_ns==before.native_encode_wall_ns,"rejected domain called codec");
    value=1;out=buffer(&value,4,0,false);
    need(tscb_compress(h,&in,&out)==TSCB_STATUS_INVALID_ARGUMENT_V1,"overlap accepted");
    auto final=buffer(nullptr,0,0,false);
    need(tscb_finalize(h,&final)==TSCB_STATUS_FINALIZE_REQUIRED_V1,"finalize without update accepted");
    for(unsigned i=0;i<8;++i){
        auto bad=in;
        if(i==0)bad.reserved=1;
        if(i==1)bad.rank=2;
        if(i==2)bad.strides_bytes[0]=8;
        if(i==3)bad.shape[0]=2;
        if(i==4)bad.shape[1]=1;
        if(i==5)bad.alignment_bytes=3;
        if(i==6)bad.dtype=TSCB_DTYPE_F32_LE_V1;
        if(i==7)bad.used_bytes=8;
        uint64_t bound=991;
        need(tscb_compress_bound(h,&bad,&bound)==TSCB_STATUS_INVALID_ARGUMENT_V1 && bound==991,
             "invalid descriptor accepted/changed bound");
    }
    auto huge=in;huge.shape[0]=16777217;huge.capacity_bytes=huge.used_bytes=huge.shape[0]*4;
    uint64_t bound=991;
    need(tscb_compress_bound(h,&huge,&bound)==TSCB_STATUS_UNSUPPORTED_V1 && bound==991,"resource bound accepted");
    const auto words=oracle({1},kind==2,marked,kind==1);
    std::vector<unsigned char> stream(40+words.size()*4,0);
    std::memcpy(stream.data(),"TSCBSPF1",8);set32(stream.data()+8,1);set32(stream.data()+12,kind);
    set32(stream.data()+16,marked);set32(stream.data()+20,words.size());
    for(size_t i=0;i<words.size();++i)set32(stream.data()+32+i*4,words[i]);
    rehash(stream);
    for(size_t length=0;length<stream.size();++length){
        auto truncated=std::vector<unsigned char>(stream.begin(),stream.begin()+length);
        reject(h,truncated,1);
    }
    for(unsigned mutation=0;mutation<7;++mutation){
        auto broken=stream;
        if(mutation==0)broken[0]^=1;
        if(mutation==1)set32(broken.data()+8,0);
        if(mutation==2)set32(broken.data()+12,(kind+1)%3);
        if(mutation==3)set32(broken.data()+16,2);
        if(mutation==4)set32(broken.data()+24,1);
        if(mutation==5)broken[32+(marked?4:0)]|=1; // zero tail bits with valid checksum
        if(mutation==6)set32(broken.data()+20,0);
        rehash(broken);reject(h,broken,2);
    }
    if(kind!=2){
        auto broken=stream;set32(broken.data()+32+(marked?4:0),15U<<28);rehash(broken);reject(h,broken,1);
    }
    // Exact readable/writable extents beside protected pages, including decoder tail.
    Protected input(1), encoded(stream.size()/4), output(1);
    input.data[0]=1;input.read_only();
    in=buffer(input.data,4,4,true);out=buffer(encoded.data,stream.size(),0,false);
    ok(tscb_compress(h,&in,&out));encoded.read_only();
    auto compressed=buffer(encoded.data,stream.size(),stream.size(),false);
    auto restored=buffer(output.data,4,0,true);ok(tscb_decompress(h,&compressed,&restored));
    need(output.data[0]==1,"guarded decode failed");
    ok(tscb_destroy(h));
}

int main() {
    try {
        const size_t lengths[]={0,1,2,3,4,5,7,8,9,14,15,16,17,27,28,29,55,56,57,127,128,129,255,256,257};
        uint64_t cases=0;
        for(unsigned kind=0;kind<3;++kind) for(bool marked:{false,true}){
            std::array<uint64_t,16> selectors_seen{};
            for(unsigned bits=0;bits<=28;++bits)for(size_t length:lengths)for(unsigned pattern=0;pattern<7;++pattern){
                std::vector<uint32_t> values(length);
                uint32_t mask=(uint32_t(1)<<bits)-1,random=0x6d2b79f5;
                for(size_t i=0;i<length;++i){
                    random=random*1664525U+1013904223U;
                    values[i]=pattern==0?0:pattern==1?mask:pattern==2?uint32_t(i)&mask:
                        pattern==3?(i%2?mask:0):pattern==4?random&mask:
                        pattern==5?(i%21>=7&&i%21<14?3U:1U)&mask:(i%21>=14?3U:1U)&mask;
                }
                case_check(kind,marked,values,cases%4,selectors_seen);++cases;
            }
            for(unsigned selector=0;selector<(kind==2?16U:kind==1?10U:9U);++selector)
                need(selectors_seen[selector]>0,"bounded ABI omitted a legal selector");
            boundaries(kind,marked);
        }
        std::cout << "{\"status\":\"PASS\",\"cases\":"<<cases
                  <<",\"variants\":6,\"input_alignments\":4,\"all_legal_selectors\":true,"
                  <<"\"atomic_failures\":true,\"exact_guard_pages\":true,"
                  <<"\"native_timer_toggle_and_accumulation\":true}"<<std::endl;
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<std::endl;return 2;}
}
