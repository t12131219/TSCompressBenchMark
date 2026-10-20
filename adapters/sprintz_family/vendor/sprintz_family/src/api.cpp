#include "sprintz_port.h"
#include "native_dispatch.hpp"
#include "native_alloc.hpp"
#include <vector>
#include <cstring>
#include <limits>
#include <cpuid.h>
extern "C" {
#include "huf.h"
}
namespace {
using B=std::vector<uint8_t>;
constexpr size_t limit=65536,padding=8192;
uint64_t read(const uint8_t*p,unsigned n){uint64_t v=0;for(unsigned i=0;i<n;i++)v|=uint64_t(p[i])<<(8*i);return v;}
void put(uint8_t*p,uint64_t v,unsigned n){for(unsigned i=0;i<n;i++)p[i]=uint8_t(v>>(8*i));}
bool valid(const sz_config*c,size_t n){return c&&(c->width==8||c->width==16)&&c->predictor<2&&c->huffman<2&&c->path<6&&c->ndims>=1&&c->ndims<=128&&n<=limit&&n%(c->width/8)==0&&(!(c->path==2)||c->ndims<=(c->width==8?4u:2u))&&(!(c->path==3||c->path==4)||c->predictor==0)&&(!(c->path==5)||(c->width==8&&c->predictor==1));}
size_t bound(size_t n){return n*2+4096;}
// Walk the complete native grammar before any unchecked SIMD decoder call.
// The parser counts both compressed payload bytes and expanded element count.
int scan(const sz_config&c,const uint8_t*p,size_t z,size_t expected,size_t&used){
 size_t e=c.width/8,n=expected/e,d=c.ndims,hbits=e==1?3:4;
 bool rle=c.path<3,low=c.path==2||(c.path==0&&d<=(e==1?4:2));
 size_t pos=rle||c.path==5?8:6;if(z<pos)return SZ_MALFORMED;
 uint64_t ng,tail;
 if(rle){ng=read(p,4);tail=read(p+4,2);if(read(p+6,2)!=d)return SZ_MALFORMED;}
 else{uint64_t total=read(p,c.path==5?6:4);if(total!=n||read(p+(c.path==5?6:4),2)!=d)return SZ_MALFORMED;ng=n<128?0:n/(16*d);tail=n-ng*16*d;}
 if(tail>n||ng>n/(8*d)+1)return SZ_MALFORMED;
 size_t produced=0,hbytes=(2*d*hbits+7)/8;
 auto take=[&](size_t k){if(k>z-pos)return false;pos+=k;return true;};
 for(size_t g=0;g<ng;g++){
  const size_t hp=pos;if(!take(hbytes))return SZ_MALFORMED;
  for(size_t b=0;b<2;b++){
   size_t sum=0;
   for(size_t j=0;j<d;j++){
    size_t bit=(b*d+j)*hbits;unsigned code=unsigned((p[hp+bit/8]>>(bit%8))&((1u<<hbits)-1));
    if(bit%8+hbits>8)code|=unsigned(p[hp+bit/8+1]<<(8-bit%8))&((1u<<hbits)-1);
    sum+=code+(code==((1u<<hbits)-1));
   }
   size_t count=8*d;
   if(rle&&sum==0){
    if(!take(1))return SZ_MALFORMED;uint8_t lo=p[pos-1];size_t len=lo&127;
    if(lo&128){if(!take(1)||p[pos-1]==0)return SZ_MALFORMED;len|=size_t(p[pos-1])<<7;}
    // The source decoder repeats dest-ndims on later RLE slots.
    // A leading zero-length slot would leave that pointer before output.
    if(len==0&&(g+1!=ng||b!=1||produced==0))return SZ_MALFORMED;
    if(len>0&&produced==0&&(g!=0||b!=0))return SZ_MALFORMED;
    count=len*8*d;
   }else{size_t payload=(rle&&low)?sum:((sum+7)/8)*8;if(!take(payload))return SZ_MALFORMED;}
   if(count>n-produced)return SZ_MALFORMED;produced+=count;
  }
 }
 if(produced+tail!=n||!take(tail*e))return SZ_MALFORMED;
 used=pos;return SZ_OK;
}
int hencode(const B&raw,size_t n,B&out,size_t&z){
 out.assign(bound(n),0);put(out.data(),n,4);size_t r=HUF_compress(out.data()+4,out.size()-4,raw.data(),n);
 if(HUF_isError(r))return SZ_CORE;
 if(r==0||r==9){put(out.data(),0,4);put(out.data()+4,n,4);std::memcpy(out.data()+8,raw.data(),n);z=n+8;}
 else if(r==1){put(out.data(),n,8);out[8]=raw[0];z=9;}else z=r+4;return SZ_OK;
}
int hdecode(const uint8_t*p,size_t z,B&raw,size_t&n,size_t max){
 if(z==9){n=read(p,8);if(n>max||n<1)return SZ_MALFORMED;raw.assign(n+padding,p[8]);return SZ_OK;}
 if(z<4)return SZ_MALFORMED;n=read(p,4);
 if(n==0){if(z<8)return SZ_MALFORMED;n=read(p+4,4);if(n>max||n!=z-8)return SZ_MALFORMED;raw.assign(n+padding,0);std::memcpy(raw.data(),p+8,n);return SZ_OK;}
 if(n>max||n==0)return SZ_MALFORMED;raw.assign(n+padding,0);size_t r=HUF_decompress(raw.data(),n,p+4,z-4);return HUF_isError(r)||r!=n?SZ_MALFORMED:SZ_OK;
}
}
extern "C" int sz_supported(void){
#if defined(__x86_64__) && defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
 unsigned a,b,c,d;bool lzcnt=__get_cpuid(0x80000001,&a,&b,&c,&d)&&(c&(1u<<5));
 __builtin_cpu_init();return __builtin_cpu_supports("avx2")&&__builtin_cpu_supports("bmi")&&__builtin_cpu_supports("bmi2")&&lzcnt&&__builtin_cpu_supports("popcnt");
#else
 return 0;
#endif
}
extern "C" void sz_test_fail_allocation(int64_t k){sz_mem::countdown=k;}
extern "C" int sz_bound(const sz_config*c,size_t n,size_t*b){if(!b)return SZ_ARGUMENT;*b=0;if(!valid(c,n))return SZ_ARGUMENT;*b=c->huffman?bound(bound(n)):bound(n);return SZ_OK;}
extern "C" int sz_encode(const sz_config*c,const void*input,size_t n,void*output,size_t cap,size_t*made){
 if(!made)return SZ_ARGUMENT;*made=0;if(!valid(c,n)||(n&&!input)||!output)return SZ_ARGUMENT;if(!sz_supported())return SZ_PLATFORM;
 try{sz_mem::scope scope;B in(n+padding,0),raw(bound(n)+padding,0);if(n)std::memcpy(in.data(),input,n);
  int64_t units=port_native_encode(c->width,c->predictor,c->path,in.data(),n/(c->width/8),raw.data(),c->ndims);if(units<0)return SZ_CORE;
  size_t candidate=size_t(units)*(c->width/8)+(c->width==16),actual=0;
  if(candidate>raw.size()||scan(*c,raw.data(),candidate,n,actual)!=SZ_OK)return SZ_CORE;
  B h;size_t z=actual;
  if(c->huffman){ // Match author's 16-bit Huffman convention, including zero pad when length even.
   size_t hz=c->width==16?candidate:actual;int rc=hencode(raw,hz,h,z);if(rc)return rc;
  }
  if(z>cap)return SZ_CAPACITY;std::memcpy(output,c->huffman?h.data():raw.data(),z);*made=z;return SZ_OK;
 }catch(const std::bad_alloc&){return SZ_MEMORY;}catch(...){return SZ_CORE;}
}
extern "C" int sz_decode(const sz_config*c,const void*input,size_t z,size_t expected,void*output,size_t cap,size_t*made){
 if(!made)return SZ_ARGUMENT;*made=0;if(!valid(c,expected)||!input||!output)return SZ_ARGUMENT;if(cap<expected)return SZ_CAPACITY;if(z>bound(bound(expected)))return SZ_MALFORMED;if(!sz_supported())return SZ_PLATFORM;
 try{sz_mem::scope scope;B raw;size_t n=z;const uint8_t*p=(const uint8_t*)input;
  if(c->huffman){int rc=hdecode(p,z,raw,n,bound(expected));if(rc)return rc;}
  else{raw.assign(z+padding,0);std::memcpy(raw.data(),p,z);}
  size_t actual=0;int rc=scan(*c,raw.data(),n,expected,actual);if(rc)return rc;
  if(actual!=n){if(!c->huffman||c->width!=16||n!=actual+1||raw[actual]!=0)return SZ_MALFORMED;}
  B out(expected+padding,0);int64_t count=port_native_decode(c->width,c->predictor,c->path,raw.data(),out.data());if(count<0||size_t(count)*(c->width/8)!=expected)return SZ_CORE;
  if(expected)std::memcpy(output,out.data(),expected);*made=expected;return SZ_OK;
 }catch(const std::bad_alloc&){return SZ_MEMORY;}catch(...){return SZ_CORE;}
}
