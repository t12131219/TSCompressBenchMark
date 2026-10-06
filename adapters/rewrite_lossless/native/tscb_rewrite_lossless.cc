// Benchmark framing only. Codec operations consume frozen standalone public APIs.
#include "tscb_adapter_v1.h"
#if TSCB_REWRITE_KIND == 1 || TSCB_REWRITE_KIND == 2
#include "chimp.hpp"
#elif TSCB_REWRITE_KIND == 3
#include "elf_plus.hpp"
#elif TSCB_REWRITE_KIND == 4
#include "self_star.hpp"
#elif TSCB_REWRITE_KIND == 5
#include "prometheus_xor_chunk.hpp"
#elif TSCB_REWRITE_KIND == 6
#include "elf_vldb.hpp"
#elif TSCB_REWRITE_KIND == 7
#include "elf_star.hpp"
#endif
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <mutex>
#include <new>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>
using Bytes=std::vector<std::uint8_t>;
struct tscb_codec_handle_v1 {bool updated=false,finalized=false;std::uint64_t encoded=0;std::string error,accounting;};
namespace {
std::mutex mutex_;std::unordered_set<tscb_codec_handle_v1*> handles;
constexpr const char* key=TSCB_REWRITE_KEY;
constexpr std::uint64_t max_elements=16777216;
bool valid(const tscb_buffer_v1* b){return b&&b->dtype==TSCB_DTYPE_BYTES_V1&&b->rank==1&&b->strides_bytes[0]==1&&b->used_bytes<=b->capacity_bytes&&(b->data||!b->capacity_bytes);}
std::uint64_t load(const std::uint8_t* p,unsigned n){std::uint64_t x=0;for(unsigned i=0;i<n;i++)x|=std::uint64_t(p[i])<<(i*8);return x;}
void store(Bytes& b,std::uint64_t x,unsigned n){for(unsigned i=0;i<n;i++)b.push_back(std::uint8_t(x>>(8*i)));}
std::uint64_t hash(const std::uint8_t* p,std::size_t n){std::uint64_t h=14695981039346656037ULL;for(std::size_t i=0;i<n;i++)h=(h^p[i])*1099511628211ULL;return h;}
void need(bool b,const char* error){if(!b)throw std::invalid_argument(error);}
struct Header {unsigned width,columns,block;std::uint64_t rows,records;};
Header header(const std::uint8_t* p,std::size_t n,bool frame){
    need(p&&n>=(frame?36:20),"truncated native header");need(std::memcmp(p,frame?"RWF1":"RWI1",4)==0,"invalid native magic");
    Header h{p[4],static_cast<unsigned>(load(p+6,2)),static_cast<unsigned>(load(p+8,4)),load(p+12,8),frame?load(p+20,8):0};
    need(p[5]==TSCB_REWRITE_KIND&&(h.width==4||h.width==8)&&h.columns&&h.block&&h.block<=65535&&h.rows<=max_elements/h.columns,"invalid dimensions");
#if TSCB_REWRITE_KIND == 4
    need(h.block<=16384&&(h.rows+h.block-1)/h.block<=1024&&h.rows*h.width<=16777216,"SElfStar session limits");
#elif TSCB_REWRITE_KIND == 5
    need(h.width==8,"Prometheus joint chunk requires binary64");
#elif TSCB_REWRITE_KIND == 6
    need(h.block<=16384,"Elf block limit");
#elif TSCB_REWRITE_KIND == 7
    need(h.block<=(h.width==4?1000u:16384u),"ElfStar upstream block limit");
#endif
    const auto nb=(h.rows+h.block-1)/h.block;
    if(frame){
        need(h.records==(TSCB_REWRITE_KIND==4?(h.rows?h.columns:0):nb*h.columns),"record count mismatch");
        need(load(p+n-8,8)==hash(p,n-8),"native checksum mismatch");
    }else need(n==20+(h.rows*h.columns+(TSCB_REWRITE_KIND==5?h.rows:0))*h.width,"input length mismatch");
    return h;
}
std::uint64_t bound(const Header& h){
    std::uint64_t result=36;
#if TSCB_REWRITE_KIND == 4
    return result+(h.rows?h.columns*(12+32+512*((h.rows+h.block-1)/h.block)+h.rows*h.width*4):0);
#else
    for(std::uint64_t start=0;start<h.rows;start+=h.block){
        const auto count=static_cast<std::size_t>(std::min<std::uint64_t>(h.block,h.rows-start));std::size_t b=0;
#if TSCB_REWRITE_KIND == 1 || TSCB_REWRITE_KIND == 2
        b=chimp::compress_bound(count,static_cast<chimp::Width>(h.width*8),TSCB_REWRITE_KIND==1?chimp::Variant::chimp:chimp::Variant::chimp128);
#elif TSCB_REWRITE_KIND == 3
        b=elf_plus::compress_bound(count,static_cast<elf_plus::Width>(h.width*8));
#elif TSCB_REWRITE_KIND == 6
        b=elf_vldb::compress_bound(count,static_cast<elf_vldb::Width>(h.width*8));
#elif TSCB_REWRITE_KIND == 7
        b=elf_star::compress_bound(count,static_cast<elf_star::Width>(h.width*8));
#elif TSCB_REWRITE_KIND == 5
        auto s=prometheus_xor::max_compressed_size(count,&b);need(s.ok(),s.message);
#endif
        result+=h.columns*(12+b);
    }return result;
#endif
}
Bytes encode(const std::uint8_t* p,std::size_t size){
    auto h=header(p,size,false);Bytes out(p,p+20);std::memcpy(out.data(),"RWF1",4);
    const auto nb=(h.rows+h.block-1)/h.block;store(out,TSCB_REWRITE_KIND==4?(h.rows?h.columns:0):nb*h.columns,8);
    auto values=p+20+(TSCB_REWRITE_KIND==5?h.rows*8:0);
    for(unsigned col=0;col<h.columns;col++){
#if TSCB_REWRITE_KIND == 4
        if(!h.rows)continue;
        self_star::Session session;session.width=static_cast<self_star::Width>(h.width*8);
        for(std::uint64_t start=0;start<h.rows;start+=h.block){auto count=std::min<std::uint64_t>(h.block,h.rows-start);auto q=values+(col*h.rows+start)*h.width;session.blocks.emplace_back(q,q+count*h.width);}
        auto bytes=self_star::compress(session).bytes;store(out,h.rows,4);store(out,bytes.size(),8);out.insert(out.end(),bytes.begin(),bytes.end());
#else
        for(std::uint64_t start=0;start<h.rows;start+=h.block){
            const auto count=static_cast<std::size_t>(std::min<std::uint64_t>(h.block,h.rows-start));auto q=values+(col*h.rows+start)*h.width;Bytes bytes;
#if TSCB_REWRITE_KIND == 1 || TSCB_REWRITE_KIND == 2
            bytes=chimp::compress(q,count,static_cast<chimp::Width>(h.width*8),TSCB_REWRITE_KIND==1?chimp::Variant::chimp:chimp::Variant::chimp128).bytes;
#elif TSCB_REWRITE_KIND == 3
            bytes=elf_plus::compress(q,count,static_cast<elf_plus::Width>(h.width*8)).bytes;
#elif TSCB_REWRITE_KIND == 6
            bytes=elf_vldb::compress(q,count,static_cast<elf_vldb::Width>(h.width*8)).bytes;
#elif TSCB_REWRITE_KIND == 7
            bytes=elf_star::compress(q,count,static_cast<elf_star::Width>(h.width*8)).bytes;
#elif TSCB_REWRITE_KIND == 5
            std::vector<prometheus_xor::Sample> samples(count);
            for(std::size_t i=0;i<count;i++){const auto t=load(p+20+(start+i)*8,8);std::memcpy(&samples[i].timestamp,&t,8);samples[i].value_bits=load(q+i*8,8);}
            std::size_t n=0;auto status=prometheus_xor::max_compressed_size(count,&n);need(status.ok(),status.message);bytes.resize(n);
            status=prometheus_xor::encode(samples.data(),count,bytes.data(),bytes.size(),&n);need(status.ok(),status.message);bytes.resize(n);
#endif
            store(out,count,4);store(out,bytes.size(),8);out.insert(out.end(),bytes.begin(),bytes.end());
        }
#endif
    }
    store(out,hash(out.data(),out.size()),8);need(out.size()<=bound(h),"bound violated");return out;
}
Bytes decode(const std::uint8_t* p,std::size_t size){
    auto h=header(p,size,true);need(size<=bound(h),"encoded object exceeds bound");
    const auto tv=TSCB_REWRITE_KIND==5?h.rows*8:0;Bytes out(static_cast<std::size_t>(h.rows*h.columns*h.width+tv));std::size_t pos=28;
    const auto nb=(h.rows+h.block-1)/h.block;
    for(unsigned col=0;col<h.columns;col++){
        const auto records=TSCB_REWRITE_KIND==4?(h.rows?1:0):nb;
        for(std::uint64_t record=0;record<records;record++){
            need(pos<=size-8&&size-8-pos>=12,"truncated record");auto count=load(p+pos,4),len=load(p+pos+4,8);pos+=12;
            const auto start=TSCB_REWRITE_KIND==4?0:record*h.block;
            need(count==(TSCB_REWRITE_KIND==4?h.rows:std::min<std::uint64_t>(h.block,h.rows-start))&&len<=size-8-pos,"invalid record geometry");Bytes decoded;
#if TSCB_REWRITE_KIND == 1 || TSCB_REWRITE_KIND == 2
            auto d=chimp::decompress(p+pos,static_cast<std::size_t>(len));need(static_cast<unsigned>(d.width)==h.width*8&&static_cast<unsigned>(d.variant)==(TSCB_REWRITE_KIND==1?1:128)&&d.count==count,"Chimp identity/count mismatch");decoded=std::move(d.values);
#elif TSCB_REWRITE_KIND == 3
            auto d=elf_plus::decompress(p+pos,static_cast<std::size_t>(len));need(static_cast<unsigned>(d.width)==h.width*8&&d.count==count,"Elf+ identity/count mismatch");decoded=std::move(d.values);
#elif TSCB_REWRITE_KIND == 6
            auto d=elf_vldb::decompress(p+pos,static_cast<std::size_t>(len));need(static_cast<unsigned>(d.width)==h.width*8&&d.count==count,"Elf identity/count mismatch");decoded=std::move(d.values);
#elif TSCB_REWRITE_KIND == 7
            auto d=elf_star::decompress(p+pos,static_cast<std::size_t>(len));need(static_cast<unsigned>(d.width)==h.width*8&&d.count==count,"ElfStar identity/count mismatch");decoded=std::move(d.values);
#elif TSCB_REWRITE_KIND == 4
            auto session=self_star::decompress(p+pos,static_cast<std::size_t>(len));need(!session.network&&static_cast<unsigned>(session.width)==h.width*8&&session.blocks.size()==nb,"SElfStar identity/block count mismatch");
            for(std::size_t i=0;i<session.blocks.size();i++){const auto& b=session.blocks[i];need(b.size()==std::min<std::uint64_t>(h.block,h.rows-i*h.block)*h.width,"SElfStar block geometry mismatch");decoded.insert(decoded.end(),b.begin(),b.end());}
#elif TSCB_REWRITE_KIND == 5
            std::vector<prometheus_xor::Sample> samples(static_cast<std::size_t>(count));std::size_t written=0;auto status=prometheus_xor::decode(p+pos,static_cast<std::size_t>(len),samples.data(),samples.size(),&written);need(status.ok(),status.message);need(written==count,"Prometheus count mismatch");
            for(std::size_t i=0;i<samples.size();i++){std::uint64_t t;std::memcpy(&t,&samples[i].timestamp,8);Bytes bits;store(bits,t,8);
                if(col==0)std::memcpy(out.data()+(start+i)*8,bits.data(),8);else need(std::memcmp(out.data()+(start+i)*8,bits.data(),8)==0,"T/V pairing mismatch across columns");store(decoded,samples[i].value_bits,8);}
#endif
            need(decoded.size()==count*h.width,"decoded record size mismatch");if(!decoded.empty())std::memcpy(out.data()+tv+(col*h.rows+start)*h.width,decoded.data(),decoded.size());pos+=static_cast<std::size_t>(len);
        }
    }
    need(pos==size-8,"trailing records");return out;
}
template<class F>tscb_status_v1 call(tscb_codec_handle_v1* h,F f){std::lock_guard<std::mutex> lock(mutex_);if(!handles.count(h))return TSCB_STATUS_INVALID_ARGUMENT_V1;
    try{return f();}catch(const std::bad_alloc&){h->error="allocation failed";return TSCB_STATUS_CODEC_ERROR_V1;}catch(const std::exception& e){h->error=e.what();return TSCB_STATUS_CODEC_ERROR_V1;}catch(...){return TSCB_STATUS_CODEC_ERROR_V1;}}
tscb_status_v1 copy(const Bytes& data,tscb_buffer_v1* output){if(!valid(output))return TSCB_STATUS_INVALID_ARGUMENT_V1;if(data.size()>output->capacity_bytes)return TSCB_STATUS_DST_TOO_SMALL_V1;
    if(!data.empty())std::memcpy(output->data,data.data(),data.size());
    output->used_bytes=data.size();return TSCB_STATUS_OK_V1;}
}
#define EXPORT extern "C" __attribute__((visibility("default")))
EXPORT std::uint32_t tscb_get_abi_version(){return 1;}
EXPORT tscb_status_v1 tscb_get_manifest_json(const char** p,std::uint64_t* n){static const std::string s=std::string("{\"algorithm\":\"")+key+"\",\"scheme\":\"FROZEN_REWRITE_RWF1\",\"safe_overread_bytes\":0}";if(!p||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=s.c_str();*n=s.size();return TSCB_STATUS_OK_V1;}
EXPORT tscb_status_v1 tscb_create(const char* p,std::uint64_t n,tscb_codec_handle_v1** out){if(!out)return TSCB_STATUS_INVALID_ARGUMENT_V1;*out=nullptr;try{need(p&&n<256,"invalid config");need(std::string(p,static_cast<std::size_t>(n))==std::string("{\"algorithm\":\"")+key+"\"}","config identity mismatch");
    std::lock_guard<std::mutex> lock(mutex_);auto h=new tscb_codec_handle_v1;try{handles.insert(h);}catch(...){delete h;throw;}*out=h;return TSCB_STATUS_OK_V1;
}catch(...){return TSCB_STATUS_INVALID_ARGUMENT_V1;}}
EXPORT tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* h){std::lock_guard<std::mutex> lock(mutex_);if(!h)return TSCB_STATUS_OK_V1;if(!handles.erase(h))return TSCB_STATUS_INVALID_ARGUMENT_V1;delete h;return TSCB_STATUS_OK_V1;}
EXPORT tscb_status_v1 tscb_reset(tscb_codec_handle_v1* h,std::uint32_t mode){return call(h,[&]{if(mode)return TSCB_STATUS_UNSUPPORTED_V1;*h=tscb_codec_handle_v1{};return TSCB_STATUS_OK_V1;});}
EXPORT tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,std::uint64_t* n){return call(h,[&]{if(!valid(in)||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;*n=bound(header(static_cast<const std::uint8_t*>(in->data),in->used_bytes,false));return TSCB_STATUS_OK_V1;});}
EXPORT tscb_status_v1 tscb_compress(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,tscb_buffer_v1* out){return call(h,[&]{if(!valid(in)||!valid(out)||h->updated||h->finalized)return TSCB_STATUS_INVALID_ARGUMENT_V1;auto data=encode(static_cast<const std::uint8_t*>(in->data),in->used_bytes);auto s=copy(data,out);if(s==TSCB_STATUS_OK_V1){h->updated=true;h->encoded=data.size();}return s;});}
EXPORT tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* h,tscb_buffer_v1* out){return call(h,[&]{if(!valid(out)||!h->updated||h->finalized)return TSCB_STATUS_INVALID_ARGUMENT_V1;out->used_bytes=0;h->finalized=true;return TSCB_STATUS_OK_V1;});}
EXPORT tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* h,const tscb_buffer_v1* in,tscb_buffer_v1* out){return call(h,[&]{if(!valid(in)||!valid(out))return TSCB_STATUS_INVALID_ARGUMENT_V1;return copy(decode(static_cast<const std::uint8_t*>(in->data),in->used_bytes),out);});}
EXPORT tscb_status_v1 tscb_query(tscb_codec_handle_v1* h,const char*,std::uint64_t,char*,std::uint64_t,std::uint64_t*){return call(h,[]{return TSCB_STATUS_UNSUPPORTED_V1;});}
EXPORT tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1* h,const char** p,std::uint64_t* n){return call(h,[&]{if(!p||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;if(!h->finalized)return TSCB_STATUS_FINALIZE_REQUIRED_V1;h->accounting="{\"final_bits\":"+std::to_string(h->encoded*8)+"}";*p=h->accounting.c_str();*n=h->accounting.size();return TSCB_STATUS_OK_V1;});}
EXPORT tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* h,const char** p,std::uint64_t* n){return call(h,[&]{if(!p||!n)return TSCB_STATUS_INVALID_ARGUMENT_V1;*p=h->error.c_str();*n=h->error.size();return TSCB_STATUS_OK_V1;});}
