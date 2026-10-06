// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0
#include "histogram_st.hpp"
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
using namespace histogram_st;
namespace {
void require(bool b,const char* message){if(!b)throw std::runtime_error(message);}
std::uint64_t bits(double value){std::uint64_t n;std::memcpy(&n,&value,8);return n;}
Sample make(Kind kind){Sample s;s.st=100;s.count=kind==Kind::Integer?3:bits(3.);s.positive_spans={{0,2}};s.positive=kind==Kind::Integer?std::vector<std::uint64_t>{1,1}:std::vector<std::uint64_t>{bits(1.),bits(2.)};return s;}
std::string hex(const std::vector<std::uint8_t>& bytes){std::ostringstream out;out<<std::hex<<std::setfill('0');for(auto b:bytes)out<<std::setw(2)<<unsigned(b);return out.str();}
}
int main(int argc,char** argv){try{
    require(argc==2,"source public API expectations required");std::ifstream input(argv[1]);require(bool(input),"missing oracle file");
    std::string record;unsigned checks=0;
    while(input>>record){
        if(record=="previous"){
            std::string name,expected;unsigned index;input>>name>>index>>expected;Kind kind=name=="int"?Kind::Integer:Kind::Floating;
            Kind old_kind=index==5?(kind==Kind::Integer?Kind::Floating:Kind::Integer):kind;
            Chunk previous(old_kind),current(kind);auto old=make(old_kind);if(index==2)old.hint=3;
            if(index!=4 && index!=5)require(previous.append(old).status.ok(),"previous append");
            auto value=make(kind);value.timestamp=1000;if(index==1)value.count=kind==Kind::Integer?2:bits(2.);if(index==3)value.schema=1;
            require(current.append(value,false,&previous).status.ok(),"current append");require(hex(current.bytes())==expected,"previous-appender oracle differs");
        }else if(record=="conversion"){
            std::string reuse;std::uint64_t a,b;input>>reuse>>std::hex>>a>>b>>std::dec;
            Chunk chunk(Kind::Integer);auto value=make(Kind::Integer);value.count=9007199254740996ULL;
            value.positive={9007199254740993ULL,std::uint64_t(0)-9007199254740990ULL};require(chunk.append(value).status.ok(),"large integer encode");
            Cursor cursor;require(cursor.reset(Kind::Integer,chunk.bytes().data(),chunk.size_bytes()).ok(),"conversion reset");Sample observed;bool available=false;
            require(cursor.next(&observed,&available,true,reuse=="true").ok() && available,"conversion next");
            require(observed.positive==std::vector<std::uint64_t>{a,b},"conversion source output-reuse arithmetic differs");
        }else throw std::runtime_error("unknown source record");
        ++checks;
    }
    require(checks==14,"incomplete API oracle");std::cout<<"PASS: 12 previous-appender cases, 2 conversion arithmetic modes\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
