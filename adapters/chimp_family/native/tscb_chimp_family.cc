// Binding and framing only. Frozen chimp-family code is compiled unchanged.
#include "chimp_family.hpp"
#include "tsbench_core.hpp"
#include "tscb_native_timing.h"
#include <algorithm>
#include <array>
#include <cstdio>
#include <memory>

#ifndef TSCB_CHIMP_METHOD
#error Missing Chimp method
#endif
namespace {
using Bytes=std::vector<uint8_t>;
constexpr auto method=static_cast<chimp::Method>(TSCB_CHIMP_METHOD);
constexpr bool lossy=TSCB_CHIMP_METHOD>=7;
constexpr size_t width=(TSCB_CHIMP_METHOD==2 || TSCB_CHIMP_METHOD==5 || lossy)?4:8;
constexpr const char* key=TSCB_CHIMP_KEY;
constexpr bool variable_history=TSCB_CHIMP_VARIABLE_HISTORY;
constexpr size_t minimum=TSCB_CHIMP_METHOD==8?2:(TSCB_CHIMP_METHOD==9 || TSCB_CHIMP_METHOD==10?1:0);
constexpr char manifest[]="{\"abi_version\":1,\"algorithm\":\"" TSCB_CHIMP_KEY "\",\"implementation\":\"chimp-family-cpp-scalar-v1\",\"qualification\":\"RESEARCH_REWRITE_VALIDATED\",\"frame\":\"CFP1\",\"column_container\":\"CFS1\",\"isa\":\"SCALAR\",\"threading\":\"SINGLE_THREAD\"}";
uint64_t le(const uint8_t* p,size_t n){uint64_t v=0;for(size_t i=0;i<n;++i)v|=uint64_t(p[i])<<(i*8);return v;}
void append(Bytes& b,uint64_t v,size_t n){for(size_t i=0;i<n;++i){b.push_back(static_cast<uint8_t>(v));v>>=8;}}
void need(bool v,const char* message){tsbench_core::require(v,message);}
struct Settings {chimp::Config config{method,128,0.1f};size_t block=1000;bool strict=true;};
Settings settings(const char* json,bool c1=false){
    tsbench_core::Parameters p(json);Settings s;
    // Parameters validates flat JSON and duplicate keys. Count top-level colons
    // to reject unknown keys without accepting arbitrary ignored configuration.
    size_t keys=0,known=0;bool quoted=false,escaped=false;
    for(const char* c=json?json:"{}";*c;++c){
        if(!quoted && *c==':')++keys;
        if(*c=='"'&&!escaped)quoted=!quoted;
        if(*c=='\\'&&!escaped)escaped=true;else escaped=false;
    }
    for(const char* name:{"isa","native_timing","algorithm","block_size","history","epsilon","quality_mode"}){
        if(!p.contains(name))continue;
        if(std::strcmp(name,"algorithm")==0){if(!c1)throw tsbench_core::Unsupported("algorithm is selected by the library");}
        if(std::strcmp(name,"history")==0 && !variable_history)throw tsbench_core::Unsupported("this variant fixes history=128");
        if(std::strcmp(name,"block_size")==0 && lossy)throw tsbench_core::Unsupported("filters operate on a complete column");
        if((std::strcmp(name,"epsilon")==0 || std::strcmp(name,"quality_mode")==0)&&!lossy)throw tsbench_core::Unsupported("lossless method has no quality parameter");
        ++known;
    }
    if(keys!=known)throw tsbench_core::Unsupported("unknown Chimp family parameters");
    if(c1)need(p.contains("algorithm")&&p.string("algorithm")==key,"Chimp algorithm identity mismatch");
    if(p.contains("isa")&&p.string("isa")!="SCALAR")throw tsbench_core::Unsupported("Chimp requires SCALAR");
    if(p.contains("native_timing"))(void)p.boolean("native_timing");
    if(p.contains("block_size"))s.block=static_cast<size_t>(p.integer("block_size",1,chimp::max_values));
    if(p.contains("history")){
        s.config.history=static_cast<uint32_t>(p.integer("history",1,65536));
        if(s.config.history&(s.config.history-1))throw tsbench_core::Unsupported("history must be a power of two");
    }
    if(lossy){
        double eps=0.1;
        try{if(p.contains("epsilon"))eps=p.real("epsilon");}
        catch(const std::out_of_range&){throw tsbench_core::Unsupported("epsilon outside representable domain");}
        if(eps<0||eps>std::numeric_limits<float>::max())throw tsbench_core::Unsupported("epsilon outside finite float32 domain");
        s.config.epsilon=static_cast<float>(eps);
        if((eps>0&&s.config.epsilon==0)||(method==chimp::Method::Quantized&&s.config.epsilon==0))throw tsbench_core::Unsupported("epsilon underflow or quantized zero epsilon");
        if(p.contains("quality_mode")){
            const auto mode=p.string("quality_mode");
            if(mode!="strict_abs"&&mode!="compatible")throw tsbench_core::Unsupported("unknown quality mode");
            s.strict=mode=="strict_abs";
        }
    }
    return s;
}
void count_check(size_t count){if(count<minimum||count>chimp::max_values)throw tsbench_core::Unsupported("Chimp family input count outside profile");}
size_t stream_bound(const Settings& s,size_t count){
    count_check(count);
    if(lossy)return tsbench_core::add(36,tsbench_core::multiply(count,52));
    size_t result=0,at=0;
    do{const size_t n=std::min(s.block,count-at);result=tsbench_core::add(result,36+chimp::raw_bound(s.config,n));at+=n;}while(at<count);
    return result;
}
void validate_values(const uint8_t* input,size_t count){
    for(size_t i=0;i<count;++i){
        const uint64_t word=le(input+i*width,width);
        if(lossy){uint32_t bits=static_cast<uint32_t>(word);float f;std::memcpy(&f,&bits,4);if(!std::isfinite(f))throw tsbench_core::Unsupported("finite float32 filter input required");}
        else if(word==(width==4?UINT64_C(0x7fc00000):UINT64_C(0x7ff8000000000000)))throw tsbench_core::Unsupported("canonical positive NaN is the Chimp EOF sentinel");
    }
}
Bytes encode_stream(const Settings& s,const uint8_t* input,size_t count){
    count_check(count);validate_values(input,count);
    try{
        if(lossy){
            std::vector<chimp::Point> points;points.reserve(count);
            for(size_t i=0;i<count;++i){const auto bits=static_cast<uint32_t>(le(input+i*4,4));float f;std::memcpy(&f,&bits,4);points.push_back({static_cast<int64_t>(i),f});}
            return chimp::encode_frame(s.config,points,s.strict);
        }
        Bytes result;size_t at=0;
        do{
            const size_t n=std::min(s.block,count-at);std::vector<uint64_t> words;words.reserve(n);
            for(size_t i=0;i<n;++i)words.push_back(le(input+(at+i)*width,width));
            auto frame=chimp::encode_frame(s.config,words);
            if(at==0&&n==count)return frame;
            result.insert(result.end(),frame.begin(),frame.end());at+=n;
        }while(at<count);
        return result;
    }catch(const std::invalid_argument& e){throw tsbench_core::Unsupported(e.what());}
}
Bytes decode_stream(const uint8_t* input,size_t length,size_t count){
    need(input&&length>=36,"truncated CFP1 stream");Bytes result;result.reserve(count*width);size_t at=0,total=0;
    do{
        need(length-at>=36&&!std::memcmp(input+at,"CFP1",4),"invalid CFP1 frame");
        const auto* frame=input+at;const auto n64=le(frame+16,8),payload=le(frame+24,8);
        need(frame[5]==TSCB_CHIMP_METHOD&&n64<=count-total&&payload<=length-at-36,"CFP1 method/count/length mismatch");
        const size_t n=static_cast<size_t>(n64),bytes=static_cast<size_t>(payload)+36;
        need(n>0||(count==0&&at==0&&bytes==length),"unexpected empty CFP1 block");
        if(!variable_history)need(le(frame+8,4)==128,"fixed history mismatch");
        if(lossy)need(at==0&&bytes==length&&n==count,"filters require one complete CFP1 frame");
        auto decoded=chimp::decode_frame(Bytes(frame,frame+bytes));
        if(lossy){
            need(decoded.points.size()==n,"filter grid count mismatch");
            for(size_t i=0;i<n;++i){need(decoded.points[i].timestamp==static_cast<int64_t>(i),"filter grid must be implicit unit indices");uint32_t bits;std::memcpy(&bits,&decoded.points[i].value,4);append(result,bits,4);}
        }else{
            need(decoded.words.size()==n,"CFP1 decoded count mismatch");
            for(auto word:decoded.words)append(result,word,width);
        }
        total+=n;at+=bytes;
    }while(at<length);
    need(at==length&&total==count&&result.size()==count*width,"CFP1 stream total mismatch");return result;
}
bool valid_buffer(const tscb_buffer_v1* b){return b&&b->dtype==TSCB_DTYPE_BYTES_V1&&b->rank==1&&b->strides_bytes[0]==1&&b->used_bytes<=b->capacity_bytes&&b->capacity_bytes<=SIZE_MAX&&(!b->capacity_bytes||b->data);}
bool overlap(const void* a,size_t na,const void* b,size_t nb){if(!na||!nb)return false;const auto x=reinterpret_cast<uintptr_t>(a),y=reinterpret_cast<uintptr_t>(b);return x<=y?y-x<na:x-y<nb;}
struct Geometry{size_t columns,rows;};
Geometry geometry(const uint8_t* data,size_t length,const char* magic){
    need(data&&length>=16&&!std::memcmp(data,magic,4)&&data[4]==width&&data[5]==TSCB_CHIMP_METHOD,"invalid Chimp column descriptor");
    Geometry g{static_cast<size_t>(le(data+6,2)),static_cast<size_t>(le(data+8,8))};
    need(g.columns&&g.rows<=chimp::max_values&&g.rows<=chimp::max_values/g.columns,"Chimp column geometry limit");count_check(g.rows);return g;
}
Geometry input_view(const tscb_buffer_v1* b){need(valid_buffer(b),"invalid Chimp input buffer");auto g=geometry(static_cast<const uint8_t*>(b->data),b->used_bytes,"CFI1");need(b->used_bytes-16==g.rows*g.columns*width,"Chimp input length mismatch");return g;}
}
struct tscb_codec_handle_v1{
    tscb_native_timer native_timer{};Settings config;bool updated=false,finalized=false;size_t input_bytes=0,stream_bytes=0;char error[256]{};std::string accounting;
};
namespace {
template<class F> tscb_status_v1 api_guard(tscb_codec_handle_v1* h,F action)noexcept{
    try{action();return TSCB_STATUS_OK_V1;}
    catch(const tsbench_core::Unsupported& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_UNSUPPORTED_V1;}
    catch(const tsbench_core::Capacity& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_DST_TOO_SMALL_V1;}
    catch(const std::exception& e){if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what());return TSCB_STATUS_CODEC_ERROR_V1;}
    catch(...){if(h)std::snprintf(h->error,sizeof(h->error),"Chimp binding failure");return TSCB_STATUS_CODEC_ERROR_V1;}
}
}
extern "C" {
uint32_t tscb_get_abi_version(){return 1;}
tscb_status_v1 tscb_get_manifest_json(const char** json,uint64_t* length){if(!json||!length)return TSCB_STATUS_INVALID_ARGUMENT_V1;*json=manifest;*length=sizeof(manifest)-1;return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_create(const char* config,uint64_t length,tscb_codec_handle_v1** result){
    if(!result)return TSCB_STATUS_INVALID_ARGUMENT_V1;*result=nullptr;
    if(!config||length>4096)return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return api_guard(nullptr,[&]{const std::string text(config,static_cast<size_t>(length));need(text.find('\0')==std::string::npos,"embedded NUL config");auto s=settings(text.c_str(),true);auto h=std::make_unique<tscb_codec_handle_v1>();h->config=s;*result=h.release();});
}
tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* h){delete h;return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_reset(tscb_codec_handle_v1* h,uint32_t mode){
    if(!h||mode)return TSCB_STATUS_INVALID_ARGUMENT_V1;
    const auto s=h->config;const int enabled=h->native_timer.enabled;*h={};h->config=s;h->native_timer.enabled=enabled;h->native_timer.available=1;return TSCB_STATUS_OK_V1;
}
TSCB_NATIVE_TIMING_API
tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* h,const tscb_buffer_v1* input,uint64_t* bound){
    if(!h||!bound)return TSCB_STATUS_INVALID_ARGUMENT_V1;*bound=0;
    return api_guard(h,[&]{const auto g=input_view(input);*bound=tsbench_core::add(16,tsbench_core::multiply(g.columns,8+stream_bound(h->config,g.rows)));});
}
tscb_status_v1 tscb_compress(tscb_codec_handle_v1* h,const tscb_buffer_v1* input,tscb_buffer_v1* output){
    if(!h||!valid_buffer(input)||!valid_buffer(output))return TSCB_STATUS_INVALID_ARGUMENT_V1;output->used_bytes=0;
    if(h->updated||h->finalized||overlap(input->data,input->used_bytes,output->data,output->capacity_bytes))return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return api_guard(h,[&]{const auto g=input_view(input);const auto* source=static_cast<const uint8_t*>(input->data);Bytes stream(source,source+16);std::memcpy(stream.data(),"CFS1",4);
        for(size_t c=0;c<g.columns;++c){Bytes frame;TSCB_TIME_CODEC(h->native_timer,encode_ns,frame=encode_stream(h->config,source+16+c*g.rows*width,g.rows));append(stream,frame.size(),8);stream.insert(stream.end(),frame.begin(),frame.end());}
        if(output->capacity_bytes<stream.size())throw tsbench_core::Capacity("Chimp column output too small");
        std::memcpy(output->data,stream.data(),stream.size());output->used_bytes=stream.size();h->input_bytes=g.rows*g.columns*width;h->stream_bytes=stream.size();h->updated=true;
    });
}
tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* h,tscb_buffer_v1* output){
    if(!h||!valid_buffer(output))return TSCB_STATUS_INVALID_ARGUMENT_V1;output->used_bytes=0;
    if(!h->updated)return TSCB_STATUS_FINALIZE_REQUIRED_V1;if(h->finalized)return TSCB_STATUS_CODEC_ERROR_V1;
    return api_guard(h,[&]{h->accounting="{\"implementation\":\"chimp-family-cpp-scalar-v1\",\"input_bytes\":"+std::to_string(h->input_bytes)+",\"complete_column_container_bytes\":"+std::to_string(h->stream_bytes)+",\"native_input_descriptor_bytes\":16,\"finalize_calls\":1}";h->finalized=true;});
}
tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* h,const tscb_buffer_v1* input,tscb_buffer_v1* output){
    if(!h||!valid_buffer(input)||!valid_buffer(output))return TSCB_STATUS_INVALID_ARGUMENT_V1;output->used_bytes=0;
    if(overlap(input->data,input->used_bytes,output->data,output->capacity_bytes))return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return api_guard(h,[&]{const auto* source=static_cast<const uint8_t*>(input->data);const size_t length=input->used_bytes;const auto g=geometry(source,length,"CFS1");const size_t total=g.rows*g.columns*width;
        if(output->capacity_bytes<total)throw tsbench_core::Capacity("Chimp decoded output too small");
        Bytes result;result.reserve(total);size_t at=16;
        for(size_t c=0;c<g.columns;++c){need(length-at>=8,"truncated Chimp column length");const uint64_t n=le(source+at,8);at+=8;need(n>=36&&n<=length-at,"invalid Chimp column length");Bytes decoded;TSCB_TIME_CODEC(h->native_timer,decode_ns,decoded=decode_stream(source+at,static_cast<size_t>(n),g.rows));result.insert(result.end(),decoded.begin(),decoded.end());at+=static_cast<size_t>(n);}
        need(at==length&&result.size()==total,"trailing Chimp column bytes");if(total)std::memcpy(output->data,result.data(),total);output->used_bytes=total;
    });
}
tscb_status_v1 tscb_query(tscb_codec_handle_v1*,const char*,uint64_t,char*,uint64_t,uint64_t* used){if(used)*used=0;return TSCB_STATUS_UNSUPPORTED_V1;}
tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1* h,const char** json,uint64_t* length){if(!h||!json||!length||!h->finalized)return TSCB_STATUS_INVALID_ARGUMENT_V1;*json=h->accounting.c_str();*length=h->accounting.size();return TSCB_STATUS_OK_V1;}
tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* h,const char** message,uint64_t* length){if(!h||!message||!length)return TSCB_STATUS_INVALID_ARGUMENT_V1;*message=h->error;*length=std::strlen(h->error);return TSCB_STATUS_OK_V1;}
}
#include "direct_core.inc"
