#include "alp_port.h"
#include <array>
#include <atomic>
#include <cfenv>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <thread>
#include <vector>
#if defined(__SSE__)
#include <xmmintrin.h>
#endif
namespace {
size_t checks = 0;
void check(bool x, const char* what) { ++checks; if (!x) throw std::runtime_error(what); }
uint32_t step(uint32_t c, const uint8_t* p, size_t n) {
    while (n--) { c ^= *p++; for (int k=0;k<8;++k) c=(c>>1)^(0xedb88320u & (0u-(c&1))); } return c;
}
void fix_crc(std::vector<uint8_t>& x) {
    const uint32_t c=~step(step(~0u,x.data(),28),x.data()+32,x.size()-32);
    for (int i=0;i<4;++i) x[28+i]=c>>(i*8);
}
template<class T> std::vector<T> input(size_t n, int pattern) {
    using U=std::conditional_t<sizeof(T)==8,uint64_t,uint32_t>;
    std::mt19937_64 rng(0x414c5031 + n + pattern);
    std::vector<T> x(n);
    const std::array<uint64_t,12> s64{{0,UINT64_C(0x8000000000000000),UINT64_C(0x7ff0000000000000),UINT64_C(0xfff0000000000000),UINT64_C(0x7ff8000000000042),UINT64_C(0x7ff0000000000001),1,UINT64_C(0x8000000000000001),UINT64_C(0x7fefffffffffffff),UINT64_C(0xffefffffffffffff),UINT64_C(0x0010000000000000),UINT64_C(0x3ff0000000000000)}};
    const std::array<uint32_t,12> s32{{0,0x80000000u,0x7f800000u,0xff800000u,0x7fc00042u,0x7f800001u,1,0x80000001u,0x7f7fffffu,0xff7fffffu,0x00800000u,0x3f800000u}};
    for(size_t i=0;i<n;++i) {
        if(pattern==0) x[i]=T(12.5);
        if(pattern==1) x[i]=T(int(i%10001)-5000)/T(100);
        if(pattern==2) x[i]=T(int(rng()%200000)-100000)/T((i%7)+1);
        if(pattern==3) { U b=static_cast<U>(rng()); std::memcpy(&x[i],&b,sizeof(T)); }
        if(pattern==4) { U b; if constexpr(sizeof(T)==8) b=s64[i%s64.size()]; else b=s32[i%s32.size()]; std::memcpy(&x[i],&b,sizeof(T)); }
        if(pattern==5) x[i]=T(0);
    }
    return x;
}
template<class T> std::vector<uint8_t> roundtrip(const std::vector<T>& x,uint8_t method,bool capacity_tests) {
    size_t bound=99,used=99; check(alp_port_bound(x.size(),sizeof(T),method,&bound)==0,"bound");
    std::vector<uint8_t> out(bound+32,0xa5), unaligned(x.size()*sizeof(T)+1);
    if(!x.empty()) std::memcpy(unaligned.data()+1,x.data(),x.size()*sizeof(T));
    const auto before=unaligned;
    check(alp_port_encode(unaligned.data()+1,x.size(),sizeof(T),method,out.data()+8,bound,&used)==0,"encode");
    check(unaligned==before,"input immutable"); check(used<=bound,"bound respected");
    for(size_t i=0;i<8;++i) check(out[i]==0xa5,"prefix guard");
    for(size_t i=8+used;i<out.size();++i) check(out[i]==0xa5,"suffix guard");
    std::vector<uint8_t> frame(out.begin()+8,out.begin()+8+used), decoded(x.size()*sizeof(T)+16,0x5a);
    size_t produced=9,consumed=9; uint64_t n=9; uint8_t d=9,m=9;
    check(alp_port_decode(frame.data(),frame.size(),decoded.data()+1,x.size()*sizeof(T),&produced,&consumed,&n,&d,&m)==0,"decode");
    check(produced==x.size()*sizeof(T)&&consumed==frame.size()&&n==x.size()&&d==sizeof(T)&&m==method,"descriptors");
    check(x.empty()||std::memcmp(x.data(),decoded.data()+1,produced)==0,"bitwise recovery");
    check(decoded[0]==0x5a && decoded[produced+1]==0x5a,"decode guards");
    if(capacity_tests) {
        std::vector<uint8_t> small(frame.size(),0x77); const auto original=small;
        size_t u=7; check(alp_port_encode(x.data(),x.size(),sizeof(T),method,small.data(),frame.size()-1,&u)==ALP_CAPACITY && u==0 && small==original,"encode short atomic");
        check(alp_port_encode(x.data(),x.size(),sizeof(T),method,small.data(),small.size(),&u)==0 && u==frame.size(),"exact encode capacity");
        if(!x.empty()) {
            auto old=decoded; produced=7; consumed=7;n=7;d=7;m=7;
            check(alp_port_decode(frame.data(),frame.size(),decoded.data()+1,x.size()*sizeof(T)-1,&produced,&consumed,&n,&d,&m)==ALP_CAPACITY,"decode short");
            check(decoded==old && !produced && !consumed && !n && !d && !m,"decode atomic");
        }
    }
    return frame;
}
template<class T> void suite() {
    for(size_t n : {0u,1u,2u,31u,32u,33u,1023u,1024u,1025u,2047u,2048u,2049u,102399u,102400u,102401u})
        for(int p=0;p<6;++p) for(uint8_t m=0;m<2;++m) {
            auto x=input<T>(n,p); roundtrip(x,m,n<=33||n==1025);
        }
}
void negative() {
    auto x=input<double>(33,1); auto frame=roundtrip(x,0,false);
    std::array<uint8_t,512> output{}; output.fill(0x77); const auto original=output;
    auto reject=[&](const uint8_t* b,size_t bytes) {
        size_t u=7,c=7;uint64_t n=7;uint8_t d=7,m=7;
        check(alp_port_decode(b,bytes,output.data(),output.size(),&u,&c,&n,&d,&m)!=0,"malformed rejection");
        check(output==original && !u&&!c&&!n&&!d&&!m,"rejection atomic");
    };
    for(size_t n=0;n<frame.size();++n) reject(frame.data(),n);
    auto extra=frame;extra.push_back(0);reject(extra.data(),extra.size());
    for(size_t i=0;i<frame.size();++i) { auto f=frame;f[i]^=0x80;reject(f.data(),f.size()); }
    for(size_t idx : {8u,9u,10u,11u,32u,33u,34u,35u,36u,56u,64u,66u,68u,69u,70u,71u}) {
        auto f=frame; f[idx]=0xff; fix_crc(f); reject(f.data(),f.size());
    }
    auto f=frame; for(int i=0;i<8;++i) f[12+i]=0xff;fix_crc(f);reject(f.data(),f.size());
    size_t z=8; check(alp_port_bound(UINT64_MAX,8,0,&z)==ALP_RESOURCE_LIMIT && z==0,"bound overflow");
    check(alp_port_bound(0,3,0,&z)==ALP_INVALID_ARGUMENT && z==0,"dtype reject");
    check(alp_port_bound(0,8,2,&z)==ALP_INVALID_ARGUMENT,"mode reject");
    check(alp_port_bound(0,8,0,nullptr)==ALP_INVALID_ARGUMENT,"null result");
    check(alp_port_encode(nullptr,1,8,0,output.data(),output.size(),&z)==ALP_INVALID_ARGUMENT && !z,"null input");
    check(alp_port_encode(output.data(),1,8,0,output.data(),output.size(),&z)==ALP_INVALID_ARGUMENT,"overlap");
    const int round=std::fegetround(); std::fesetround(FE_DOWNWARD);
    check(alp_port_encode(x.data(),x.size(),8,0,output.data(),output.size(),&z)==ALP_FP_ENV,"rounding reject"); std::fesetround(round);
#if defined(__SSE__)
    const auto csr=_mm_getcsr();_mm_setcsr(csr|(1u<<15));
    check(alp_port_encode(x.data(),x.size(),8,0,output.data(),output.size(),&z)==ALP_FP_ENV,"FTZ reject");_mm_setcsr(csr);
    _mm_setcsr(csr|(1u<<13));
    check(alp_port_encode(x.data(),x.size(),8,0,output.data(),output.size(),&z)==ALP_FP_ENV,"SSE-only rounding reject");_mm_setcsr(csr);
    _mm_setcsr(csr & ~(1u<<7));
    check(alp_port_encode(x.data(),x.size(),8,0,output.data(),output.size(),&z)==ALP_FP_ENV,"unmasked trap reject");_mm_setcsr(csr);
#endif
    std::cout<<"negative_cases_complete frame_bytes="<<frame.size()<<'\n';
}
void concurrency() {
    std::atomic<int> failures{0};std::vector<std::thread> threads;
    for(int t=0;t<8;++t) threads.emplace_back([&,t] {
        for(int i=0;i<30;++i) {
            auto x=input<double>(1025+(i%3),t%6);size_t b=0,u=0,c=0,v=0;uint64_t n=0;uint8_t d=0,m=0;
            if(alp_port_bound(x.size(),8,i%2,&b)) {++failures;continue;}
            std::vector<uint8_t> f(b),y(x.size()*8);
            if(alp_port_encode(x.data(),x.size(),8,i%2,f.data(),f.size(),&u)||
               alp_port_decode(f.data(),u,y.data(),y.size(),&v,&c,&n,&d,&m)||v!=x.size()*8||std::memcmp(x.data(),y.data(),v)) ++failures;
        }
    });
    for(auto& t:threads)t.join();check(failures==0,"concurrent recovery");
}
}
int main(int argc,char** argv) {
    try {
        if(argc==2 && std::string(argv[1])=="concurrency") concurrency();
        else {suite<float>();suite<double>();negative();concurrency();}
        std::cout<<"PASS checks="<<checks<<" profile="<<alp_port_profile()<<" seed=0x414c5031\n"; return 0;
    } catch(const std::exception& e) {std::cerr<<"FAIL "<<e.what()<<" checks="<<checks<<'\n';return 1;}
}
