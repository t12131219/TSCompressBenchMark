// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: MIT
#include "tsm_timestamp.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
using namespace tsm_timestamp;
void check(Status s){if(!s.ok())throw std::runtime_error(s.message);}
int main(int argc,char** argv){try{
    if(argc!=3)throw std::runtime_error("stream|batch input.txt");
    auto profile=std::string(argv[1])=="stream"?Profile::Stream:Profile::Batch;
    std::ifstream input(argv[2]);if(!input)throw std::runtime_error("missing input");
    std::vector<std::int64_t> values;std::int64_t value;while(input>>value)values.push_back(value);
    std::vector<std::uint8_t> expected;check(encode(values.data(),values.size(),profile,&expected));
    std::cout<<"{\"warmups\":3,\"repetitions\":15,\"samples\":"<<values.size()<<",\"runs\":[";
    std::uint64_t checksum=0;
    using Clock=std::chrono::steady_clock;
    for(unsigned iteration=0;iteration<18;++iteration){
        auto start=Clock::now();auto caller=values;std::vector<std::uint8_t> encoded;
        if(profile==Profile::Stream){Encoder encoder(profile);for(auto v:caller)check(encoder.append(v));check(encoder.finish());encoded=encoder.bytes();}
        else check(encode(caller.data(),caller.size(),profile,&encoded));
        const auto encode_us=std::chrono::duration<double,std::micro>(Clock::now()-start).count();
        if(encoded!=expected)throw std::runtime_error("encode output changed");
        start=Clock::now();auto transported=encoded;std::vector<std::int64_t> decoded;
        if(profile==Profile::Batch)check(decode(transported.data(),transported.size(),&decoded));
        else{Cursor cursor;check(cursor.reset(transported.data(),transported.size()));bool available=false;
            for(;;){check(cursor.next(&value,&available));if(!available)break;decoded.push_back(value);}}
        const auto decode_us=std::chrono::duration<double,std::micro>(Clock::now()-start).count();
        if(decoded!=values)throw std::runtime_error("decode output changed");
        for(auto v:decoded)checksum^=std::uint64_t(v);
        if(iteration>=3){if(iteration>3)std::cout<<',';std::cout<<"{\"encode_us\":"<<encode_us<<",\"decode_us\":"<<decode_us<<",\"physical_bytes\":"<<encoded.size()<<'}';}
    }
    rusage usage{};if(getrusage(RUSAGE_SELF,&usage))throw std::runtime_error("getrusage");
    std::cout<<"],\"max_rss_kib\":"<<usage.ru_maxrss<<",\"checksum\":"<<checksum<<"}\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
