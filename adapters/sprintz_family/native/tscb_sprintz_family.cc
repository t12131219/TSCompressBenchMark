// Binding only. The released Sprintz native port and Huff0 compile unchanged.
#include "sprintz_port.h"
#include "tsbench_core.hpp"
#include "tscb_native_timing.h"
#include <cstdio>
#include <memory>

namespace {
using Bytes=std::vector<uint8_t>;
using tsbench_core::require;
constexpr size_t header=24,limit=65536;
constexpr unsigned predictor=TSCB_SPRINTZ_PREDICTOR,huffman=TSCB_SPRINTZ_HUFFMAN;
constexpr char manifest[]="{\"abi_version\":1,\"algorithm\":\"" TSCB_SPRINTZ_KEY "\",\"implementation\":\"sprintz-native-20261017-api-v1\",\"frame\":\"SZF1\",\"isa\":\"AVX2_BMI1_BMI2_LZCNT_POPCNT\",\"threading\":\"SINGLE_THREAD\",\"qualification\":\"LIMITED_NATIVE_PORT\"}";
uint64_t le(const uint8_t* p,size_t n){uint64_t x=0;for(size_t i=0;i<n;++i)x|=uint64_t(p[i])<<(8*i);return x;}
void put(uint8_t* p,uint64_t x,size_t n){for(size_t i=0;i<n;++i){p[i]=static_cast<uint8_t>(x);x>>=8;}}
struct Settings{uint32_t path=0;};
Settings settings(const char* json,bool c1=false){
    tsbench_core::Parameters p(json);Settings s;size_t keys=0,known=0;bool quoted=false,escaped=false;
    for(const char* c=json?json:"{}";*c;++c){if(!quoted&&*c==':')++keys;if(*c=='"'&&!escaped)quoted=!quoted;if(*c=='\\'&&!escaped)escaped=true;else escaped=false;}
    for(const char* name:{"isa","native_timing","algorithm","path"})if(p.contains(name))++known;
    if(keys!=known)throw tsbench_core::Unsupported("unknown Sprintz parameter");
    if(p.contains("algorithm")){if(!c1)throw tsbench_core::Unsupported("library selects Sprintz algorithm");require(p.string("algorithm")==TSCB_SPRINTZ_KEY,"Sprintz identity mismatch");}
    else if(c1)throw std::invalid_argument("missing Sprintz identity");
    if(p.contains("isa")&&p.string("isa")!="AVX2_BMI1_BMI2_LZCNT_POPCNT")throw tsbench_core::Unsupported("Sprintz ISA profile mismatch");
    if(p.contains("native_timing"))(void)p.boolean("native_timing");
    if(p.contains("path"))s.path=static_cast<uint32_t>(p.integer("path",0,5));
    return s;
}
void cpu(){if(!sz_supported())throw tsbench_core::Unsupported("Sprintz requires Linux x86_64 AVX2/BMI1/BMI2/LZCNT/POPCNT");}
sz_config configuration(size_t width,size_t dims,const Settings& s,size_t bytes){
    if((width!=1&&width!=2)||dims<1||dims>128||bytes>limit||bytes%width)throw tsbench_core::Unsupported("Sprintz input outside integer/shape/64KiB profile");
    sz_config cfg{static_cast<uint32_t>(width*8),predictor,huffman,s.path,static_cast<uint32_t>(dims)};size_t bound=0;
    if(sz_bound(&cfg,bytes,&bound)!=SZ_OK)throw tsbench_core::Unsupported("unsupported Sprintz path/width/dimensions");return cfg;
}
void status(int rc){
    if(rc==SZ_OK)return;
    if(rc==SZ_CAPACITY)throw tsbench_core::Capacity("Sprintz output capacity too small");
    if(rc==SZ_PLATFORM||rc==SZ_ARGUMENT)throw tsbench_core::Unsupported("Sprintz unsupported platform/configuration");
    if(rc==SZ_MEMORY)throw std::bad_alloc();
    if(rc==SZ_MALFORMED)throw std::invalid_argument("malformed Sprintz payload");
    throw std::runtime_error("Sprintz native codec failure");
}
size_t bound(const sz_config& c,size_t n){size_t b=0;status(sz_bound(&c,n,&b));return tsbench_core::add(header,b);}
// Prefix is committed after the safe native API succeeds. No caller writes on failure.
size_t encode_frame(const sz_config& c,const uint8_t* input,size_t n,uint8_t* output,size_t capacity){
    if(!output||capacity<header)throw tsbench_core::Capacity("Sprintz frame capacity too small");
    size_t made=0;status(sz_encode(&c,input,n,output+header,capacity-header,&made));
    std::memcpy(output,"SZF1",4);output[4]=static_cast<uint8_t>(c.width/8);output[5]=static_cast<uint8_t>(c.predictor);output[6]=static_cast<uint8_t>(c.huffman);output[7]=static_cast<uint8_t>(c.path);
    put(output+8,c.ndims,2);put(output+10,0,2);put(output+12,n,4);put(output+16,made,4);put(output+20,0,4);return header+made;
}
struct Frame{sz_config config;size_t bytes,payload;};
Frame frame(const uint8_t* input,size_t length){
    require(input&&length>=header&&!std::memcmp(input,"SZF1",4),"invalid Sprintz frame magic/length");
    require(input[5]==predictor&&input[6]==huffman&&le(input+10,2)==0&&le(input+20,4)==0,"Sprintz frame identity/reserved mismatch");
    Settings s;s.path=input[7];const auto n=static_cast<size_t>(le(input+12,4));auto cfg=configuration(input[4],static_cast<size_t>(le(input+8,2)),s,n);
    const auto z=static_cast<size_t>(le(input+16,4));require(z==length-header&&length<=bound(cfg,n),"Sprintz frame payload length mismatch");return {cfg,n,z};
}
size_t decode_frame(const uint8_t* input,size_t length,uint8_t* output,size_t capacity,size_t width=0,size_t dims=0,size_t bytes=SIZE_MAX){
    const auto f=frame(input,length);
    require((!width||f.config.width==width*8)&&(!dims||f.config.ndims==dims)&&(bytes==SIZE_MAX||bytes==f.bytes),"Sprintz task/frame geometry mismatch");
    uint8_t dummy=0;size_t made=0;status(sz_decode(&f.config,input+header,f.payload,f.bytes,output?output:&dummy,capacity,&made));require(made==f.bytes,"Sprintz decoded size mismatch");return made;
}
bool valid(const tscb_buffer_v1* b){return b&&b->dtype==TSCB_DTYPE_BYTES_V1&&b->rank==1&&b->strides_bytes[0]==1&&b->used_bytes<=b->capacity_bytes&&b->capacity_bytes<=SIZE_MAX&&(!b->capacity_bytes||b->data);}
bool overlap(const void* a,size_t na,const void* b,size_t nb){if(!na||!nb)return false;const auto x=reinterpret_cast<uintptr_t>(a),y=reinterpret_cast<uintptr_t>(b);return x<=y?y-x<na:x-y<nb;}
struct Input{sz_config config;size_t bytes;const uint8_t* data;};
Input input_view(const tscb_buffer_v1* b,const Settings& s){
    require(valid(b)&&b->used_bytes>=16,"invalid Sprintz input descriptor");const auto* p=static_cast<const uint8_t*>(b->data);
    require(!std::memcmp(p,"SZI1",4)&&p[5]==0,"Sprintz input magic/reserved mismatch");
    const auto count=le(p+8,8);if(count>limit)throw tsbench_core::Unsupported("Sprintz element count limit");const size_t n=static_cast<size_t>(count)*p[4];
    auto c=configuration(p[4],static_cast<size_t>(le(p+6,2)),s,n);require(b->used_bytes-16==n,"Sprintz input size mismatch");return {c,n,p+16};
}
}
struct tscb_codec_handle_v1{tscb_native_timer native_timer{};Settings config;bool updated=false,finalized=false;size_t input_bytes{},stream_bytes{};char error[256]{};std::string accounting;};
namespace {
template<class F> tscb_status_v1 api_guard(tscb_codec_handle_v1* h,F f)noexcept{
    try{f();return TSCB_STATUS_OK_V1;}
    catch(const tsbench_core::Unsupported& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_UNSUPPORTED_V1;}
    catch(const tsbench_core::Capacity& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_DST_TOO_SMALL_V1;}
    catch(const std::exception& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_CODEC_ERROR_V1;}
    catch(...){if(h)std::snprintf(h->error,sizeof(h->error),"Sprintz binding failure");return TSCB_STATUS_CODEC_ERROR_V1;}
}
}
extern "C" {
uint32_t tscb_get_abi_version(){return 1;}
tscb_status_v1 tscb_get_manifest_json(const char** p,uint64_t* n){if(!p||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=manifest;*n=sizeof(manifest)-1;return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_create(const char* json,uint64_t length,tscb_codec_handle_v1** result){
    if(!result)return TSCB_STATUS_INVALID_ARGUMENT_V1;*result=nullptr;if(!json||length>4096)return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return api_guard(nullptr,[&]{std::string text(json,static_cast<size_t>(length));require(text.find('\0')==std::string::npos,"embedded config NUL");auto s=settings(text.c_str(),true);cpu();auto h=std::make_unique<tscb_codec_handle_v1>();h->config=s;*result=h.release();});
}
tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* h){delete h;return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_reset(tscb_codec_handle_v1* h,uint32_t mode){if(!h||mode)return TSCB_STATUS_INVALID_ARGUMENT_V1;const auto s=h->config;const int enabled=h->native_timer.enabled;*h={};h->config=s;h->native_timer.enabled=enabled;h->native_timer.available=1;return TSCB_STATUS_OK_V1;}
TSCB_NATIVE_TIMING_API
tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,uint64_t* result){if(!h||!result)return TSCB_STATUS_INVALID_ARGUMENT_V1;*result=0;return api_guard(h,[&]{auto v=input_view(in,h->config);*result=bound(v.config,v.bytes);});}
tscb_status_v1 tscb_compress(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,tscb_buffer_v1* out){
    if(!h||!valid(in)||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;
    if(h->updated||h->finalized||overlap(in->data,in->used_bytes,out->data,out->capacity_bytes))return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return api_guard(h,[&]{auto v=input_view(in,h->config);size_t made=0;TSCB_TIME_CODEC(h->native_timer,encode_ns,made=encode_frame(v.config,v.data,v.bytes,static_cast<uint8_t*>(out->data),out->capacity_bytes));out->used_bytes=made;h->input_bytes=v.bytes;h->stream_bytes=made;h->updated=true;});
}
tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* h,tscb_buffer_v1* out){
    if(!h||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;if(!h->updated)return TSCB_STATUS_FINALIZE_REQUIRED_V1;if(h->finalized)return TSCB_STATUS_CODEC_ERROR_V1;
    return api_guard(h,[&]{h->accounting="{\"implementation\":\"sprintz-native-20261017-api-v1\",\"input_bytes\":"+std::to_string(h->input_bytes)+",\"native_payload_bytes\":"+std::to_string(h->stream_bytes-header)+",\"frame_bytes\":"+std::to_string(h->stream_bytes)+",\"recovery_header_bytes\":24,\"finalize_calls\":1}";h->finalized=true;});
}
tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,tscb_buffer_v1* out){
    if(!h||!valid(in)||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;if(overlap(in->data,in->used_bytes,out->data,out->capacity_bytes))return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return api_guard(h,[&]{size_t made=0;TSCB_TIME_CODEC(h->native_timer,decode_ns,made=decode_frame(static_cast<const uint8_t*>(in->data),in->used_bytes,static_cast<uint8_t*>(out->data),out->capacity_bytes));out->used_bytes=made;});
}
tscb_status_v1 tscb_query(tscb_codec_handle_v1*,const char*,uint64_t,char*,uint64_t,uint64_t* used){if(used)*used=0;return TSCB_STATUS_UNSUPPORTED_V1;}
tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1* h,const char** p,uint64_t* n){if(!h||!p||!n||!h->finalized)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=h->accounting.c_str();*n=h->accounting.size();return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* h,const char** p,uint64_t* n){if(!h||!p||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=h->error;*n=std::strlen(h->error);return TSCB_STATUS_OK_V1;}
}
#include "direct_core.inc"
