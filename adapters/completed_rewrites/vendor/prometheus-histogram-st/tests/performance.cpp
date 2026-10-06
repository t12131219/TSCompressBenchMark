// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0
#include "histogram_st.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/resource.h>
using namespace histogram_st;
namespace {
void check(Status s){if(!s.ok())throw std::runtime_error(s.message);}
std::vector<std::uint8_t> unhex(const std::string& s){
    if(s.size()%2)throw std::runtime_error("odd hex");
    std::vector<std::uint8_t> b;
    for(std::size_t i=0;i<s.size();i+=2)b.push_back(std::uint8_t(std::stoul(s.substr(i,2),nullptr,16)));
    return b;
}
using Clock=std::chrono::steady_clock;
double micros(Clock::time_point start){return std::chrono::duration<double,std::micro>(Clock::now()-start).count();}
std::vector<std::uint8_t> frame(const Chunk& c){
    std::vector<std::uint8_t> b(c.frame_bytes());std::size_t n=0;
    check(c.serialize_frame(b.data(),b.size(),&n));return b;
}
}
int main(int argc,char** argv){try{
    if(argc!=3)throw std::runtime_error("kind chunks.hex");
    const Kind kind=std::string(argv[1])=="int"?Kind::Integer:Kind::Floating;
    std::ifstream input(argv[2]);if(!input)throw std::runtime_error("input missing");
    std::vector<Sample> samples;std::vector<std::vector<std::uint8_t>> expected;
    std::string text;
    while(input>>text){auto bytes=unhex(text);Cursor cursor;check(cursor.reset(kind,bytes.data(),bytes.size()));
        Sample s;bool available=false;
        for(;;){check(cursor.next(&s,&available));if(!available)break;samples.push_back(s);}
        expected.push_back(std::move(bytes));
    }
    std::uint64_t checksum=0;
    std::cout<<"{\"warmups\":3,\"repetitions\":15,\"samples\":"<<samples.size()<<",\"runs\":[";
    for(unsigned iteration=0;iteration<18;++iteration){
        auto start=Clock::now();
        // Setup, immutable caller copy, append/recode and frame allocation/export.
        auto caller=samples;Chunk c(kind);
        std::vector<std::vector<std::uint8_t>> frames,raw;
        for(const auto& s:caller){auto old=c;auto result=c.append(s);check(result.status);
            if(result.new_chunk){frames.push_back(frame(old));raw.push_back(old.bytes());}}
        frames.push_back(frame(c));raw.push_back(c.bytes());
        const double encode_us=micros(start);
        if(raw!=expected)throw std::runtime_error("benchmark re-encode differs from oracle");
        std::size_t physical=0,payload=0;for(const auto& b:frames)physical+=b.size();for(const auto& b:raw)payload+=b.size();
        start=Clock::now();
        auto transported=frames;std::vector<Sample> decoded;
        for(const auto& b:transported){Cursor cursor;check(cursor.reset_frame(b.data(),b.size()));Sample s;bool available=false;
            for(;;){check(cursor.next(&s,&available));if(!available)break;decoded.push_back(s);checksum^=s.sum;}}
        const double decode_us=micros(start);
        if(decoded.size()!=samples.size())throw std::runtime_error("benchmark sample count");
        if(iteration>=3){if(iteration>3)std::cout<<',';
            std::cout<<"{\"encode_us\":"<<encode_us<<",\"decode_us\":"<<decode_us<<",\"payload_bytes\":"<<payload
                <<",\"frame_bytes\":"<<physical<<",\"chunk_count\":"<<frames.size()<<'}';}
    }
    rusage usage{};if(getrusage(RUSAGE_SELF,&usage))throw std::runtime_error("getrusage");
    std::cout<<"],\"max_rss_kib\":"<<usage.ru_maxrss<<",\"checksum\":"<<checksum<<"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
