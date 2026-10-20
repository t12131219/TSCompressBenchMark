// Independent trusted-fixture driver. Compiled ONLY against frozen original
// upstream headers/TUs, never vendor or alp_port. Not an untrusted file API.
#include <array>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>
#include "alp.hpp"
namespace {
struct Bytes {
    std::vector<unsigned char> data; size_t at=0;
    void put(uint64_t x,size_t n){for(size_t i=0;i<n;++i){data.push_back(x&255);x>>=8;}}
    uint64_t get(size_t n){if(n>data.size()-at)throw std::runtime_error("short trusted fixture");uint64_t x=0;for(size_t i=0;i<n;++i)x|=uint64_t(data[at++])<<(i*8);return x;}
    template<class T> void store(const T* p,size_t bytes){for(size_t i=0;i<bytes/sizeof(T);++i){std::make_unsigned_t<T> v;std::memcpy(&v,p+i,sizeof(T));put(v,sizeof(T));}}
    template<class T> void load(T* p,size_t bytes){for(size_t i=0;i<bytes/sizeof(T);++i){auto v=static_cast<std::make_unsigned_t<T>>(get(sizeof(T)));std::memcpy(p+i,&v,sizeof(T));}}
};
uint32_t crc(const std::vector<unsigned char>& b){uint32_t c=~0u;for(size_t i=0;i<b.size();++i){if(i>=28&&i<32)continue;c^=b[i];for(int k=0;k<8;++k)c=(c>>1)^(0xedb88320u&(0u-(c&1)));}return ~c;}
template<class T> Bytes compress(const Bytes& raw,uint8_t method){
    using ST=typename alp::inner_t<T>::st;using UT=typename alp::inner_t<T>::ut;
    const size_t n=raw.data.size()/sizeof(T);Bytes out;
    for(char c:std::string("ALPRW001"))out.put(c,1);out.put(sizeof(T),1);out.put(method,1);out.put(0,2);out.put(n,8);out.put(0,8);out.put(0,4);
    for(size_t start=0;start<n;start+=alp::config::ROWGROUP_SIZE){
        const size_t count=std::min(alp::config::ROWGROUP_SIZE,n-start),padded=(count+1023)/1024*1024;
        std::vector<T> v(padded,T(0));std::memcpy(v.data(),raw.data.data()+start*sizeof(T),count*sizeof(T));
        std::array<T,1024> samples{},exception{},decoded{};
        std::array<ST,1024> digit{},packed{},unpacked{};
        std::array<UT,1024> right{},pr{},ur{};
        std::array<uint16_t,1024> left{},pl{},ul{},positions{},rex{};
        alp::state<T> s;
        if(method)alp::rd_encoder<T>::init(v.data(),0,padded,samples.data(),s);
        else {alp::encoder<T>::init(v.data(),0,padded,samples.data(),s);if(s.scheme==alp::Scheme::ALP_RD)alp::rd_encoder<T>::init(v.data(),0,padded,samples.data(),s);}
        const bool rd=s.scheme==alp::Scheme::ALP_RD;
        out.put(rd?1:2,1);out.put(rd?s.right_bit_width:0,1);out.put(rd?s.left_bit_width:0,1);out.put(rd?s.actual_dictionary_size:0,1);out.put(count,4);
        for(auto x:s.left_parts_dict)out.put(rd?x:0,2);out.put(0,8);
        for(size_t k=0;k<padded;k+=1024){
            uint16_t ec=0;ST base=0;uint8_t bw=0;
            if(rd){
                alp::rd_encoder<T>::encode(v.data()+k,rex.data(),positions.data(),&ec,right.data(),left.data(),s);
                ffor::ffor(right.data(),pr.data(),s.right_bit_width,&s.right_for_base);ffor::ffor(left.data(),pl.data(),s.left_bit_width,&s.left_for_base);
            }else{
                alp::encoder<T>::encode(v.data()+k,exception.data(),positions.data(),&ec,digit.data(),s);
                alp::encoder<T>::analyze_ffor(digit.data(),bw,&base);ffor::ffor(digit.data(),packed.data(),bw,&base);
            }
            out.put(std::min(size_t(1024),count-k),2);out.put(ec,2);out.put(bw,1);out.put(rd?0:s.fac,1);out.put(rd?0:s.exp,1);out.put(0,1);
            UT bb;std::memcpy(&bb,&base,sizeof(ST));out.put(bb,8);
            if(rd){out.store(pr.data(),size_t(s.right_bit_width)*128);out.store(pl.data(),size_t(s.left_bit_width)*128);}
            else out.store(packed.data(),size_t(bw)*128);
            for(size_t j=0;j<ec;++j){out.put(positions[j],2);if(rd)out.put(rex[j],2);else{UT bb;std::memcpy(&bb,&exception[j],sizeof(T));out.put(bb,sizeof(T));}}
        }
    }
    uint64_t size=out.data.size()-32;for(int i=0;i<8;++i)out.data[20+i]=size>>(i*8);
    uint32_t c=crc(out.data);for(int i=0;i<4;++i)out.data[28+i]=c>>(i*8);return out;
}
template<class T> Bytes decompress(Bytes& in){
    using ST=typename alp::inner_t<T>::st;using UT=typename alp::inner_t<T>::ut;
    in.at=12;size_t n=in.get(8);if(n>16777216)throw std::runtime_error("fixture resource limit");in.at=32;Bytes out;
    for(size_t start=0;start<n;start+=102400){
        alp::state<T> s;bool rd=in.get(1)==1;s.right_bit_width=in.get(1);s.left_bit_width=in.get(1);s.actual_dictionary_size=in.get(1);size_t count=in.get(4);
        for(auto& x:s.left_parts_dict)x=in.get(2);in.get(8);
        for(size_t k=0;k<count;k+=1024){
            auto take=in.get(2);uint16_t ec=in.get(2);uint8_t bw=in.get(1),fac=in.get(1),exp=in.get(1);in.get(1);UT bb=in.get(8);ST base;std::memcpy(&base,&bb,sizeof(ST));
            std::array<ST,1024> packed{},digits{};std::array<UT,1024> pr{},right{};std::array<uint16_t,1024> pl{},left{},positions{},rex{};std::array<T,1024> values{},exceptions{};
            if(rd){in.load(pr.data(),size_t(s.right_bit_width)*128);in.load(pl.data(),size_t(s.left_bit_width)*128);unffor::unffor(pr.data(),right.data(),s.right_bit_width,&s.right_for_base);unffor::unffor(pl.data(),left.data(),s.left_bit_width,&s.left_for_base);}
            else{in.load(packed.data(),size_t(bw)*128);unffor::unffor(packed.data(),digits.data(),bw,&base);alp::decoder<T>::decode(digits.data(),fac,exp,values.data());}
            for(size_t j=0;j<ec;++j){positions[j]=in.get(2);if(rd)rex[j]=in.get(2);else{UT b=in.get(sizeof(T));std::memcpy(&exceptions[j],&b,sizeof(T));}}
            if(rd)alp::rd_encoder<T>::decode(values.data(),right.data(),left.data(),rex.data(),positions.data(),&ec,s);
            else alp::decoder<T>::patch_exceptions(values.data(),exceptions.data(),positions.data(),&ec);
            const auto* bytes=reinterpret_cast<const unsigned char*>(values.data());out.data.insert(out.data.end(),bytes,bytes+take*sizeof(T));
        }
    }
    if(in.at!=in.data.size())throw std::runtime_error("fixture trailing bytes");return out;
}
}
int main(int argc,char** argv){
    try{
        if(argc!=6)throw std::runtime_error("usage: oracle encode|decode f32|f64 alp|alp-rd input output (trusted fixtures only)");
        std::ifstream f(argv[4],std::ios::binary);if(!f)throw std::runtime_error("input");Bytes in;in.data.assign(std::istreambuf_iterator<char>(f),{});
        const bool dbl=std::string(argv[2])=="f64",rd=std::string(argv[3])=="alp-rd";Bytes out;
        if(std::string(argv[1])=="encode")out=dbl?compress<double>(in,rd):compress<float>(in,rd);
        else out=dbl?decompress<double>(in):decompress<float>(in);
        std::ofstream g(argv[5],std::ios::binary);g.write(reinterpret_cast<const char*>(out.data.data()),out.data.size());if(!g)throw std::runtime_error("output");
        std::cout<<"upstream-original bytes="<<out.data.size()<<" commit=31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
