// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: MIT
#include "tsm_timestamp.hpp"
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
using namespace tsm_timestamp;
void check(Status s){if(!s.ok())throw std::runtime_error(s.message);}
int main(int argc,char** argv){try{
    if(argc!=3)throw std::runtime_error("encode|decode|count|legacy-empty stream|batch");
    const std::string mode=argv[1],profile=argv[2];if(profile!="stream"&&profile!="batch")throw std::runtime_error("invalid profile");
    if(mode=="encode"){
        std::vector<std::int64_t> values;std::int64_t n;while(std::cin>>n)values.push_back(n);if(!std::cin.eof())throw std::runtime_error("invalid int64");
        std::vector<std::uint8_t> bytes;check(encode(values.data(),values.size(),profile=="stream"?Profile::Stream:Profile::Batch,&bytes));
        for(auto byte:bytes)std::cout<<std::hex<<std::setfill('0')<<std::setw(2)<<unsigned(byte);std::cout<<'\n';
    }else if(mode=="legacy-empty"){
        Encoder encoder;for(int i=0;i<10;++i)check(encoder.append(100+i*1000));check(encoder.finish());Cursor c;check(c.source_init(encoder.bytes().data(),encoder.bytes().size()));
        std::int64_t n;bool available=false;while(c.next(&n,&available).ok()&&available){}check(c.source_init(nullptr,0));
        while(c.next(&n,&available).ok()&&available)std::cout<<n<<'\n';
    }else if(mode=="decode"||mode=="count"){
        std::string hex;std::cin>>hex;if(hex.size()%2)throw std::runtime_error("odd hex");std::vector<std::uint8_t> bytes;
        for(std::size_t i=0;i<hex.size();i+=2){std::size_t parsed=0;auto n=std::stoul(hex.substr(i,2),&parsed,16);if(parsed!=2)throw std::runtime_error("invalid hex");bytes.push_back(std::uint8_t(n));}
        if(mode=="count"){std::size_t count=0;check(count_timestamps(bytes.data(),bytes.size(),&count));std::cout<<count<<'\n';
        }else if(profile=="batch"){std::vector<std::int64_t> out;check(decode(bytes.data(),bytes.size(),&out));for(auto n:out)std::cout<<n<<'\n';
        }else{Cursor c;check(c.reset(bytes.data(),bytes.size()));std::int64_t n;bool available=false;
            for(;;){check(c.next(&n,&available));if(!available)break;std::cout<<n<<'\n';}}
    }else throw std::runtime_error("invalid mode");return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 3;}}
