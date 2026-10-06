// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0
#include "histogram_st.hpp"
#include <cstring>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace histogram_st;
namespace {
void check(Status status){if(!status.ok())throw std::runtime_error(status.message);}
std::uint64_t read_bits(){std::uint64_t value;if(!(std::cin>>std::hex>>value>>std::dec))throw std::runtime_error("invalid bits");return value;}
std::int64_t signed_bits(std::uint64_t value){std::int64_t result;std::memcpy(&result,&value,8);return result;}
std::uint64_t unsigned_bits(std::int64_t value){std::uint64_t result;std::memcpy(&result,&value,8);return result;}
std::size_t length(){std::size_t n;if(!(std::cin>>n) || n>100000)throw std::runtime_error("array limit");return n;}
std::vector<Span> read_spans(){std::vector<Span> result(length());for(auto& s:result)if(!(std::cin>>s.offset>>s.length))throw std::runtime_error("invalid span");return result;}
std::vector<std::uint64_t> read_values(bool integer){std::vector<std::uint64_t> result(length());for(auto& v:result){if(integer){std::int64_t s;if(!(std::cin>>s))throw std::runtime_error("invalid bucket");v=unsigned_bits(s);}else v=read_bits();}return result;}
bool read_sample(Sample& s,Kind kind){
    if(!(std::cin>>s.st)){if(std::cin.eof())return false;throw std::runtime_error("invalid ST");}
    unsigned hint;if(!(std::cin>>s.timestamp>>s.schema))throw std::runtime_error("invalid timestamp/schema");
    s.threshold=read_bits();if(!(std::cin>>hint) || hint>3)throw std::runtime_error("invalid hint");s.hint=std::uint8_t(hint);
    s.count=read_bits();s.zero=read_bits();s.sum=read_bits();
    s.positive_spans=read_spans();s.negative_spans=read_spans();s.custom=read_values(false);
    s.positive=read_values(kind==Kind::Integer);s.negative=read_values(kind==Kind::Integer);return true;
}
void print_bits(std::uint64_t v){std::cout<<std::hex<<std::setfill('0')<<std::setw(16)<<v<<std::dec;}
void print_spans(const std::vector<Span>& spans){std::cout<<' '<<spans.size();for(auto s:spans)std::cout<<' '<<s.offset<<' '<<s.length;}
void print_values(const std::vector<std::uint64_t>& values,bool integer){std::cout<<' '<<values.size();for(auto v:values){std::cout<<' ';if(integer)std::cout<<signed_bits(v);else print_bits(v);}}
void print_sample(const Sample& s,bool integer){
    std::cout<<s.st<<' '<<s.timestamp<<' '<<s.schema<<' ';print_bits(s.threshold);std::cout<<' '<<unsigned(s.hint)<<' ';
    print_bits(s.count);std::cout<<' ';print_bits(s.zero);std::cout<<' ';print_bits(s.sum);
    print_spans(s.positive_spans);print_spans(s.negative_spans);print_values(s.custom,false);print_values(s.positive,integer);print_values(s.negative,integer);std::cout<<'\n';
}
void print_chunk(const std::vector<std::uint8_t>& bytes){for(auto byte:bytes)std::cout<<std::hex<<std::setfill('0')<<std::setw(2)<<unsigned(byte);std::cout<<std::dec<<'\n';}
std::vector<std::uint8_t> parse_hex(const std::string& text){
    if(text.size()%2)throw std::runtime_error("odd hex");std::vector<std::uint8_t> out;
    auto nibble=[](char c)->unsigned{if(c>='0'&&c<='9')return unsigned(c-'0');if(c>='a'&&c<='f')return unsigned(c-'a'+10);if(c>='A'&&c<='F')return unsigned(c-'A'+10);throw std::runtime_error("invalid hex");};
    for(std::size_t i=0;i<text.size();i+=2)out.push_back(std::uint8_t((nibble(text[i])<<4)|nibble(text[i+1])));return out;
}
}
int main(int argc,char** argv){
    try {
        if(argc<3)throw std::runtime_error("mode kind [resume|seek] [append-only|convert]");
        std::string mode=argv[1],kind_text=argv[2];if(kind_text!="int"&&kind_text!="float")throw std::runtime_error("invalid kind");
        Kind kind=kind_text=="int"?Kind::Integer:Kind::Floating;
        if(mode=="encode"){
            unsigned resume=argc>3?unsigned(std::stoul(argv[3])):0;bool append_only=argc>4&&std::string(argv[4])=="append-only";
            Chunk chunk(kind);Sample sample;std::size_t index=0;
            while(read_sample(sample,kind)){
                auto before=chunk.bytes();auto result=chunk.append(sample,append_only);check(result.status);
                if(result.new_chunk)print_chunk(before);
                if(resume && ++index%resume==0){auto bytes=chunk.bytes();check(chunk.reset(bytes.data(),bytes.size()));}
            }
            print_chunk(chunk.bytes());
        } else if(mode=="decode"){
            bool has_seek=argc>3&&std::string(argv[3])!="none",convert=argc>4&&std::string(argv[4])=="convert";
            std::int64_t target=has_seek?std::stoll(argv[3]):0;std::string text;
            while(std::cin>>text){auto bytes=parse_hex(text);Cursor cursor;check(cursor.reset(kind,bytes.data(),bytes.size()));Sample sample;bool available=false;
                check(cursor.next(&sample,&available,convert));if(has_seek)check(cursor.seek(target,&sample,&available,convert));
                while(available){print_sample(sample,kind==Kind::Integer&&!convert);check(cursor.next(&sample,&available,convert));}
            }
        } else throw std::runtime_error("invalid mode");
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 3;}
}
