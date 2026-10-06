// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: MIT
#include "tsm_timestamp.hpp"
#include <algorithm>
#include <atomic>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <sys/mman.h>
#include <unistd.h>
using namespace tsm_timestamp;
namespace {
void require(bool v,const char* message){if(!v)throw std::runtime_error(message);}
void putvar(std::vector<std::uint8_t>& b,std::uint64_t n){while(n>=128){b.push_back(std::uint8_t(n)|128);n>>=7;}b.push_back(std::uint8_t(n));}
std::vector<std::uint8_t> rle(std::size_t n){std::vector<std::uint8_t> b(9,0);b[0]=32;putvar(b,1);putvar(b,n);return b;}
void suite(Profile profile){
    for(std::size_t n:{0U,1U,2U,119U,120U,121U,239U,240U,241U,8192U}){
        std::vector<std::int64_t> values;for(std::size_t i=0;i<n;++i)values.push_back(std::int64_t(i*i));auto original=values;
        std::vector<std::uint8_t> bytes;require(encode(values.data(),n,profile,&bytes).ok(),"encode");
        std::size_t bound=0,written=0;require(encode_bound(values.data(),n,profile,&bound).ok()&&bound==bytes.size(),"exact bound");
        std::vector<std::uint8_t> output(bound+2,0x9a);
        if(bound){require(encode_to(values.data(),n,profile,output.data()+1,bound-1,&written).code==Code::OutputTooSmall,"bound-1");
            require(std::all_of(output.begin(),output.end(),[](auto v){return v==0x9a;}),"bound-1 touched output");}
        require(encode_to(values.data(),n,profile,output.data()+1,bound,&written).ok()&&written==bound,"bound success");
        require(output.front()==0x9a&&output.back()==0x9a&&values==original,"canary/input immutability");
        Encoder encoder(profile);for(auto value:values)require(encoder.append(value).ok(),"stream append");require(encoder.finish().ok()&&encoder.bytes()==bytes,"incremental profile path");
        require(encoder.final_bits()==bytes.size()*8,"physical bit accounting");
        require(encoder.finalize(output.data()+1,bound,&written).ok()&&encoder.finalize(output.data()+1,bound,&written).ok(),"repeat finalize");
        require(encoder.append(0).code==Code::Finalized,"append after terminal finalize");encoder.reset();require(encoder.samples()==0&&encoder.finish().ok()&&encoder.bytes().empty(),"reset/empty finalize");
        std::vector<std::int64_t> decoded;require(decode(bytes.data(),bytes.size(),&decoded).ok()&&decoded==values,"batch decode");
        Cursor cursor;require(cursor.reset(bytes.data(),bytes.size()).ok()&&cursor.count()==n,"count/reset");
        bool available=false;std::int64_t value=0;
        for(auto expected:values)require(cursor.next(&value,&available).ok()&&available&&value==expected,"iterator pairing");
        require(cursor.next(&value,&available).ok()&&!available,"exhaustion");
        require(cursor.next(nullptr,&available).code==Code::InvalidArgument,"null cursor output");
        require(cursor.reset(nullptr,0).ok()&&cursor.next(&value,&available).ok()&&!available,"clean empty reset");
        if(bytes.empty())continue;
        const auto page=std::size_t(sysconf(_SC_PAGESIZE));const auto accessible=((bytes.size()+page-1)/page)*page;
        auto* mapping=static_cast<std::uint8_t*>(mmap(nullptr,accessible+page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
        require(mapping!=MAP_FAILED,"guard allocation");require(mprotect(mapping+accessible,page,PROT_NONE)==0,"guard protection");
        for(std::size_t length=0;length<=bytes.size();++length){auto* guarded=mapping+accessible-length;std::memcpy(guarded,bytes.data(),length);
            auto status=cursor.reset(guarded,length,10000);
            if(status.ok()){std::size_t seen=0;for(;;){require(cursor.next(&value,&available).ok(),"guard prefix decode");if(!available)break;++seen;}require(seen==cursor.count(),"valid prefix count");}}
        require(munmap(mapping,accessible+page)==0,"guard unmap");
    }
    Encoder limited(profile,3);for(unsigned i=0;i<3;++i)require(limited.append(i).ok(),"limit append");require(limited.append(4).code==Code::ResourceLimit&&limited.samples()==3,"limit B+1");
    require(limited.finish().ok(),"limited finish");std::vector<std::int64_t> preserved{42};require(decode(limited.bytes().data(),limited.bytes().size(),&preserved,2).code==Code::ResourceLimit&&preserved==std::vector<std::int64_t>{42},"decode limit transactional");
    Cursor c;auto maximum=rle(default_sample_limit);require(c.reset(maximum.data(),maximum.size()).ok()&&c.count()==default_sample_limit,"max decoded count");
    auto excessive=rle(default_sample_limit+1);require(c.reset(excessive.data(),excessive.size()).code==Code::ResourceLimit,"oversized RLE");
    auto old=rle(10);require(c.source_init(old.data(),old.size()).ok(),"source init RLE");std::int64_t v=0;bool available=false;while(c.next(&v,&available).ok()&&available){}
    require(c.source_init(nullptr,0).ok(),"legacy empty init");for(int i=1;i<10;++i)require(c.next(&v,&available).ok()&&available&&v==i,"legacy ghost parity");require(c.next(&v,&available).ok()&&!available,"legacy count");
    require(c.reset(nullptr,0).ok()&&c.next(&v,&available).ok()&&!available,"safe clean reset after legacy");
    std::uint64_t rng=0x20261003;
    for(unsigned i=0;i<10000;++i){std::vector<std::uint8_t> malformed(i%100);
        for(auto& byte:malformed){rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;byte=std::uint8_t(rng);}
        if(c.reset(malformed.data(),malformed.size(),1000).ok())for(unsigned j=0;j<=1000;++j){require(c.next(&v,&available).ok(),"fuzz next status");if(!available)break;require(j<1000,"fuzz sample limit");}}
}
}
int main(){try{
    require(std::strcmp(version(),"influxdb-tsm-adaptive-timestamp-cpp-v1")==0,"version");
    bool supported=false;require(capability("encode.batch",&supported).ok()&&supported,"capability");require(capability("unsupported",&supported).ok()&&!supported,"unknown capability");
    std::vector<std::uint8_t> bytes{42};require(encode(nullptr,1,Profile::Batch,&bytes).code==Code::InvalidArgument&&bytes==std::vector<std::uint8_t>{42},"null input preserved output");
    require(encode(nullptr,0,static_cast<Profile>(42),&bytes).code==Code::InvalidArgument,"unknown profile");
    alignas(std::int64_t) std::uint8_t misaligned[17]{};require(encode(reinterpret_cast<std::int64_t*>(misaligned+1),1,Profile::Batch,&bytes).code==Code::InvalidArgument,"misaligned typed input");
    suite(Profile::Stream);suite(Profile::Batch);
    std::atomic<unsigned> failures{0};std::vector<std::thread> workers;
    for(unsigned i=0;i<4;++i)workers.emplace_back([&,i]{try{for(unsigned j=0;j<1000;++j){Encoder e(i%2?Profile::Stream:Profile::Batch);require(e.append(j).ok()&&e.append(j+3).ok()&&e.finish().ok(),"concurrent encode");
        std::vector<std::int64_t> values;require(decode(e.bytes().data(),e.bytes().size(),&values).ok()&&values==std::vector<std::int64_t>{j,j+3},"concurrent decode");}}catch(...){++failures;}});
    for(auto& worker:workers)worker.join();require(!failures,"independent handles");
    std::cout<<"PASS: both profiles, input/bound/canary/lifecycle/accounting/guard pages/malformed/count limits/legacy init/concurrent handles\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
