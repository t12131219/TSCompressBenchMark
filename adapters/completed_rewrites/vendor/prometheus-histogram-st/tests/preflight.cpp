// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0
#include "histogram_st.hpp"
#include <algorithm>
#include <atomic>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <thread>
#if defined(__unix__)
#include <sys/mman.h>
#include <unistd.h>
#endif
using namespace histogram_st;
namespace {
void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
std::uint64_t bits(double value){std::uint64_t n;std::memcpy(&n,&value,8);return n;}
Sample make(Kind kind,std::size_t index=0){
    Sample s;s.timestamp=std::int64_t(index*1000);s.st=100;s.hint=3;
    s.count=kind==Kind::Integer?index+3:bits(double(index)+3.);s.sum=bits(double(index));s.zero=kind==Kind::Integer?0:bits(0.);
    s.positive_spans={{0,2}};s.positive=kind==Kind::Integer?std::vector<std::uint64_t>{index+1,1}:std::vector<std::uint64_t>{bits(double(index)+1.),bits(double(index)+2.)};return s;
}
void suite(Kind kind){
    Chunk chunk(kind);require(chunk.size_bytes()==3 && chunk.samples()==0,"empty chunk");
    Cursor cursor;Sample observed;bool available=true;require(cursor.reset(kind,chunk.bytes().data(),chunk.size_bytes()).ok(),"empty reset");
    require(cursor.next(&observed,&available).ok() && !available,"empty next");
    for(std::size_t i=0;i<130;++i){auto input=make(kind,i);auto original=input.positive;std::size_t bound=0;
        require(chunk.append_bound(input,&bound).ok(),"bound query");auto result=chunk.append(input);require(result.status.ok(),"append");
        require(!result.new_chunk && chunk.size_bytes()<=bound,"bound/append flags");require(input.positive==original,"input mutated");
        if(i==1 || i==126 || i==127){auto bytes=chunk.bytes();require(chunk.reset(bytes.data(),bytes.size()).ok(),"alias import resume");}
    }
    auto snapshot=chunk.bytes();auto incompatible=make(kind,131);incompatible.schema=1;
    require(chunk.append(incompatible,true).status.code==Code::AppendOnly && chunk.bytes()==snapshot,"append-only transactional failure");
    Chunk layout_chunk(kind);auto narrow=make(kind);require(layout_chunk.append(narrow).status.ok(),"layout setup");
    auto wide=narrow;wide.timestamp=1000;wide.positive_spans={{0,3}};
    wide.positive=kind==Kind::Integer?std::vector<std::uint64_t>{1,1,0}:std::vector<std::uint64_t>{bits(1.),bits(2.),bits(2.)};
    auto unchanged=layout_chunk.bytes();
    require(layout_chunk.append(wide,true).status.code==Code::AppendOnly && layout_chunk.bytes()==unchanged,"append-only forward recode");
    require(layout_chunk.clear().ok() && layout_chunk.append(wide).status.ok(),"backward setup");
    unchanged=layout_chunk.bytes();narrow.timestamp=2000;
    require(layout_chunk.append(narrow,true).status.code==Code::AppendOnly && layout_chunk.bytes()==unchanged,"append-only gauge backward recode");
    std::vector<std::uint8_t> canary(chunk.size_bytes()+2,0xa5);std::size_t written=0;
    require(chunk.finalize(canary.data()+1,chunk.size_bytes()-1,&written).code==Code::OutputTooSmall,"bound-1 finalize");
    require(std::all_of(canary.begin(),canary.end(),[](auto v){return v==0xa5;}),"bound-1 touched output");
    require(chunk.finalize(canary.data()+1,chunk.size_bytes(),&written).ok() && written==chunk.size_bytes(),"exact finalize");
    require(canary.front()==0xa5 && canary.back()==0xa5,"output canary");
    require(chunk.finalize(canary.data()+1,chunk.size_bytes(),&written).ok(),"repeat finalize");
    require(chunk.compact().ok() && chunk.bytes()==snapshot && chunk.payload_bits()==8*chunk.size_bytes()
            && chunk.final_bits()==chunk.payload_bits()+72 && chunk.frame_bytes()==chunk.size_bytes()+9,"compact/accounting");
    std::vector<std::uint8_t> frame(chunk.frame_bytes()+2,0xc7);
    require(chunk.serialize_frame(frame.data()+1,chunk.frame_bytes()-1,&written).code==Code::OutputTooSmall,"frame bound-1");
    require(std::all_of(frame.begin(),frame.end(),[](auto v){return v==0xc7;}),"frame bound-1 mutated output");
    require(chunk.serialize_frame(frame.data()+1,chunk.frame_bytes(),&written).ok(),"serialize frame");
    require(frame.front()==0xc7 && frame.back()==0xc7,"frame canary");
    require(cursor.reset_frame(frame.data()+1,chunk.frame_bytes()).ok(),"self-contained frame cursor");
    require(cursor.next(&observed,&available).ok() && available && observed.st==100,"frame decode");
    Chunk framed(kind==Kind::Integer?Kind::Floating:Kind::Integer);
    require(framed.reset_frame(frame.data()+1,chunk.frame_bytes()).ok() && framed.kind()==kind && framed.bytes()==snapshot,"frame kind/length reset");
    require(!framed.reset_frame(frame.data()+1,chunk.frame_bytes()-1).ok() && framed.bytes()==snapshot,"frame truncation transactional failure");
    auto valid_encoding=frame[1];frame[1]=255;
    require(!framed.reset_frame(frame.data()+1,chunk.frame_bytes()).ok() && framed.bytes()==snapshot,"invalid frame encoding");frame[1]=valid_encoding;
    require(cursor.reset(kind,snapshot.data(),snapshot.size()).ok(),"cursor reset");
    for(std::size_t i=0;i<130;++i){require(cursor.next(&observed,&available).ok() && available,"next");
        require(observed.timestamp==std::int64_t(i*1000) && observed.st==100,"paired ST/timestamp");}
    require(cursor.next(&observed,&available).ok() && !available,"exhaustion");
    require(cursor.reset(kind,snapshot.data(),snapshot.size()).ok(),"cursor reuse");
    require(cursor.seek(127001,&observed,&available).ok() && available && observed.timestamp==128000,"seek");
    require(cursor.next(nullptr,&available).code==Code::InvalidArgument,"null next");
    for(std::size_t length=0;length<snapshot.size();++length){
        Chunk imported(kind);auto status=imported.reset(snapshot.data(),length);
        require(!status.ok(),"truncated import accepted");require(imported.samples()==0 && imported.size_bytes()==3,"failed import modified chunk");
    }
#if defined(__unix__)
    // An inaccessible page immediately after the last byte proves zero overread.
    const auto page=std::size_t(sysconf(_SC_PAGESIZE));
    const auto accessible=((snapshot.size()+page-1)/page)*page;
    auto* mapping=static_cast<std::uint8_t*>(mmap(nullptr,accessible+page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
    require(mapping!=MAP_FAILED,"guard mapping");
    require(mprotect(mapping+accessible,page,PROT_NONE)==0,"guard protection");
    auto* guarded=mapping+accessible-snapshot.size();
    std::memcpy(guarded,snapshot.data(),snapshot.size());
    require(cursor.reset(kind,guarded,snapshot.size()).ok(),"guard reset");
    for(unsigned i=0;i<130;++i)require(cursor.next(&observed,&available).ok() && available,"guard decode");
    for(std::size_t length=0;length<snapshot.size();++length){
        auto* truncated=mapping+accessible-length;
        std::memcpy(truncated,snapshot.data(),length);
        Chunk imported(kind);require(!imported.reset(truncated,length).ok(),"guard truncation accepted");
    }
    require(munmap(mapping,accessible+page)==0,"guard unmap");
#endif
    // The malformed corpus includes allocation-sized fields and arbitrary bits.
    std::uint64_t rng=0x20261003;
    for(unsigned i=0;i<3000;++i){std::vector<std::uint8_t> malformed(3+i%100);
        for(auto& byte:malformed){rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;byte=std::uint8_t(rng);}
        malformed[0]=0;malformed[1]=1;
        (void)cursor.reset(kind,malformed.data(),malformed.size());(void)cursor.next(&observed,&available);
    }
    require(chunk.clear().ok() && chunk.samples()==0 && chunk.size_bytes()==3,"clear lifecycle");
    // Explicit native sample count boundary and stable error at B+1.
    for(std::size_t i=0;i<16383;++i)require(chunk.append(make(kind,i)).status.ok(),"capacity append");
    require(chunk.samples()==16383,"capacity count");auto before=chunk.bytes();
    require(chunk.append(make(kind,16383)).status.code==Code::SampleLimit && before==chunk.bytes(),"capacity B+1");
}
}
int main(){try{
    require(std::strcmp(version(),"prometheus-histogram-st-cpp-v1")==0,"version");
    bool supported=false;require(capability("stream.resume",&supported).ok() && supported,"capability query");
    require(capability("unsupported.capability",&supported).ok() && !supported,"unknown capability");
    require(capability(nullptr,&supported).code==Code::InvalidArgument,"null capability");
    suite(Kind::Integer);suite(Kind::Floating);
    std::atomic<unsigned> failures{0};std::vector<std::thread> workers;
    for(unsigned i=0;i<4;++i)workers.emplace_back([&,i]{try{for(unsigned j=0;j<200;++j){Chunk c(i%2?Kind::Integer:Kind::Floating);require(c.append(make(c.kind(),j)).status.ok(),"independent handle");auto bytes=c.bytes();require(c.reset(bytes.data(),bytes.size()).ok(),"concurrent import");}}catch(...){++failures;}});
    for(auto& worker:workers)worker.join();require(!failures,"concurrent handles");
    std::cout<<"PASS: lifecycle/buffer/input/seek/truncation/guard-page/malformed/capacity/concurrent handles\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
