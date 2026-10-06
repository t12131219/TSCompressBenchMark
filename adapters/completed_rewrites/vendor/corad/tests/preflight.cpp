// SPDX-License-Identifier: NOASSERTION
#include "corad.hpp"
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
template<class F>void error(F f,corad::Code code){try{f();}catch(const corad::Error& e){verify(e.code==code,"Wrong error code");verify(std::strlen(e.what())>0,"Empty error");return;}throw std::runtime_error("Expected error missing");}
std::vector<double> values(std::size_t n,std::size_t d){std::vector<double> x(n*d);for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<d;++j)x[i*d+j]=std::sin(static_cast<double>(i)*.17+static_cast<double>(j))+.01*static_cast<double>(i*j);return x;}
void patch(std::vector<std::uint8_t>& b,std::size_t p,std::uint64_t v,std::size_t n){for(std::size_t i=0;i<n;++i)b[p+i]=static_cast<std::uint8_t>(v>>(8*i));}
void checksum(std::vector<std::uint8_t>& b){std::uint32_t crc=UINT32_MAX;for(std::size_t i=0;i<b.size();++i){crc^=(i>=88&&i<92)?0:b[i];for(int j=0;j<8;++j)crc=(crc>>1)^(0xedb88320U&(0U-(crc&1U)));}patch(b,88,~crc,4);}
}
int main(){try{
    corad::Config c;c.length=8;c.atoms=8;c.nonzeros=2;c.threshold=2.;
    auto x=values(65,3),original=x;auto bound=corad::compress_bound(65,3,c);std::vector<std::uint8_t> dst(static_cast<std::size_t>(bound)+32,0xa5);
    error([&]{corad::compress(x.data(),65,3,c,dst.data()+16,static_cast<std::size_t>(bound)-1);},corad::Code::OutputTooSmall);
    verify(std::all_of(dst.begin(),dst.end(),[](auto v){return v==0xa5;}),"Failure wrote output");
    auto used=corad::compress(x.data(),65,3,c,dst.data()+16,static_cast<std::size_t>(bound));
    verify(x==original,"Input mutated");verify(std::all_of(dst.begin(),dst.begin()+16,[](auto v){return v==0xa5;})&&std::all_of(dst.end()-16,dst.end(),[](auto v){return v==0xa5;}),"Canary damaged");
    auto frame=corad::encode(x.data(),65,3,c);verify(used==frame.size()&&std::equal(frame.begin(),frame.end(),dst.begin()+16),"Used size or frame mismatch");
    auto decoded=corad::decode(frame.data(),frame.size());verify(decoded.windows==8&&decoded.original_rows==65&&decoded.values.size()==192,"Shape/tail mismatch");verify(decoded.accounting.physical_bytes()==frame.size()&&decoded.accounting.final_bits()==8*frame.size(),"Accounting mismatch");
    verify(frame==corad::encode(x.data(),65,3,c),"Nondeterministic encode");
    for(std::uint32_t solver=0;solver<5;++solver){c.solver=static_cast<corad::Solver>(solver);auto f=corad::encode(x.data(),65,3,c);auto d=corad::decode(f.data(),f.size());verify(d.values.size()==192,"Solver roundtrip shape");}
    c.solver=corad::Solver::Omp;
    for(std::size_t n:{0U,1U,2U,7U})error([&]{corad::encode(x.data(),n,3,c);},corad::Code::InvalidArgument);
    for(std::size_t n:{8U,9U,15U,16U,17U}){auto v=values(n,2);auto f=corad::encode(v.data(),n,2,c);auto d=corad::decode(f.data(),f.size());verify(d.windows==n/8,"Window boundary error");}
    for(double special:{0.,-0.,std::numeric_limits<double>::quiet_NaN(),std::numeric_limits<double>::infinity()}){
        auto v=x;for(std::size_t i=0;i<65;++i)v[i*3]=special;error([&]{corad::encode(v.data(),65,3,c);},corad::Code::InvalidArgument);}
    auto bad=c;bad.length=0;error([&]{corad::compress_bound(65,3,bad);},corad::Code::InvalidArgument);
    error([&]{corad::compress_bound(UINT64_MAX,3,c);},corad::Code::InvalidArgument);
    corad::Limits small;small.workspace_bytes=1;error([&]{corad::encode(x.data(),65,3,c,small);},corad::Code::ResourceLimit);
    small={};small.output_bytes=10;error([&]{corad::decode(frame.data(),frame.size(),small);},corad::Code::ResourceLimit);
    error([&]{corad::encode(nullptr,65,3,c);},corad::Code::InvalidArgument);
    error([&]{corad::compress(x.data(),65,3,c,reinterpret_cast<std::uint8_t*>(x.data()),static_cast<std::size_t>(bound));},corad::Code::InvalidArgument);
    corad::Config huge;c.solver=corad::Solver::Omp;huge.atoms=UINT32_MAX;
    error([&]{tristan::train(x,1,huge);},corad::Code::InvalidArgument);
    error([&]{tristan::sparse(x,std::numeric_limits<std::size_t>::max(),x,c);},corad::Code::InvalidArgument);
    std::fesetround(FE_DOWNWARD);error([&]{corad::encode(x.data(),65,3,c);},corad::Code::Unsupported);std::fesetround(FE_TONEAREST);
    for(std::size_t cut=0;cut<frame.size();++cut)error([&]{corad::decode(frame.data(),cut);},corad::Code::CorruptStream);
    auto corrupt=frame;corrupt.push_back(0);error([&]{corad::decode(corrupt.data(),corrupt.size());},corad::Code::CorruptStream);
    for(std::size_t off:{8U,12U,16U,20U,32U,36U,40U,44U,64U,72U,80U,92U}){
        corrupt=frame;patch(corrupt,off,UINT32_MAX,4);checksum(corrupt);error([&]{corad::decode(corrupt.data(),corrupt.size());},corad::Code::CorruptStream);}
    corrupt=frame;patch(corrupt,104+8,0,8);checksum(corrupt);error([&]{corad::decode(corrupt.data(),corrupt.size());},corad::Code::CorruptStream);
    corrupt=frame;patch(corrupt,104+48,0x7ff0000000000000ULL,8);checksum(corrupt);error([&]{corad::decode(corrupt.data(),corrupt.size());},corad::Code::CorruptStream);
    auto row=104+48+8*c.atoms*c.length;corrupt=frame;patch(corrupt,row,UINT32_MAX,4);checksum(corrupt);error([&]{corad::decode(corrupt.data(),corrupt.size());},corad::Code::CorruptStream);
    corrupt=frame;patch(corrupt,row+4,c.atoms,4);checksum(corrupt);error([&]{corad::decode(corrupt.data(),corrupt.size());},corad::Code::CorruptStream);
    auto u32=[](const std::vector<std::uint8_t>& b,std::size_t p){std::uint32_t n=0;for(std::size_t i=0;i<4;++i)n|=static_cast<std::uint32_t>(b[p+i])<<(8*i);return n;};
    auto v=values(8,2);auto forward=corad::encode(v.data(),8,2,c);auto first_row=104+32+8*c.atoms*c.length;
    auto replace_row=[&](std::vector<std::uint8_t>& b,std::size_t off,std::uint32_t target){auto tag=u32(b,off);auto length=tag==UINT32_MAX?8U:4U+12U*tag;
        b.erase(b.begin()+static_cast<std::ptrdiff_t>(off),b.begin()+static_cast<std::ptrdiff_t>(off+length));b.insert(b.begin()+static_cast<std::ptrdiff_t>(off),8,0);patch(b,off,UINT32_MAX,4);patch(b,off+4,target,4);patch(b,72,b.size()-104,8);checksum(b);};
    replace_row(forward,first_row,1);auto fwd=corad::decode(forward.data(),forward.size());verify(std::equal(fwd.values.begin(),fwd.values.begin()+8,fwd.values.begin()+8),"Forward reference not copied");verify(fwd.accounting.reference_bytes==4,"Reference accounting wrong");
    auto self=forward;patch(self,first_row+4,0,4);checksum(self);error([&]{corad::decode(self.data(),self.size());},corad::Code::CorruptStream);
    auto outside=forward;patch(outside,first_row+4,2,4);checksum(outside);error([&]{corad::decode(outside.data(),outside.size());},corad::Code::CorruptStream);
    auto cycle=forward;replace_row(cycle,first_row+8,0);error([&]{corad::decode(cycle.data(),cycle.size());},corad::Code::CorruptStream);
    corrupt=frame;patch(corrupt,96,0x7ff8000000000000ULL,8);checksum(corrupt);error([&]{corad::decode(corrupt.data(),corrupt.size());},corad::Code::CorruptStream);
    error([&]{corad::correlate(nullptr,65,3,8,.8);},corad::Code::InvalidArgument);
    error([&]{corad::correlate(x.data(),65,3,8,std::numeric_limits<double>::quiet_NaN());},corad::Code::InvalidArgument);
    std::mt19937 rng(83);std::size_t fuzz_cases=2000;
    for(std::size_t i=0;i<fuzz_cases;++i){corrupt=frame;auto off=static_cast<std::size_t>(rng())%corrupt.size();corrupt[off]^=static_cast<std::uint8_t>((rng()%255)+1);if(i%2==0)checksum(corrupt);
        try{auto d=corad::decode(corrupt.data(),corrupt.size());verify(d.accounting.physical_bytes()==corrupt.size(),"Accepted fuzz accounting mismatch");}catch(const corad::Error&){} }
    auto first=std::async(std::launch::async,[&]{return corad::encode(x.data(),65,3,c);});auto second=std::async(std::launch::async,[&]{return corad::encode(x.data(),65,3,c);});verify(first.get()==frame&&second.get()==frame,"Independent concurrent objects changed frame");
    std::cout<<"PASS capacity canaries immutable-input all-solvers boundaries malformed fuzz="<<fuzz_cases<<" concurrent-handles\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
