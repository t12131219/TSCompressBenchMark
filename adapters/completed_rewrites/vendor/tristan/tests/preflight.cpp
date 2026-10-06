// SPDX-License-Identifier: NOASSERTION
#include "tristan.hpp"
#include <algorithm>
#include <cfenv>
#include <cmath>
#include <cstring>
#include <future>
#include <iostream>
#include <limits>
#include <random>

namespace {
void verify(bool v,const char* msg){if(!v)throw std::runtime_error(msg);}
template<class F>void error(F f,tristan::Code code){try{f();}catch(const tristan::Error& e){verify(e.code==code,"Wrong error code");verify(std::strlen(e.what())>0,"Empty error");return;}throw std::runtime_error("Expected error missing");}
std::vector<double> values(std::size_t n,std::size_t d){std::vector<double> x(n*d);for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<d;++j)x[i*d+j]=std::sin(static_cast<double>(i)*.17+static_cast<double>(j))+.01*static_cast<double>(i*j);return x;}
void patch(std::vector<std::uint8_t>& b,std::size_t p,std::uint64_t v,std::size_t n){for(std::size_t i=0;i<n;++i)b[p+i]=static_cast<std::uint8_t>(v>>(8*i));}
void checksum(std::vector<std::uint8_t>& b){std::uint32_t crc=UINT32_MAX;for(std::size_t i=0;i<b.size();++i){crc^=(i>=88&&i<92)?0:b[i];for(int j=0;j<8;++j)crc=(crc>>1)^(0xedb88320U&(0U-(crc&1U)));}patch(b,88,~crc,4);}
}
int main(){try{
    tristan::Config c;c.length=8;c.atoms=8;c.nonzeros=2;
    auto x=values(65,3),original=x;auto bound=tristan::compress_bound(65,3,c);std::vector<std::uint8_t> dst(static_cast<std::size_t>(bound)+32,0xa5);
    error([&]{tristan::compress(x.data(),65,3,c,dst.data()+16,static_cast<std::size_t>(bound)-1);},tristan::Code::OutputTooSmall);
    verify(std::all_of(dst.begin(),dst.end(),[](auto v){return v==0xa5;}),"Failure wrote output");
    auto used=tristan::compress(x.data(),65,3,c,dst.data()+16,static_cast<std::size_t>(bound));
    verify(x==original,"Input mutated");verify(std::all_of(dst.begin(),dst.begin()+16,[](auto v){return v==0xa5;})&&std::all_of(dst.end()-16,dst.end(),[](auto v){return v==0xa5;}),"Canary damaged");
    auto frame=tristan::encode(x.data(),65,3,c);verify(used==frame.size()&&std::equal(frame.begin(),frame.end(),dst.begin()+16),"Used size or frame mismatch");
    auto decoded=tristan::decode(frame.data(),frame.size());verify(decoded.windows==8&&decoded.original_rows==65&&decoded.values.size()==192,"Shape/tail mismatch");verify(decoded.accounting.physical_bytes()==frame.size()&&decoded.accounting.final_bits()==8*frame.size(),"Accounting mismatch");
    verify(frame==tristan::encode(x.data(),65,3,c),"Nondeterministic encode");
    for(std::uint32_t solver=0;solver<5;++solver){c.solver=static_cast<tristan::Solver>(solver);auto f=tristan::encode(x.data(),65,3,c);auto d=tristan::decode(f.data(),f.size());verify(d.values.size()==192,"Solver roundtrip shape");}
    c.solver=tristan::Solver::Omp;
    for(std::size_t n:{0U,1U,2U,7U})error([&]{tristan::encode(x.data(),n,3,c);},tristan::Code::InvalidArgument);
    for(std::size_t n:{8U,9U,15U,16U,17U}){auto v=values(n,2);auto f=tristan::encode(v.data(),n,2,c);auto d=tristan::decode(f.data(),f.size());verify(d.windows==n/8,"Window boundary error");}
    for(double special:{0.,-0.,std::numeric_limits<double>::quiet_NaN(),std::numeric_limits<double>::infinity()}){
        auto v=x;for(std::size_t i=0;i<65;++i)v[i*3]=special;error([&]{tristan::encode(v.data(),65,3,c);},tristan::Code::InvalidArgument);}
    auto bad=c;bad.length=0;error([&]{tristan::compress_bound(65,3,bad);},tristan::Code::InvalidArgument);
    error([&]{tristan::compress_bound(UINT64_MAX,3,c);},tristan::Code::InvalidArgument);
    tristan::Limits small;small.workspace_bytes=1;error([&]{tristan::encode(x.data(),65,3,c,small);},tristan::Code::ResourceLimit);
    small={};small.output_bytes=10;error([&]{tristan::decode(frame.data(),frame.size(),small);},tristan::Code::ResourceLimit);
    error([&]{tristan::encode(nullptr,65,3,c);},tristan::Code::InvalidArgument);
    error([&]{tristan::compress(x.data(),65,3,c,reinterpret_cast<std::uint8_t*>(x.data()),static_cast<std::size_t>(bound));},tristan::Code::InvalidArgument);
    tristan::Config huge;c.solver=tristan::Solver::Omp;huge.atoms=UINT32_MAX;
    error([&]{tristan::train(x,1,huge);},tristan::Code::InvalidArgument);
    error([&]{tristan::sparse(x,std::numeric_limits<std::size_t>::max(),x,c);},tristan::Code::InvalidArgument);
    std::fesetround(FE_DOWNWARD);error([&]{tristan::encode(x.data(),65,3,c);},tristan::Code::Unsupported);std::fesetround(FE_TONEAREST);
    for(std::size_t cut=0;cut<frame.size();++cut)error([&]{tristan::decode(frame.data(),cut);},tristan::Code::CorruptStream);
    auto corrupt=frame;corrupt.push_back(0);error([&]{tristan::decode(corrupt.data(),corrupt.size());},tristan::Code::CorruptStream);
    for(std::size_t off:{8U,12U,16U,20U,32U,36U,40U,44U,64U,72U,80U,92U}){
        corrupt=frame;patch(corrupt,off,UINT32_MAX,4);checksum(corrupt);error([&]{tristan::decode(corrupt.data(),corrupt.size());},tristan::Code::CorruptStream);}
    corrupt=frame;patch(corrupt,96+8,0,8);checksum(corrupt);error([&]{tristan::decode(corrupt.data(),corrupt.size());},tristan::Code::CorruptStream);
    corrupt=frame;patch(corrupt,96+48,0x7ff0000000000000ULL,8);checksum(corrupt);error([&]{tristan::decode(corrupt.data(),corrupt.size());},tristan::Code::CorruptStream);
    auto row=96+48+8*c.atoms*c.length;corrupt=frame;patch(corrupt,row,UINT32_MAX,4);checksum(corrupt);error([&]{tristan::decode(corrupt.data(),corrupt.size());},tristan::Code::CorruptStream);
    corrupt=frame;patch(corrupt,row+4,c.atoms,4);checksum(corrupt);error([&]{tristan::decode(corrupt.data(),corrupt.size());},tristan::Code::CorruptStream);
    std::mt19937 rng(83);std::size_t fuzz_cases=2000;
    for(std::size_t i=0;i<fuzz_cases;++i){corrupt=frame;auto off=static_cast<std::size_t>(rng())%corrupt.size();corrupt[off]^=static_cast<std::uint8_t>((rng()%255)+1);if(i%2==0)checksum(corrupt);
        try{auto d=tristan::decode(corrupt.data(),corrupt.size());verify(d.accounting.physical_bytes()==corrupt.size(),"Accepted fuzz accounting mismatch");}catch(const tristan::Error&){} }
    auto first=std::async(std::launch::async,[&]{return tristan::encode(x.data(),65,3,c);});auto second=std::async(std::launch::async,[&]{return tristan::encode(x.data(),65,3,c);});verify(first.get()==frame&&second.get()==frame,"Independent concurrent objects changed frame");
    std::cout<<"PASS capacity canaries immutable-input all-solvers boundaries malformed fuzz="<<fuzz_cases<<" concurrent-handles\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
