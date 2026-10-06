// Copyright (c) 2013-2018 InfluxData Inc.
// Copyright (c) 2015 Jason Wilder
// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: MIT
#include "tsm_timestamp.hpp"
#include <algorithm>
#include <cstring>
#include <limits>
#include <new>
namespace tsm_timestamp {
namespace {
constexpr unsigned counts[]={240,120,60,30,20,15,12,10,8,7,6,5,4,3,2,1};
constexpr unsigned widths[]={0,0,1,2,3,4,5,6,7,8,10,12,15,20,30,60};
constexpr std::uint64_t max_simple=(UINT64_C(1)<<60)-1;
Status invalid(const char* text){return {Code::InvalidArgument,text};}
Status malformed(const char* text){return {Code::MalformedStream,text};}
Status resource(){return {Code::ResourceLimit,"sample/allocation limit"};}
bool profile_valid(Profile p){return p==Profile::Stream || p==Profile::Batch;}
std::uint64_t unsigned_bits(std::int64_t n){std::uint64_t v;std::memcpy(&v,&n,8);return v;}
std::int64_t signed_bits(std::uint64_t n){std::int64_t v;std::memcpy(&v,&n,8);return v;}
void put64(std::vector<std::uint8_t>& out,std::uint64_t n){for(unsigned i=0;i<8;++i)out.push_back(std::uint8_t(n>>(56-i*8)));}
std::uint64_t get64(const std::uint8_t* p){std::uint64_t n=0;for(unsigned i=0;i<8;++i)n=(n<<8)|p[i];return n;}
void putvar(std::vector<std::uint8_t>& out,std::uint64_t n){while(n>=128){out.push_back(std::uint8_t(n)|128);n>>=7;}out.push_back(std::uint8_t(n));}
Status getvar(const std::uint8_t* data,std::size_t bytes,std::size_t& pos,std::uint64_t& value){
    value=0;
    for(unsigned i=0;i<10;++i){if(pos==bytes)return malformed("truncated varint");auto byte=data[pos++];
        if(i==9 && byte>1)return malformed("varint overflow");
        value|=std::uint64_t(byte&127)<<(7*i);
        if(!(byte&128))return {};}
    return malformed("varint overflow");
}
unsigned pack_one(const std::uint64_t* input,std::size_t n,bool batch,std::uint64_t& word){
    for(unsigned selector=0;selector<16;++selector){const unsigned count=counts[selector],width=widths[selector];
        if(n<count)continue;
        const std::size_t inspect=width?count:batch?count:n;
        bool fits=true;
        for(std::size_t i=0;i<inspect;++i){if(width?input[i]>((UINT64_C(1)<<width)-1):input[i]!=1){fits=false;break;}}
        if(!fits)continue;
        word=std::uint64_t(selector)<<60;
        if(width)for(unsigned i=0;i<count;++i)word|=input[i]<<(i*width);
        return count;
    }
    return 0;
}
Status export_bytes(const std::vector<std::uint8_t>& bytes,std::uint8_t* output,std::size_t capacity,std::size_t* written){
    if(!written || (!output && capacity))return invalid("invalid output");
    const auto count=bytes.size();
    *written=count;
    if(capacity<count || (!output && count))return {Code::OutputTooSmall,"output too small"};
    if(count)std::memmove(output,bytes.data(),count);
    return {};
}
}
Status encode(const std::int64_t* input,std::size_t count,Profile profile,std::vector<std::uint8_t>* output,std::size_t limit)noexcept{
    limit=std::min(limit,default_sample_limit);
    if(!output || (!input && count) || !profile_valid(profile) || (count && reinterpret_cast<std::uintptr_t>(input)%alignof(std::int64_t)))return invalid("input/profile/alignment");
    if(count>limit || count>(std::numeric_limits<std::size_t>::max()-1)/8)return resource();
    try{
        std::vector<std::uint8_t> bytes;
        if(!count){output->swap(bytes);return {};}
        std::vector<std::uint64_t> deltas;deltas.reserve(count);
        std::uint64_t previous=0,maximum=0,divisor=UINT64_C(1000000000000);bool rle=count>1;
        for(std::size_t i=0;i<count;++i){const auto current=unsigned_bits(input[i]);deltas.push_back(current-previous);previous=current;
            if(i){maximum=std::max(maximum,deltas[i]);while(divisor>1 && deltas[i]%divisor)divisor/=10;
                if(i>1 && deltas[i]!=deltas[1])rle=false;}}
        unsigned exponent=0;for(auto n=divisor;n>1;n/=10)++exponent;
        if(rle){bytes.push_back(std::uint8_t(32|exponent));put64(bytes,deltas[0]);putvar(bytes,deltas[1]/divisor);putvar(bytes,count);
        }else if(maximum>max_simple){bytes.push_back(0);for(auto n:deltas)put64(bytes,n);
        }else{
            bytes.push_back(std::uint8_t(16|exponent));put64(bytes,deltas[0]);
            for(std::size_t i=1;i<count;++i)deltas[i]/=divisor;
            if(profile==Profile::Batch){std::size_t i=1;while(i<count){std::uint64_t word=0;auto n=pack_one(deltas.data()+i,count-i,true,word);if(!n)return invalid("unpackable delta");put64(bytes,word);i+=n;}
            }else{
                std::vector<std::uint64_t> buffered;buffered.reserve(240);
                auto flush=[&](){std::uint64_t word=0;auto n=pack_one(buffered.data(),buffered.size(),false,word);put64(bytes,word);buffered.erase(buffered.begin(),buffered.begin()+n);};
                for(std::size_t i=1;i<count;++i){if(buffered.size()==240)flush();buffered.push_back(deltas[i]);}
                while(!buffered.empty())flush();
            }
        }
        output->swap(bytes);return {};
    }catch(...){return resource();}
}
Status encode_bound(const std::int64_t* input,std::size_t count,Profile profile,std::size_t* bytes,std::size_t limit)noexcept{
    if(!bytes)return invalid("null bound");
    std::vector<std::uint8_t> output;auto s=encode(input,count,profile,&output,limit);
    if(s.ok())*bytes=output.size();
    return s;
}
Status encode_to(const std::int64_t* input,std::size_t count,Profile profile,std::uint8_t* output,std::size_t capacity,std::size_t* written,std::size_t limit)noexcept{
    if(!written || (!output && capacity))return invalid("invalid output");
    std::vector<std::uint8_t> bytes;auto s=encode(input,count,profile,&bytes,limit);
    return s.ok()?export_bytes(bytes,output,capacity,written):s;
}
Status Cursor::reset(const std::uint8_t* data,std::size_t bytes,std::size_t limit)noexcept{
    limit=std::min(limit,default_sample_limit);
    *this=Cursor{};
    if(!data && bytes)return invalid("null bytes");
    if(!bytes){initialized_=true;return {};}
    Cursor next;next.data_=data;next.type_=data[0]>>4;next.initialized_=true;next.offset_=1;
    if(next.type_>2)return malformed("unknown encoding");
    if(next.type_==0){if((bytes-1)%8)return malformed("raw length not multiple of8");next.total_=(bytes-1)/8;
    }else{
        if(bytes<9)return malformed("missing first timestamp");
        next.accumulator_=get64(data+1);next.offset_=9;
        for(unsigned i=0;i<(data[0]&15);++i)next.divisor_*=10;
        if(next.type_==2){std::uint64_t count=0;auto s=getvar(data,bytes,next.offset_,next.delta_);if(!s.ok())return s;
            s=getvar(data,bytes,next.offset_,count);if(!s.ok())return s;
            if(count>limit || count>std::numeric_limits<std::size_t>::max())return resource();
            next.total_=std::size_t(count);next.legacy_n_=next.total_;next.delta_*=next.divisor_;
        }else{
            if((bytes-9)%8)return malformed("packed length not multiple of8");
            next.total_=1;
            for(std::size_t pos=9;pos<bytes;pos+=8){const auto n=counts[data[pos]>>4];
                if(next.total_>limit || n>limit-next.total_)return resource();
                next.total_+=n;}
        }
    }
    if(next.total_>limit)return resource();
    *this=next;return {};
}
Status Cursor::source_init(const std::uint8_t* data,std::size_t bytes,std::size_t limit)noexcept{
    if(!bytes && initialized_ && type_==2){
        if(legacy_n_>limit)return resource();
        read_=0;total_=legacy_n_?legacy_n_-1:0;
        accumulator_=delta_;data_=nullptr;offset_=0;return {};
    }
    return reset(data,bytes,limit);
}
Status Cursor::next(std::int64_t* value,bool* available)noexcept{
    if(available)*available=false;
    if(!value || !available || !initialized_)return invalid("cursor/output not initialized");
    if(read_==total_)return {};
    if(type_==0){accumulator_+=get64(data_+offset_);offset_+=8;
    }else if(type_==2){if(read_)accumulator_+=delta_;
    }else if(read_){
        if(!word_index_ || word_index_==counts[selector_]){word_=get64(data_+offset_);offset_+=8;selector_=unsigned(word_>>60);word_index_=0;}
        const unsigned width=widths[selector_];const std::uint64_t delta=width?((word_>>(word_index_*width))&((UINT64_C(1)<<width)-1)):1;
        accumulator_+=delta*divisor_;++word_index_;
    }
    *value=signed_bits(accumulator_);++read_;*available=true;return {};
}
Status count_timestamps(const std::uint8_t* data,std::size_t bytes,std::size_t* count,std::size_t limit)noexcept{
    if(!count)return invalid("null count");
    Cursor c;auto s=c.reset(data,bytes,limit);
    if(s.ok())*count=c.count();
    return s;
}
Status decode(const std::uint8_t* data,std::size_t bytes,std::vector<std::int64_t>* output,std::size_t limit)noexcept{
    if(!output)return invalid("null output");
    Cursor c;auto s=c.reset(data,bytes,limit);if(!s.ok())return s;
    try{std::vector<std::int64_t> decoded;decoded.reserve(c.count());std::int64_t value=0;bool available=false;
        for(;;){s=c.next(&value,&available);if(!s.ok())return s;if(!available)break;decoded.push_back(value);}output->swap(decoded);return {};
    }catch(...){return resource();}
}
Status Encoder::append(std::int64_t value)noexcept{
    if(!profile_valid(profile_))return invalid("invalid profile");
    if(finalized_)return {Code::Finalized,"reset required after finalize"};
    if(input_.size()==limit_)return resource();
    try{input_.push_back(value);return {};}catch(...){return resource();}
}
Status Encoder::finish()noexcept{
    if(finalized_)return {};
    auto s=encode(input_.data(),input_.size(),profile_,&bytes_,limit_);
    if(s.ok())finalized_=true;
    return s;
}
Status Encoder::finalize(std::uint8_t* output,std::size_t capacity,std::size_t* written)noexcept{
    if(finalized_)return export_bytes(bytes_,output,capacity,written);
    std::vector<std::uint8_t> bytes;auto s=encode(input_.data(),input_.size(),profile_,&bytes,limit_);if(!s.ok())return s;
    s=export_bytes(bytes,output,capacity,written);if(s.ok()){bytes_.swap(bytes);finalized_=true;}return s;
}
void Encoder::reset()noexcept{input_.clear();bytes_.clear();finalized_=false;}
const char* version()noexcept{return "influxdb-tsm-adaptive-timestamp-cpp-v1";}
Status capability(const char* identifier,bool* supported)noexcept{
    if(!identifier || !supported)return invalid("null capability");
    constexpr const char* names[]={"encode.stream","encode.batch","select.adaptive","preprocess.delta_modulo","preprocess.decimal_scale", "wire.raw","wire.rle","wire.simple8b","decode.iterator","decode.batch","query.count","state.legacy_empty_init","api.lifecycle_ownership","api.accounting","threading.independent_handles"};
    *supported=false;for(const auto* name:names)if(std::strcmp(name,identifier)==0){*supported=true;break;}return {};
}
}
