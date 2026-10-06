#include "tscb_adapter_v1.h"
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/mman.h>
#include <unistd.h>
using Bytes=std::vector<std::uint8_t>;
void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
void put(Bytes& b,std::uint64_t x,unsigned n){for(unsigned i=0;i<n;i++)b.push_back(std::uint8_t(x>>(i*8)));}
Bytes input(unsigned n,unsigned w){Bytes b{'R','W','I','1',std::uint8_t(w),TSCB_REWRITE_KIND};put(b,2,2);put(b,7,4);put(b,n,8);
    if(TSCB_REWRITE_KIND==5)for(unsigned i=0;i<n;i++){std::uint64_t ts[]={0x8000000000000000ULL,0x7fffffffffffffffULL,0,0,0xffffffffffffffffULL};put(b,ts[i%5],8);}
    for(unsigned c=0;c<2;c++)for(unsigned i=0;i<n;i++){
        double d=(int(i%19)-9)/10.;if(w==8){std::uint64_t u;std::memcpy(&u,&d,8);put(b,u,8);}else{float f=float(d);std::uint32_t u;std::memcpy(&u,&f,4);put(b,u,4);}}
    return b;
}
tscb_buffer_v1 buf(void* p,std::size_t cap,std::size_t used=0){tscb_buffer_v1 b{};b.data=p;b.capacity_bytes=cap;b.used_bytes=used;b.dtype=TSCB_DTYPE_BYTES_V1;b.rank=1;b.shape[0]=used;b.strides_bytes[0]=1;b.alignment_bytes=1;return b;}
int main(){try{
    check(tscb_get_abi_version()==1,"ABI");const char* text=nullptr;std::uint64_t len=0;check(tscb_get_manifest_json(&text,&len)==0&&len,"manifest");
    auto config=std::string("{\"algorithm\":\"")+TSCB_REWRITE_KEY+"\"}";
    tscb_codec_handle_v1* h=nullptr;check(tscb_create(config.data(),config.size(),&h)==0&&h,"create");
    auto page=std::size_t(sysconf(_SC_PAGESIZE));auto* protected_output=mmap(nullptr,page,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);check(protected_output!=MAP_FAILED,"mmap");
    for(unsigned w:{4,8}){if(TSCB_REWRITE_KIND==5&&w==4)continue;for(unsigned n:{0,1,2,6,7,8,1001}){
        auto data=input(n,w),before=data;auto in=buf(data.data(),data.size(),data.size());std::uint64_t bound=0;
        check(tscb_reset(h,0)==0&&tscb_reset(h,1)==2,"reset");check(tscb_compress_bound(h,&in,&bound)==0&&bound>=36,"bound");
        auto short_out=buf(protected_output,0);check(tscb_compress(h,&in,&short_out)==3,"protected capacity no-write");
        Bytes out(std::size_t(bound)+2,0xA5);auto target=buf(out.data()+1,std::size_t(bound));check(tscb_compress(h,&in,&target)==0,"encode");
        check(data==before&&out.front()==0xA5&&out.back()==0xA5,"input/canary");Bytes encoded(out.begin()+1,out.begin()+1+std::ptrdiff_t(target.used_bytes));
        check(tscb_compress(h,&in,&target)==1,"double update");auto final=buf(nullptr,0);check(tscb_finalize(h,&final)==0&&tscb_finalize(h,&final)==1,"finalize");
        check(tscb_get_accounting_json(h,&text,&len)==0&&len,"accounting");
        tscb_codec_handle_v1* decoder=nullptr;check(tscb_create(config.data(),config.size(),&decoder)==0,"fresh decoder");
        auto coded=buf(encoded.data(),encoded.size(),encoded.size());auto count=data.size()-20;Bytes decoded(count+2,0x5A);auto dst=buf(decoded.data()+1,count);
        if(count){auto small=buf(protected_output,count-1);check(tscb_decompress(decoder,&coded,&small)==3,"decode no-write");}
        check(tscb_decompress(decoder,&coded,&dst)==0&&dst.used_bytes==count,"decode");check(decoded.front()==0x5A&&decoded.back()==0x5A,"decode canary");
        check(std::equal(data.begin()+20,data.end(),decoded.begin()+1),"paired bitwise output");
        for(auto cut:{std::size_t(0),std::size_t(1),encoded.size()-1}){auto broken=buf(encoded.data(),encoded.size(),cut);auto saved=decoded;check(tscb_decompress(decoder,&broken,&dst)!=0&&saved==decoded,"truncation atomicity");}
        encoded.back()^=1;auto saved=decoded;dst.used_bytes=0;check(tscb_decompress(decoder,&coded,&dst)!=0&&saved==decoded,"corruption atomicity");
        check(tscb_destroy(decoder)==0&&tscb_destroy(decoder)==1,"destroy lifecycle");
    }}
    check(tscb_query(h,nullptr,0,nullptr,0,nullptr)==2,"query unavailable");check(tscb_destroy(h)==0&&tscb_destroy(h)==1&&tscb_destroy(nullptr)==0,"destroy");munmap(protected_output,page);
    std::cout<<TSCB_REWRITE_KEY<<" native ABI, fresh decoding, paired int64 extremes, bounds, protected output, lifecycle and malformed PASS\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}return 0;}
